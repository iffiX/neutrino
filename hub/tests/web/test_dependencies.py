"""The panel's one session cookie, named after the hub.

What these pin: the name is ``neutrino_session_`` and the first 12
characters of the hub's id, or the prefix alone while the identity file is
missing; a password login from loopback and from another address, and a
client's sign-in, each set that name and the next call reads it; over HTTPS
the same name, ``Secure``; the redirect from the port the panel left deletes
that name; and a cookie of another hub or of a 0.5 panel opens nothing.
"""

import json

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import neutrino_hub.utils.json_file
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web import auth
from neutrino_hub.web.auth import PanelTokenStore, SessionStore, hash_password
from neutrino_hub.web.dependencies import get_runtime, require_session, session_cookie
from neutrino_hub.web.https_redirect import PanelHttpsRedirectMiddleware
from neutrino_hub.web.origin_guard import OriginGuardMiddleware
from neutrino_hub.web.panel_sign_in import PanelSignInMiddleware
from neutrino_hub.web.routers.hub import auth as auth_router

HUB_ID = "a9cae9416662417c8f1e2d3c4b5a6978"  # scan: allow
COOKIE = "neutrino_session_a9cae9416662"
PASSWORD = "panel-password"  # scan: allow
LOOPBACK = ("127.0.0.1", 50000)
LAN = ("192.168.1.20", 50000)


class Runtime:
    """The settings, sessions and sign-in tokens the cookie path reads."""

    def __init__(self):
        self.settings = {
            "listen_port": 8080,
            "https_listen_port": 8444,
            "session_ttl_hours": 1,
        }
        self.sessions = SessionStore(
            password_hash=hash_password(PASSWORD), session_ttl_hours=1
        )
        self.panel_tokens = PanelTokenStore()
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """An empty config directory."""
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(auth, "WEB_LOGIN_LOCKOUT_STATE_PATH", tmp_path / "lockout")
    return tmp_path


@pytest.fixture
def identity(config_dir):
    """A config directory whose identity file holds ``HUB_ID``."""
    (config_dir / "web").mkdir()
    (config_dir / "web" / "identity.json").write_text(
        json.dumps({"id": HUB_ID, "name": "argon"})
    )
    return config_dir


def panel(runtime: Runtime, *, peer: tuple, scheme: str = "http") -> TestClient:
    """The panel's three middlewares in the app's order, over the login and a
    read that requires the session."""
    app = FastAPI()
    app.include_router(auth_router.router)

    @app.get("/api/hub/thing", dependencies=[Depends(require_session)])
    def read_thing() -> dict:
        return {"read": True}

    app.dependency_overrides[get_runtime] = lambda: runtime
    app.add_middleware(PanelSignInMiddleware, runtime=runtime)
    app.add_middleware(OriginGuardMiddleware)
    app.add_middleware(PanelHttpsRedirectMiddleware, runtime=runtime)
    return TestClient(
        app, base_url=f"{scheme}://testserver", client=peer, follow_redirects=False
    )


def test_the_cookie_is_named_after_the_hub_id(identity):
    assert session_cookie() == COOKIE


def test_a_panel_without_its_identity_file_names_the_prefix_alone(config_dir):
    assert session_cookie() == "neutrino_session_"


@pytest.mark.parametrize("peer", [LOOPBACK, LAN], ids=["loopback", "lan"])
def test_a_password_login_sets_the_cookie_the_next_call_reads(identity, peer):
    with panel(Runtime(), peer=peer) as opened:
        login = opened.post("/api/hub/auth/login", json={"password": PASSWORD})
        call = opened.get("/api/hub/thing")

    assert login.headers["set-cookie"].startswith(f"{COOKIE}=")
    assert "Secure" not in login.headers["set-cookie"]
    assert call.json() == {"read": True}


def test_a_login_without_the_identity_file_still_opens_a_session(config_dir):
    with panel(Runtime(), peer=LOOPBACK) as opened:
        login = opened.post("/api/hub/auth/login", json={"password": PASSWORD})
        call = opened.get("/api/hub/thing")

    assert login.headers["set-cookie"].startswith("neutrino_session_=")
    assert call.json() == {"read": True}


def test_a_client_sign_in_sets_the_cookie_the_next_call_reads(identity):
    registry = ClientRegistry()
    client_id = registry.create("laptop")
    registry.set_permission(client_id, ["web", "panel"])
    runtime = Runtime()
    token = runtime.panel_tokens.mint(client_id)

    with panel(runtime, peer=LOOPBACK) as opened:
        sign_in = opened.get(f"/?tkn={token}")
        call = opened.get("/api/hub/thing")

    assert sign_in.status_code == 302
    assert sign_in.headers["set-cookie"].startswith(f"{COOKIE}=")
    assert call.json() == {"read": True}


@pytest.mark.parametrize("peer", [LOOPBACK, LAN], ids=["loopback", "lan"])
def test_a_login_over_https_sets_the_cookie_secure_and_the_next_call_reads_it(
    identity, peer
):
    runtime = Runtime()
    runtime.settings["is_https_enabled"] = True

    with panel(runtime, peer=peer, scheme="https") as opened:
        login = opened.post("/api/hub/auth/login", json={"password": PASSWORD})
        call = opened.get("/api/hub/thing")

    assert login.headers["set-cookie"].startswith(f"{COOKIE}=")
    assert "Secure" in login.headers["set-cookie"]
    assert call.json() == {"read": True}


@pytest.mark.parametrize(
    "is_https_enabled, scheme", [(True, "http"), (False, "https")], ids=["on", "off"]
)
def test_the_redirect_from_the_port_left_deletes_the_cookie(
    identity, is_https_enabled, scheme
):
    runtime = Runtime()
    runtime.settings["is_https_enabled"] = is_https_enabled

    with panel(runtime, peer=LAN, scheme=scheme) as opened:
        answer = opened.get("/api/hub/thing")

    assert answer.status_code == 301
    assert answer.headers["set-cookie"].startswith(f"{COOKIE}=; Max-Age=0")


@pytest.mark.parametrize(
    "name", ["neutrino_session_ffffffffffff", "neutrino_session_8080"]
)
def test_a_cookie_of_another_hub_or_of_a_0_5_panel_opens_nothing(identity, name):
    runtime = Runtime()
    token = runtime.sessions.login(PASSWORD)

    with panel(runtime, peer=LAN) as opened:
        call = opened.get("/api/hub/thing", headers={"cookie": f"{name}={token}"})

    assert call.status_code == 401
    assert call.json()["detail"]["code"] == "not_authenticated"
