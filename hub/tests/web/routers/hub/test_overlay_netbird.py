"""The NetBird block's API, with the daemon, the disk and the converge step
replaced.

What is pinned is the kept setup key: a join that worked keeps it and
converges once, a join that failed keeps nothing, the key can be replaced or
forgotten without running ``netbird up``, and leaving keeps it.
"""

import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.netbird.config import read_stored
from neutrino_hub.modules.overlay.peer_latency import OverlayPeerLatencies
from neutrino_hub.modules.netbird.ops import NetbirdPeer, NetbirdState
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import overlay_netbird as netbird_router
from tests.conftest import unlock_vault

SETUP_KEY = "A1B2C3D4-0000-4000-8000-000000000000"  # scan: allow
OTHER_KEY = "E5F6A7B8-0000-4000-8000-000000000000"  # scan: allow


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

    def __init__(self, pushes: list):
        self.services = FakeServices()
        self._pushes = pushes
        self.peer_latencies = OverlayPeerLatencies(echo=lambda address: 41.6)
        self.peer_latencies.refresh(["100.64.0.9"])

    def network(self) -> RouterNetworkConfig:
        return RouterNetworkConfig.from_dict({"mode": "server", "interfaces": []})

    async def converge_network(self, *, only=None) -> str:
        self._pushes.append("converged")
        return "applied"


class FakeEnroller:
    """Records each join instead of running ``netbird up``."""

    joins: list = []
    leaves: int = 0
    refusal: Exception | None = None

    def join(self, *, setup_key: str, management_url: str = "") -> None:
        if FakeEnroller.refusal is not None:
            raise FakeEnroller.refusal
        FakeEnroller.joins.append((setup_key, management_url))

    def leave(self) -> None:
        if FakeEnroller.refusal is not None:
            raise FakeEnroller.refusal
        FakeEnroller.leaves += 1


class FakeReader:
    peers: list = []

    def survey(self) -> NetbirdState:
        return NetbirdState(
            is_installed=True,
            is_enrolled=True,
            fqdn="hub.netbird.cloud",
            peers=list(FakeReader.peers),
        )


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A gateway with an open vault, a fake daemon, and config/ under tmp."""
    FakeEnroller.joins = []
    FakeEnroller.leaves = 0
    FakeEnroller.refusal = None
    unlock_vault(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config_dir)
    monkeypatch.setattr(netbird_router, "NetbirdEnroller", FakeEnroller)
    monkeypatch.setattr(netbird_router, "NetbirdStatusReader", FakeReader)
    monkeypatch.setattr(netbird_router, "device_addresses", dict)
    pushes: list = []
    runtime = FakeRuntime(pushes)
    app = FastAPI()
    app.include_router(netbird_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, pushes


def test_a_join_that_worked_keeps_the_key_and_converges_once(box):
    client, pushes = box

    reply = client.post(
        "/api/hub/overlay/netbird/join",
        json={"setup_key": SETUP_KEY, "management_url": "https://nb.example.org"},
    )

    assert reply.status_code == 200
    assert reply.json()["has_setup_key"] is True
    stored = read_stored()
    assert stored.setup_key() == SETUP_KEY
    assert stored.management_url == "https://nb.example.org"
    assert pushes == ["converged"]


def test_a_join_that_failed_keeps_nothing(box):
    client, pushes = box
    FakeEnroller.refusal = subprocess.CalledProcessError(1, ["netbird", "up"])

    reply = client.post("/api/hub/overlay/netbird/join", json={"setup_key": SETUP_KEY})

    assert reply.status_code == 502
    assert reply.json()["detail"]["code"] == "overlay_join_failed"
    assert not read_stored().has_setup_key
    assert pushes == []


def test_setting_the_key_replaces_it_without_joining(box):
    client, pushes = box
    client.post(
        "/api/hub/overlay/netbird/join",
        json={"setup_key": SETUP_KEY, "management_url": "https://nb.example.org"},
    )

    reply = client.post(
        "/api/hub/overlay/netbird/setup_key/set", json={"setup_key": OTHER_KEY}
    )

    assert reply.status_code == 200
    assert FakeEnroller.joins == [(SETUP_KEY, "https://nb.example.org")]
    stored = read_stored()
    assert stored.setup_key() == OTHER_KEY
    assert stored.management_url == "https://nb.example.org"
    assert pushes == ["converged", "converged"]


def test_an_empty_key_forgets_the_kept_one_and_converges(box):
    client, pushes = box
    client.post("/api/hub/overlay/netbird/join", json={"setup_key": SETUP_KEY})

    reply = client.post(
        "/api/hub/overlay/netbird/setup_key/set", json={"setup_key": ""}
    )

    assert reply.json()["has_setup_key"] is False
    assert not read_stored().has_setup_key
    assert pushes == ["converged", "converged"]


def test_the_view_says_whether_a_key_is_kept(box):
    client, _ = box

    assert client.get("/api/hub/overlay/netbird").json()["has_setup_key"] is False
    client.post("/api/hub/overlay/netbird/join", json={"setup_key": SETUP_KEY})
    payload = client.get("/api/hub/overlay/netbird").json()

    assert payload["has_setup_key"] is True
    assert SETUP_KEY not in str(payload)


def test_leaving_keeps_the_key_and_converges(box):
    client, pushes = box
    client.post("/api/hub/overlay/netbird/join", json={"setup_key": SETUP_KEY})

    reply = client.post("/api/hub/overlay/netbird/leave")

    assert reply.status_code == 200
    assert FakeEnroller.leaves == 1
    assert read_stored().setup_key() == SETUP_KEY
    assert pushes == ["converged", "converged"]


def test_a_leave_the_daemon_refuses_is_reported(box):
    client, pushes = box
    FakeEnroller.refusal = subprocess.CalledProcessError(1, ["systemctl"])

    reply = client.post("/api/hub/overlay/netbird/leave")

    assert reply.status_code == 502
    assert reply.json()["detail"]["code"] == "overlay_leave_failed"
    assert pushes == []


def test_a_relayed_peer_the_daemon_gives_no_latency_shows_the_hubs_echo(box):
    """The engine reports none for a peer behind a relay; the hub's own
    echo, measured by the address sampler, fills the same field."""
    client, _ = box
    FakeReader.peers = [
        NetbirdPeer(
            fqdn="laptop.netbird.cloud",
            netbird_ip="100.64.0.9/16",
            is_connected=True,
            connection_type="Relayed",
            latency_ms=None,
        ),
        NetbirdPeer(
            fqdn="phone.netbird.cloud",
            netbird_ip="100.64.0.10",
            is_connected=True,
            connection_type="Relayed",
            latency_ms=None,
        ),
        NetbirdPeer(
            fqdn="desk.netbird.cloud",
            netbird_ip="100.64.0.11",
            is_connected=True,
            connection_type="P2P",
            latency_ms=7,
        ),
    ]
    try:
        peers = client.get("/api/hub/overlay/netbird").json()["peers"]
    finally:
        FakeReader.peers = []

    assert [(peer["fqdn"], peer["latency_ms"]) for peer in peers] == [
        ("laptop.netbird.cloud", 42),
        ("phone.netbird.cloud", None),
        ("desk.netbird.cloud", 7),
    ]
