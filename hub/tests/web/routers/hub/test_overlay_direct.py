"""The Direct section's API, with the converge step replaced.

What is pinned is what the routes store and refuse: a host that is neither an
address nor a host name, a port out of range, a converge step that fails; and
the addresses the section lists, which are what Direct adds to ``urls``.
"""

import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.overlay.direct_config import (
    OverlayDirectConfig,
    read_direct,
    write_direct,
)
from neutrino_hub.web import channel_addresses
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import overlay_direct as direct_router
from tests.conftest import lan_entry, network_config, wan_entry


class FakeRuntime:
    def __init__(self):
        self.settings = {"agent_listen_port": 9443}
        self.converged = 0
        self.refusal: Exception | None = None
        self.entries = [wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.8.1")]

    def network(self):
        return network_config(*self.entries, overlays=[])

    async def converge_network(self, *, only=None):
        self.converged += 1
        if self.refusal is not None:
            raise self.refusal
        return []


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        channel_addresses, "device_addresses", lambda: {"enp2s0": "203.0.113.7/24"}
    )
    monkeypatch.setattr(
        channel_addresses,
        "device_ipv6_addresses",
        lambda: {"enp1s0": ["fd00:8::1/64"], "enp2s0": ["2001:db8::7/64"]},
    )
    runtime = FakeRuntime()
    app = FastAPI()
    app.include_router(direct_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_an_unset_direct_reads_off_and_lists_what_turning_it_on_adds(api):
    client, _ = api

    view = client.get("/api/hub/overlay/direct").json()

    assert view == {
        "is_enabled": False,
        "public_host": "",
        "public_port": 8443,
        "urls": [
            "https://[fd00:8::1]:9443",
            "https://203.0.113.7:9443",
            "https://[2001:db8::7]:9443",
        ],
        "interface_state": "added",
    }


def test_setting_stores_the_address_keeps_the_switch_and_converges(api):
    client, runtime = api
    write_direct(OverlayDirectConfig(is_enabled=True))

    response = client.post(
        "/api/hub/overlay/direct/set",
        json={"public_host": " hub.example.org ", "public_port": 443},
    )

    assert response.status_code == 200
    assert read_direct() == OverlayDirectConfig(
        is_enabled=True, public_host="hub.example.org", public_port=443
    )
    assert runtime.converged == 1
    assert response.json()["urls"] == [
        "https://[fd00:8::1]:9443",
        "https://203.0.113.7:9443",
        "https://[2001:db8::7]:9443",
        "https://hub.example.org:443",
    ]


def test_an_empty_host_states_no_public_address(api):
    client, _ = api

    response = client.post(
        "/api/hub/overlay/direct/set", json={"public_host": "", "public_port": 443}
    )

    assert response.status_code == 200
    assert response.json()["urls"][-1] == "https://[2001:db8::7]:9443"


@pytest.mark.parametrize("host", ["two words", "-oProxyCommand=x", "a..b"])
def test_a_host_that_is_neither_an_address_nor_a_name_is_refused(api, host):
    client, runtime = api

    response = client.post(
        "/api/hub/overlay/direct/set", json={"public_host": host, "public_port": 443}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "direct_host_invalid",
        "params": {"host": host},
    }
    assert runtime.converged == 0
    assert read_direct() == OverlayDirectConfig()


@pytest.mark.parametrize("port", [0, 65536])
def test_a_port_out_of_range_is_refused(api, port):
    client, runtime = api

    response = client.post(
        "/api/hub/overlay/direct/set",
        json={"public_host": "hub.example.org", "public_port": port},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "port_out_of_range",
        "params": {"minimum": 1, "maximum": 65535, "value": port},
    }
    assert runtime.converged == 0


def test_a_converge_step_that_fails_answers_502(api):
    client, runtime = api
    runtime.refusal = subprocess.CalledProcessError(1, ["nft"], stderr="refused")

    response = client.post(
        "/api/hub/overlay/direct/set",
        json={"public_host": "hub.example.org", "public_port": 443},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "direct_apply_failed"


def test_an_ipv6_public_address_is_stored_bare_and_listed_in_brackets(api):
    client, _ = api

    response = client.post(
        "/api/hub/overlay/direct/set",
        json={"public_host": "2001:db8::99", "public_port": 443},
    )

    assert response.status_code == 200
    assert read_direct().public_host == "2001:db8::99"
    assert response.json()["public_host"] == "2001:db8::99"
    assert response.json()["urls"][-1] == "https://[2001:db8::99]:443"


@pytest.mark.parametrize(
    ("public_host", "url"),
    [
        ("203.0.113.7", "https://203.0.113.7:9443"),
        ("2001:DB8:0::7", "https://[2001:db8::7]:9443"),
    ],
)
def test_a_public_address_that_is_an_interface_s_is_listed_once(api, public_host, url):
    client, _ = api

    response = client.post(
        "/api/hub/overlay/direct/set",
        json={"public_host": public_host, "public_port": 9443},
    )

    assert response.status_code == 200
    assert response.json()["urls"].count(url) == 1
    assert len(response.json()["urls"]) == 3


# --- what the section says under the addresses ---


def test_direct_adding_an_interface_s_address_reads_added(api):
    client, _ = api

    view = client.get("/api/hub/overlay/direct").json()

    assert view["interface_state"] == "added"
    assert "https://203.0.113.7:9443" in view["urls"]


def test_every_interface_already_exposed_reads_exposed(api, monkeypatch):
    """A hub with one network card, exposed, and IPv4 alone: Direct adds none
    of its addresses, and the public address can still be set."""
    client, runtime = api
    runtime.entries = [lan_entry("enp1s0", address="192.168.8.1")]
    monkeypatch.setattr(
        channel_addresses, "device_addresses", lambda: {"enp1s0": "192.168.8.1/24"}
    )
    monkeypatch.setattr(channel_addresses, "device_ipv6_addresses", dict)

    unset = client.get("/api/hub/overlay/direct").json()
    stated = client.post(
        "/api/hub/overlay/direct/set",
        json={"public_host": "hub.example.org", "public_port": 443},
    ).json()

    assert (unset["interface_state"], unset["urls"]) == ("exposed", [])
    assert stated["interface_state"] == "exposed"
    assert stated["urls"] == ["https://hub.example.org:443"]


def test_an_exposed_interface_s_ipv6_address_is_one_direct_adds(api, monkeypatch):
    client, runtime = api
    runtime.entries = [lan_entry("enp1s0", address="192.168.8.1")]
    monkeypatch.setattr(
        channel_addresses, "device_ipv6_addresses", lambda: {"enp1s0": ["fd00:8::1/64"]}
    )

    view = client.get("/api/hub/overlay/direct").json()

    assert view["interface_state"] == "added"
    assert view["urls"] == ["https://[fd00:8::1]:9443"]


def test_no_interface_with_an_address_reads_none(api, monkeypatch):
    client, runtime = api
    runtime.entries = []
    monkeypatch.setattr(channel_addresses, "device_addresses", dict)
    monkeypatch.setattr(channel_addresses, "device_ipv6_addresses", dict)

    view = client.get("/api/hub/overlay/direct").json()

    assert view["interface_state"] == "none"
    assert view["urls"] == []
