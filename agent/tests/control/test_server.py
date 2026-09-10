"""The control channel end to end: six routes, one root caller.

The socket is root's — 0600 under a 0700 directory — so nothing judges an
identity in a handler and no route is refused for scope.

One server serves the whole module; every test resets the fakes it drives.
"""

import json
import os
import stat

import pytest

from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from neutrino_agent.exceptions import EnrollmentError
from tests.conftest import FakeControlAgent, FakeControlPlatform, bind


@pytest.fixture(scope="module")
def control_stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("control")
    agent = FakeControlAgent()
    platform = FakeControlPlatform()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp / "run" / "agent.sock"),
    )
    server.start()
    assert server.socket_path
    yield server, agent
    server.stop()


@pytest.fixture
def control(control_stack):
    server, agent = control_stack
    FakeControlAgent.__init__(agent)
    return server, agent


def over_socket(server, method, path, body=None):
    return client.request(
        socket_path=server.socket_path, method=method, path=path, body=body
    )


# --- the socket is root's alone ---


def test_the_socket_and_its_directory_are_closed_to_everyone_else(control):
    server, _agent = control

    socket_mode = stat.S_IMODE(os.stat(server.socket_path).st_mode)
    directory_mode = stat.S_IMODE(os.stat(os.path.dirname(server.socket_path)).st_mode)

    assert socket_mode == 0o600
    assert directory_mode == 0o700


# --- GET /api/state ---


def test_the_state_carries_the_connection_the_version_and_the_modules(control):
    server, _agent = control

    status, state = over_socket(server, "GET", "/api/state")

    assert status == 200
    assert state["version"]
    assert state["is_connected"] is False
    assert state["platform"]["os"] == "linux"
    assert [row["name"] for row in state["modules"]] == ["rustdesk"]
    assert state["modules"][0]["state"] == "installed"
    assert state["modules"][0]["source"] == "rustdesk/rustdesk"
    assert state["modules"][0]["license"] == "AGPL-3.0"


def test_the_state_carries_the_share_and_no_password(control):
    server, agent = control
    agent.share.update({"is_shared": True, "state": "sharing", "account": "alice"})

    status, state = over_socket(server, "GET", "/api/state")

    assert status == 200
    assert state["rdp"]["is_shared"] is True
    assert state["rdp"]["account"] == "alice"
    assert state["rdp"]["attention"] == ""
    assert "password" not in state["rdp"]


def test_the_state_says_whether_the_socket_to_the_hub_is_up(control):
    server, agent = control

    _status, state = over_socket(server, "GET", "/api/state")
    assert state["is_online"] is False

    agent.is_socket_open = True
    _status, state = over_socket(server, "GET", "/api/state")
    assert state["is_online"] is True


def test_the_state_never_carries_the_device_token(control, config_path):
    server, _agent = control
    bind(config_path)

    status, state = over_socket(server, "GET", "/api/state")

    assert status == 200
    assert state["is_connected"] is True
    assert state["gateway_url"] == "http://127.0.0.1:9"
    assert "tok" not in json.dumps(state)


# --- POST /api/sync ---


def test_sync_asks_the_agent_and_answers_the_state(control):
    server, agent = control

    status, state = over_socket(server, "POST", "/api/sync", {})

    assert status == 200
    assert agent.syncs == 1
    assert "is_connected" in state


def test_sync_with_no_socket_maps_to_400(control):
    server, agent = control
    agent.sync_reply = {"code": "hub_unreachable", "params": {}}

    status, reply = over_socket(server, "POST", "/api/sync", {})

    assert (status, reply["code"]) == (400, "hub_unreachable")


# --- POST /api/connect and /api/disconnect ---


def test_connect_and_disconnect_ride_through(control):
    server, agent = control

    status, _state = over_socket(
        server, "POST", "/api/connect", {"link": "neutrino://enroll/x"}
    )
    assert status == 200
    assert agent.connected_links == ["neutrino://enroll/x"]

    status, _state = over_socket(server, "POST", "/api/disconnect", {})
    assert status == 200
    assert agent.is_disconnected is True


def test_a_refused_link_reports_on_the_state(control):
    server, agent = control
    agent.connect_error = EnrollmentError("the link is unusable")

    status, state = over_socket(
        server, "POST", "/api/connect", {"link": "neutrino://enroll/x"}
    )

    assert status == 200
    assert state["error"] == "the link is unusable"


# --- POST /api/rdp/start and /api/rdp/stop ---


def test_a_share_names_its_account_and_no_password_at_all(control):
    server, agent = control

    status, state = over_socket(server, "POST", "/api/rdp/start", {"user": "alice"})

    assert status == 200
    assert agent.rdp_calls == ["alice"]
    assert state["rdp"]["is_shared"] is False


def test_an_unnamed_account_reaches_the_agent_as_empty(control):
    server, agent = control

    status, _state = over_socket(server, "POST", "/api/rdp/start", {})

    assert status == 200
    assert agent.rdp_calls == [""]


def test_a_share_refusal_maps_to_400(control):
    server, agent = control
    agent.rdp_reply = {"code": "rdp_wrong_seat", "params": {"account": "bob"}}

    status, reply = over_socket(server, "POST", "/api/rdp/start", {"user": "bob"})

    assert status == 400
    assert reply == {"code": "rdp_wrong_seat", "params": {"account": "bob"}}


def test_stopping_a_share_rides_through(control):
    server, agent = control

    status, _state = over_socket(server, "POST", "/api/rdp/stop", {})

    assert status == 200
    assert agent.is_unshared is True


def test_an_unknown_request_from_a_handler_maps_to_404(control):
    server, agent = control
    agent.rdp_reply = {"code": "unknown_request", "params": {}}

    status, reply = over_socket(server, "POST", "/api/rdp/stop", {})

    assert (status, reply["code"]) == (404, "unknown_request")


# --- the dispatch guard ---


def test_a_garbage_body_acts_on_nothing_and_never_crashes(control):
    server, agent = control

    connection = client._ControlSocketHttpConnection(server.socket_path, timeout_s=5)
    connection.request(
        "POST",
        "/api/rdp/start",
        body=b"not json at all",
        headers={"Content-Type": "application/json"},
    )
    reply = connection.getresponse()
    status = reply.status
    reply.read()
    connection.close()

    # The garbage decodes to an empty object: nothing named, and the agent's
    # own guard does nothing with a nameless ask.
    assert status == 200
    assert agent.rdp_calls == [""]


def test_a_handler_exception_answers_typed_and_keeps_the_server_answering(control):
    server, agent = control
    agent.rdp_error = OSError("a secret-bearing message")

    status, reply = over_socket(server, "POST", "/api/rdp/start", {"user": "alice"})

    # The wire carries the class name only, never the message's own words.
    assert status == 500
    assert reply == {"code": "agent_internal", "params": {"error": "OSError"}}
    assert "secret-bearing" not in json.dumps(reply)

    agent.rdp_error = None
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["version"]


# --- unknown routes ---


def test_an_unknown_route_answers_a_code(control):
    server, _agent = control

    status, reply = over_socket(server, "GET", "/api/nothing")
    assert (status, reply["code"]) == (404, "unknown_request")

    status, reply = over_socket(server, "POST", "/api/nothing", {})
    assert (status, reply["code"]) == (404, "unknown_request")


def test_no_route_serves_a_page(control):
    server, _agent = control

    status, reply = over_socket(server, "GET", "/")

    assert (status, reply["code"]) == (404, "unknown_request")


def test_the_deleted_routes_are_gone(control):
    server, _agent = control

    for method, path in (
        ("GET", "/api/fs"),
        ("POST", "/api/fs"),
        ("POST", "/api/module"),
        ("POST", "/api/services/file"),
    ):
        status, reply = over_socket(
            server, method, path, {} if method == "POST" else None
        )
        assert (status, reply["code"]) == (404, "unknown_request")
