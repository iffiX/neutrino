"""The Services tab's API, with systemd replaced by a recorder.

The rule under test is the one that keeps the box reachable: a core unit can be
started and restarted but never stopped or disabled. The panel hides those
buttons, which is not the same as the gateway refusing them — a stopped
``neutrino_web`` takes the panel with it, so the refusal has to live where every
caller passes.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import service_control


class RecordingServices:
    """Every managed unit, running and enabled, and nothing actually done."""

    def __init__(self):
        self.performed: list[tuple[str, str]] = []

    def status(self, name: str) -> ServiceStatus:
        return ServiceStatus(
            name=name,
            unit=f"{name}.service",
            is_installed=True,
            is_active=True,
            is_enabled=True,
        )

    def status_all(self) -> list[ServiceStatus]:
        return [
            self.status(name)
            for name in (
                "xray",
                "router",
                "dnsmasq",
                "web",
                "netbird",
                "samba",
                "gitea",
            )
        ]

    def control(self, name: str, action: str) -> None:
        self.performed.append((name, action))


class FakeRuntime:
    def __init__(self, services: RecordingServices):
        self.services = services
        # The real task registry: cheap, and it exercises the actual
        # thread-to-stream bridge instead of a pretend one.
        from neutrino_hub.web.task_stream import TaskStreamRegistry

        self.tasks = TaskStreamRegistry()


@pytest.fixture
def box():
    services = RecordingServices()
    app = FastAPI()
    app.include_router(service_control.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime(services)
    with TestClient(app) as client:
        yield client, services


def test_the_view_says_which_units_are_core(box):
    client, _ = box

    payload = client.get("/api/services").json()

    core = {entry["name"] for entry in payload["services"] if entry["is_core"]}
    assert core == {"xray", "router", "dnsmasq", "web", "netbird"}


@pytest.mark.parametrize("name", ["xray", "router", "dnsmasq", "web", "netbird"])
@pytest.mark.parametrize("action", ["stop", "disable"])
def test_a_core_unit_cannot_be_stopped_or_disabled(box, name, action):
    client, services = box

    response = client.post(f"/api/services/{name}/{action}")

    assert response.status_code == 400
    assert services.performed == [], "systemd was asked anyway"


@pytest.mark.parametrize("action", ["start", "restart"])
def test_a_core_unit_can_still_be_started_and_restarted(box, action):
    """The refusal is about losing the gateway, not about touching it."""
    client, services = box

    response = client.post(f"/api/services/xray/{action}")

    assert response.status_code == 200
    assert services.performed == [("xray", action)]


@pytest.mark.parametrize("action", ["stop", "disable", "start", "enable"])
def test_an_optional_unit_takes_every_action(box, action):
    client, services = box

    response = client.post(f"/api/services/samba/{action}")

    assert response.status_code == 200
    assert services.performed == [("samba", action)]


class FakeProvisioner:
    """Provisions nothing, remembers everything."""

    performed: list[tuple] = []

    def provision(self, *, report=None):
        from neutrino_hub.system.provisioning import ProvisionResult

        if report is not None:
            report("pretending to install")
        FakeProvisioner.performed.append(("provision",))
        return ProvisionResult(is_changed=True, message="pretend-installed")

    def deprovision(self, *, is_data_kept=True, report=None):
        from neutrino_hub.system.provisioning import ProvisionResult

        FakeProvisioner.performed.append(("deprovision", is_data_kept))
        return ProvisionResult(is_changed=True, message="pretend-removed")


@pytest.fixture
def installable_box(box, monkeypatch):
    from neutrino_hub.modules.registry import ModuleSpec
    from neutrino_hub.web.routers import service_control

    FakeProvisioner.performed = []
    monkeypatch.setattr(
        service_control,
        "MODULE_SPECS",
        {
            "gitea": ModuleSpec(
                unit="gitea.service",
                provisioner=FakeProvisioner,
                architectures=("*",),
                install_note="",
                data_description="repositories",
            ),
            "narrow": ModuleSpec(
                unit="narrow.service",
                provisioner=FakeProvisioner,
                architectures=("never-built",),
                install_note="",
                data_description="",
            ),
        },
    )
    # systemctl enable --now must not reach the real systemd from a test.
    monkeypatch.setattr(service_control, "run", lambda *a, **k: None)
    return box


def drain_task(client, task_id: str) -> list[str]:
    with client.websocket_connect(f"/ws/task/{task_id}") as socket:
        lines = []
        while True:
            message = socket.receive_json()
            if message["type"] == "done":
                return lines
            lines.append(message["data"])


def test_install_streams_and_lands(installable_box):
    client, _ = installable_box

    started = client.post("/api/services/gitea/install").json()

    assert "task_id" in started
    assert ("provision",) in _wait_performed()


def test_uninstall_carries_the_data_decision(installable_box):
    client, _ = installable_box

    kept = client.post("/api/services/gitea/uninstall", json={"is_data_kept": True})
    deleted = client.post("/api/services/gitea/uninstall", json={"is_data_kept": False})

    assert kept.status_code == 200
    assert deleted.status_code == 200
    performed = _wait_performed(count=2)
    assert ("deprovision", True) in performed
    assert ("deprovision", False) in performed


def test_a_core_service_cannot_be_installed_or_removed(installable_box):
    """Core is not in the registry, so the answer is 404 rather than a rule."""
    client, _ = installable_box

    assert client.post("/api/services/xray/install").status_code == 404
    assert (
        client.post(
            "/api/services/xray/uninstall", json={"is_data_kept": True}
        ).status_code
        == 404
    )


def test_an_unsupported_machine_is_refused_before_anything_lands(installable_box):
    client, _ = installable_box

    response = client.post("/api/services/narrow/install")

    assert response.status_code == 400
    assert "never-built" in response.json()["detail"]
    assert FakeProvisioner.performed == []


def _wait_performed(count: int = 1) -> list[tuple]:
    import time

    for _ in range(50):
        if len(FakeProvisioner.performed) >= count:
            return FakeProvisioner.performed
        time.sleep(0.05)
    return FakeProvisioner.performed


def test_netbird_installs_from_the_panel_but_never_leaves(installable_box, monkeypatch):
    """The way back into the box goes in through the panel and never out."""
    from neutrino_hub.modules.registry import ModuleSpec
    from neutrino_hub.web.routers import service_control

    service_control.MODULE_SPECS["netbird"] = ModuleSpec(
        unit="netbird.service",
        provisioner=FakeProvisioner,
        architectures=("*",),
        install_note="",
        data_description="identity",
    )
    client, _ = installable_box

    installed = client.post("/api/services/netbird/install")
    removed = client.post(
        "/api/services/netbird/uninstall", json={"is_data_kept": True}
    )

    assert installed.status_code == 200
    assert removed.status_code == 400
    assert "core" in removed.json()["detail"]
