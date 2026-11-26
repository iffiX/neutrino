"""The session probe of ``/api/hub/auth``.

What these pin: ``is_opened_by_client`` is true for a session a client's
token opened and false for a password login and for no session at all.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web import auth
from neutrino_hub.web.auth import SessionStore, hash_password
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.routers.hub import auth as auth_routes

# The session cookie of a panel with no identity file.
COOKIE = "neutrino_session_"
PASSWORD = "panel-password"  # scan: allow


class Runtime:
    def __init__(self):
        self.sessions = SessionStore(
            password_hash=hash_password(PASSWORD), session_ttl_hours=1
        )
        self.settings = {"session_ttl_hours": 1}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(auth, "WEB_LOGIN_LOCKOUT_STATE_PATH", tmp_path / "lockout")
    app = FastAPI()
    app.include_router(auth_routes.router)
    runtime = Runtime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_a_session_a_client_s_token_opened_says_so(api):
    client, runtime = api
    client.cookies.set(COOKIE, runtime.sessions.open_for_client("laptop"))

    body = client.get("/api/hub/auth/session").json()

    assert body["is_authenticated"] is True
    assert body["is_opened_by_client"] is True


def test_a_password_session_and_no_session_are_not_a_client_s(api):
    client, runtime = api

    assert client.get("/api/hub/auth/session").json()["is_opened_by_client"] is False
    client.cookies.set(COOKIE, runtime.sessions.login(PASSWORD))

    body = client.get("/api/hub/auth/session").json()

    assert body["is_authenticated"] is True
    assert body["is_opened_by_client"] is False
