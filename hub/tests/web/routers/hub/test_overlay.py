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

from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
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
def box(monkeypatch):
    """A gateway on NetBird, with the converge step replaced."""
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


def test_the_view_has_one_switch_per_engine_and_no_none(box):
    client, _ = box

    payload = client.get("/api/hub/overlay").json()

    assert [entry["key"] for entry in payload["kinds"]] == [
        OVERLAY_NETBIRD,
        OVERLAY_EASYTIER,
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


# --- Switching --------------------------------------------------------------


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
