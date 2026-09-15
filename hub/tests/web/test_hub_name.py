"""The hub's name, written with the rest of the panel's own settings.

What is pinned is that the settings carry the name, that a write naming it
changes the identity file and nothing restarts, that a write leaving it out
leaves it as it is, and that a blank name is refused by its code.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web import identity
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.identity import ensure_hub_identity
from neutrino_hub.web.routers import settings as settings_router


class FakeRuntime:
    """Just the settings dictionary the panel keeps in memory."""

    def __init__(self, settings: dict):
        self.settings = settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    stored: dict = {"listen_port": 8080}
    restarts: list = []
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "gateway")
    ensure_hub_identity()
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
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, tmp_path, restarts


def identity_file(config_dir) -> dict:
    return json.loads((config_dir / "web" / "identity.json").read_text())


def test_the_settings_carry_the_name(client):
    opened, _, _ = client

    assert opened.get("/api/settings").json()["hub_name"] == "gateway"


def test_a_new_name_is_written_and_nothing_restarts(client):
    opened, config_dir, restarts = client
    before = identity_file(config_dir)

    response = opened.put(
        "/api/settings", json={"listen_port": 8080, "hub_name": "lab"}
    )

    assert response.status_code == 200
    assert response.json()["hub_name"] == "lab"
    assert identity_file(config_dir) == {"id": before["id"], "name": "lab"}
    assert restarts == []


def test_a_write_naming_no_hub_name_leaves_the_stored_one(client):
    opened, config_dir, _ = client
    opened.put("/api/settings", json={"listen_port": 8080, "hub_name": "lab"})

    response = opened.put("/api/settings", json={"listen_port": 8080, "theme": "light"})

    assert response.status_code == 200
    assert response.json()["hub_name"] == "lab"
    assert identity_file(config_dir)["name"] == "lab"


def test_a_blank_name_is_refused(client):
    opened, config_dir, _ = client

    response = opened.put("/api/settings", json={"listen_port": 8080, "hub_name": "  "})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "hub_name_required"
    assert identity_file(config_dir)["name"] == "gateway"
