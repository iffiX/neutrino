"""The Overlay switches' API, with the machine underneath it replaced.

Nothing here installs anything: the converge step is a fake, and what is
asserted is what the route writes, in which order, and what it refuses. The
refusals matter most: an overlay is how somebody reaches this box from
outside, so a switch that half-applies is a switch that can strand a person.
"""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_NETBIRD,
    OVERLAY_RELAY,
)
from neutrino_hub.modules.overlay.relay_config import (
    OverlayRelayConfig,
    read_relay,
    write_relay,
)
from neutrino_hub.modules.overlay.route_check import OverlayRouteConflict
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import overlay as overlay_router


class FakeServices:
    """Systemd, as far as the switches read it."""

    def __init__(self, running: set):
        self._running = running

    def status(self, name: str) -> ServiceStatus:
        if name not in ("netbird", "easytier"):
            raise KeyError(name)
        return ServiceStatus(
            name=name,
            unit=f"{name}.service",
            is_installed=name in self._running,
            is_active=name in self._running,
            is_enabled=name in self._running,
        )


class FakeRelayMonitor:
    """Where the relay stands, as the monitor would say."""

    def __init__(self):
        self.state = "disabled"

    def view(self) -> dict:
        return {
            "state": self.state,
            "last_error": "",
            "host_key_fingerprint": "",
            "checked_at": "",
        }


class FakeSession:
    def __init__(self, address: str):
        self.address = address


class FakeSessions:
    def __init__(self, addresses: list):
        self._sessions = [FakeSession(address) for address in addresses]

    def sessions(self) -> list:
        return list(self._sessions)


class FakeRuntime:
    """Just the parts of :class:`PanelRuntime` the Overlay routes reach for."""

    def __init__(self, config: RouterNetworkConfig, running: set):
        self._config = config
        self.services = FakeServices(running)
        self.client_sessions = FakeSessions(["100.64.3.9", "192.168.100.20"])
        self.converged: list = []
        self.refusal: Exception | None = None
        self.overlay_route_conflicts: list = []
        self.relay_monitor = FakeRelayMonitor()

    def network(self) -> RouterNetworkConfig:
        return RouterNetworkConfig.from_dict(self._config.to_dict())

    def write_network(self, config: RouterNetworkConfig) -> None:
        self._config = config

    async def converge_network(self, *, only=None) -> str:
        self.converged.append(
            [overlay.provider for overlay in self._config.enabled_overlays]
        )
        if self.refusal is not None:
            raise self.refusal
        return "applied"


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A gateway on NetBird, with the converge step replaced."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(overlay_router, "ssh_path", lambda: "/usr/bin/ssh")
    runtime = FakeRuntime(
        RouterNetworkConfig.from_dict(
            {"mode": "router", "overlays": [{"provider": OVERLAY_NETBIRD}]}
        ),
        running={"netbird"},
    )
    monkeypatch.setattr(overlay_router, "_is_supported", lambda name: True)
    monkeypatch.setattr(
        overlay_router, "device_addresses", lambda: {"wt0": "100.64.0.1/16"}
    )
    monkeypatch.setattr(
        overlay_router,
        "overlay_subnets",
        lambda providers: {
            key: {OVERLAY_NETBIRD: ["100.64.0.0/10"], OVERLAY_EASYTIER: []}[key]
            for key in providers
        },
    )
    monkeypatch.setattr(
        overlay_router,
        "engine_devices",
        lambda provider: ["wt0"] if provider == OVERLAY_NETBIRD else ["easytier"],
    )

    app = FastAPI()
    app.include_router(overlay_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def kinds_of(payload: dict) -> dict:
    return {entry["key"]: entry for entry in payload["kinds"]}


# --- Reading ----------------------------------------------------------------


def test_the_view_has_one_switch_per_engine_then_the_relay_and_no_none(box):
    client, _ = box

    payload = client.get("/api/hub/overlay").json()

    assert [entry["key"] for entry in payload["kinds"]] == [
        OVERLAY_NETBIRD,
        OVERLAY_EASYTIER,
        OVERLAY_RELAY,
    ]
    kinds = kinds_of(payload)
    assert kinds[OVERLAY_NETBIRD]["is_enabled"] is True
    assert kinds[OVERLAY_EASYTIER]["is_enabled"] is False


def test_a_running_engine_reads_as_running(box):
    client, _ = box

    kinds = kinds_of(client.get("/api/hub/overlay").json())

    assert kinds[OVERLAY_NETBIRD]["is_active"]
    assert kinds[OVERLAY_NETBIRD]["title"] == "NetBird"
    assert kinds[OVERLAY_EASYTIER]["title"] == "EasyTier"


def test_the_clients_reaching_the_hub_through_an_engine_are_counted(box):
    """The apply bar's warning names how many people turning it off
    disconnects: a client counts when its socket comes from the engine's
    network."""
    client, _ = box

    kinds = kinds_of(client.get("/api/hub/overlay").json())

    assert kinds[OVERLAY_NETBIRD]["client_count"] == 1
    assert kinds[OVERLAY_EASYTIER]["client_count"] == 0


def test_the_relay_row_is_off_and_installed_where_ssh_is(box):
    client, _ = box

    relay = kinds_of(client.get("/api/hub/overlay").json())[OVERLAY_RELAY]

    assert relay["title"] == "Relay"
    assert relay["is_enabled"] is False
    assert relay["is_installed"] is True
    assert relay["is_active"] is False
    assert relay["client_count"] == 0


def test_a_connected_relay_is_active_and_counts_the_clients_from_loopback(box):
    client, runtime = box
    write_relay(OverlayRelayConfig(is_enabled=True, host="vps", account="r"))
    runtime.relay_monitor.state = "connected"
    runtime.client_sessions = FakeSessions(
        ["127.0.0.1", "127.0.0.1", "192.168.100.20", "::1"]
    )

    relay = kinds_of(client.get("/api/hub/overlay").json())[OVERLAY_RELAY]

    assert relay["is_enabled"] is True
    assert relay["is_active"] is True
    assert relay["client_count"] == 3


def test_the_relay_row_says_when_the_machine_has_no_ssh(box, monkeypatch):
    client, _ = box
    monkeypatch.setattr(overlay_router, "ssh_path", lambda: "")

    relay = kinds_of(client.get("/api/hub/overlay").json())[OVERLAY_RELAY]

    assert relay["is_installed"] is False


# --- Switching --------------------------------------------------------------


def test_turning_the_relay_on_writes_its_file_and_converges(box):
    client, runtime = box
    write_relay(OverlayRelayConfig(host="vps", account="relay", key_id="k1"))

    payload = client.post(
        "/api/hub/overlay/set", json={"relay": {"is_enabled": True}}
    ).json()

    assert kinds_of(payload)[OVERLAY_RELAY]["is_enabled"] is True
    assert read_relay().is_enabled is True
    assert read_relay().host == "vps"
    assert runtime.converged == [[OVERLAY_NETBIRD]]


def test_turning_the_relay_on_without_ssh_is_refused(box, monkeypatch):
    client, runtime = box
    monkeypatch.setattr(overlay_router, "ssh_path", lambda: "")

    response = client.post("/api/hub/overlay/set", json={"relay": {"is_enabled": True}})

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "relay_ssh_missing", "params": {}}
    assert read_relay().is_enabled is False
    assert runtime.converged == []


def test_turning_the_relay_off_needs_no_ssh(box, monkeypatch):
    client, _ = box
    write_relay(OverlayRelayConfig(is_enabled=True, host="vps"))
    monkeypatch.setattr(overlay_router, "ssh_path", lambda: "")

    response = client.post(
        "/api/hub/overlay/set", json={"relay": {"is_enabled": False}}
    )

    assert response.status_code == 200
    assert read_relay().is_enabled is False


def test_turning_a_second_engine_on_keeps_the_first(box):
    client, runtime = box

    payload = client.post(
        "/api/hub/overlay/set", json={"easytier": {"is_enabled": True}}
    ).json()

    assert kinds_of(payload)[OVERLAY_EASYTIER]["is_enabled"] is True
    assert runtime.converged == [[OVERLAY_NETBIRD, OVERLAY_EASYTIER]]


def test_turning_every_engine_off_keeps_the_rows(box):
    client, runtime = box

    client.post(
        "/api/hub/overlay/set",
        json={"netbird": {"is_enabled": False}, "easytier": {"is_enabled": False}},
    )

    assert runtime.converged == [[]]
    assert [overlay.provider for overlay in runtime.network().overlays] == [
        OVERLAY_NETBIRD
    ]
    assert runtime.network().overlays[0].is_enabled is False


def test_setting_what_is_stored_still_makes_the_machine_agree(box):
    client, runtime = box

    client.post("/api/hub/overlay/set", json={"netbird": {"is_enabled": True}})

    assert runtime.converged == [[OVERLAY_NETBIRD]]


def test_the_rows_are_written_before_the_converge(box):
    client, runtime = box
    runtime.refusal = OSError("the daemon refused")

    response = client.post(
        "/api/hub/overlay/set", json={"easytier": {"is_enabled": True}}
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "overlay_switch_failed"
    # The membership is stored, so the page and the next apply agree with what
    # was asked for rather than with what failed.
    assert [overlay.provider for overlay in runtime.network().enabled_overlays] == [
        OVERLAY_NETBIRD,
        OVERLAY_EASYTIER,
    ]


def test_the_old_single_provider_shape_turns_nothing_on(box):
    client, runtime = box

    client.post("/api/hub/overlay/set", json={"provider": "easytier"})

    assert runtime.network().overlay(OVERLAY_EASYTIER) is None


def test_an_engine_this_hub_does_not_run_yet_is_refused(box, monkeypatch):
    """An engine the table names but nothing provisions is offered and
    refused, rather than half started."""
    client, runtime = box
    engine = overlay_router.OVERLAY_ENGINES[OVERLAY_EASYTIER]
    monkeypatch.setitem(
        overlay_router.OVERLAY_ENGINES,
        OVERLAY_EASYTIER,
        replace(engine, is_integrated=False),
    )

    response = client.post(
        "/api/hub/overlay/set", json={"easytier": {"is_enabled": True}}
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "overlay_not_integrated"
    assert detail["params"] == {"title": "EasyTier"}
    assert runtime.converged == []


def test_a_machine_with_no_build_of_the_engine_is_refused(box, monkeypatch):
    client, runtime = box
    monkeypatch.setattr(overlay_router, "_is_supported", lambda name: False)

    response = client.post(
        "/api/hub/overlay/set", json={"easytier": {"is_enabled": True}}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "overlay_not_supported"
    assert runtime.converged == []


def test_turning_an_engine_off_needs_no_build_of_it(box, monkeypatch):
    client, runtime = box
    monkeypatch.setattr(overlay_router, "_is_supported", lambda name: False)

    response = client.post(
        "/api/hub/overlay/set", json={"netbird": {"is_enabled": False}}
    )

    assert response.status_code == 200
    assert runtime.converged == [[]]


# --- Networks that must not overlap -----------------------------------------


def test_an_engine_whose_network_overlaps_one_this_box_is_on_is_refused(
    box, monkeypatch
):
    client, runtime = box
    monkeypatch.setattr(
        overlay_router,
        "overlay_subnets",
        lambda providers: {
            key: {
                OVERLAY_NETBIRD: ["100.64.0.0/10"],
                OVERLAY_EASYTIER: ["10.0.0.0/24"],
            }[key]
            for key in providers
        },
    )
    monkeypatch.setattr(
        overlay_router,
        "device_addresses",
        lambda: {"wt0": "100.64.0.1/16", "enp1s0": "10.0.0.1/24"},
    )

    response = client.post(
        "/api/hub/overlay/set", json={"easytier": {"is_enabled": True}}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "overlay_subnet_overlap",
        "params": {
            "title": "EasyTier",
            "subnet": "10.0.0.0/24",
            "conflict": "10.0.0.0/24",
        },
    }
    assert runtime.converged == []
    assert runtime.network().overlay(OVERLAY_EASYTIER) is None


def test_two_overlays_on_one_network_are_refused(box, monkeypatch):
    client, _ = box
    monkeypatch.setattr(
        overlay_router,
        "overlay_subnets",
        lambda providers: {
            key: {
                OVERLAY_NETBIRD: ["100.64.0.0/10"],
                OVERLAY_EASYTIER: ["100.100.0.0/16"],
            }[key]
            for key in providers
        },
    )

    response = client.post(
        "/api/hub/overlay/set", json={"easytier": {"is_enabled": True}}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["params"]["conflict"] == "100.100.0.0/16"


def test_turning_an_engine_off_is_never_refused_for_an_overlap(box, monkeypatch):
    client, runtime = box
    monkeypatch.setattr(
        overlay_router,
        "device_addresses",
        lambda: {"enp1s0": "100.64.0.1/24"},
    )

    response = client.post(
        "/api/hub/overlay/set", json={"netbird": {"is_enabled": False}}
    )

    assert response.status_code == 200


# --- Routes the hub refused -------------------------------------------------


def test_the_refused_routes_are_named_on_the_page(box):
    client, runtime = box
    runtime.overlay_route_conflicts = [
        OverlayRouteConflict(
            provider=OVERLAY_NETBIRD,
            route="0.0.0.0/0",
            conflict="",
            is_withdrawn=True,
        ),
        OverlayRouteConflict(
            provider=OVERLAY_EASYTIER,
            route="192.168.100.0/24",
            conflict="192.168.100.0/24",
        ),
    ]

    conflicts = client.get("/api/hub/overlay").json()["route_conflicts"]

    assert conflicts == [
        {
            "code": "overlay_default_route_refused",
            "params": {"title": "NetBird", "route": "0.0.0.0/0", "conflict": ""},
            "is_withdrawn": True,
        },
        {
            "code": "overlay_route_overlap",
            "params": {
                "title": "EasyTier",
                "route": "192.168.100.0/24",
                "conflict": "192.168.100.0/24",
            },
            "is_withdrawn": False,
        },
    ]
