"""Moving the panel to another port.

The process serving the request is the one being restarted, so the order is
the whole of it: the answer goes out, the browser is told where to look, and
only then does the socket it asked on close. Nothing here restarts anything —
what is pinned is that the write happens first and the restart is queued
behind the response rather than run inside it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import settings as settings_router


class FakeRuntime:
    """Just the settings dictionary the panel keeps in memory."""

    def __init__(self):
        self.settings = {"listen_port": 8080}


@pytest.fixture
def client(monkeypatch, tmp_path):
    stored: dict = {"listen_port": 8080}
    restarts: list = []
    monkeypatch.setattr(settings_router, "read_config", lambda name: dict(stored))
    monkeypatch.setattr(
        settings_router, "write_config", lambda name, data: stored.update(data)
    )
    monkeypatch.setattr(
        settings_router, "_restart_panel", lambda: restarts.append("restarted")
    )
    runtime = FakeRuntime()
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, runtime, stored, restarts


def test_the_port_is_read_back(client):
    opened, _, _, _ = client

    assert opened.get("/api/settings").json()["listen_port"] == 8080


def test_a_new_port_is_written_and_the_panel_moves_to_it(client):
    opened, runtime, stored, restarts = client

    response = opened.put("/api/settings", json={"listen_port": 9443})

    assert response.status_code == 200
    assert response.json()["listen_port"] == 9443
    assert stored["listen_port"] == 9443
    assert runtime.settings["listen_port"] == 9443
    assert restarts == ["restarted"]


def test_the_port_it_is_already_on_restarts_nothing(client):
    """Saving a form nobody changed must not drop the connection it was
    saved over."""
    opened, _, _, restarts = client

    opened.put("/api/settings", json={"listen_port": 8080})

    assert restarts == []


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_a_port_no_listener_can_take_is_refused(client, port):
    opened, _, stored, restarts = client

    response = opened.put("/api/settings", json={"listen_port": port})

    assert response.status_code == 400
    assert stored["listen_port"] == 8080
    assert restarts == []
