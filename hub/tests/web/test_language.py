"""The language the panel is drawn in.

Two surfaces for one value: the page reads it before anybody has signed in,
and the Settings tab writes it with the rest of the panel's own settings. What
is pinned here is that the read needs no session, that a write naming no
language leaves the stored one alone — the panel's port is written from a
panel of its own — and that a language nobody ships is refused by its code
rather than silently stored.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import language as language_router
from neutrino_hub.web.routers import settings as settings_router


class FakeRuntime:
    """Just the settings dictionary the panel keeps in memory."""

    def __init__(self, settings: dict):
        self.settings = settings


@pytest.fixture
def client(monkeypatch):
    stored: dict = {"listen_port": 8080, "language": "en"}
    restarts: list = []
    monkeypatch.setattr(settings_router, "read_config", lambda name: dict(stored))
    monkeypatch.setattr(
        settings_router, "write_config", lambda name, data: stored.update(data)
    )
    monkeypatch.setattr(
        settings_router, "_restart_panel", lambda: restarts.append("restarted")
    )
    runtime = FakeRuntime(stored)
    app = FastAPI()
    app.include_router(settings_router.router)
    app.include_router(language_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, runtime, stored, restarts


def test_the_language_is_answered_before_there_is_a_session():
    """The login card is the one screen a session cannot word."""
    app = FastAPI()
    app.include_router(language_router.router)
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime({"language": "zh-CN"})

    with TestClient(app) as opened:
        response = opened.get("/api/language")

    assert response.status_code == 200
    assert response.json() == {"language": "zh-CN"}


def test_a_box_that_stores_no_language_answers_english():
    app = FastAPI()
    app.include_router(language_router.router)
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime({})

    with TestClient(app) as opened:
        assert opened.get("/api/language").json() == {"language": "en"}


def test_the_settings_carry_the_language(client):
    opened, _, _, _ = client

    assert opened.get("/api/settings").json()["language"] == "en"


def test_a_new_language_is_written_and_nothing_restarts(client):
    opened, runtime, stored, restarts = client

    response = opened.put(
        "/api/settings", json={"listen_port": 8080, "language": "zh-CN"}
    )

    assert response.status_code == 200
    assert response.json()["language"] == "zh-CN"
    assert stored["language"] == "zh-CN"
    assert runtime.settings["language"] == "zh-CN"
    assert restarts == []


def test_a_language_this_panel_does_not_ship_is_refused(client):
    opened, _, stored, _ = client

    response = opened.put("/api/settings", json={"listen_port": 8080, "language": "fr"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "language_unknown"
    assert stored["language"] == "en"


def test_a_write_naming_no_language_leaves_the_stored_one(client):
    """The panel port is written from a panel that knows nothing of this."""
    opened, _, stored, _ = client
    opened.put("/api/settings", json={"listen_port": 8080, "language": "zh-CN"})

    response = opened.put("/api/settings", json={"listen_port": 9443})

    assert response.status_code == 200
    assert response.json()["language"] == "zh-CN"
    assert stored["language"] == "zh-CN"
