"""The Containers tab's API, with podman replaced by a recorder.

The rule with teeth: a declared container is driven through systemd, an
ad-hoc one through podman — mixing those up leaves systemd supervising a
container it believes crashed.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.podman.config import PodmanConfig
from neutrino_hub.modules.podman.ops import PodmanContainerState
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import podman as podman_router


class FakeReader:
    """Two containers exist: one declared, one someone ran by hand."""

    def survey(self, *, declared_names):
        return [
            PodmanContainerState(
                name="webdav",
                image="nginx",
                status="Up 2 hours",
                is_running=True,
                is_declared="webdav" in declared_names,
            ),
            PodmanContainerState(
                name="stray",
                image="alpine",
                status="Exited",
                is_running=False,
                is_declared=False,
            ),
        ]


class FakeController:
    performed: list[tuple] = []

    def control(self, name, action, *, is_declared):
        FakeController.performed.append((name, action, is_declared))


class FakeServices:
    def status(self, name):
        return ServiceStatus(
            name=name,
            unit="podman.socket",
            is_installed=True,
            is_active=True,
            is_enabled=True,
        )


class FakeRuntime:
    def __init__(self, config: PodmanConfig):
        self._config = config
        self.services = FakeServices()
        self.applied_count = 0

    def podman(self) -> PodmanConfig:
        return PodmanConfig.from_dict(self._config.to_dict())

    def write_podman(self, config: PodmanConfig) -> None:
        config.validate()
        self._config = config

    async def apply_podman(self) -> str:
        self.applied_count += 1
        return "containers: webdav.container"


@pytest.fixture
def box(monkeypatch):
    FakeController.performed = []
    runtime = FakeRuntime(
        PodmanConfig.from_dict({"containers": [{"name": "webdav", "image": "nginx"}]})
    )
    monkeypatch.setattr(podman_router, "PodmanStatusReader", FakeReader)
    monkeypatch.setattr(podman_router, "PodmanContainerController", FakeController)
    monkeypatch.setattr(podman_router.shutil, "which", lambda name: "/usr/bin/podman")
    monkeypatch.setattr(
        podman_router,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "podman version 4.9.3"})(),
    )

    app = FastAPI()
    app.include_router(podman_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_the_view_separates_declared_from_ad_hoc(box):
    client, _ = box

    payload = client.get("/api/podman").json()

    assert [c["name"] for c in payload["containers"]] == ["webdav"]
    by_name = {entry["name"]: entry for entry in payload["running"]}
    assert by_name["webdav"]["is_declared"] is True
    assert by_name["stray"]["is_declared"] is False
    assert payload["version"] == "4.9.3"


def test_a_bad_declaration_is_refused_and_nothing_stored(box):
    client, runtime = box

    response = client.put(
        "/api/podman/containers",
        json={"containers": [{"name": "Bad Name", "image": "x"}]},
    )

    assert response.status_code == 400
    assert [c.name for c in runtime.podman().containers] == ["webdav"]


def test_each_container_is_driven_through_its_rightful_owner(box):
    """Declared through systemd, ad hoc through podman."""
    client, _ = box

    client.post("/api/podman/containers/webdav/restart")
    client.post("/api/podman/containers/stray/start")

    assert ("webdav", "restart", True) in FakeController.performed
    assert ("stray", "start", False) in FakeController.performed


def test_an_unknown_container_is_refused(box):
    client, _ = box

    response = client.post("/api/podman/containers/ghost/start")

    assert response.status_code == 404
    assert FakeController.performed == []


def test_apply_reports_what_it_did(box):
    client, runtime = box

    payload = client.post("/api/podman/apply").json()

    assert payload["is_applied"] is True
    assert runtime.applied_count == 1
