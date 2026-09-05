"""The control channel end to end: one handler set, two transports.

The socket answers each caller with the kernel-reported identity's own
scope; the loopback page answers only to tokens minted over the socket,
and refuses request shapes a cross-site form can produce. Tokens are minted
only while the page is actually served, watched and revoked only over the
socket, and expired when their pulse stops.
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
from tests.conftest import ALICE, ROOT, FakeControlAgent, FakeControlPlatform



@pytest.fixture
def control(tmp_path):
    agent = FakeControlAgent()
    platform = FakeControlPlatform()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=lambda message: None,
        socket_path=str(tmp_path / "agent.sock"),
        page_port=0,
    )
    server.start()
    assert server.socket_path and server.page_port
    yield server, agent, platform
    server.stop()


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


def test_an_unreadable_peer_is_refused_not_guessed(control):
    server, _agent, platform = control

    platform.peer_error = KeyError(4242)
    status, reply = over_socket(server, "GET", "/api/state")
    assert (status, reply["code"]) == (403, "control_identity_unknown")

    platform.peer_error = PlatformUnsupportedError("no peers here")
    status, reply = over_socket(server, "GET", "/api/state")
    assert (status, reply["code"]) == (403, "unsupported_platform")


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


def test_a_tokenless_loopback_request_gets_only_the_hint_page(control):
    server, _agent, _platform = control

    status, raw = over_loopback(server, "GET", "/")
    assert status == 200
    assert b"nagent ui" in raw

    status, reply = loopback_json(server, "GET", "/api/state")
    assert (status, reply["code"]) == (401, "control_token_invalid")

    status, reply = loopback_json(server, "GET", "/api/state", token="never-minted")
    assert (status, reply["code"]) == (401, "control_token_invalid")


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
    assert agent.requested == [("openssh_server", False, None)]


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


def test_a_refused_link_reports_on_the_state(control):
    server, agent, platform = control
    platform.peer = dict(ROOT)
    agent.connect_error = enrollment.EnrollmentError("the link is unusable")

    status, state = over_socket(
        server, "POST", "/api/connect", {"link": "neutrino://enroll/x"}
    )

    assert status == 200
    assert state["error"] == "the link is unusable"


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


def test_the_mint_reply_names_the_page_port(control):
    server, _agent, platform = control
    platform.peer = dict(ROOT)

    status, reply = over_socket(server, "POST", "/api/token", {})

    assert status == 200
    assert reply["page_port"] == server.page_port


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


def test_making_a_folder_follows_the_same_identity_rules(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    status, reply = over_socket(server, "POST", "/api/fs", {"path": "/srv/new"})
    assert status == 200
    assert platform.fs_calls[-1] == ("mkdir", "alice", "/srv/new")

    status, reply = over_socket(server, "POST", "/api/fs", {"path": "relative"})
    assert (status, reply["code"]) == (403, "fs_refused")


def test_an_unknown_route_answers_a_code(control):
    server, _agent, platform = control
    platform.peer = dict(ROOT)

    status, reply = over_socket(server, "GET", "/api/nothing")
    assert (status, reply["code"]) == (404, "unknown_request")

    status, reply = over_socket(server, "POST", "/api/nothing", {})
    assert (status, reply["code"]) == (404, "unknown_request")
