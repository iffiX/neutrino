"""The palette the panel is drawn in, held to the language's own contract.

Two surfaces for one value: the page reads it before anybody has signed in,
and the Settings tab writes it with the rest of the panel's own settings. What
is pinned here is that the read needs no session, that a write naming no theme
leaves the stored one alone, and that a theme this panel does not have is
refused by its code rather than silently stored.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import settings as settings_router
from neutrino_hub.web.routers import theme as theme_router


class FakeRuntime:
    """Just the settings dictionary the panel keeps in memory."""

    def __init__(self, settings: dict):
        self.settings = settings


@pytest.fixture
def client(monkeypatch):
    stored: dict = {"listen_port": 8080, "language": "en", "theme": "dark"}
    restarts: list = []
    monkeypatch.setattr(settings_router, "read_config", lambda name: dict(stored))
    monkeypatch.setattr(settings_router, "hub_name", lambda: "gateway")
    monkeypatch.setattr(
        settings_router, "write_config", lambda name, data: stored.update(data)
    )
    monkeypatch.setattr(
        settings_router, "_restart_panel", lambda: restarts.append("restarted")
    )
    runtime = FakeRuntime(stored)
    app = FastAPI()
    app.include_router(settings_router.router)
    app.include_router(theme_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, runtime, stored, restarts


def test_the_theme_is_answered_before_there_is_a_session():
    """The login card is drawn before a session can say which palette."""
    app = FastAPI()
    app.include_router(theme_router.router)
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime({"theme": "light"})

    with TestClient(app) as opened:
        response = opened.get("/api/theme")

    assert response.status_code == 200
    assert response.json() == {"theme": "light"}


def test_a_box_that_stores_no_theme_answers_dark():
    app = FastAPI()
    app.include_router(theme_router.router)
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime({})

    with TestClient(app) as opened:
        assert opened.get("/api/theme").json() == {"theme": "dark"}


def test_the_settings_carry_the_theme(client):
    opened, _, _, _ = client

    assert opened.get("/api/settings").json()["theme"] == "dark"


def test_a_new_theme_is_written_and_nothing_restarts(client):
    opened, runtime, stored, restarts = client

    response = opened.put("/api/settings", json={"listen_port": 8080, "theme": "light"})

    assert response.status_code == 200
    assert response.json()["theme"] == "light"
    assert stored["theme"] == "light"
    assert runtime.settings["theme"] == "light"
    assert restarts == []


def test_a_theme_this_panel_does_not_have_is_refused(client):
    opened, _, stored, _ = client

    response = opened.put("/api/settings", json={"listen_port": 8080, "theme": "neon"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "theme_unknown"
    assert stored["theme"] == "dark"


def test_a_write_naming_no_theme_leaves_the_stored_one(client):
    """The language is written from a panel that knows nothing of this."""
    opened, _, stored, _ = client
    opened.put("/api/settings", json={"listen_port": 8080, "theme": "system"})

    response = opened.put("/api/settings", json={"listen_port": 8080, "language": "en"})

    assert response.status_code == 200
    assert response.json()["theme"] == "system"
    assert stored["theme"] == "system"
