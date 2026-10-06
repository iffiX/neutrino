"""The EasyTier settings' API, with the converge step and the disk replaced.

The network is a name and a secret this hub owns, so what is pinned here is
where the secret lives (sealed, never in the view) and what the one write
refuses before the engine is handed something it would read as a different
network. Every setting travels in that one write, and a write that stored
something converges once.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.easytier.ops import (
    EasyTierInstance,
    EasyTierPeer,
    read_stored,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web import channel_overlay
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import overlay as overlay_router
from neutrino_hub.web.routers.hub import overlay_easytier as easytier_router
from tests.conftest import unlock_vault

PEERS = [
    EasyTierPeer(
        hostname="neutrino",
        address="",
        link="local",
        protocol="",
        latency_ms=None,
        loss_ratio=None,
        rx_bytes=None,
        tx_bytes=None,
        nat_type="PortRestricted",
        version="2.6.4",
        is_connected=True,
    ),
    EasyTierPeer(
        hostname="laptop",
        address="10.0.0.4",
        link="direct",
        protocol="tcp",
        latency_ms=19.85,
        loss_ratio=0.0,
        rx_bytes=917,
        tx_bytes=1024,
        nat_type="Cone",
        version="2.6.4",
        is_connected=True,
    ),
]


class FakeServices:
    def status(self, name: str) -> ServiceStatus:
        return ServiceStatus(
            name=name,
            unit=f"neutrino_hub_{name}.service",
            is_installed=True,
            is_active=True,
            is_enabled=True,
        )


class FakeRuntime:
    """Just the parts of :class:`PanelRuntime` these routes reach for."""

    def __init__(self, network: RouterNetworkConfig):
        self._network = network
        self.services = FakeServices()
        # What was stored each time the converge step ran.
        self.converged: list = []
        self.refusal: Exception | None = None

    def network(self) -> RouterNetworkConfig:
        return self._network

    async def converge_network(self, *, only=None) -> str:
        if self.refusal is not None:
            raise self.refusal
        self.converged.append(read_stored())
        return "applied"


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A gateway with an open vault, a fake engine, and config/ under tmp."""
    unlock_vault(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config_dir)
    monkeypatch.setattr(easytier_router, "EasyTierStatusReader", lambda: _Reader(PEERS))
    monkeypatch.setattr(
        channel_overlay,
        "device_addresses",
        lambda: {"enp1s0": "192.168.100.1/24", "enp2s0": "198.51.100.9/25"},
    )
    monkeypatch.setattr(
        easytier_router,
        "device_addresses",
        lambda: {"enp1s0": "192.168.100.1/24", "enp2s0": "198.51.100.9/25"},
    )
    runtime = FakeRuntime(
        RouterNetworkConfig.from_dict(
            {
                "mode": "router",
                "interfaces": [
                    {
                        "name": "enp1s0",
                        "role": "lan",
                        "lan": {"address": "192.168.100.1", "prefix_len": 24},
                    },
                    {"name": "enp2s0", "role": "wan"},
                ],
            }
        )
    )

    app = FastAPI()
    app.include_router(easytier_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


class _Reader:
    def __init__(self, peers):
        self._peers = peers

    def peers(self):
        return list(self._peers)

    def instances(self):
        return [
            EasyTierInstance(
                instance_name="",
                network_name="home",
                address="10.126.126.1/24",
                hostname="",
                subnet_routes=["192.168.100.0/24"],
                withheld=["hostname"],
            )
        ]


def settings(**changes) -> dict:
    """A whole settings body in manual mode, with some fields changed."""
    body = {
        "mode": "manual",
        "config_server": None,
        "is_secure_mode": False,
        "network_name": "neutrino-1234",
        "network_secret": "a-network-secret",
        "address": "10.0.0.1/24",
        "hostname": "",
        "peers": ["tcp://198.51.100.7:11010"],
        "exported_networks": [],
    }
    body.update(changes)
    return body


def a_network(client) -> dict:
    """Store a network, the way the panel's first Apply does."""
    return client.post("/api/hub/overlay/easytier/set", json=settings()).json()


# --- reading ----------------------------------------------------------------


def test_a_box_with_no_network_says_so(box):
    client, _ = box

    payload = client.get("/api/hub/overlay/easytier").json()

    assert payload["network_name"] == ""
    assert payload["is_secret_set"] is False
    assert payload["node"] is None


def test_this_machines_own_networks_are_offered_for_export(box):
    client, _ = box

    payload = client.get("/api/hub/overlay/easytier").json()

    assert [entry["cidr"] for entry in payload["suggested_networks"]] == [
        "192.168.100.0/24",
        "198.51.100.0/25",
    ]


def test_the_uplinks_address_is_what_another_machine_dials(box):
    client, _ = box

    assert client.get("/api/hub/overlay/easytier").json()["join_host"] == "198.51.100.9"


def test_the_secret_is_never_in_the_view(box):
    client, _ = box
    a_network(client)

    payload = client.get("/api/hub/overlay/easytier").json()

    assert payload["is_secret_set"] is True
    assert "a-network-secret" not in str(payload)


def test_the_secret_is_handed_over_where_it_is_asked_for(box):
    client, _ = box
    a_network(client)

    reply = client.get("/api/hub/overlay/easytier/secret").json()

    assert reply["network_secret"] == "a-network-secret"


def test_the_peers_are_the_others_and_this_box_is_the_node(box):
    client, _ = box
    a_network(client)

    payload = client.get("/api/hub/overlay/easytier").json()

    assert [peer["hostname"] for peer in payload["live_peers"]] == ["laptop"]
    assert payload["live_peers"][0]["rx_bytes"] == 917
    assert payload["node"]["is_connected"] is True
    assert payload["node"]["hostname"] == "neutrino"


# --- writing ----------------------------------------------------------------


def test_storing_a_network_converges_on_it_once(box):
    client, runtime = box

    payload = a_network(client)

    assert payload["network_name"] == "neutrino-1234"
    assert payload["address"] == "10.0.0.1/24"
    assert [config.network_name for config in runtime.converged] == ["neutrino-1234"]


def test_a_refused_network_is_not_stored_or_converged(box):
    client, runtime = box

    reply = client.post(
        "/api/hub/overlay/easytier/set", json=settings(address="10.0.0.1")
    )

    assert reply.status_code == 400
    assert runtime.converged == []
    assert read_stored().network_name == ""


def test_an_empty_secret_keeps_the_one_already_stored(box):
    client, _ = box
    a_network(client)

    client.post(
        "/api/hub/overlay/easytier/set",
        json=settings(network_secret="", address="10.0.0.2/24"),
    )

    assert client.get("/api/hub/overlay/easytier/secret").json()["network_secret"] == (
        "a-network-secret"
    )


def test_a_first_network_with_no_secret_is_refused(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set",
        json=settings(network_secret="", address=""),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_secret_missing"


def test_a_name_that_could_hide_in_a_relay_whitelist_is_refused(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set", json=settings(network_name="two words")
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_name_invalid"


def test_an_address_with_no_prefix_is_refused(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set", json=settings(address="10.0.0.1")
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_address_invalid"


def test_the_bootstrap_peers_are_stored_in_order(box):
    client, _ = box

    payload = client.post(
        "/api/hub/overlay/easytier/set",
        json=settings(peers=["tcp://198.51.100.7:11010", "txt://net.example.com"]),
    ).json()

    assert payload["peers"] == ["tcp://198.51.100.7:11010", "txt://net.example.com"]


def test_an_address_the_engine_would_not_dial_is_refused(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set", json=settings(peers=["example.com:11010"])
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "easytier_peer_invalid"
    assert detail["params"] == {"uri": "example.com:11010"}


def test_a_manual_network_with_no_bootstrap_peer_is_refused(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set", json=settings(peers=["", "  "])
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "easytier_invalid"
    assert detail["params"] == {"field": "peers"}


def test_the_console_mode_needs_no_bootstrap_peer(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set",
        json=settings(mode="console", network_name="", peers=[]),
    )

    assert response.json().get("detail", {}).get("code") != "easytier_invalid"


def test_the_exported_networks_are_stored(box):
    client, _ = box

    payload = client.post(
        "/api/hub/overlay/easytier/set",
        json=settings(exported_networks=["192.168.100.0/24"]),
    ).json()

    assert payload["exported_networks"] == ["192.168.100.0/24"]


def test_exporting_the_whole_internet_is_refused(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set", json=settings(exported_networks=["0.0.0.0/0"])
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_network_invalid"


def test_a_converge_that_fails_is_reported(box):
    client, runtime = box
    runtime.refusal = OSError("the engine refused")

    response = client.post("/api/hub/overlay/easytier/set", json=settings())

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "easytier_apply_failed"


def test_an_address_on_the_lan_is_refused_while_easytier_runs(box, monkeypatch):
    """Two networks with one range route one of them nowhere."""
    client, runtime = box
    network = runtime.network()
    runtime._network = RouterNetworkConfig.from_dict(
        {
            **network.to_dict(),
            "overlays": [
                {"provider": "netbird", "is_enabled": True},
                {"provider": "easytier", "is_enabled": True},
            ],
        }
    )
    monkeypatch.setattr(
        overlay_router, "device_addresses", lambda: {"enp1s0": "192.168.100.1/24"}
    )

    response = client.post(
        "/api/hub/overlay/easytier/set", json=settings(address="192.168.100.5/24")
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "overlay_subnet_overlap",
        "params": {
            "title": "EasyTier",
            "subnet": "192.168.100.0/24",
            "conflict": "192.168.100.0/24",
        },
    }
    assert runtime.converged == []


def test_an_address_is_not_checked_while_easytier_is_off(box, monkeypatch):
    client, runtime = box
    monkeypatch.setattr(
        overlay_router, "device_addresses", lambda: {"enp1s0": "192.168.100.1/24"}
    )

    response = client.post(
        "/api/hub/overlay/easytier/set", json=settings(address="192.168.100.5/24")
    )

    assert response.status_code == 200


# --- the console mode -------------------------------------------------------

CONSOLE = "tcp://et-web.console.easytier.net:22020/etk_example"  # scan: allow


def console(**changes) -> dict:
    """A settings body in console mode with no manual network."""
    return settings(
        mode="console", network_name="", network_secret="", address="", **changes
    )


def test_a_box_starts_in_manual_mode_with_no_console(box):
    client, _ = box

    payload = client.get("/api/hub/overlay/easytier").json()

    assert payload["mode"] == "manual"
    assert payload["has_config_server"] is False
    assert payload["is_secure_mode"] is False
    assert payload["instances"] == []


def test_the_console_mode_needs_no_manual_network(box):
    client, runtime = box

    payload = client.post(
        "/api/hub/overlay/easytier/set", json=console(config_server=CONSOLE)
    ).json()

    assert payload["mode"] == "console"
    assert [config.mode for config in runtime.converged] == ["console"]


def test_a_mode_that_is_not_one_is_refused(box):
    client, runtime = box

    response = client.post("/api/hub/overlay/easytier/set", json=settings(mode="x"))

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "easytier_mode_unknown",
        "params": {"mode": "x"},
    }
    assert runtime.converged == []


def test_the_console_address_is_kept_sealed_and_never_shown(box):
    client, _ = box

    payload = client.post(
        "/api/hub/overlay/easytier/set", json=console(config_server=CONSOLE)
    ).json()

    assert payload["has_config_server"] is True
    assert "etk_example" not in str(payload)
    assert "etk_example" not in str(client.get("/api/hub/overlay/easytier").json())


def test_no_console_address_keeps_the_kept_one(box):
    client, _ = box
    client.post("/api/hub/overlay/easytier/set", json=console(config_server=CONSOLE))

    payload = client.post(
        "/api/hub/overlay/easytier/set", json=console(is_secure_mode=True)
    ).json()

    assert payload["has_config_server"] is True
    assert payload["is_secure_mode"] is True


def test_an_empty_console_address_forgets_the_kept_one(box):
    client, _ = box
    client.post("/api/hub/overlay/easytier/set", json=console(config_server=CONSOLE))

    payload = client.post(
        "/api/hub/overlay/easytier/set", json=console(config_server="")
    ).json()

    assert payload["has_config_server"] is False


def test_a_console_address_that_is_not_one_is_refused_without_echoing_it(box):
    client, _ = box

    response = client.post(
        "/api/hub/overlay/easytier/set",
        json=console(config_server="http://example.com/etk secret"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "easytier_config_server_invalid",
        "params": {},
    }


def test_switching_to_the_console_keeps_the_manual_network(box):
    client, _ = box
    a_network(client)

    client.post(
        "/api/hub/overlay/easytier/set",
        json=settings(mode="console", config_server=CONSOLE, network_secret=""),
    )

    stored = read_stored()
    assert stored.network_name == "neutrino-1234"
    assert stored.secret() == "a-network-secret"


def test_console_mode_shows_what_the_engine_runs(box):
    client, _ = box
    client.post("/api/hub/overlay/easytier/set", json=console(config_server=CONSOLE))

    payload = client.get("/api/hub/overlay/easytier").json()

    assert payload["instances"] == [
        {
            "instance_name": "",
            "network_name": "home",
            "address": "10.126.126.1/24",
            "hostname": "",
            "subnet_routes": ["192.168.100.0/24"],
            "withheld": ["hostname"],
        }
    ]
    assert payload["node"]["address"] == "10.126.126.1/24"


# --- suggesting -------------------------------------------------------------


def test_a_suggestion_stores_nothing_and_avoids_this_boxs_own_networks(box):
    client, _ = box

    suggestion = client.post("/api/hub/overlay/easytier/suggestion/create").json()

    assert suggestion["network_name"].startswith("neutrino-")
    assert suggestion["network_secret"]
    assert suggestion["address"] == "10.0.0.1/24"
    assert client.get("/api/hub/overlay/easytier").json()["network_name"] == ""
