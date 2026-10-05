"""The terminal sockets, bridged to a device's shell stream end to end.

What these pin: the session gate, a device with no channel turned away
with ``agent_offline``, an agent's refusal sending a ``closing`` frame
with its code and params and then closing with its code, the
browser's input reaching the stream and a resize opening one ``command
{agent, resize}`` stream naming the shell, the stream's bytes becoming
output frames and its close an exit frame, the container variant
opening the ``shell`` kind with the module and the container's name, and
the close of a socket the browser already left raising nothing; the
session id the page generated riding the open stamped ``owner: hub``, a
persist message opening one ``command {agent, persist}`` naming it with
both flags, and a persist on a session another viewer owns answered with
a ``session_not_owned`` frame and sent nowhere; the panel joining a
client's unshared session, and the panel's unshare of its own session
closing every client's stream on it.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from neutrino_hub.web import ws
from neutrino_hub.web.dependencies import session_cookie
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.web.shell_bridge import ShellSessionLedger
from tests.conftest import FakeChannelSessions

MAC = "aa:bb:cc:dd:ee:ff"
SESSION_TOKEN = "panel-session"
# This panel answers on the default port, so its cookie is named for it.
SESSION_COOKIE = session_cookie(SimpleNamespace(settings={}))
POLICY_VIOLATION_CODE = 1008
INTERNAL_ERROR_CODE = 1011


class StubSessions:
    def is_valid(self, token) -> bool:
        return token == SESSION_TOKEN


class FakeRuntime:
    def __init__(self):
        self.settings: dict = {}
        self.sessions = StubSessions()
        self.agent_sessions = FakeChannelSessions(online=[MAC])
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.shell_ledger = ShellSessionLedger()


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(ws.router)
    runtime = FakeRuntime()
    app.state.runtime = runtime
    with TestClient(app) as client:
        yield client, runtime


def closed_with(socket) -> tuple:
    message = socket.receive()
    assert message["type"] == "websocket.close"
    return message["code"], message.get("reason", "")


def wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def open_terminal(client, path: str):
    socket = client.websocket_connect(path, cookies={SESSION_COOKIE: SESSION_TOKEN})
    socket.__enter__()
    return socket


def test_without_a_session_the_socket_is_turned_away(api):
    client, _ = api

    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect(f"/ws/agent/terminal?device_id={MAC}"):
            pass

    assert refusal.value.code == POLICY_VIOLATION_CODE


def test_a_device_with_no_channel_is_turned_away_as_offline(api):
    client, runtime = api
    runtime.agent_sessions.online.clear()

    socket = open_terminal(client, f"/ws/agent/terminal?device_id={MAC}")
    try:
        assert closed_with(socket) == (POLICY_VIOLATION_CODE, "agent_offline")
    finally:
        socket.__exit__(None, None, None)


def test_an_agents_refusal_closes_with_its_code(api):
    """The agent refuses by closing the stream with a code before any byte."""
    client, runtime = api
    runtime.agent_sessions.scripts["shell"] = lambda args: (
        [],
        {"code": "container_unknown", "params": {"name": "kuma"}},
    )

    socket = open_terminal(client, f"/ws/agent/terminal?device_id={MAC}&container=kuma")
    try:
        assert socket.receive_json() == {
            "type": "closing",
            "code": "container_unknown",
            "params": {"name": "kuma"},
        }
        assert closed_with(socket) == (INTERNAL_ERROR_CODE, "container_unknown")
    finally:
        socket.__exit__(None, None, None)


def test_a_refusals_params_reach_the_page_whole_before_the_close(api):
    """A path longer than a close reason holds still arrives whole."""
    client, runtime = api
    path = "/opt/" + "a" * 200 + "/shell"
    runtime.agent_sessions.scripts["shell"] = lambda args: (
        [],
        {"code": "shell_program_unusable", "params": {"path": path}},
    )

    socket = open_terminal(
        client, f"/ws/agent/terminal?device_id={MAC}&session_id={'a' * 32}"
    )
    try:
        frame = socket.receive_json()
        assert frame["type"] == "closing"
        assert frame["params"] == {"path": path}
        assert closed_with(socket) == (INTERNAL_ERROR_CODE, "shell_program_unusable")
    finally:
        socket.__exit__(None, None, None)


def test_input_and_resizes_reach_the_stream_and_output_and_exit_come_back(api):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent/terminal?device_id={MAC}")
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        stream = runtime.agent_sessions.streams[0]
        assert stream.kind == "shell"
        assert stream.args == {"cols": 80, "rows": 24}

        socket.send_json({"type": "resize", "cols": 132, "rows": 40})
        socket.send_json({"type": "input", "data": "ls\n"})
        assert wait_until(lambda: stream.sent_bytes() == b"ls\n")
        _, resize = runtime.agent_sessions.streams
        assert resize.kind == "command"
        assert resize.args == {
            "module": "agent",
            "verb": "resize",
            "shell": stream.id,
            "cols": 132,
            "rows": 40,
        }

        stream.feed(("data", "total 0\r\n".encode()))
        assert socket.receive_json() == {"type": "output", "data": "total 0\r\n"}

        stream.finish({"code": "", "params": {"exit_code": 3}})
        assert socket.receive_json() == {"type": "exit", "code": 3}
        assert closed_with(socket)[0] == 1000
    finally:
        socket.__exit__(None, None, None)


def test_a_split_multibyte_character_is_joined_across_frames(api):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent/terminal?device_id={MAC}")
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        stream = runtime.agent_sessions.streams[0]
        encoded = "é".encode()

        stream.feed(("data", encoded[:1]))
        stream.feed(("data", encoded[1:] + b"!"))

        assert socket.receive_json() == {"type": "output", "data": "é!"}
    finally:
        socket.__exit__(None, None, None)


def test_the_browser_closing_asks_the_agent_to_end_the_stream(api):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent/terminal?device_id={MAC}")
    assert wait_until(lambda: runtime.agent_sessions.streams)
    stream = runtime.agent_sessions.streams[0]

    socket.__exit__(None, None, None)

    assert wait_until(lambda: stream.is_close_asked)


def test_the_container_variant_opens_a_shell_naming_the_module_and_the_container(
    api,
):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent/terminal?device_id={MAC}&container=kuma")
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        stream = runtime.agent_sessions.streams[0]
        assert stream.kind == "shell"
        assert stream.args == {
            "module": "podman",
            "container": "kuma",
            "cols": 80,
            "rows": 24,
        }

        stream.finish({"code": "", "params": {"exit_code": 0}})
        assert socket.receive_json() == {"type": "exit", "code": 0}
    finally:
        socket.__exit__(None, None, None)


class GoneSocket:
    """A socket whose close raises what starlette raises for a given code."""

    def __init__(self, code: int):
        self.code = code

    async def close(self, **kwargs) -> None:
        raise WebSocketDisconnect(self.code)


def test_closing_a_socket_the_browser_already_left_is_quiet():
    asyncio.run(ws._close(GoneSocket(1006)))
    asyncio.run(ws._close(GoneSocket(1006), code=INTERNAL_ERROR_CODE, reason="x"))


def test_closing_with_any_other_disconnect_still_raises():
    with pytest.raises(WebSocketDisconnect):
        asyncio.run(ws._close(GoneSocket(1000)))


def test_the_session_id_rides_the_open_and_a_persist_names_it(api):
    client, runtime = api
    socket = open_terminal(
        client, f"/ws/agent/terminal?device_id={MAC}&session_id=4f1c2a"
    )
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        stream = runtime.agent_sessions.streams[0]
        assert stream.args == {
            "cols": 80,
            "rows": 24,
            "session_id": "4f1c2a",
            "owner": "hub",
            "is_shared": False,
        }

        socket.send_json({"type": "persist", "is_persistent": True, "is_shared": 1})
        assert wait_until(lambda: len(runtime.agent_sessions.streams) == 2)
        persist = runtime.agent_sessions.streams[1]
        assert (persist.kind, persist.args) == (
            "command",
            {
                "module": "agent",
                "verb": "persist",
                "session_id": "4f1c2a",
                "is_persistent": True,
                "is_shared": True,
            },
        )
    finally:
        socket.__exit__(None, None, None)


def test_a_persist_on_a_session_another_viewer_owns_is_refused(api, monkeypatch):
    client, runtime = api
    reports = {
        MAC: {"machine": {"sessions": [{"session_id": "4f1c2a", "owner": "client:c1"}]}}
    }
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)
    socket = open_terminal(
        client,
        f"/ws/agent/terminal?device_id={MAC}&session_id=4f1c2a&is_resumed=true",
    )
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        socket.send_json({"type": "persist", "is_shared": True})

        assert socket.receive_json() == {
            "type": "refused",
            "code": "session_not_owned",
            "params": {"session_id": "4f1c2a"},
        }
        assert len(runtime.agent_sessions.streams) == 1
    finally:
        socket.__exit__(None, None, None)


def test_a_persist_on_a_shell_opened_without_a_session_sends_nothing(api):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent/terminal?device_id={MAC}")
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        stream = runtime.agent_sessions.streams[0]
        socket.send_json({"type": "persist", "is_persistent": True})
        socket.send_json({"type": "input", "data": "x"})
        assert wait_until(lambda: stream.sent_bytes() == b"x")
        assert len(runtime.agent_sessions.streams) == 1
    finally:
        socket.__exit__(None, None, None)


def test_attaching_a_listed_session_asks_the_agent_to_resume_it(api):
    client, runtime = api
    socket = open_terminal(
        client,
        f"/ws/agent/terminal?device_id={MAC}&session_id=4f1c2a&is_resumed=true",
    )
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        assert runtime.agent_sessions.streams[0].args == {
            "cols": 80,
            "rows": 24,
            "session_id": "4f1c2a",
            "owner": "hub",
            "is_shared": False,
            "is_resumed": True,
        }
    finally:
        socket.__exit__(None, None, None)


def test_the_panel_joins_a_clients_session_that_is_not_shared(api, monkeypatch):
    client, runtime = api
    reports = {
        MAC: {
            "machine": {
                "sessions": [
                    {"session_id": "4f1c2a", "owner": "client:c1", "is_shared": False}
                ]
            }
        }
    }
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)
    socket = open_terminal(
        client,
        f"/ws/agent/terminal?device_id={MAC}&session_id=4f1c2a&is_resumed=true",
    )
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        assert runtime.agent_sessions.streams[0].args["session_id"] == "4f1c2a"
    finally:
        socket.__exit__(None, None, None)


class ViewerSession:
    """A client's socket holding one shell on a session."""

    def __init__(self, key: str, shells: dict):
        self.key = key
        self.shells = shells
        self.loop = None
        self.closed: list = []

    def close_stream_from_thread(self, stream_id, code, params=None) -> bool:
        self.closed.append((stream_id, code, dict(params or {})))
        return True


def test_the_panels_unshare_closes_every_clients_stream_on_its_session(
    api, monkeypatch
):
    client, runtime = api
    reports = {
        MAC: {
            "machine": {
                "sessions": [
                    {"session_id": "4f1c2a", "owner": "hub", "is_shared": True}
                ]
            }
        }
    }
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)
    viewer = ViewerSession("c1", {4: (MAC, 11, "4f1c2a")})
    monkeypatch.setattr(runtime.client_sessions, "sessions", lambda: [viewer])
    socket = open_terminal(
        client,
        f"/ws/agent/terminal?device_id={MAC}&session_id=4f1c2a&is_resumed=true",
    )
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        socket.send_json({"type": "persist", "is_shared": False})
        assert wait_until(lambda: viewer.closed)
        assert viewer.closed == [(4, "session_not_owned", {"session_id": "4f1c2a"})]
    finally:
        socket.__exit__(None, None, None)
