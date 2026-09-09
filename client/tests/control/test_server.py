"""The control channel end to end: one route table, one person answered.

The socket answers only the peer the kernel says is this person; any other
account is refused, never guessed. The socket is 0600, a live socket is not
stolen, and a handler exception answers typed without dropping the wire.
"""

import json
import os

import pytest

from neutrino_client.control import client
from neutrino_client.control.server import ControlServer
from neutrino_client.platforms.base import PlatformUnsupportedError
from tests.conftest import OTHER_USER, SAME_USER, FakeClientPlatform, FakeSession


@pytest.fixture(scope="module")
def control_stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("control")
    session = FakeSession()
    platform = FakeClientPlatform()
    server = ControlServer(
        session=session,
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp / "client.sock"),
    )
    assert server.start()
    assert server.socket_path
    yield server, session, platform
    server.stop()


@pytest.fixture
def control(control_stack):
    server, session, platform = control_stack
    FakeSession.__init__(session, platform=platform)
    FakeClientPlatform.__init__(platform)
    return server, session, platform


def over_socket(server, method, path, body=None):
    return client.request(
        socket_path=server.socket_path, method=method, path=path, body=body
    )


def test_the_socket_is_the_persons_own(control):
    server, _session, _platform = control

    assert oct(os.stat(server.socket_path).st_mode & 0o777) == "0o600"


def test_the_same_user_is_answered(control):
    server, _session, platform = control
    platform.peer = dict(SAME_USER)

    status, state = over_socket(server, "GET", "/api/state")

    assert status == 200
    assert state["hostname"] == "box"
    assert "tok" not in json.dumps(state)


def test_another_account_is_refused_on_every_route(control):
    server, session, platform = control
    platform.peer = dict(OTHER_USER)

    for method, path, body in (
        ("GET", "/api/state", None),
        ("GET", "/api/fs?path=/srv", None),
        ("POST", "/api/disconnect", {}),
        ("POST", "/api/services/port", {"id": "svc_tcp", "is_enabled": True}),
        ("POST", "/api/show", {}),
    ):
        status, reply = over_socket(server, method, path, body)
        assert (status, reply["code"]) == (403, "control_peer_refused"), path
    assert session.service_calls == []
    assert session.is_disconnected is False
    assert session.shows == 0


def test_an_unreadable_peer_is_refused_not_guessed(control):
    server, _session, platform = control
    platform.peer_error = PlatformUnsupportedError("no peers here")

    status, reply = over_socket(server, "GET", "/api/state")

    assert (status, reply["code"]) == (403, "unsupported_platform")


def test_service_actions_reach_the_session_with_their_body(control):
    server, session, _platform = control

    status, state = over_socket(
        server, "POST", "/api/services/port", {"id": "svc_tcp", "is_enabled": True}
    )

    assert status == 200
    assert session.service_calls == [("port", {"id": "svc_tcp", "is_enabled": True})]
    assert "forwards" in state


def test_a_garbage_body_acts_on_nothing_and_never_crashes(control):
    server, session, _platform = control

    connection = client._ControlSocketHttpConnection(server.socket_path, timeout_s=5)
    connection.request(
        "POST",
        "/api/services/ai",
        body=b"not json at all",
        headers={"Content-Type": "application/json"},
    )
    reply = connection.getresponse()
    status = reply.status
    reply.read()
    connection.close()

    assert status == 200
    assert session.service_calls == [("ai", {})]


def test_a_handler_exception_answers_typed_and_keeps_the_server_answering(control):
    server, session, _platform = control
    session.service_error = OSError("a secret-bearing message")

    status, reply = over_socket(
        server, "POST", "/api/services/file", {"action": "mount"}
    )

    assert status == 500
    assert reply == {"code": "client_internal", "params": {"error": "OSError"}}
    assert "secret-bearing" not in json.dumps(reply)

    session.service_error = None
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["hostname"] == "box"


def test_the_show_route_answers_the_same_user(control):
    server, session, _platform = control

    status, reply = over_socket(server, "POST", "/api/show", {})

    assert (status, reply) == (200, {})
    assert session.shows == 1


def test_a_live_socket_is_not_stolen(control, tmp_path):
    server, session, platform = control

    second = ControlServer(
        session=session,
        platform=platform,
        log=lambda message: None,
        socket_path=server.socket_path,
    )

    assert second.bind() is False
    status, _state = over_socket(server, "GET", "/api/state")
    assert status == 200


def test_a_dead_socket_file_is_replaced(tmp_path):
    path = tmp_path / "stale.sock"
    path.write_text("")
    server = ControlServer(
        session=FakeSession(),
        platform=FakeClientPlatform(),
        log=lambda message: None,
        socket_path=str(path),
    )

    assert server.start()
    status, _state = over_socket(server, "GET", "/api/state")
    server.stop()

    assert status == 200
    assert not path.exists()


def test_a_platform_without_a_socket_does_not_bind():
    class NoSocketPlatform(FakeClientPlatform):
        def control_socket_path(self):
            raise PlatformUnsupportedError("none")

    lines = []
    server = ControlServer(
        session=FakeSession(), platform=NoSocketPlatform(), log=lines.append
    )

    assert server.bind() is False
    assert server.socket_path == ""
    assert lines
