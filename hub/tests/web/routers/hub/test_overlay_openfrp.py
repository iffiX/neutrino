"""The OpenFrp section's API against a fake OpenFrp.

What is pinned: the login hands back the authorization URL while it waits,
a logout calls nobody, OpenFrp's 401 marks the login expired and refuses
the list and the pick until the next login, a rotated Authorization is
resealed, the pick takes the tunnel's proxy from its node's config, and
every request names the hub.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.frp import ops
from neutrino_hub.modules.frp.config import FrpConfig, read_frp, write_frp
from neutrino_hub.modules.frp.constants import (
    FRP_OPENFRP,
    FRP_OPENFRP_API,
    FRP_OPENFRP_LOGIN_REQUEST_URL,
    FRP_USER_AGENT,
)
from neutrino_hub.modules.frp.ops import OpenFrpLogin, frp_file
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import overlay_openfrp
from tests.conftest import unlock_vault
from tests.modules.frp.fake_vendors import (
    OPENFRP_AUTHORIZATION,
    FakeVendors,
    answer,
    openfrp_answer,
)


class FakeFrpMonitor:
    def view(self) -> dict:
        return {"state": "connecting", "last_error": "", "checked_at": ""}


class FakeRuntime:
    def __init__(self):
        self.settings = {"agent_listen_port": 8443}
        self.frp_monitors = {"sakurafrp": FakeFrpMonitor(), "openfrp": FakeFrpMonitor()}
        self.polls: list = []
        self.openfrp_login = OpenFrpLogin(
            spawn=lambda target, args: self.polls.append(args[1])
        )
        self.converged = 0
        self.applied: list = []

    async def converge_network(self, *, only=None):
        self.converged += 1
        return []

    def apply_frp(self, vendor, *, is_restarted=False):
        self.applied.append((vendor, is_restarted))
        return ""


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(ops, "UTILS_STATE_ROOT", tmp_path / "state")
    vendors = FakeVendors()
    monkeypatch.setattr("neutrino_hub.modules.frp.vendor_api.http_call", vendors)
    monkeypatch.setattr(ops, "connect_ms", lambda host, port: 9)
    runtime = FakeRuntime()
    app = FastAPI()
    app.include_router(overlay_openfrp.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, vendors


def signed_in(**fields) -> FrpConfig:
    config = FrpConfig(vendor=FRP_OPENFRP, is_enabled=True, **fields)
    config.set_credential(OPENFRP_AUTHORIZATION)
    write_frp(config)
    return config


def test_the_view_carries_the_login_and_calls_nobody(api):
    client, _, vendors = api

    view = client.get("/api/hub/overlay/openfrp").json()

    assert view["is_signed_in"] is False
    assert view["is_login_expired"] is False
    assert view["login"] == {"state": "idle", "authorization_url": ""}
    assert view["console_url"] == "https://console.openfrp.net/"
    assert vendors.requests == []


def test_starting_the_login_answers_the_url_to_confirm_at(api):
    client, runtime, vendors = api

    view = client.post("/api/hub/overlay/openfrp/login/start").json()

    assert runtime.polls == ["9a23ed00-07e6-4f11-bcfd-b0216e3bcacf"]
    assert view["login"] == {
        "state": "waiting",
        "authorization_url": "https://console.openfrp.net/usercenter?argoaccess=9a23",
    }
    assert vendors.urls() == [FRP_OPENFRP_LOGIN_REQUEST_URL]
    assert vendors.requests[0][2]["User-Agent"] == FRP_USER_AGENT


def test_a_login_openfrp_refuses_to_start_is_502(api):
    client, _, vendors = api
    vendors.answers[("POST", FRP_OPENFRP_LOGIN_REQUEST_URL)] = answer(
        {"code": 429, "msg": "too many"}, status=429
    )

    response = client.post("/api/hub/overlay/openfrp/login/start")

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "frp_vendor_unreachable",
        "params": {"title": "OpenFrp", "detail": "HTTP 429"},
    }
    assert client.get("/api/hub/overlay/openfrp").json()["login"]["state"] == "failed"


def test_a_logout_forgets_the_account_and_the_tunnel_and_calls_nobody(api):
    client, runtime, vendors = api
    signed_in(tunnel_id="120623", public_host="x.example", public_port=1)
    runtime.openfrp_login.is_expired = True

    view = client.post("/api/hub/overlay/openfrp/logout").json()

    assert (view["is_signed_in"], view["tunnel_id"], view["url"]) == (False, "", "")
    assert view["is_login_expired"] is False
    assert read_frp(FRP_OPENFRP).is_enabled is True
    assert vendors.requests == []
    assert runtime.converged == 1


def test_the_tunnel_list_is_filtered_and_timed(api):
    client, _, vendors = api
    signed_in(tunnel_id="120623")

    view = client.get("/api/hub/overlay/openfrp/tunnel").json()

    assert view["tunnels"] == [
        {
            "tunnel_id": "120623",
            "name": "neutrino",
            "node_name": "重庆联通-2",
            "region": "mainland",
            "latency_ms": 9,
            "is_picked": True,
        },
        {
            "tunnel_id": "120627",
            "name": "tokyo",
            "node_name": "日本-1",
            "region": "abroad",
            "latency_ms": 9,
            "is_picked": False,
        },
    ]
    assert {headers["Authorization"] for _, _, headers, _ in vendors.requests} == {
        OPENFRP_AUTHORIZATION
    }
    assert all(
        headers["User-Agent"] == FRP_USER_AGENT for _, _, headers, _ in vendors.requests
    )


def test_openfrps_401_marks_the_login_expired_and_refuses_until_the_next(api):
    client, runtime, vendors = api
    signed_in()
    vendors.answers[("POST", f"{FRP_OPENFRP_API}/getUserProxies")] = answer(
        {"flag": False, "msg": "未登录"}, status=401
    )

    first = client.get("/api/hub/overlay/openfrp/tunnel")
    asked = len(vendors.requests)
    second = client.post(
        "/api/hub/overlay/openfrp/tunnel/set", json={"tunnel_id": "120623"}
    )

    for response in (first, second):
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "frp_not_signed_in",
            "params": {"title": "OpenFrp"},
        }
    assert len(vendors.requests) == asked
    assert client.get("/api/hub/overlay/openfrp").json()["is_login_expired"] is True


def test_a_rotated_authorization_is_resealed(api):
    client, _, vendors = api
    signed_in()
    vendors.answers[("POST", f"{FRP_OPENFRP_API}/getNodeList")] = openfrp_answer(
        {"total": 0, "list": []}, headers={"authorization": "OPENFRPsecond"}
    )

    client.get("/api/hub/overlay/openfrp/tunnel")

    assert read_frp(FRP_OPENFRP).credential() == "OPENFRPsecond"


def test_picking_takes_the_tunnels_proxy_from_its_nodes_config(api):
    client, runtime, vendors = api
    signed_in()

    view = client.post(
        "/api/hub/overlay/openfrp/tunnel/set", json={"tunnel_id": "120623"}
    ).json()

    assert view["url"] == "tcp://cn-cq-plc-1.of-7af93c01.shop:51607"
    assert view["tunnel_id"] == "120623"
    text = frp_file(FRP_OPENFRP).read_text()
    assert 'name = "neutrino"' in text and 'name = "mc"' not in text
    assert "localPort = 18444" in text
    assert runtime.applied == [("openfrp", True)]


def test_an_auto_tls_tunnel_is_unknown_to_the_pick(api):
    client, _, _ = api
    signed_in()

    response = client.post(
        "/api/hub/overlay/openfrp/tunnel/set", json={"tunnel_id": "120624"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "frp_tunnel_unknown"
