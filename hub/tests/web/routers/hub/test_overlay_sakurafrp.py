"""The SakuraFrp section's API against a fake SakuraFrp.

What is pinned: the key is stored sealed only once SakuraFrp accepts it,
forgetting it clears the picked tunnel, the view calls nobody, the tunnel
list and the pick refuse by code, and every request names the hub.
"""

import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.frp import ops
from neutrino_hub.modules.frp.config import FrpConfig, read_frp, write_frp
from neutrino_hub.modules.frp.constants import (
    FRP_SAKURAFRP,
    FRP_SAKURAFRP_API,
    FRP_USER_AGENT,
    FRP_VERSION,
)
from neutrino_hub.modules.frp.ops import frp_file
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import overlay_sakurafrp
from tests.conftest import unlock_vault
from tests.modules.frp.fake_vendors import SAKURAFRP_KEY, FakeVendors, answer


class FakeFrpMonitor:
    def __init__(self):
        self.state = "no_tunnel"

    def view(self) -> dict:
        return {"state": self.state, "last_error": "", "checked_at": ""}


class FakeLogin:
    is_expired = False


class FakeRuntime:
    def __init__(self):
        self.settings = {"agent_listen_port": 8443}
        self.frp_monitors = {"sakurafrp": FakeFrpMonitor(), "openfrp": FakeFrpMonitor()}
        self.openfrp_login = FakeLogin()
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
    monkeypatch.setattr(ops, "connect_ms", lambda host, port: 17)
    runtime = FakeRuntime()
    app = FastAPI()
    app.include_router(overlay_sakurafrp.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, vendors


def signed_in(**fields) -> FrpConfig:
    config = FrpConfig(vendor=FRP_SAKURAFRP, is_enabled=True, **fields)
    config.set_credential(SAKURAFRP_KEY)
    write_frp(config)
    return config


def test_the_view_reads_the_file_and_calls_nobody(api):
    client, _, vendors = api
    signed_in(
        tunnel_id="114514",
        node_name="宁波电信",
        local_port=8443,
        public_host="frp-a.natfrp.cloud",
        public_port=41234,
    )

    view = client.get("/api/hub/overlay/sakurafrp").json()

    assert view == {
        "is_enabled": True,
        "is_signed_in": True,
        "tunnel_id": "114514",
        "node_name": "宁波电信",
        "local_port": 8443,
        "url": "https://frp-a.natfrp.cloud:41234",
        "state": "no_tunnel",
        "last_error": "",
        "checked_at": "",
        "console_url": "https://www.natfrp.com/tunnel/",
    }
    assert vendors.requests == []


def test_an_accepted_key_is_stored_sealed_and_converges(api, tmp_path):
    client, runtime, vendors = api

    response = client.post(
        "/api/hub/overlay/sakurafrp/access_key/set",
        json={"access_key": f" {SAKURAFRP_KEY} "},
    )

    assert response.status_code == 200
    assert response.json()["is_signed_in"] is True
    assert read_frp(FRP_SAKURAFRP).credential() == SAKURAFRP_KEY
    assert SAKURAFRP_KEY not in (tmp_path / "overlay" / "sakurafrp.json").read_text()
    assert vendors.urls() == [f"{FRP_SAKURAFRP_API}/user/info"]
    assert vendors.requests[0][2]["Authorization"] == f"Bearer {SAKURAFRP_KEY}"
    assert runtime.converged == 1


def test_a_refused_key_is_not_stored(api):
    client, runtime, vendors = api
    vendors.answers[("GET", f"{FRP_SAKURAFRP_API}/user/info")] = answer(
        {"code": 401, "msg": "访问密钥无效"}, status=500
    )

    response = client.post(
        "/api/hub/overlay/sakurafrp/access_key/set", json={"access_key": "wrong"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "frp_credential_refused",
        "params": {"title": "SakuraFrp"},
    }
    assert read_frp(FRP_SAKURAFRP).is_signed_in is False
    assert runtime.converged == 0


def test_sakurafrp_out_of_reach_is_502(api):
    client, _, vendors = api
    vendors.answers.clear()

    response = client.post(
        "/api/hub/overlay/sakurafrp/access_key/set", json={"access_key": "k"}
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "frp_vendor_unreachable"
    assert response.json()["detail"]["params"]["title"] == "SakuraFrp"


def test_an_empty_key_forgets_the_account_and_the_tunnel(api):
    client, runtime, vendors = api
    signed_in(tunnel_id="114514", public_host="frp-a.natfrp.cloud", public_port=1)

    view = client.post(
        "/api/hub/overlay/sakurafrp/access_key/set", json={"access_key": ""}
    ).json()

    assert (view["is_signed_in"], view["tunnel_id"], view["url"]) == (False, "", "")
    assert read_frp(FRP_SAKURAFRP).is_enabled is True
    assert vendors.requests == []
    assert runtime.converged == 1


def test_the_tunnel_list_is_filtered_timed_and_marks_the_picked_one(api):
    client, _, vendors = api
    signed_in(tunnel_id="114518")

    view = client.get("/api/hub/overlay/sakurafrp/tunnel").json()

    assert view == {
        "tunnels": [
            {
                "tunnel_id": "114514",
                "name": "neutrino",
                "node_name": "宁波电信",
                "region": "mainland",
                "latency_ms": 17,
                "is_picked": False,
            },
            {
                "tunnel_id": "114518",
                "name": "hk",
                "node_name": "香港",
                "region": "outside_mainland",
                "latency_ms": 17,
                "is_picked": True,
            },
        ]
    }
    assert all(
        headers["User-Agent"] == FRP_USER_AGENT for _, _, headers, _ in vendors.requests
    )


def test_the_list_follows_the_connection_port(api):
    client, runtime, _ = api
    signed_in()
    runtime.settings["agent_listen_port"] = 22

    view = client.get("/api/hub/overlay/sakurafrp/tunnel").json()

    assert [row["name"] for row in view["tunnels"]] == ["ssh"]


def test_listing_or_picking_while_signed_out_is_409(api):
    client, _, vendors = api

    listed = client.get("/api/hub/overlay/sakurafrp/tunnel")
    picked = client.post(
        "/api/hub/overlay/sakurafrp/tunnel/set", json={"tunnel_id": "114514"}
    )

    for response in (listed, picked):
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "frp_not_signed_in",
            "params": {"title": "SakuraFrp"},
        }
    assert vendors.requests == []


def test_a_key_refused_later_refuses_the_list(api):
    client, _, vendors = api
    signed_in()
    vendors.answers[("GET", f"{FRP_SAKURAFRP_API}/tunnels")] = answer(
        {"code": 401, "msg": "访问密钥无效"}, status=500
    )

    response = client.get("/api/hub/overlay/sakurafrp/tunnel")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "frp_credential_refused"


def test_picking_writes_the_file_stores_the_tunnel_and_restarts_frpc(api):
    client, runtime, vendors = api
    signed_in()

    view = client.post(
        "/api/hub/overlay/sakurafrp/tunnel/set", json={"tunnel_id": "114514"}
    ).json()

    stored = read_frp(FRP_SAKURAFRP)
    assert (stored.tunnel_id, stored.node_name, stored.local_port) == (
        "114514",
        "宁波电信",
        8443,
    )
    assert (stored.public_host, stored.public_port) == ("frp-a.natfrp.cloud", 41234)
    assert view["url"] == "https://frp-a.natfrp.cloud:41234"
    path = frp_file(FRP_SAKURAFRP)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "localPort = 18443" in path.read_text()
    assert runtime.applied == [("sakurafrp", True)]
    assert runtime.converged == 1
    config_asks = [body for _, url, _, body in vendors.requests if "config" in url]
    assert len(config_asks) == 1


def test_a_tunnel_the_list_does_not_hold_is_refused(api):
    client, runtime, _ = api
    signed_in()

    response = client.post(
        "/api/hub/overlay/sakurafrp/tunnel/set", json={"tunnel_id": "114515"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "frp_tunnel_unknown",
        "params": {"title": "SakuraFrp", "tunnel_id": "114515"},
    }
    assert read_frp(FRP_SAKURAFRP).tunnel_id == ""
    assert runtime.applied == []


def test_a_config_without_the_tunnels_proxy_is_frp_config_unusable(api):
    client, runtime, vendors = api
    signed_in()
    vendors.answers[("POST", f"{FRP_SAKURAFRP_API}/tunnel/config")] = answer(
        'serverAddr = "x"\n[[proxies]]\nname = "someone_else"\n'
    )

    response = client.post(
        "/api/hub/overlay/sakurafrp/tunnel/set", json={"tunnel_id": "114514"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "frp_config_unusable",
        "params": {"title": "SakuraFrp"},
    }
    assert not frp_file(FRP_SAKURAFRP).exists()


def test_the_config_is_asked_for_the_carried_frpc(api):
    client, _, vendors = api
    signed_in()

    client.post("/api/hub/overlay/sakurafrp/tunnel/set", json={"tunnel_id": "114514"})

    (body,) = [body for _, url, _, body in vendors.requests if "config" in url]
    assert f"frpc={FRP_VERSION}" in body.decode()
