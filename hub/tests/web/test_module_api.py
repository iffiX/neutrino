"""The Modules tab's API, with systemd replaced by a recorder.

The rule under test is the one that keeps the box reachable: a core unit can be
started and restarted but never stopped or disabled. The panel hides those
buttons, which is not the same as the gateway refusing them — a stopped
``neutrino_web`` takes the panel with it, so the refusal has to live where every
caller passes.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import modules as modules_router


class RecordingServices:
    """Every managed unit, running and enabled, and nothing actually done."""

    def __init__(self):
        self.performed: list[tuple[str, str]] = []
        self.installed = True

    def status(self, name: str) -> ServiceStatus:
        return ServiceStatus(
            name=name,
            unit=f"{name}.service",
            is_installed=self.installed,
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
def box(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    services = RecordingServices()
    app = FastAPI()
    app.include_router(modules_router.router)
    app.dependency_overrides[require_session] = lambda: None
    # One runtime for the whole fixture: a fresh one per request would give
    # every call its own task registry, and nothing that spans two requests —
    # a second install joining the first — could be seen at all.
    runtime = FakeRuntime(services)
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, services


def test_the_view_says_which_units_are_core(box):
    """Read against the declaration, so moving a module does not move a test."""
    client, services = box

    payload = client.get("/api/modules").json()

    listed = {entry["name"] for entry in payload["modules"]}
    core = {entry["name"] for entry in payload["modules"] if entry["is_core"]}
    assert core == listed & set(SYSTEM_CORE_UNITS)
    assert "netbird" in listed and "netbird" not in core


@pytest.mark.parametrize("name", ["xray", "router", "dnsmasq", "web"])
@pytest.mark.parametrize("action", ["stop", "disable"])
def test_a_core_unit_cannot_be_stopped_or_disabled(box, name, action):
    client, services = box

    response = client.post(f"/api/modules/{name}/{action}")

    assert response.status_code == 400
    assert services.performed == [], "systemd was asked anyway"


@pytest.mark.parametrize("action", ["start", "restart"])
def test_a_core_unit_can_still_be_started_and_restarted(box, action):
    """The refusal is about losing the gateway, not about touching it."""
    client, services = box

    response = client.post(f"/api/modules/xray/{action}")

    assert response.status_code == 200
    assert services.performed == [("xray", action)]


@pytest.mark.parametrize("action", ["stop", "disable", "start", "enable"])
def test_an_optional_unit_takes_every_action(box, action):
    client, services = box

    response = client.post(f"/api/modules/samba/{action}")

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
    from neutrino_hub.web.routers import modules as modules_router

    FakeProvisioner.performed = []
    monkeypatch.setattr(
        modules_router,
        "MODULE_SPECS",
        {
            "gitea": ModuleSpec(
                unit="neutrino_hub_gitea.service",
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
    monkeypatch.setattr(modules_router, "run", lambda *a, **k: None)
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

    started = client.post("/api/modules/gitea/install").json()

    assert "task_id" in started
    assert ("provision",) in _wait_performed()


def test_uninstall_carries_the_data_decision(installable_box):
    client, _ = installable_box

    kept = client.post("/api/modules/gitea/uninstall", json={"is_data_kept": True})
    deleted = client.post("/api/modules/gitea/uninstall", json={"is_data_kept": False})

    assert kept.status_code == 200
    assert deleted.status_code == 200
    performed = _wait_performed(count=2)
    assert ("deprovision", True) in performed
    assert ("deprovision", False) in performed


def test_a_core_service_cannot_be_installed_or_removed(installable_box):
    """Core is not in the registry, so the answer is 404 rather than a rule."""
    client, _ = installable_box

    assert client.post("/api/modules/xray/install").status_code == 404
    assert (
        client.post(
            "/api/modules/xray/uninstall", json={"is_data_kept": True}
        ).status_code
        == 404
    )


def test_an_unsupported_machine_is_refused_before_anything_lands(installable_box):
    client, _ = installable_box

    response = client.post("/api/modules/narrow/install")

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


def test_netbird_installs_and_uninstalls_from_the_panel(installable_box, monkeypatch):
    """Remote access is a capability, so it goes in and out like the others.

    It was core once, on the reasoning that removing the way back into the box
    is how somebody locks themselves out. A gateway routes, resolves and
    serves without it, and the machine that installs it is the one sitting in
    front of it.
    """
    from neutrino_hub.modules.registry import ModuleSpec
    from neutrino_hub.web.routers import modules as modules_router

    modules_router.MODULE_SPECS["netbird"] = ModuleSpec(
        unit="netbird.service",
        provisioner=FakeProvisioner,
        architectures=("*",),
        install_note="",
        data_description="identity",
    )
    client, _ = installable_box

    installed = client.post("/api/modules/netbird/install")
    removed = client.post("/api/modules/netbird/uninstall", json={"is_data_kept": True})

    assert installed.status_code == 200
    assert removed.status_code == 200


def test_a_module_that_is_not_installed_cannot_be_started(box):
    """systemd's own answer is "Unit x.service does not exist", which reaches
    the page as an error about a file when the thing to know is that the
    module was never installed."""
    opened, services = box
    services.installed = False

    response = opened.post("/api/modules/samba/action", json={"action": "start"})

    assert response.status_code == 400
    assert "not installed" in response.json()["detail"]


def test_a_journal_longer_than_the_limit_is_refused(box):
    """Unbounded, one call reads an entire unit journal into one response."""
    opened, _ = box

    assert opened.get("/api/modules/samba/journal?lines=100000000").status_code == 422
    assert opened.get("/api/modules/samba/journal?lines=-5").status_code == 422


def test_a_second_install_joins_the_first(box, monkeypatch):
    """Two downloads writing one path and two package managers on one lock:
    the second corrupts what the first fetched, and the browser only ever sees
    the log of whichever started last. Double-clicking Install is all it takes.
    """
    opened, _ = box
    monkeypatch.setattr(modules_router, "_install_source", _never_finishes)

    first = opened.post("/api/modules/samba/install")
    second = opened.post("/api/modules/samba/install")

    assert first.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]


def test_installing_another_module_is_its_own_job(box, monkeypatch):
    opened, _ = box
    monkeypatch.setattr(modules_router, "_install_source", _never_finishes)

    first = opened.post("/api/modules/samba/install")
    other = opened.post("/api/modules/gitea/install")

    assert first.json()["task_id"] != other.json()["task_id"]


def test_a_running_install_can_be_found_again(box, monkeypatch):
    """The task id lived in the browser and the job did not, so a reload used
    to leave a package manager running with a live Install button beside it."""
    opened, _ = box
    monkeypatch.setattr(modules_router, "_install_source", _never_finishes)
    started = opened.post("/api/modules/samba/install").json()

    listed = opened.get("/api/modules/tasks").json()["tasks"]

    assert listed == [{"id": started["task_id"], "label": "install samba"}]


def test_a_box_with_nothing_running_lists_nothing(box):
    opened, _ = box

    assert opened.get("/api/modules/tasks").json()["tasks"] == []


def test_a_finished_job_is_not_offered_to_adopt(box, monkeypatch):
    """Adopting one reopens a socket on a task that is over, which the stream
    hook reads as a transport failure rather than as a finished install."""
    opened, _ = box
    monkeypatch.setattr(modules_router, "_install_source", _finishes_at_once)
    opened.post("/api/modules/samba/install")

    for _ in range(20):
        listed = opened.get("/api/modules/tasks").json()["tasks"]
        if not listed:
            break

    assert listed == []


async def _never_finishes(name, spec, *, is_consented=False):
    """An install that is still going when the second press arrives."""
    yield f"installing {name}"
    await asyncio.sleep(30)


async def _finishes_at_once(name, spec, *, is_consented=False):
    """An install that is over before anything asks about it."""
    yield f"installed {name}"
