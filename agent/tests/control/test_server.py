"""The control channel end to end: one handler set, two transports.

The socket answers each caller with the kernel-reported identity's own
scope; the loopback page answers only to tokens minted over the socket,
and refuses request shapes a cross-site form can produce. Tokens are minted
only while the page is actually served, watched and revoked only over the
socket, and expired when their pulse stops.

One server serves the whole module; every test resets the fakes it drives.
"""

import http.client
import json

import pytest

import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.constants import AGENT_CONTROL_PAGE_ORIGIN
from neutrino_agent.control import client
from neutrino_agent.control.identity import ControlTokenStore
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
        page_port=0,
    )
    server.start()
    assert server.socket_path and server.page_port
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


def over_loopback(server, method, path, *, token="", body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.page_port, timeout=5)
    sent = {}
    if token:
        sent["Authorization"] = f"Bearer {token}"
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        sent["Content-Type"] = "application/json"
    if headers:
        sent.update(headers)
    connection.request(method, path, body=payload, headers=sent)
    reply = connection.getresponse()
    raw = reply.read()
    connection.close()
    return reply.status, raw


def loopback_json(server, method, path, **kwargs):
    status, raw = over_loopback(server, method, path, **kwargs)
    return status, json.loads(raw.decode("utf-8"))


def mint(server, platform, peer, body=None):
    platform.peer = dict(peer)
    status, reply = over_socket(server, "POST", "/api/token", body or {})
    assert status == 200
    return reply["token"]


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

    token = mint(server, platform, ALICE)
    _status, state = loopback_json(server, "GET", "/api/state", token=token)
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


# --- minting: own scope free, another account privileged and downscoped ---


def test_a_minted_token_unlocks_the_page_in_its_own_scope(control):
    server, _agent, platform = control
    token = mint(server, platform, ALICE)

    status, state = loopback_json(server, "GET", "/api/state", token=token)

    assert status == 200
    assert state["caller"] == {
        "account": "alice",
        "is_privileged": False,
        "home": "/home/alice",
    }
    assert state["accounts"] == ["alice"]


def test_the_mint_reply_names_the_scope_and_page_port(control):
    server, _agent, platform = control
    platform.peer = dict(ROOT)

    status, reply = over_socket(server, "POST", "/api/token", {})

    assert status == 200
    assert reply["account"] == "root"
    assert reply["is_privileged"] is True
    assert reply["page_port"] == server.page_port


def test_minting_for_another_account_is_privileged(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    status, reply = over_socket(server, "POST", "/api/token", {"account": "bob"})
    assert (status, reply["code"]) == (403, "control_scope_refused")

    token = mint(server, platform, ROOT, {"account": "bob"})
    status, state = loopback_json(server, "GET", "/api/state", token=token)
    assert status == 200
    assert state["caller"] == {
        "account": "bob",
        "is_privileged": False,
        "home": "/home/bob",
    }
    assert state["accounts"] == ["bob"]

    platform.peer = dict(ROOT)
    status, reply = over_socket(server, "POST", "/api/token", {"account": "mallory"})
    assert (status, reply["code"]) == (400, "control_unknown_account")


def test_an_ordinary_caller_may_not_mint_privilege_by_naming_root(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    status, reply = over_socket(server, "POST", "/api/token", {"account": "root"})

    assert (status, reply["code"]) == (403, "control_scope_refused")


def test_naming_your_own_account_mints_without_privilege(control):
    server, _agent, platform = control
    token = mint(server, platform, ALICE, {"account": "alice"})

    status, state = loopback_json(server, "GET", "/api/state", token=token)

    assert status == 200
    assert state["caller"] == {
        "account": "alice",
        "is_privileged": False,
        "home": "/home/alice",
    }


def test_a_downscoped_token_may_not_use_privileged_verbs(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT, {"account": "bob"})

    for path, body in (
        ("/api/connect", {"link": "neutrino://enroll/x"}),
        ("/api/disconnect", {}),
        ("/api/module", {"name": "openssh_server", "is_enabled": False}),
    ):
        status, reply = loopback_json(server, "POST", path, token=token, body=body)
        assert (status, reply["code"]) == (403, "control_scope_refused")
    assert agent.requested == []
    assert agent.connected_links == []
    assert agent.is_disconnected is False


def test_tokens_are_minted_only_over_the_socket(control):
    server, _agent, platform = control
    token = mint(server, platform, ROOT)

    status, reply = loopback_json(server, "POST", "/api/token", token=token, body={})

    assert (status, reply["code"]) == (404, "unknown_request")


def test_minting_refuses_while_the_page_is_not_served(tmp_path):
    platform = FakeControlPlatform()
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp_path / "agent.sock"),
        is_page_served=False,
    )
    server.start()
    try:
        platform.peer = dict(ROOT)
        status, reply = over_socket(server, "POST", "/api/token", {})
        assert (status, reply["code"]) == (409, "control_page_not_served")
    finally:
        server.stop()


# --- the loopback belts: token, Origin, Content-Type ---


def test_a_tokenless_loopback_request_gets_only_the_hint_page(control):
    server, _agent, _platform = control

    status, raw = over_loopback(server, "GET", "/")
    assert status == 200
    assert b"nagent ui" in raw

    status, reply = loopback_json(server, "GET", "/api/state")
    assert (status, reply["code"]) == (401, "control_token_invalid")

    status, reply = loopback_json(server, "GET", "/api/state", token="never-minted")
    assert (status, reply["code"]) == (401, "control_token_invalid")


def test_any_non_api_path_serves_the_page_itself(control):
    server, _agent, _platform = control

    status, raw = over_loopback(server, "GET", "/anything/else")

    assert status == 200
    assert b"Neutrino agent" in raw


def test_a_mismatched_origin_is_refused_regardless_of_token(control):
    server, _agent, platform = control
    token = mint(server, platform, ROOT)

    status, reply = loopback_json(
        server,
        "POST",
        "/api/module",
        token=token,
        body={"name": "openssh_server"},
        headers={"Origin": "http://evil.example"},
    )

    assert (status, reply["code"]) == (403, "control_origin_refused")


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/connect", {"link": "x"}),
        ("/api/disconnect", {}),
        ("/api/services/port", {"id": "svc_tcp"}),
        ("/api/fs", {"path": "/srv/new"}),
    ],
)
def test_the_origin_belt_covers_every_state_changing_route(control, path, body):
    server, agent, platform = control
    token = mint(server, platform, ROOT)

    status, reply = loopback_json(
        server,
        "POST",
        path,
        token=token,
        body=body,
        headers={"Origin": "http://evil.example"},
    )

    assert (status, reply["code"]) == (403, "control_origin_refused")
    assert agent.connected_links == []
    assert agent.is_disconnected is False
    assert agent.service_calls == []
    assert platform.fs_calls == []


def test_a_get_carries_no_origin_belt(control):
    server, _agent, platform = control
    token = mint(server, platform, ROOT)

    status, state = loopback_json(
        server,
        "GET",
        "/api/state",
        token=token,
        headers={"Origin": "http://evil.example"},
    )

    assert status == 200
    assert state["caller"]["account"] == "root"


def test_a_loopback_post_must_be_json(control):
    server, _agent, platform = control
    token = mint(server, platform, ROOT)

    status, reply = loopback_json(
        server,
        "POST",
        "/api/module",
        token=token,
        body={"name": "openssh_server"},
        headers={"Content-Type": "text/plain"},
    )

    assert (status, reply["code"]) == (400, "control_content_type_refused")


def test_a_json_content_type_with_charset_passes(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT)

    status, _state = loopback_json(
        server,
        "POST",
        "/api/module",
        token=token,
        body={"name": "openssh_server", "is_enabled": True},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    assert status == 200
    assert agent.requested == [("openssh_server", True)]


def test_a_post_without_an_origin_header_passes(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT)

    status, _state = loopback_json(
        server, "POST", "/api/disconnect", token=token, body={}
    )

    assert status == 200
    assert agent.is_disconnected is True


def test_the_pages_own_origin_passes(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT)

    status, state = loopback_json(
        server,
        "POST",
        "/api/module",
        token=token,
        body={"name": "openssh_server", "is_enabled": False},
        headers={"Origin": AGENT_CONTROL_PAGE_ORIGIN},
    )

    assert status == 200
    assert state["caller"]["is_privileged"] is True
    assert agent.requested == [("openssh_server", False)]


def test_a_garbage_body_acts_on_nothing_and_never_crashes(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT)

    connection = http.client.HTTPConnection("127.0.0.1", server.page_port, timeout=5)
    connection.request(
        "POST",
        "/api/module",
        body=b"not json at all",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    reply = connection.getresponse()
    status = reply.status
    reply.read()
    connection.close()

    # The garbage decodes to an empty object: nothing named, and the agent's
    # own guard does nothing with a nameless ask.
    assert status == 200
    assert agent.requested == [("", None)]


def test_a_handler_exception_answers_typed_and_keeps_the_connection(control):
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

    # Both transports share the guard, and the server keeps answering.
    token = mint(server, platform, ROOT)
    status, reply = loopback_json(
        server,
        "POST",
        "/api/services/file",
        token=token,
        body={"action": "mount"},
    )
    assert status == 500
    assert reply == {"code": "agent_internal", "params": {"error": "OSError"}}

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


def test_an_ordinary_token_may_not_use_privileged_verbs(control):
    server, agent, platform = control
    token = mint(server, platform, ALICE)

    for path, body in (
        ("/api/connect", {"link": "neutrino://enroll/x"}),
        ("/api/disconnect", {}),
        ("/api/module", {"name": "openssh_server", "is_enabled": False}),
    ):
        status, reply = loopback_json(server, "POST", path, token=token, body=body)
        assert (status, reply["code"]) == (403, "control_scope_refused")
    assert agent.requested == []
    assert agent.connected_links == []
    assert agent.is_disconnected is False


def test_a_module_uninstall_request_rides_through(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)

    status, _state = over_socket(
        server, "POST", "/api/module", {"name": "openssh_server", "is_enabled": False}
    )

    assert status == 200
    assert agent.requested == [("openssh_server", False)]


def test_privileged_verbs_work_over_the_loopback_with_a_root_token(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT)

    status, state = loopback_json(
        server,
        "POST",
        "/api/disconnect",
        token=token,
        body={},
        headers={"Origin": AGENT_CONTROL_PAGE_ORIGIN},
    )

    assert status == 200
    assert agent.is_disconnected is True
    assert state["caller"]["account"] == "root"


def test_a_refused_link_reports_on_the_state(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)
    agent.connect_error = enrollment.EnrollmentError("the link is unusable")

    status, state = over_socket(
        server, "POST", "/api/connect", {"link": "neutrino://enroll/x"}
    )

    assert status == 200
    assert state["error"] == "the link is unusable"


# --- the token lifecycle ---


def test_a_token_is_watched_and_revoked_over_the_socket(control):
    server, _agent, platform = control
    token = mint(server, platform, ALICE)

    status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert (status, reply) == (200, {"is_claimed": False, "is_alive": True})

    status, _reply = over_socket(server, "POST", "/api/token/revoke", {"token": token})
    assert status == 200
    status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert reply == {"is_claimed": False, "is_alive": False}

    status, reply = loopback_json(server, "GET", "/api/state", token=token)
    assert (status, reply["code"]) == (401, "control_token_invalid")


def test_the_first_page_request_claims_the_token(control):
    server, _agent, platform = control
    token = mint(server, platform, ALICE)

    _status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert reply["is_claimed"] is False

    status, _state = loopback_json(server, "GET", "/api/state", token=token)
    assert status == 200

    _status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert reply == {"is_claimed": True, "is_alive": True}


def test_watch_and_revoke_ask_no_identity_of_the_caller(control):
    # Holding the token is the authorization; the waiting command may be
    # another account's session.
    server, _agent, platform = control
    token = mint(server, platform, ALICE)

    platform.peer_error = KeyError(4242)
    status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert (status, reply) == (200, {"is_claimed": False, "is_alive": True})

    status, _reply = over_socket(server, "POST", "/api/token/revoke", {"token": token})
    assert status == 200
    _status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert reply == {"is_claimed": False, "is_alive": False}


def test_a_claimed_then_revoked_token_reads_unclaimed_and_dead(control):
    server, _agent, platform = control
    token = mint(server, platform, ALICE)

    status, _state = loopback_json(server, "GET", "/api/state", token=token)
    assert status == 200
    over_socket(server, "POST", "/api/token/revoke", {"token": token})

    _status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert reply == {"is_claimed": False, "is_alive": False}


def test_a_used_then_revoked_token_stays_dead(control):
    server, _agent, platform = control
    token = mint(server, platform, ALICE)

    status, _state = loopback_json(server, "GET", "/api/state", token=token)
    assert status == 200
    over_socket(server, "POST", "/api/token/revoke", {"token": token})

    status, reply = loopback_json(server, "GET", "/api/state", token=token)
    assert (status, reply["code"]) == (401, "control_token_invalid")


def test_two_tokens_are_independent(control):
    server, _agent, platform = control
    kept = mint(server, platform, ALICE)
    dropped = mint(server, platform, ROOT)

    over_socket(server, "POST", "/api/token/revoke", {"token": dropped})

    status, state = loopback_json(server, "GET", "/api/state", token=kept)
    assert status == 200
    assert state["caller"]["account"] == "alice"
    status, reply = loopback_json(server, "GET", "/api/state", token=dropped)
    assert (status, reply["code"]) == (401, "control_token_invalid")


def test_a_restart_forgets_every_token(tmp_path):
    platform = FakeControlPlatform()
    first = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp_path / "agent.sock"),
        page_port=0,
    )
    first.start()
    token = mint(first, platform, ROOT)
    first.stop()

    second = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp_path / "agent.sock"),
        page_port=0,
    )
    second.start()
    try:
        status, reply = over_socket(
            second, "POST", "/api/token/watch", {"token": token}
        )
        assert reply == {"is_claimed": False, "is_alive": False}
        status, reply = loopback_json(second, "GET", "/api/state", token=token)
        assert (status, reply["code"]) == (401, "control_token_invalid")
    finally:
        second.stop()


def test_watch_and_revoke_answer_only_on_the_socket(control):
    server, _agent, platform = control
    token = mint(server, platform, ALICE)

    for path in ("/api/token/watch", "/api/token/revoke"):
        status, reply = loopback_json(
            server, "POST", path, token=token, body={"token": token}
        )
        assert (status, reply["code"]) == (404, "unknown_request")
    _status, reply = over_socket(server, "POST", "/api/token/watch", {"token": token})
    assert reply["is_alive"] is True


def test_watching_an_unknown_token_answers_dead(control):
    server, _agent, _platform = control

    _status, reply = over_socket(
        server, "POST", "/api/token/watch", {"token": "never-minted"}
    )

    assert reply == {"is_claimed": False, "is_alive": False}


def test_revoking_an_unknown_token_is_nothing(control):
    server, _agent, _platform = control

    status, reply = over_socket(
        server, "POST", "/api/token/revoke", {"token": "never-minted"}
    )

    assert (status, reply) == (200, {})


def test_an_unclaimed_token_waits_forever(tmp_path):
    now = [0.0]
    tokens = ControlTokenStore(idle_ttl_s=10, clock=lambda: now[0])
    platform = FakeControlPlatform()
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp_path / "agent.sock"),
        page_port=0,
        tokens=tokens,
    )
    server.start()
    try:
        token = mint(server, platform, ALICE)
        # No page request yet: the pulse has not started, so nothing expires.
        now[0] = 100000.0
        _status, reply = over_socket(
            server, "POST", "/api/token/watch", {"token": token}
        )
        assert reply == {"is_claimed": False, "is_alive": True}
        status, state = loopback_json(server, "GET", "/api/state", token=token)
        assert status == 200
        assert state["caller"]["account"] == "alice"
        # Claimed now: the pulse runs, and stopping it ends the session.
        now[0] = 100011.0
        _status, reply = over_socket(
            server, "POST", "/api/token/watch", {"token": token}
        )
        assert reply == {"is_claimed": True, "is_alive": False}
    finally:
        server.stop()


def test_an_expired_pulse_ends_the_token(tmp_path):
    now = [0.0]
    tokens = ControlTokenStore(idle_ttl_s=10, clock=lambda: now[0])
    platform = FakeControlPlatform()
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp_path / "agent.sock"),
        page_port=0,
        tokens=tokens,
    )
    server.start()
    try:
        token = mint(server, platform, ALICE)
        # The page's polling keeps the pulse alive.
        now[0] = 8.0
        status, _state = loopback_json(server, "GET", "/api/state", token=token)
        assert status == 200
        now[0] = 16.0
        status, reply = over_socket(
            server, "POST", "/api/token/watch", {"token": token}
        )
        assert reply == {"is_claimed": True, "is_alive": True}
        # The pulse stops; the idle TTL passes; the session is over — and
        # the watch still says a page HAD claimed it, which is what words
        # the close as a closed window.
        now[0] = 27.0
        status, reply = over_socket(
            server, "POST", "/api/token/watch", {"token": token}
        )
        assert reply == {"is_claimed": True, "is_alive": False}
        status, reply = loopback_json(server, "GET", "/api/state", token=token)
        assert (status, reply["code"]) == (401, "control_token_invalid")
    finally:
        server.stop()


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


def test_a_downscoped_token_acts_as_its_account(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT, {"account": "bob"})

    status, _state = loopback_json(
        server,
        "POST",
        "/api/services/ai",
        token=token,
        body={"targets": {"bob": True}},
        headers={"Origin": AGENT_CONTROL_PAGE_ORIGIN},
    )

    assert status == 200
    assert agent.service_calls[-1] == (
        "ai",
        "bob",
        False,
        {"targets": {"bob": True}},
    )


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


def test_the_fs_routes_answer_over_the_loopback_as_the_token(control):
    server, _agent, platform = control
    token = mint(server, platform, ROOT, {"account": "bob"})

    status, reply = loopback_json(server, "GET", "/api/fs?path=/srv", token=token)
    assert status == 200
    assert reply == {"path": "/srv", "dirs": ["docs", "media"]}
    assert platform.fs_calls[-1] == ("list", "bob", "/srv")

    status, reply = loopback_json(server, "GET", "/api/fs", token=token)
    assert status == 200
    assert reply["path"] == "/home/bob"

    status, _reply = loopback_json(
        server,
        "POST",
        "/api/fs",
        token=token,
        body={"path": "/srv/new"},
        headers={"Origin": AGENT_CONTROL_PAGE_ORIGIN},
    )
    assert status == 200
    assert platform.fs_calls[-1] == ("mkdir", "bob", "/srv/new")


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


def test_an_unknown_loopback_post_authenticates_before_it_404s(control):
    server, _agent, platform = control

    status, reply = loopback_json(server, "POST", "/api/nothing", body={})
    assert (status, reply["code"]) == (401, "control_token_invalid")

    token = mint(server, platform, ALICE)
    status, reply = loopback_json(server, "POST", "/api/nothing", token=token, body={})
    assert (status, reply["code"]) == (404, "unknown_request")


def test_an_unknown_loopback_get_answers_404_without_a_token(control):
    server, _agent, _platform = control

    status, reply = loopback_json(server, "GET", "/api/nothing")

    assert (status, reply["code"]) == (404, "unknown_request")
