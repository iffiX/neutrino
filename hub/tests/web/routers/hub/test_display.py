"""The language and the palette the panel is drawn in, and the hub's update.

Two surfaces for two values: the page reads both before anybody has signed
in, and the Settings page writes each with the rest of the panel's own
settings. What is pinned here is that the read needs no session and answers
both at once, that a write naming neither leaves the stored ones alone, and
that a language or a palette nobody ships is refused by its code rather than
silently stored. The same read carries the hub's update while it runs and
for 30 minutes after, which the page follows across the panel's restart: its
stage, versions and end, never its lines or its log.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.hub_update.installer import HubUpdateInstaller
from neutrino_hub.modules.hub_update.state import HubUpdateRecord, HubUpdateStateFile
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import display as display_router
from neutrino_hub.web.routers.hub import setting as settings_router

DISPLAY_PATH = "/api/hub/display"
SETTING_PATH = "/api/hub/setting"
SET_PATH = "/api/hub/setting/set"


class FakeTasks:
    def __init__(self):
        self.running_stream = None

    def running(self, label: str):
        return self.running_stream


class NoPortsHeld:
    """A box where no other program listens on any port."""

    def ports(self, *, ignoring: str = "") -> set:
        return set()


class FakeRuntime:
    """The settings dictionary the panel keeps in memory, its tasks, and the
    box's listening ports."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.tasks = FakeTasks()
        self.listening_ports = NoPortsHeld()


@pytest.fixture(autouse=True)
def update_record(monkeypatch, tmp_path):
    """The update's record in the test's own directory, its unit stopped."""
    state = HubUpdateStateFile(path=tmp_path / "hub_update" / "state.json")
    installer = HubUpdateInstaller(
        checker=SimpleNamespace(),
        state=state,
        family="debian",
        unit_state_of=lambda unit: "inactive",
    )
    monkeypatch.setattr(display_router, "_update_installer", lambda: installer)
    return state


@pytest.fixture
def client(monkeypatch, tmp_path):
    stored: dict = {"listen_port": 8080, "language": "en", "theme": "dark"}
    restarts: list = []
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
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
        "update": None,
    }


def test_a_box_that_stores_neither_answers_english_and_dark():
    assert display_of({}) == {"language": "en", "theme": "dark", "update": None}


# --- the hub's update, followed with no session ---


def stamp(minutes_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


STEPS = [
    "downloading neutrino-hub_0.5.2_amd64.deb  41 MB",
    "25%  50%  75%  100%",
    "checked",
    "installing; the panel restarts now",
]


def update_record_of(stage: str, **overrides) -> HubUpdateRecord:
    values = {
        "stage": stage,
        "from_version": "0.5.1",
        "to_version": "0.5.2",
        "started_at": stamp(3),
        "output": "Setting up neutrino-hub (0.5.2) ...",
        "steps": list(STEPS),
    }
    values.update(overrides)
    return HubUpdateRecord(**values)


def test_an_update_under_way_is_shown_with_no_steps_and_no_log(update_record):
    update_record.save(update_record_of("installing"))

    assert display_of({})["update"] == {
        "stage": "installing",
        "from_version": "0.5.1",
        "to_version": "0.5.2",
        "finished_at": "",
    }


def test_an_update_that_ended_moments_ago_is_shown(update_record):
    finished = stamp(29)
    update_record.save(
        update_record_of(
            "installed", finished_at=finished, steps=[*STEPS, "installed 0.5.2", "done"]
        )
    )

    shown = display_of({})["update"]

    assert shown["stage"] == "installed"
    assert shown["finished_at"] == finished
    assert "steps" not in shown


def test_an_update_that_ended_long_ago_is_not_shown(update_record):
    update_record.save(update_record_of("rolled_back", finished_at=stamp(31)))

    assert display_of({})["update"] is None


def test_an_update_whose_install_died_is_shown_as_interrupted(update_record):
    update_record.save(update_record_of("installing"))
    moment = time.time() - 60
    os.utime(update_record.path, (moment, moment))

    shown = display_of({})["update"]

    assert shown["stage"] == "failed"
    assert shown["finished_at"].endswith("Z")


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

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "language_unknown"
    assert stored["language"] == "en"


def test_a_theme_this_panel_does_not_have_is_refused(client):
    opened, _, stored, _ = client

    response = opened.post(SET_PATH, json={"listen_port": 8080, "theme": "neon"})

    assert response.status_code == 400
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
