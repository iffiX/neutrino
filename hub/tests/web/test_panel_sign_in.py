"""A client's sign-in to the panel through its forward, and the end of the
sessions it opened.

What these pin, row by row of the sign-in: a token that spends, on the HTTP
port from loopback, opens a session marked with the client and answers 302
to the same address without ``tkn``, keeping every other parameter; a token
used twice, one after its time, and one whose client was switched off or
lost ``panel`` since it was minted open nothing and answer the same 302; a
``tkn`` from another peer or over HTTPS is never looked up and is dropped by
the 302; a request with no ``tkn`` reaches the panel. A client's session ends
when it may no longer open the panel, and one that still may keeps it.
"""

import asyncio

import pytest

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web import auth
from neutrino_hub.web.auth import PanelTokenStore, SessionStore, hash_password
from neutrino_hub.web.panel_sign_in import (
    PanelSignInMiddleware,
    end_client_panel_sessions,
    split_token,
)

COOKIE = "neutrino_session_8080"
PASSWORD = "panel-password"  # scan: allow


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Runtime:
    def __init__(self):
        self.clock = Clock()
        self.panel_tokens = PanelTokenStore(clock=self.clock)
        self.sessions = SessionStore(
            password_hash=hash_password(PASSWORD), session_ttl_hours=1
        )
        self.settings = {"listen_port": 8080, "session_ttl_hours": 1}
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)


@pytest.fixture
def runtime(tmp_path, monkeypatch) -> Runtime:
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(auth, "WEB_LOGIN_LOCKOUT_STATE_PATH", tmp_path / "lockout")
    return Runtime()


@pytest.fixture
def panel_client() -> str:
    """A client that holds the panel permission."""
    registry = ClientRegistry()
    client_id = registry.create("laptop")
    registry.set_permission(client_id, ["web", "panel"])
    return client_id


def answer(runtime, target: str, *, peer: str = "127.0.0.1", scheme: str = "http"):
    """What the panel answers one GET, as ``(status, headers)``; status 200
    means the request reached the panel itself."""
    path, _, query = target.partition("?")
    sent: list = []

    async def panel(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "scheme": scheme,
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(b"host", b"panel-hub.localhost:20005")],
        "client": (peer, 50000),
    }
    asyncio.run(PanelSignInMiddleware(panel, runtime=runtime)(scope, receive, send))
    start = sent[0]
    headers = {}
    for name, value in start["headers"]:
        headers.setdefault(name.decode(), value.decode())
    return start["status"], headers


def cookie_session(headers: dict) -> str:
    cookie = headers.get("set-cookie", "")
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie and "Path=/" in cookie and "Secure" not in cookie
    return cookie.split(";")[0].split("=", 1)[1]


def test_a_token_from_loopback_opens_a_session_and_drops_only_itself(
    runtime, panel_client
):
    token = runtime.panel_tokens.mint(panel_client)

    status, headers = answer(runtime, f"/devices?tab=a&tkn={token}&b=x%20y")

    assert status == 302
    assert headers["location"] == "/devices?tab=a&b=x%20y"
    session = cookie_session(headers)
    assert runtime.sessions.is_valid(session)
    assert runtime.sessions.client_sessions() == [(session, panel_client)]


def test_a_token_alone_lands_on_the_root(runtime, panel_client):
    token = runtime.panel_tokens.mint(panel_client)

    status, headers = answer(runtime, f"/?tkn={token}")

    assert (status, headers["location"]) == (302, "/")
    assert "set-cookie" in headers


def test_a_token_used_twice_opens_one_session(runtime, panel_client):
    token = runtime.panel_tokens.mint(panel_client)
    answer(runtime, f"/?tkn={token}")

    status, headers = answer(runtime, f"/?tkn={token}")

    assert (status, headers["location"]) == (302, "/")
    assert "set-cookie" not in headers
    assert len(runtime.sessions.client_sessions()) == 1


def test_a_token_after_its_time_opens_nothing(runtime, panel_client):
    token = runtime.panel_tokens.mint(panel_client)
    runtime.clock.now += 61

    status, headers = answer(runtime, f"/?tkn={token}")

    assert (status, "set-cookie" in headers) == (302, False)
    assert runtime.sessions.client_sessions() == []


def test_a_token_of_a_client_switched_off_since_opens_nothing(runtime, panel_client):
    token = runtime.panel_tokens.mint(panel_client)
    ClientRegistry().set_disabled(panel_client, True)

    status, headers = answer(runtime, f"/?tkn={token}")

    assert (status, "set-cookie" in headers) == (302, False)


def test_a_token_of_a_client_that_lost_the_panel_since_opens_nothing(
    runtime, panel_client
):
    token = runtime.panel_tokens.mint(panel_client)
    ClientRegistry().set_permission(panel_client, ["web"])

    status, headers = answer(runtime, f"/?tkn={token}")

    assert (status, "set-cookie" in headers) == (302, False)


@pytest.mark.parametrize(
    "peer, scheme",
    [("192.168.1.20", "http"), ("10.0.0.5", "http"), ("127.0.0.1", "https")],
)
def test_a_token_from_another_peer_or_over_https_is_dropped_unread(
    runtime, panel_client, peer, scheme
):
    token = runtime.panel_tokens.mint(panel_client)

    status, headers = answer(runtime, f"/x?tkn={token}&y=1", peer=peer, scheme=scheme)

    assert (status, headers["location"], "set-cookie" in headers) == (
        302,
        "/x?y=1",
        False,
    )
    assert runtime.panel_tokens.spend(token) == (panel_client, "")


def test_a_request_with_no_token_reaches_the_panel(runtime):
    assert answer(runtime, "/devices?tab=a")[0] == 200


def test_the_token_is_split_from_the_query_as_it_arrived():
    assert split_token("a=1&tkn=T&b=%2F") == ("T", "a=1&b=%2F")
    assert split_token("tkn=T") == ("T", "")
    assert split_token("a=1") == (None, "a=1")
    assert split_token("") == (None, "")


def test_a_clients_sessions_end_once_it_may_not_open_the_panel_and_no_sooner(
    runtime, panel_client
):
    registry = ClientRegistry()
    other = registry.create("desk")
    registry.set_permission(other, ["panel"])
    mine = runtime.sessions.open_for_client(panel_client)
    theirs = runtime.sessions.open_for_client(other)
    password = runtime.sessions.login(PASSWORD)

    assert end_client_panel_sessions(runtime, why="permission taken") == []
    registry.set_permission(panel_client, ["web"])

    assert end_client_panel_sessions(runtime, why="permission taken") == [panel_client]
    assert not runtime.sessions.is_valid(mine)
    assert runtime.sessions.is_valid(theirs)
    assert runtime.sessions.is_valid(password)
