"""The Gitea tab's API, with the CLI underneath replaced.

What matters here is the request path and the one gate with teeth: the panel
makes the first administrator and refuses to make a second, because every
later account belongs inside Gitea.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.gitea.ops import GiteaState
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import gitea as gitea_router


class FakeAdminManager:
    """The server is installed; which admins exist is the dial."""

    def __init__(self):
        self.admins: list[str] = []
        self.created: list[str] = []
        self.password_reset_for: list[str] = []

    def survey(self) -> GiteaState:
        return GiteaState(
            is_installed=True, version="1.24.3", admin_usernames=list(self.admins)
        )

    def create_admin(self, *, username, password, email):
        self.created.append(username)
        self.admins.append(username)

    def change_password(self, *, username, password):
        self.password_reset_for.append(username)


class FakeServices:
    def status(self, name: str) -> ServiceStatus:
        return ServiceStatus(
            name=name,
            unit=f"{name}.service",
            is_installed=True,
            is_active=True,
            is_enabled=True,
        )


class FakeRuntime:
    def __init__(self, config: GiteaConfig):
        self._config = config
        self.services = FakeServices()
        self.applied_count = 0

    def gitea(self) -> GiteaConfig:
        return GiteaConfig.from_dict(self._config.to_dict())

    def write_gitea(self, config: GiteaConfig) -> None:
        config.validate()
        self._config = config

    async def apply_gitea(self) -> str:
        self.applied_count += 1
        return "restarted gitea"


@pytest.fixture
def box(monkeypatch):
    runtime = FakeRuntime(GiteaConfig())
    manager = FakeAdminManager()
    monkeypatch.setattr(gitea_router, "GiteaAdminManager", lambda: manager)

    app = FastAPI()
    app.include_router(gitea_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, manager


def test_the_view_reports_config_beside_reality(box):
    client, _, _ = box

    payload = client.get("/api/gitea").json()

    assert payload["listen_port"] == 3000
    assert payload["is_installed"] is True
    assert payload["version"] == "1.24.3"
    assert payload["has_admin"] is False


def test_saving_settings_stores_them(box):
    client, runtime, _ = box

    response = client.put(
        "/api/gitea",
        json={"listen_port": 3100, "root_url": "", "is_registration_enabled": True},
    )

    assert response.status_code == 200
    assert runtime.gitea().listen_port == 3100
    assert runtime.gitea().is_registration_enabled is True


def test_a_port_the_gateway_owns_is_refused_and_nothing_stored(box):
    client, runtime, _ = box

    response = client.put(
        "/api/gitea",
        json={"listen_port": 80, "root_url": "", "is_registration_enabled": False},
    )

    assert response.status_code == 400
    assert runtime.gitea().listen_port == 3000


def test_the_first_admin_is_made_and_the_second_refused(box):
    """Later accounts belong inside Gitea, where managing them lives."""
    client, _, manager = box

    first = client.post(
        "/api/gitea/admin",
        json={"username": "ann", "password": "pw", "email": "a@b.c"},
    )
    second = client.post(
        "/api/gitea/admin",
        json={"username": "again", "password": "pw", "email": "a@b.c"},
    )

    assert first.status_code == 200
    assert first.json()["has_admin"] is True
    assert second.status_code == 409
    assert manager.created == ["ann"]


def test_apply_reports_what_it_did(box):
    client, runtime, _ = box

    payload = client.post("/api/gitea/apply").json()

    assert payload["is_applied"] is True
    assert runtime.applied_count == 1


def test_a_password_reset_lands_only_on_an_administrator(box):
    """The recovery door: a forgotten admin password cannot be fixed from a
    login screen it locks."""
    client, _, manager = box
    manager.admins.append("ann")

    good = client.post("/api/gitea/admin/ann/password", json={"password": "pw"})
    bad = client.post("/api/gitea/admin/ghost/password", json={"password": "pw"})

    assert good.status_code == 200
    assert bad.status_code == 404
    assert manager.password_reset_for == ["ann"]
