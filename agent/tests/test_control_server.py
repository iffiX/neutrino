"""The control channel end to end: one handler set, two transports.

The socket answers each caller with the kernel-reported identity's own
scope; the loopback page answers only to tokens minted over the socket,
and refuses request shapes a cross-site form can produce.
"""

import http.client
import json

import pytest

import neutrino_agent.enrollment as enrollment
from neutrino_agent.constants import AGENT_CONTROL_PAGE_ORIGIN
from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError

ROOT = {"account": "root", "uid": 0, "is_privileged": True}
ALICE = {"account": "alice", "uid": 1000, "is_privileged": False}


class FakeControlPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self):
        self.peer = dict(ROOT)
        self.peer_error = None

    def human_accounts(self) -> list:
        return ["alice", "bob"]

    def read_peer_identity(self, connection) -> dict:
        if self.peer_error is not None:
            raise self.peer_error
        return self.peer


class FakeControlAgent:
    def __init__(self):
        self.requested = []
        self.connected_links = []
        self.is_disconnected = False
        self.connect_error = None

    def platform(self) -> dict:
        return {"os": "linux", "family": "debian", "arch": "x86_64"}

    def catalog(self) -> dict:
        return {
            "functions": {
                "openssh": {
                    "title": "SSH server",
                    "description": "",
                    "platforms": {"linux": {}},
                }
            },
            "services": {
                "ai": {"kind": "ai", "title": "AI tools"},
                "svc_wiki": {"kind": "link", "title": "Wiki", "url": "http://w/"},
                "svc_tcp": {"kind": "port", "title": "tcp", "host": "h", "port": 5432},
            },
        }

    def function_states(self) -> dict:
        return {"openssh": {"state": "installed", "is_active": True}}

    def desired_functions(self) -> dict:
        return {"openssh": {"is_enabled": True}}

    def last_error(self):
        return None

    def accounts(self) -> list:
        return ["alice", "bob"]

    def ai_targets(self) -> dict:
        return {"alice": True, "bob": False}

    def request_function(self, name, *, is_enabled=None, is_activated=None):
        self.requested.append((name, is_enabled, is_activated))

    def connect(self, link):
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_links.append(link)

    def disconnect(self):
        self.is_disconnected = True


@pytest.fixture
def control(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(tmp_path / "agent.json"))
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
    assert state["caller"] == {"account": "root", "is_privileged": True}
    assert state["accounts"] == ["alice", "bob"]
    assert state["ai_targets"] == {"alice": True, "bob": False}

    platform.peer = dict(ALICE)
    status, state = over_socket(server, "GET", "/api/state")
    assert status == 200
    assert state["caller"] == {"account": "alice", "is_privileged": False}
    assert state["accounts"] == ["alice"]
    assert state["ai_targets"] == {"alice": True}
    assert state["services"]["svc_wiki"]["url"] == "http://w/"
    assert [f["name"] for f in state["functions"]] == ["openssh"]


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
    assert state["caller"] == {"account": "alice", "is_privileged": False}
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
        "/api/function",
        token=token,
        body={"name": "openssh"},
        headers={"Origin": "http://evil.example"},
    )

    assert (status, reply["code"]) == (403, "control_origin_refused")


def test_a_loopback_post_must_be_json(control):
    server, _agent, platform = control
    token = mint(server, platform, ROOT)

    status, reply = loopback_json(
        server,
        "POST",
        "/api/function",
        token=token,
        body={"name": "openssh"},
        headers={"Content-Type": "text/plain"},
    )

    assert (status, reply["code"]) == (400, "control_content_type_refused")


def test_the_pages_own_origin_passes(control):
    server, agent, platform = control
    token = mint(server, platform, ROOT)

    status, state = loopback_json(
        server,
        "POST",
        "/api/function",
        token=token,
        body={"name": "openssh", "is_enabled": False},
        headers={"Origin": AGENT_CONTROL_PAGE_ORIGIN},
    )

    assert status == 200
    assert state["caller"]["is_privileged"] is True
    assert agent.requested == [("openssh", False, None)]


def test_privileged_verbs_refuse_an_ordinary_caller(control):
    server, agent, platform = control
    platform.peer = dict(ALICE)

    for path, body in (
        ("/api/connect", {"link": "neutrino://enroll/x"}),
        ("/api/disconnect", {}),
        ("/api/function", {"name": "openssh", "is_enabled": False}),
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
    assert state["caller"] == {"account": "bob", "is_privileged": False}
    assert state["accounts"] == ["bob"]

    platform.peer = dict(ROOT)
    status, reply = over_socket(server, "POST", "/api/token", {"account": "mallory"})
    assert (status, reply["code"]) == (400, "control_unknown_account")


def test_tokens_are_minted_only_over_the_socket(control):
    server, _agent, platform = control
    token = mint(server, platform, ROOT)

    status, reply = loopback_json(server, "POST", "/api/token", token=token, body={})

    assert (status, reply["code"]) == (404, "unknown_request")


def test_service_actions_are_declared_with_scopes_but_not_filled(control):
    server, _agent, platform = control

    platform.peer = dict(ALICE)
    status, reply = over_socket(
        server, "POST", "/api/services/ai", {"account": "bob", "is_activated": True}
    )
    assert (status, reply["code"]) == (403, "control_scope_refused")

    status, reply = over_socket(
        server, "POST", "/api/services/ai", {"account": "alice", "is_activated": True}
    )
    assert (status, reply["code"]) == (501, "not_implemented")

    platform.peer = dict(ROOT)
    status, reply = over_socket(
        server, "POST", "/api/services/ai", {"account": "bob", "is_activated": True}
    )
    assert (status, reply["code"]) == (501, "not_implemented")

    for path in ("/api/services/mount", "/api/services/forward"):
        status, reply = over_socket(server, "POST", path, {})
        assert (status, reply["code"]) == (501, "not_implemented")


def test_an_unknown_route_answers_a_code(control):
    server, _agent, platform = control
    platform.peer = dict(ROOT)

    status, reply = over_socket(server, "GET", "/api/nothing")
    assert (status, reply["code"]) == (404, "unknown_request")

    status, reply = over_socket(server, "POST", "/api/nothing", {})
    assert (status, reply["code"]) == (404, "unknown_request")
