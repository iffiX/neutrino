"""The EasyTier sections' API, with the engine and the disk replaced.

The network is a name and a secret this hub owns, so what is pinned here is
where the secret lives (sealed, never in the view) and what the writes refuse
before the engine is handed something it would read as a different network.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.easytier.ops import EasyTierPeer
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import easytier as easytier_router
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

    def network(self) -> RouterNetworkConfig:
        return self._network


class FakeApplier:
    """Records what it was asked to apply instead of applying it."""

    applied: list = []
    refusal: Exception | None = None

    def apply(self, config, *, hostname: str) -> str:
        if FakeApplier.refusal is not None:
            raise FakeApplier.refusal
        FakeApplier.applied.append((config.network_name, hostname))
        return "applied"


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A gateway with an open vault, a fake engine, and config/ under tmp."""
    FakeApplier.applied = []
    FakeApplier.refusal = None
    unlock_vault(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config_dir)
    monkeypatch.setattr(easytier_router, "EasyTierConfigApplier", FakeApplier)
    monkeypatch.setattr(easytier_router, "EasyTierStatusReader", lambda: _Reader(PEERS))
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


def a_network(client) -> dict:
    """Store a network, the way the panel's first Apply does."""
    return client.put(
        "/api/easytier",
        json={
            "network_name": "neutrino-1234",
            "network_secret": "a-network-secret",
            "address": "10.0.0.1/24",
            "hostname": "",
        },
    ).json()


# --- reading ----------------------------------------------------------------


def test_a_box_with_no_network_says_so(box):
    client, _ = box

    payload = client.get("/api/easytier").json()

    assert payload["network_name"] == ""
    assert payload["is_secret_set"] is False
    assert payload["node"] is None


def test_this_machines_own_networks_are_offered_for_export(box):
    client, _ = box

    payload = client.get("/api/easytier").json()

    assert [entry["cidr"] for entry in payload["suggested_networks"]] == [
        "192.168.100.0/24",
        "198.51.100.0/25",
    ]


def test_the_uplinks_address_is_what_another_machine_dials(box):
    client, _ = box

    assert client.get("/api/easytier").json()["join_host"] == "198.51.100.9"


def test_the_secret_is_never_in_the_view(box):
    client, _ = box
    a_network(client)

    payload = client.get("/api/easytier").json()

    assert payload["is_secret_set"] is True
    assert "a-network-secret" not in str(payload)


def test_the_secret_is_handed_over_where_it_is_asked_for(box):
    client, _ = box
    a_network(client)

    reply = client.get("/api/easytier/secret").json()

    assert reply["network_secret"] == "a-network-secret"


def test_the_peers_are_the_others_and_this_box_is_the_node(box):
    client, _ = box
    a_network(client)

    payload = client.get("/api/easytier").json()

    assert [peer["hostname"] for peer in payload["live_peers"]] == ["laptop"]
    assert payload["live_peers"][0]["rx_bytes"] == 917
    assert payload["node"]["is_connected"] is True
    assert payload["node"]["hostname"] == "neutrino"


# --- writing ----------------------------------------------------------------


def test_storing_a_network_applies_it(box):
    client, _ = box

    payload = a_network(client)

    assert payload["network_name"] == "neutrino-1234"
    assert payload["address"] == "10.0.0.1/24"
    assert FakeApplier.applied and FakeApplier.applied[0][0] == "neutrino-1234"


def test_an_empty_secret_keeps_the_one_already_stored(box):
    client, _ = box
    a_network(client)

    client.put(
        "/api/easytier",
        json={
            "network_name": "neutrino-1234",
            "network_secret": "",
            "address": "10.0.0.2/24",
            "hostname": "",
        },
    )

    assert client.get("/api/easytier/secret").json()["network_secret"] == (
        "a-network-secret"
    )


def test_a_first_network_with_no_secret_is_refused(box):
    client, _ = box

    response = client.put(
        "/api/easytier",
        json={"network_name": "neutrino-1234", "network_secret": "", "address": ""},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_secret_missing"


def test_a_name_that_could_hide_in_a_relay_whitelist_is_refused(box):
    client, _ = box

    response = client.put(
        "/api/easytier",
        json={
            "network_name": "two words",
            "network_secret": "a-network-secret",
            "address": "",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_name_invalid"


def test_an_address_with_no_prefix_is_refused(box):
    client, _ = box

    response = client.put(
        "/api/easytier",
        json={
            "network_name": "neutrino-1234",
            "network_secret": "a-network-secret",
            "address": "10.0.0.1",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_address_invalid"


def test_the_bootstrap_peers_are_stored_in_order(box):
    client, _ = box
    a_network(client)

    payload = client.put(
        "/api/easytier/peers",
        json={"peers": ["tcp://198.51.100.7:11010", "txt://net.example.com"]},
    ).json()

    assert payload["peers"] == ["tcp://198.51.100.7:11010", "txt://net.example.com"]


def test_an_address_the_engine_would_not_dial_is_refused(box):
    client, _ = box
    a_network(client)

    response = client.put("/api/easytier/peers", json={"peers": ["example.com:11010"]})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "easytier_peer_invalid"
    assert detail["params"] == {"uri": "example.com:11010"}


def test_the_exported_networks_are_stored(box):
    client, _ = box
    a_network(client)

    payload = client.put(
        "/api/easytier/networks", json={"exported_networks": ["192.168.100.0/24"]}
    ).json()

    assert payload["exported_networks"] == ["192.168.100.0/24"]


def test_exporting_the_whole_internet_is_refused(box):
    client, _ = box
    a_network(client)

    response = client.put(
        "/api/easytier/networks", json={"exported_networks": ["0.0.0.0/0"]}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "easytier_network_invalid"


def test_an_engine_that_refuses_what_was_written_is_reported(box):
    client, _ = box
    FakeApplier.refusal = OSError("the engine refused")

    response = client.put(
        "/api/easytier",
        json={
            "network_name": "neutrino-1234",
            "network_secret": "a-network-secret",
            "address": "",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "easytier_apply_failed"


# --- suggesting -------------------------------------------------------------


def test_a_suggestion_stores_nothing_and_avoids_this_boxs_own_networks(box):
    client, _ = box

    suggestion = client.post("/api/easytier/suggestion").json()

    assert suggestion["network_name"].startswith("neutrino-")
    assert suggestion["network_secret"]
    assert suggestion["address"] == "10.0.0.1/24"
    assert client.get("/api/easytier").json()["network_name"] == ""
