"""The Overlay chooser's API, with the machine underneath it replaced.

Nothing here installs anything: the switcher and the network apply are fakes,
and what is asserted is the order the route does its work in and what it
refuses. The refusals matter most — an overlay is how somebody reaches this
box from outside, so a chooser that half-applies is a chooser that can strand
a person.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_NETBIRD,
    OVERLAY_NONE,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import overlay as overlay_router


class FakeServices:
    """Systemd, as far as the chooser reads it."""

    def __init__(self, running: set):
        self._running = running

    def status(self, name: str) -> ServiceStatus:
        if name not in ("netbird", "cliproxyapi", "xray"):
            raise KeyError(name)
        return ServiceStatus(
            name=name,
            unit=f"{name}.service",
            is_installed=name in self._running,
            is_active=name in self._running,
            is_enabled=name in self._running,
        )


class FakeRuntime:
    """Just the parts of :class:`PanelRuntime` the Overlay routes reach for."""

    def __init__(self, config: RouterNetworkConfig, running: set):
        self._config = config
        self.services = FakeServices(running)
        self.applied: list = []

    def network(self) -> RouterNetworkConfig:
        return RouterNetworkConfig.from_dict(self._config.to_dict())

    def write_network(self, config: RouterNetworkConfig) -> None:
        self._config = config

    async def apply_network(self, *, only=None) -> str:
        self.applied.append(only)
        return "applied"


class FakeSwitcher:
    """Records what it was told to run instead of running it."""

    converged: list = []
    refusal: Exception | None = None

    def converge(self, provider: str, *, report=None) -> str:
        FakeSwitcher.converged.append(provider)
        if FakeSwitcher.refusal is not None:
            raise FakeSwitcher.refusal
        return "started"


@pytest.fixture
def box(monkeypatch):
    """A gateway on NetBird, with the switcher and the apply replaced."""
    FakeSwitcher.converged = []
    FakeSwitcher.refusal = None
    runtime = FakeRuntime(
        RouterNetworkConfig.from_dict(
            {"mode": "router", "overlays": [{"provider": OVERLAY_NETBIRD}]}
        ),
        running={"netbird"},
    )
    monkeypatch.setattr(overlay_router, "OverlaySwitcher", lambda: FakeSwitcher())

    app = FastAPI()
    app.include_router(overlay_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def kinds_of(payload: dict) -> dict:
    return {entry["key"]: entry for entry in payload["kinds"]}


# --- Reading ----------------------------------------------------------------


def test_the_view_names_the_stored_overlay_and_every_choice(box):
    client, _ = box

    payload = client.get("/api/overlay").json()

    assert payload["provider"] == OVERLAY_NETBIRD
    assert [entry["key"] for entry in payload["kinds"]] == [
        OVERLAY_NONE,
        OVERLAY_NETBIRD,
        OVERLAY_EASYTIER,
    ]


def test_a_running_engine_reads_as_running(box):
    client, _ = box

    kinds = kinds_of(client.get("/api/overlay").json())

    assert kinds[OVERLAY_NETBIRD]["is_active"]
    assert kinds[OVERLAY_NETBIRD]["is_integrated"]
    assert kinds[OVERLAY_NETBIRD]["title"] == "NetBird"


def test_an_engine_this_hub_does_not_run_yet_says_so(box):
    client, _ = box

    kinds = kinds_of(client.get("/api/overlay").json())

    assert kinds[OVERLAY_EASYTIER]["is_integrated"] is False
    assert kinds[OVERLAY_EASYTIER]["is_installed"] is False


def test_no_overlay_reads_as_none(box):
    client, runtime = box
    runtime.write_network(
        RouterNetworkConfig.from_dict({"mode": "router", "overlays": []})
    )

    assert client.get("/api/overlay").json()["provider"] == OVERLAY_NONE


# --- Choosing ---------------------------------------------------------------


def test_leaving_every_overlay_writes_no_row_and_stands_the_engines_down(box):
    client, runtime = box

    payload = client.put("/api/overlay", json={"provider": OVERLAY_NONE}).json()

    assert payload["provider"] == OVERLAY_NONE
    assert runtime.network().overlays == []
    assert FakeSwitcher.converged == [OVERLAY_NONE]
    assert runtime.applied == [None]


def test_choosing_the_stored_overlay_still_makes_the_machine_agree(box):
    client, runtime = box

    client.put("/api/overlay", json={"provider": OVERLAY_NETBIRD})

    assert FakeSwitcher.converged == [OVERLAY_NETBIRD]
    assert runtime.applied == [None]


def test_the_row_is_written_before_the_engine_is_started(box):
    client, runtime = box
    client.put("/api/overlay", json={"provider": OVERLAY_NONE})
    FakeSwitcher.refusal = OSError("the daemon refused")

    response = client.put("/api/overlay", json={"provider": OVERLAY_NETBIRD})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "overlay_switch_failed"
    # The membership is stored, so the page and the next apply agree with what
    # was asked for rather than with what failed.
    assert runtime.network().overlays[0].provider == OVERLAY_NETBIRD


def test_an_overlay_nobody_runs_is_refused(box):
    client, runtime = box

    response = client.put("/api/overlay", json={"provider": "tailscale"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "overlay_unknown_provider"
    assert FakeSwitcher.converged == []
    assert runtime.network().overlays[0].provider == OVERLAY_NETBIRD


def test_an_engine_this_hub_does_not_run_yet_is_refused(box):
    client, runtime = box

    response = client.put("/api/overlay", json={"provider": OVERLAY_EASYTIER})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "overlay_not_integrated"
    assert detail["params"] == {"title": "EasyTier"}
    assert FakeSwitcher.converged == []


def test_a_machine_with_no_build_of_the_engine_is_refused(box, monkeypatch):
    client, _ = box
    monkeypatch.setattr(overlay_router, "_is_supported", lambda name: False)

    response = client.put("/api/overlay", json={"provider": OVERLAY_NETBIRD})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "overlay_not_supported"
    assert FakeSwitcher.converged == []
