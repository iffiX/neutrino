"""The control channel end to end: one handler set, kernel-scoped callers.

The socket answers each caller with the kernel-reported identity's own
scope; nothing a request carries can name a different caller, and a peer
the kernel cannot vouch for is refused, never guessed.

One server serves the whole module; every test resets the fakes it drives.
"""

import json

import pytest

import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from neutrino_agent.platforms.base import PlatformUnsupportedError
from tests.conftest import ALICE, ROOT, FakeControlAgent, FakeControlPlatform, bind


@pytest.fixture(scope="module")
def control_stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("control")
    agent = FakeControlAgent()
    platform = FakeControlPlatform()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp / "agent.sock"),
    )
    server.start()
    assert server.socket_path
    yield server, agent, platform
    server.stop()


@pytest.fixture
def control(control_stack):
    server, agent, platform = control_stack
    FakeControlAgent.__init__(agent)
    FakeControlPlatform.__init__(platform)
    return server, agent, platform


def over_socket(server, method, path, body=None):
    return client.request(
        socket_path=server.socket_path, method=method, path=path, body=body
    )


# --- state over the socket, scoped to the kernel-reported peer ---


def test_socket_state_is_scoped_to_the_peer(control):
    server, _agent, platform = control

    platform.peer = dict(ROOT)
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["caller"] == {
        "account": "root",
        "is_privileged": True,
        "home": "/root",
    }
    assert state["accounts"] == ["alice", "bob"]
    assert state["ai_targets"] == {"alice": True, "bob": False}

    platform.peer = dict(ALICE)
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["caller"] == {
        "account": "alice",
        "is_privileged": False,
        "home": "/home/alice",
    }
    assert state["accounts"] == ["alice"]
    assert state["ai_targets"] == {"alice": True}
    assert [m["name"] for m in state["modules"]] == ["openssh_server"]
    assert state["modules"][0]["kind"] == "openssh"
    # The tier rides the row, so the page can withhold the buttons a
    # user-tier module never offers.
    assert state["modules"][0]["installer"] == "platform"


def test_the_state_carries_the_mount_location_shape_for_every_scope(control):
    server, _agent, platform = control

    for peer in (dict(ROOT), dict(ALICE)):
        platform.peer = peer
        _status, state = over_socket(server, "GET", "/api/state")
        assert state["mount_location_shape"] == "path"


def test_an_ordinary_caller_sees_only_its_own_ai_rows(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    _status, state = over_socket(server, "GET", "/api/state")

    assert sorted(state["ai_states"]) == ["alice"]

    platform.peer = dict(ROOT)
    _status, state = over_socket(server, "GET", "/api/state")
    assert sorted(state["ai_states"]) == ["alice", "bob"]


def test_the_ai_state_keys_are_exactly_the_staging_inputs(control):
    server, _agent, platform = control

    platform.peer = dict(ROOT)
    _status, state = over_socket(server, "GET", "/api/state")
    assert {key for key in state if key.startswith("ai_")} == {
        "ai_targets",
        "ai_states",
        "ai_tool_configs",
    }


def test_mount_records_are_machine_state_with_their_owner_named(control, monkeypatch):
    # The page greys the unmount button by the record's account, so every
    # scope sees the record and whose it is.
    server, agent, platform = control
    monkeypatch.setattr(
        agent,
        "service_states",
        lambda: {
            "forwards": {"svc_tcp": {"local_port": 5432, "is_active": True}},
            "mounts": [
                {
                    "record_id": "r2",
                    "entry_id": "hub_share_media",
                    "path": "/srv/media",
                    "account": "bob",
                    "is_attached": True,
                    "code": "",
                    "params": {},
                }
            ],
        },
    )

    platform.peer = dict(ALICE)
    status, state = over_socket(server, "GET", "/api/state")

    assert status == 200
    assert state["forwards"]["svc_tcp"]["is_active"] is True
    assert [(m["record_id"], m["account"]) for m in state["mounts"]] == [("r2", "bob")]


def test_the_state_carries_the_typed_service_list(control):
    server, _agent, platform = control

    platform.peer = dict(ROOT)
    status, state = over_socket(server, "GET", "/api/state")

    assert status == 200
    assert [entry["type"] for entry in state["services"]] == ["ai", "web", "port"]
    assert state["services"][1]["payload"]["url"] == "http://w/"
    assert state["forwards"]["svc_tcp"]["local_port"] == 5432
    assert state["mounts"][0]["record_id"] == "r1"
    assert state["ai_tool_configs"] == {"claude": {"default": "m1"}}


def test_the_state_carries_the_hubs_operation_for_every_scope(control):
    server, agent, platform = control
    operation = {
        "kind": "order",
        "action": "install",
        "title": "FakeDesk",
        "state": "installing",
        "output": "fakedesk: installing",
    }
    agent.operation_payload = operation

    platform.peer = dict(ROOT)
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["operation"] == operation

    platform.peer = dict(ALICE)
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["operation"] == operation

    agent.operation_payload = None
    status, state = over_socket(server, "GET", "/api/state")
    assert state["operation"] is None


def test_the_state_never_carries_the_device_token(control, config_path):
    server, _agent, platform = control
    bind(config_path)

    platform.peer = dict(ROOT)
    status, state = over_socket(server, "GET", "/api/state")

    assert status == 200
    assert state["is_connected"] is True
    assert state["gateway_url"] == "http://127.0.0.1:9"
    assert "tok" not in json.dumps(state)


def test_an_unreadable_peer_is_refused_not_guessed(control):
    server, _agent, platform = control

    platform.peer_error = KeyError(4242)
    status, reply = over_socket(server, "GET", "/api/state")
    assert (status, reply["code"]) == (403, "control_identity_unknown")

    platform.peer_error = PlatformUnsupportedError("no peers here")
    status, reply = over_socket(server, "GET", "/api/state")
    assert (status, reply["code"]) == (403, "unsupported_platform")


def test_an_unreadable_peer_is_refused_on_posts_too(control):
    server, agent, platform = control

    platform.peer_error = KeyError(4242)
    status, reply = over_socket(server, "POST", "/api/disconnect", {})

    assert (status, reply["code"]) == (403, "control_identity_unknown")
    assert agent.is_disconnected is False


def test_a_garbage_body_acts_on_nothing_and_never_crashes(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)

    connection = client._ControlSocketHttpConnection(server.socket_path, timeout_s=5)
    connection.request(
        "POST",
        "/api/module",
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
    assert agent.requested == [("", None)]


def test_a_handler_exception_answers_typed_and_keeps_the_server_answering(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)
    agent.service_error = OSError("a secret-bearing message")

    status, reply = over_socket(
        server, "POST", "/api/services/file", {"action": "mount"}
    )

    # The wire carries the class name only, never the message's own words.
    assert status == 500
    assert reply == {"code": "agent_internal", "params": {"error": "OSError"}}
    assert "secret-bearing" not in json.dumps(reply)

    agent.service_error = None
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["caller"]["account"] == "root"


# --- privileged verbs ---


def test_privileged_verbs_refuse_an_ordinary_caller(control):
    server, agent, platform = control
    platform.peer = dict(ALICE)

    for path, body in (
        ("/api/connect", {"link": "neutrino://enroll/x"}),
        ("/api/disconnect", {}),
        ("/api/module", {"name": "openssh_server", "is_enabled": False}),
    ):
        status, reply = over_socket(server, "POST", path, body)
        assert (status, reply["code"]) == (403, "control_scope_refused")
    assert agent.requested == []
    assert agent.connected_links == []
    assert agent.is_disconnected is False


def test_privileged_verbs_work_over_the_socket_as_root(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)

    status, _state = over_socket(
        server, "POST", "/api/connect", {"link": "neutrino://enroll/x"}
    )
    assert status == 200
    assert agent.connected_links == ["neutrino://enroll/x"]

    status, _state = over_socket(server, "POST", "/api/disconnect", {})
    assert status == 200
    assert agent.is_disconnected is True


def test_a_module_uninstall_request_rides_through(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)

    status, _state = over_socket(
        server, "POST", "/api/module", {"name": "openssh_server", "is_enabled": False}
    )

    assert status == 200
    assert agent.requested == [("openssh_server", False)]


def test_a_refused_link_reports_on_the_state(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)
    agent.connect_error = enrollment.EnrollmentError("the link is unusable")

    status, state = over_socket(
        server, "POST", "/api/connect", {"link": "neutrino://enroll/x"}
    )

    assert status == 200
    assert state["error"] == "the link is unusable"


# --- service actions ---


def test_service_actions_carry_the_callers_identity(control):
    server, agent, platform = control

    platform.peer = dict(ALICE)
    status, _state = over_socket(
        server,
        "POST",
        "/api/services/port",
        {"id": "svc_tcp", "is_enabled": True},
    )
    assert status == 200
    assert agent.service_calls[-1] == (
        "port",
        "alice",
        False,
        {"id": "svc_tcp", "is_enabled": True},
    )

    platform.peer = dict(ROOT)
    status, _state = over_socket(
        server,
        "POST",
        "/api/services/file",
        {"action": "unmount", "record_id": "r1"},
    )
    assert status == 200
    assert agent.service_calls[-1] == (
        "file",
        "root",
        True,
        {"action": "unmount", "record_id": "r1"},
    )


def test_a_body_naming_an_account_changes_nothing_about_the_scope(control):
    # Identity is the kernel's; a request body cannot name a different one.
    server, agent, platform = control
    platform.peer = dict(ALICE)

    status, _state = over_socket(
        server,
        "POST",
        "/api/services/ai",
        {"targets": {"bob": True}, "account": "root", "is_privileged": True},
    )

    assert status == 200
    assert agent.service_calls[-1][:3] == ("ai", "alice", False)


@pytest.mark.parametrize("service_type", ["web", "port", "ai", "file"])
def test_a_scope_refusal_maps_to_403_for_every_type(control, service_type):
    server, agent, platform = control
    platform.peer = dict(ALICE)
    agent.service_reply = {"code": "control_scope_refused", "params": {}}

    status, reply = over_socket(server, "POST", f"/api/services/{service_type}", {})

    assert (status, reply["code"]) == (403, "control_scope_refused")


def test_a_service_refusal_maps_to_its_status(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)

    agent.service_reply = {"code": "mountpoint_not_empty", "params": {}}
    status, reply = over_socket(
        server, "POST", "/api/services/file", {"action": "mount", "id": "x"}
    )
    assert (status, reply["code"]) == (400, "mountpoint_not_empty")

    agent.service_reply = {"code": "unknown_request", "params": {}}
    status, reply = over_socket(server, "POST", "/api/services/nothing", {})
    assert (status, reply["code"]) == (404, "unknown_request")

    agent.service_reply = {"code": "control_scope_refused", "params": {}}
    status, reply = over_socket(
        server, "POST", "/api/services/ai", {"targets": {"bob": True}}
    )
    assert (status, reply["code"]) == (403, "control_scope_refused")

    agent.service_reply = {"code": "fs_refused", "params": {}}
    status, reply = over_socket(
        server, "POST", "/api/services/file", {"action": "mount", "id": "x"}
    )
    assert (status, reply["code"]) == (403, "fs_refused")


def test_a_clean_service_action_answers_fresh_state(control):
    server, agent, platform = control
    platform.peer = dict(ALICE)

    status, state = over_socket(
        server, "POST", "/api/services/port", {"id": "svc_tcp", "is_enabled": False}
    )

    assert status == 200
    assert state["caller"]["account"] == "alice"
    assert "forwards" in state


# --- /api/fs, as the caller's identity ---


def test_the_directory_listing_runs_as_the_caller(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    status, reply = over_socket(server, "GET", "/api/fs?path=/srv")
    assert status == 200
    assert reply == {"path": "/srv", "dirs": ["docs", "media"]}
    assert platform.fs_calls[-1] == ("list", "alice", "/srv")

    platform.peer = dict(ROOT)
    status, reply = over_socket(server, "GET", "/api/fs?path=/srv")
    assert status == 200
    assert platform.fs_calls[-1] == ("list", "", "/srv")

    status, reply = over_socket(server, "GET", "/api/fs")
    assert status == 200
    assert platform.fs_calls[-1] == ("list", "", "/root")

    platform.fs_error = OSError("refused")
    status, reply = over_socket(server, "GET", "/api/fs?path=/srv")
    assert (status, reply["code"]) == (403, "fs_refused")


def test_the_listing_defaults_to_the_callers_own_home(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    status, reply = over_socket(server, "GET", "/api/fs")

    assert status == 200
    assert reply["path"] == "/home/alice"
    assert platform.fs_calls[-1] == ("list", "alice", "/home/alice")


def test_making_a_folder_follows_the_same_identity_rules(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    status, reply = over_socket(server, "POST", "/api/fs", {"path": "/srv/new"})
    assert status == 200
    assert platform.fs_calls[-1] == ("mkdir", "alice", "/srv/new")

    status, reply = over_socket(server, "POST", "/api/fs", {"path": "relative"})
    assert (status, reply["code"]) == (403, "fs_refused")


def test_making_a_folder_as_root_runs_as_the_agent(control):
    server, _agent, platform = control

    platform.peer = dict(ROOT)
    status, _reply = over_socket(server, "POST", "/api/fs", {"path": "/srv/new"})

    assert status == 200
    assert platform.fs_calls[-1] == ("mkdir", "", "/srv/new")


def test_a_platform_without_stepping_down_refuses_fs(control):
    server, _agent, platform = control
    platform.fs_error = PlatformUnsupportedError("no stepping down")

    platform.peer = dict(ALICE)
    status, reply = over_socket(server, "GET", "/api/fs?path=/srv")
    assert (status, reply["code"]) == (403, "fs_refused")

    status, reply = over_socket(server, "POST", "/api/fs", {"path": "/srv/new"})
    assert (status, reply["code"]) == (403, "fs_refused")


# --- unknown routes ---


def test_an_unknown_route_answers_a_code(control):
    server, _agent, platform = control
    platform.peer = dict(ROOT)

    status, reply = over_socket(server, "GET", "/api/nothing")
    assert (status, reply["code"]) == (404, "unknown_request")

    status, reply = over_socket(server, "POST", "/api/nothing", {})
    assert (status, reply["code"]) == (404, "unknown_request")


def test_no_route_serves_a_page_any_more(control):
    # The window loads the page from the package's own files; the channel
    # answers JSON and nothing else.
    server, _agent, platform = control
    platform.peer = dict(ROOT)

    status, reply = over_socket(server, "GET", "/")

    assert (status, reply["code"]) == (404, "unknown_request")
