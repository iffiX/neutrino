"""The scripted running client every ``nclient`` command is tried against.

A command reaches the running client only through ``client.request`` and
``client.upgrade`` on the control socket; the fixture here stands in for
both. It answers ``GET /api/state`` with a state document a test edits,
records every request, answers each route by a test's own answer or with
the state, and hands back scripted kept connections for a 101. A client
that is not running refuses the connection, as a missing socket does. The
words are English unless a test fixes another language.
"""

import copy
import time

import pytest

from neutrino_client.cli import ssh, terminal, wording
from neutrino_client.control import client

FUTURE_S = 3600

HOME = {
    "hub_id": "h1",
    "hub_name": "home",
    "binding_id": "c1",
    "gateway_url": "tcp://192.168.1.2:8443",
    "connection": "connected",
    "reached_through": "lan",
    "rtt_ms": 3,
    "wait_reason": "",
    "wait_code": None,
    "next_round_at": None,
    "is_panel_allowed": True,
    "last_error": None,
    "jobs": {"is_opening_panel": False},
}
OFFICE = {
    "hub_id": "h2",
    "hub_name": "office",
    "binding_id": "c2",
    "gateway_url": "tcp://10.0.0.2:8443",
    "connection": "waiting",
    "reached_through": "",
    "rtt_ms": None,
    "wait_reason": "hub_silent",
    "wait_code": None,
    "next_round_at": None,
    "is_panel_allowed": False,
    "last_error": None,
    "jobs": {"is_opening_panel": False},
}


def _app(hub_id, app_id, title, source, device_id, device_name, local_name):
    return {
        "hub_id": hub_id,
        "id": app_id,
        "title": title,
        "source": source,
        "device_id": device_id,
        "device_name": device_name,
        "local_name": local_name,
        "job": "",
        "last_error": None,
        "is_in_use": False,
    }


def _entry(hub_id, entry_id, kind, payload, **fields):
    entry = {
        "hub_id": hub_id,
        "id": entry_id,
        "type": kind,
        "title": "",
        "payload": payload,
        "is_healthy": True,
        "source": "module",
        "description": "",
        "device_id": "d1",
        "device_name": "lab-gpu",
        "is_own_machine": False,
        "job": "",
        "last_error": None,
    }
    entry.update(fields)
    return entry


APPS = [
    _app(
        "h1", "gitea_d1", "Gitea", "module", "d1", "lab-gpu", "gitea.lab-gpu.localhost"
    ),
    _app(
        "h1", "ssh_server_d1", "SSH", "module", "d1", "lab-gpu", "ssh.lab-gpu.localhost"
    ),
    _app("h2", "gitea_d7", "Gitea", "module", "d7", "build", "gitea.build.localhost"),
    _app("h1", "decl_dns", "DNS", "declared", "", "", "dns.home.localhost"),
]
SERVICES = [
    _entry(
        "h1",
        "gitea_d1_web",
        "web",
        {"url": "http://192.168.1.5:3000/explore", "is_token_required": False},
        app_id="gitea_d1",
        name="web",
        local_port=25101,
        forward=None,
    ),
    _entry(
        "h1",
        "gitea_d1_ssh",
        "port",
        {"host": "192.168.1.5", "port": 2222, "protocol": "tcp"},
        app_id="gitea_d1",
        name="ssh",
        local_port=26022,
        forward=None,
    ),
    _entry(
        "h1",
        "ssh_server_d1_iffi",
        "ssh",
        {"host": "192.168.1.5", "port": 22001, "account": "iffi"},
        app_id="ssh_server_d1",
        name="iffi",
        local_port=27001,
        forward=None,
    ),
    _entry(
        "h1",
        "ssh_server_d1_lab",
        "ssh",
        {"host": "192.168.1.5", "port": 22002, "account": "lab"},
        app_id="ssh_server_d1",
        name="lab",
        local_port=27002,
        forward=None,
    ),
    _entry(
        "h2",
        "gitea_d7_web",
        "web",
        {"url": "https://10.0.0.7/", "is_token_required": False},
        app_id="gitea_d7",
        name="web",
        local_port=25500,
        forward=None,
        device_id="d7",
        device_name="build",
    ),
    _entry(
        "h1",
        "decl_dns_port_53_udp",
        "port",
        {"host": "192.168.1.9", "port": 53, "protocol": "udp"},
        app_id="decl_dns",
        name="port_53_udp",
        local_port=24053,
        forward=None,
        source="declared",
        device_id="",
        device_name="",
        is_healthy=None,
    ),
    _entry(
        "h1",
        "ai",
        "ai",
        {"endpoint": "http://192.168.1.2:8317", "protocol": "openai", "models": []},
        local_port="auto",
        forward=None,
        device_id="",
        device_name="",
    ),
    _entry(
        "h1",
        "share_d1_alice",
        "file",
        {"protocol": "smb", "host": "192.168.1.5", "share": "alice", "users": []},
        local_port="auto",
        forward=None,
        mount_default="/home/alice/remote/lab-gpu-alice",
        is_declared=False,
    ),
    _entry(
        "h1",
        "nas_file_media",
        "file",
        {"protocol": "smb", "host": "192.168.1.9", "share": "media", "users": []},
        local_port="auto",
        forward=None,
        source="declared",
        app_id="nas",
        name="file_media",
        device_id="",
        device_name="",
        mount_default="/home/alice/remote/192-168-1-9-media",
        is_declared=True,
    ),
    _entry(
        "h1",
        "rdp_d1",
        "rdp",
        {"protocol": "rustdesk", "host": "192.168.1.5", "port": 21118, "attention": ""},
        local_port="auto",
        forward=None,
    ),
]
MOUNTED = {
    "record_id": "r1",
    "hub_id": "h1",
    "entry_id": "share_d1_alice",
    "host": "192.168.1.5",
    "server": "127.0.0.1",
    "share": "alice",
    "username": "alice",
    "path": "/home/alice/remote/lab-gpu-alice",
    "is_attached": True,
    "state": "mounted",
    "code": "",
    "params": {},
}
SESSION = "3f2a1b4c-0000-4000-8000-000000000001"
OTHER_SESSION = "3f2a9999-0000-4000-8000-000000000002"
TERMINALS = {
    "machines": [
        {
            "hub_id": "h1",
            "device_id": "d1",
            "name": "lab-gpu",
            "is_online": True,
            "accounts": ["iffi", "lab"],
        },
        {
            "hub_id": "h2",
            "device_id": "d7",
            "name": "build",
            "is_online": True,
            "accounts": ["ci"],
        },
        {
            "hub_id": "h2",
            "device_id": "d8",
            "name": "lab-gpu",
            "is_online": False,
            "accounts": [],
        },
    ],
    "sessions": [
        {
            "hub_id": "h1",
            "device_id": "d1",
            "session_id": SESSION,
            "title": "vim notes.md",
            "account": "iffi",
            "owner": "client:c1",
            "owner_name": "box",
            "is_owned": True,
            "is_persistent": True,
            "is_shared": False,
            "attached_count": 2,
            "started_at": 0,
        },
        {
            "hub_id": "h1",
            "device_id": "d1",
            "session_id": OTHER_SESSION,
            "title": "top",
            "account": "lab",
            "owner": "hub",
            "owner_name": "home",
            "is_owned": False,
            "is_persistent": False,
            "is_shared": True,
            "attached_count": 1,
            "started_at": 0,
        },
    ],
}


def state_document() -> dict:
    """The state of a client bound to two hubs, as GET /api/state answers."""
    sessions = copy.deepcopy(TERMINALS)
    for row in sessions["sessions"]:
        row["started_at"] = int(time.time()) - 3700
    return {
        "version": "0.6.0",
        "language": "en",
        "theme": "dark",
        "is_ssh_include_enabled": False,
        "hostname": "box",
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        "mount_location_shape": "path",
        "home": "/home/alice",
        "is_connected": True,
        "exit_hub_id": "",
        "hubs": [dict(HOME), dict(OFFICE)],
        "notices": [],
        "apps": copy.deepcopy(APPS),
        "services": copy.deepcopy(SERVICES),
        "mounts": [dict(MOUNTED)],
        "terminals": sessions,
        "ai": {
            "is_enabled": False,
            "is_active": False,
            "is_managed": False,
            "state": "installed",
            "code": "",
            "params": {},
            "work": {"state": "idle"},
        },
        "ai_tool_configs": {"claude": {"default": "m1"}},
        "viewers": {},
    }


def unbound_document() -> dict:
    """The state of a running client that has joined no hub."""
    state = state_document()
    state.update(
        is_connected=False,
        hubs=[],
        apps=[],
        services=[],
        mounts=[],
        terminals={"machines": [], "sessions": []},
    )
    return state


class KeptConnection:
    """One connection the running client kept: what it hands back, what it was sent."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.sent = []
        self.is_closed = False

    def read(self, size):
        if not self.chunks:
            return b""
        data, rest = self.chunks[0][:size], self.chunks[0][size:]
        if rest:
            self.chunks[0] = rest
        else:
            self.chunks.pop(0)
        return data

    def send(self, data):
        self.sent.append(bytes(data))

    def close(self):
        self.is_closed = True


class ScriptedClient:
    """The running client as the commands meet it, scripted by a test.

    Attributes:
        state: The state document ``GET /api/state`` answers with.
        requests: Every request, ``(method, path, body)``.
        answers: A route's own answer, ``answer(body) -> (status, reply)``.
        is_running: Whether anything answers on the socket.
        upgrades: A 101 route's answer, ``(status, reply)``.
        output: The bytes the output connection hands back.
        result: What ``/api/terminal/result`` answers.
        kept: The connections handed out, by route.
        on_state: Called with the state before each ``GET /api/state`` is
            answered, so a job a test started can move on.
    """

    def __init__(self):
        self.state = state_document()
        self.requests = []
        self.answers = {}
        self.is_running = True
        self.upgrades = {}
        self.output = [b"$ "]
        self.result = {"exit_code": None}
        self.kept = {}
        self.on_state = None

    def posts(self, path: str) -> list:
        """The bodies posted to one route, in order."""
        return [
            body
            for method, asked, body in self.requests
            if method == "POST" and asked == path
        ]

    def request(self, *, socket_path, method, path, body=None, timeout_s=5):
        if not self.is_running:
            raise ConnectionRefusedError(socket_path)
        self.requests.append((method, path, copy.deepcopy(body)))
        if path == "/api/terminal/result":
            return 200, dict(self.result)
        if path in self.answers:
            return self.answers[path](body)
        if method == "GET" and path == "/api/state" and self.on_state is not None:
            self.on_state(self.state)
        return 200, copy.deepcopy(self.state)

    def upgrade(self, *, socket_path, path, body, timeout_s=5):
        if not self.is_running:
            raise ConnectionRefusedError(socket_path)
        self.requests.append(("UPGRADE", path, copy.deepcopy(body)))
        status, reply = self.upgrades.get(path, (101, {"terminal_id": "t1"}))
        if status != 101:
            return status, dict(reply), None
        chunks = self.output if path == terminal.TERMINAL_OUTPUT_ROUTE else []
        connection = KeptConnection(chunks)
        self.kept[path] = connection
        return 101, dict(reply), connection


class _SocketPlatform:
    """A platform whose control socket is a name nothing listens on."""

    def control_socket_path(self) -> str:
        return "/nowhere/client.sock"

    def easytier_daemon_address(self) -> str:
        return "/nowhere/easytier.sock"

    def config_dir(self) -> str:
        return "/nowhere"

    def system_language(self) -> str:
        return "en"


@pytest.fixture
def running(monkeypatch):
    """A running client the commands reach, in English."""
    scripted = ScriptedClient()
    monkeypatch.setattr(client, "request", scripted.request)
    monkeypatch.setattr(client, "upgrade", scripted.upgrade)
    monkeypatch.setattr(wording, "detect_platform", _SocketPlatform)
    monkeypatch.setattr(wording, "CLIENT_JOB_POLL_S", 0)
    monkeypatch.setattr(terminal, "detect_platform", _SocketPlatform)
    monkeypatch.setattr(ssh, "detect_platform", _SocketPlatform)
    wording.fix_language("en")
    yield scripted
    wording.fix_language("")


@pytest.fixture
def chinese():
    """The client's language fixed to Chinese for one test."""
    wording.fix_language("zh-CN")
    yield
    wording.fix_language("")
