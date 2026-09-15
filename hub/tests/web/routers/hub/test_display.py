"""The language and the palette the panel is drawn in.

Two surfaces for two values: the page reads both before anybody has signed
in, and the Settings page writes each with the rest of the panel's own
settings. What is pinned here is that the read needs no session and answers
both at once, that a write naming neither leaves the stored ones alone, and
that a language or a palette nobody ships is refused by its code rather than
silently stored.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import display as display_router
from neutrino_hub.web.routers.hub import setting as settings_router

DISPLAY_PATH = "/api/hub/display"
SETTING_PATH = "/api/hub/setting"
SET_PATH = "/api/hub/setting/set"


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
    app.include_router(display_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, runtime, stored, restarts


def display_of(settings: dict) -> dict:
    """What a panel storing these settings is drawn in, asked with no session."""
    app = FastAPI()
    app.include_router(display_router.router)
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime(settings)
    with TestClient(app) as opened:
        response = opened.get(DISPLAY_PATH)
    assert response.status_code == 200
    return response.json()


def test_the_display_is_answered_before_there_is_a_session():
    """The login card is the one screen a session cannot word or colour."""
    assert display_of({"language": "zh-CN", "theme": "light"}) == {
        "language": "zh-CN",
        "theme": "light",
    }


def test_a_box_that_stores_neither_answers_english_and_dark():
    assert display_of({}) == {"language": "en", "theme": "dark"}


def test_the_settings_carry_both(client):
    opened, _, _, _ = client

    settings = opened.get(SETTING_PATH).json()

    assert settings["language"] == "en"
    assert settings["theme"] == "dark"


def test_a_new_language_is_written_and_nothing_restarts(client):
    opened, runtime, stored, restarts = client

    response = opened.post(SET_PATH, json={"listen_port": 8080, "language": "zh-CN"})

    assert response.status_code == 200
    assert response.json()["language"] == "zh-CN"
    assert stored["language"] == "zh-CN"
    assert runtime.settings["language"] == "zh-CN"
    assert restarts == []


def test_a_new_theme_is_written_and_nothing_restarts(client):
    opened, runtime, stored, restarts = client

    response = opened.post(SET_PATH, json={"listen_port": 8080, "theme": "light"})

    assert response.status_code == 200
    assert response.json()["theme"] == "light"
    assert stored["theme"] == "light"
    assert runtime.settings["theme"] == "light"
    assert restarts == []


def test_a_language_this_panel_does_not_ship_is_refused(client):
    opened, _, stored, _ = client

    response = opened.post(SET_PATH, json={"listen_port": 8080, "language": "fr"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "language_unknown"
    assert stored["language"] == "en"


def test_a_theme_this_panel_does_not_have_is_refused(client):
    opened, _, stored, _ = client

    response = opened.post(SET_PATH, json={"listen_port": 8080, "theme": "neon"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "theme_unknown"
    assert stored["theme"] == "dark"


def test_a_write_naming_no_language_leaves_the_stored_one(client):
    """The panel port is written from a panel that knows nothing of this."""
    opened, _, stored, _ = client
    opened.post(SET_PATH, json={"listen_port": 8080, "language": "zh-CN"})

    response = opened.post(SET_PATH, json={"listen_port": 9443})

    assert response.status_code == 200
    assert response.json()["language"] == "zh-CN"
    assert stored["language"] == "zh-CN"


def test_a_write_naming_no_theme_leaves_the_stored_one(client):
    """The language is written from a panel that knows nothing of this."""
    opened, _, stored, _ = client
    opened.post(SET_PATH, json={"listen_port": 8080, "theme": "system"})

    response = opened.post(SET_PATH, json={"listen_port": 8080, "language": "en"})

    assert response.status_code == 200
    assert response.json()["theme"] == "system"
    assert stored["theme"] == "system"
