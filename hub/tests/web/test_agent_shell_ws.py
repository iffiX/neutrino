"""The terminal sockets, bridged to a device's shell stream end to end.

What these pin: the session gate, a device with no channel turned away
with ``agent_offline``, an agent's refusal closing with its code, the
browser's input and resizes reaching the stream, the stream's bytes
becoming output frames and its close an exit frame, and the container
variant opening its own kind with the container's name.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from neutrino_hub.web import ws
from neutrino_hub.web.constants import WEB_SESSION_COOKIE
from tests.conftest import FakeAgentSessions

MAC = "aa:bb:cc:dd:ee:ff"
SESSION_TOKEN = "panel-session"
POLICY_VIOLATION_CODE = 1008
INTERNAL_ERROR_CODE = 1011


class StubSessions:
    def is_valid(self, token) -> bool:
        return token == SESSION_TOKEN


class FakeRuntime:
    def __init__(self):
        self.sessions = StubSessions()
        self.agent_sessions = FakeAgentSessions(online=[MAC])


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
    socket = client.websocket_connect(path, cookies={WEB_SESSION_COOKIE: SESSION_TOKEN})
    socket.__enter__()
    return socket


def test_without_a_session_the_socket_is_turned_away(api):
    client, _ = api

    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect(f"/ws/agent_shell/{MAC}"):
            pass

    assert refusal.value.code == POLICY_VIOLATION_CODE


def test_a_device_with_no_channel_is_turned_away_as_offline(api):
    client, runtime = api
    runtime.agent_sessions.online.clear()

    socket = open_terminal(client, f"/ws/agent_shell/{MAC}")
    try:
        assert closed_with(socket) == (POLICY_VIOLATION_CODE, "agent_offline")
    finally:
        socket.__exit__(None, None, None)


def test_an_agents_refusal_closes_with_its_code(api):
    client, runtime = api
    runtime.agent_sessions.refusal = ("container_unknown", {"name": "kuma"})

    socket = open_terminal(client, f"/ws/agent_container/{MAC}/kuma")
    try:
        assert closed_with(socket) == (INTERNAL_ERROR_CODE, "container_unknown")
    finally:
        socket.__exit__(None, None, None)


def test_input_and_resizes_reach_the_stream_and_output_and_exit_come_back(api):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent_shell/{MAC}")
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        stream = runtime.agent_sessions.streams[0]
        assert stream.kind == "shell"
        assert stream.args == {"cols": 80, "rows": 24}

        socket.send_json({"type": "resize", "cols": 132, "rows": 40})
        socket.send_json({"type": "input", "data": "ls\n"})
        assert wait_until(lambda: stream.sent_bytes() == b"ls\n")
        assert stream.resizes == [(132, 40)]

        stream.feed(("data", "total 0\r\n".encode()))
        assert socket.receive_json() == {"type": "output", "data": "total 0\r\n"}

        stream.finish({"exit_code": 3, "code": "", "params": {}})
        assert socket.receive_json() == {"type": "exit", "code": 3}
        assert closed_with(socket)[0] == 1000
    finally:
        socket.__exit__(None, None, None)


def test_a_split_multibyte_character_is_joined_across_frames(api):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent_shell/{MAC}")
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
    socket = open_terminal(client, f"/ws/agent_shell/{MAC}")
    assert wait_until(lambda: runtime.agent_sessions.streams)
    stream = runtime.agent_sessions.streams[0]

    socket.__exit__(None, None, None)

    assert wait_until(lambda: stream.is_close_asked)


def test_the_container_variant_opens_its_kind_with_the_name(api):
    client, runtime = api
    socket = open_terminal(client, f"/ws/agent_container/{MAC}/kuma")
    try:
        assert wait_until(lambda: runtime.agent_sessions.streams)
        stream = runtime.agent_sessions.streams[0]
        assert (stream.kind, stream.args) == ("container_shell", {"name": "kuma"})

        stream.finish({"exit_code": 0, "code": "", "params": {}})
        assert socket.receive_json() == {"type": "exit", "code": 0}
    finally:
        socket.__exit__(None, None, None)
