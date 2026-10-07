"""Suite-wide isolation and the shared fakes, defined once.

The autouse redirect keeps every store off the real machine: the platform's
configuration directory, and with it the bindings, the state store and the
mount credentials, all land in ``tmp_path``, and the control socket in a
runtime directory of its own. The fakes here are the ones more than one
directory drives: the client platform, the resident, the injected clock,
the link builder and the log sink. ``HUB_SERVICES`` is what one hub sends
in a state; ``SERVICES`` is the two-hub list the resident merges from it,
each entry stamped with its ``hub_id``.
"""

import base64
import json
import os
import socket
import subprocess
import threading
import zlib

import pytest

import neutrino_client.cli.wording as wording_module
import neutrino_client.core.enrollment as enrollment
from neutrino_client.platforms.base import ClientPlatform
from neutrino_client.platforms.darwin import DarwinPlatform
from neutrino_client.platforms.linux import LinuxPlatform
from neutrino_client.platforms.windows import WindowsPlatform
from neutrino_client import edition


def pytest_collection_modifyitems(config, items):
    """Skip the tests of a left-out feature the tree does not carry."""
    for item in items:
        for marker in item.iter_markers(name="feature"):
            if not edition.has_feature(marker.args[0]):
                item.add_marker(
                    pytest.mark.skip(reason=f"this tree has no {marker.args[0]}")
                )


SAME_USER = {"account": "alice", "uid": 1000, "is_same_user": True}
OTHER_USER = {"account": "bob", "uid": 1001, "is_same_user": False}

HUB_SERVICES = [
    {
        "id": "ai",
        "type": "ai",
        "title": "AI tools",
        "payload": {
            "endpoint": "http://hub:8080",
            "protocol": "anthropic",
            "models": ["m1", "m2"],
        },
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "svc_wiki",
        "type": "web",
        "title": "Wiki",
        "payload": {"url": "http://w/"},
        "is_healthy": True,
        "source": "declared",
        "description": "declared by hand",
    },
    {
        "id": "svc_tcp",
        "type": "port",
        "title": "tcp",
        "payload": {"host": "h", "port": 5432},
        "is_healthy": True,
        "source": "module",
        "description": "published by container mysql:8.0",
    },
    {
        "id": "share_media",
        "type": "file",
        "title": "media",
        "payload": {"protocol": "smb", "host": "hub", "share": "media"},
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "rdp_s9",
        "type": "rdp",
        "title": "studio",
        "payload": {"protocol": "rustdesk", "host": "192.168.100.6", "port": 21118},
        "is_healthy": True,
        "source": "device",
        "description": "shared from studio",
    },
]

# What the second hub sends; its ids overlap the first's on purpose.
OFFICE_SERVICES = [
    {
        "id": "ai",
        "type": "ai",
        "title": "Office AI",
        "payload": {
            "endpoint": "http://office:8080",
            "protocol": "anthropic",
            "models": ["o1"],
        },
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "svc_docs",
        "type": "web",
        "title": "Docs",
        "payload": {"url": "http://docs/"},
        "is_healthy": True,
        "source": "declared",
        "description": "declared by hand",
    },
    {
        "id": "svc_tcp",
        "type": "port",
        "title": "office db",
        "payload": {"host": "office", "port": 5432},
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "share_media",
        "type": "file",
        "title": "office media",
        "payload": {"protocol": "smb", "host": "office", "share": "media"},
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "rdp_lab",
        "type": "rdp",
        "title": "lab",
        "payload": {"protocol": "rustdesk", "host": "10.0.0.6", "port": 21118},
        "is_healthy": True,
        "source": "device",
        "description": "shared from lab",
    },
]


def with_hub(entries: list, hub_id: str) -> list:
    """One hub's entries the way the resident merges them, stamped with the hub."""
    return [dict(entry, hub_id=hub_id) for entry in entries]


SERVICES = with_hub(HUB_SERVICES, "h1") + with_hub(OFFICE_SERVICES, "h2")


@pytest.fixture(autouse=True)
def _isolated_person_paths(tmp_path, monkeypatch):
    config_dir = str(tmp_path / "config")
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

    def redirected(self) -> str:
        return config_dir

    for platform_class in (
        ClientPlatform,
        DarwinPlatform,
        LinuxPlatform,
        WindowsPlatform,
    ):
        monkeypatch.setattr(platform_class, "config_dir", redirected)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # cc-switch's store is named to it through the process's environment;
    # each test starts with none named and leaves none behind.
    monkeypatch.delenv("CC_SWITCH_CONFIG_DIR", raising=False)
    (tmp_path / "home").mkdir()


# The real ask of the EasyTier daemon, for the tests that drive it.
REAL_ASK_HOLD = wording_module.ask_hold


@pytest.fixture(autouse=True)
def _isolated_network(monkeypatch):
    """The hub's name resolves to nothing, no route is looked at and no
    EasyTier daemon of this machine is asked who holds it, unless a test says
    otherwise."""
    monkeypatch.setattr(wording_module, "ask_hold", lambda verb: {})
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "")
    monkeypatch.setattr(enrollment, "default_source_address", lambda urls: "")


@pytest.fixture
def config_path(tmp_path):
    """The binding file the autouse redirect already points the client at."""
    return tmp_path / "config" / "client.json"


class Clock:
    """An injected clock: time moves only when a test says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def link_for(payload: dict) -> str:
    """An enrollment link over one payload as a hub writes it: compact JSON,
    zlib level 9, unpadded base64url; ``role`` defaults to client."""
    body = {"role": "client", **payload}
    text = json.dumps(body, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(zlib.compress(text, 9)).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def discard(message: str) -> None:
    """Swallow the log lines."""


BINDING = {
    "id": "c1",
    "name": "box",
    "hub_id": "h1",
    "hub_name": "home",
    "gateway_url": "http://127.0.0.1:9",
    "gateway_urls": [],
    "fingerprint": "",
    "token": "tok",
    "overlays": [],
    "is_overlay_on": False,
    "overlay_pick": "",
}
OFFICE_BINDING = {
    "id": "c2",
    "name": "box",
    "hub_id": "h2",
    "hub_name": "office",
    "gateway_url": "https://office.lan:8443",
    "gateway_urls": [],
    "fingerprint": "",
    "token": "tok2",
    "overlays": [],
    "is_overlay_on": False,
    "overlay_pick": "",
}


def bind(path, url="http://127.0.0.1:9", fingerprint="", bindings=None) -> None:
    """The bindings on disk, the way ``client.json`` keeps them.

    Args:
        path: The binding file.
        url: The first binding's gateway url.
        fingerprint: The first binding's fingerprint.
        bindings: Every binding to write; None writes the one binding.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if bindings is None:
        bindings = [dict(BINDING, gateway_url=url, fingerprint=fingerprint)]
    path.write_text(json.dumps({"bindings": list(bindings), "exit_hub_id": ""}))


# The overlay part of a hub row: a NetBird network this machine is on.
OVERLAY_ROW = {
    "network": "netbird",
    "networks": [
        {"provider": "netbird", "network": "api.netbird.io"},
        {"provider": "easytier", "network": "home"},
    ],
    "state": "on",
    "stage": "",
    "is_waiting": False,
    "address": "100.64.0.7",
    "error": None,
}
# The jobs of a hub at rest.
IDLE_JOBS = {"is_refreshing": False, "overlay_job": "", "is_leaving": False}
HUB_ROW = {
    "hub_id": "h1",
    "hub_name": "home",
    "binding_id": "c1",
    "gateway_url": "https://hub.lan:8443",
    "software": "neutrino_hub/0.3.0",
    "connection": "connected",
    "is_pending": False,
    "last_error": None,
    "is_exit": True,
    "overlay": dict(OVERLAY_ROW),
    "jobs": dict(IDLE_JOBS),
}
# The machines the first hub offers a terminal on, as the resident merges them.
TERMINALS = [
    {"hub_id": "h1", "device_id": "d_lepton", "name": "lepton", "is_online": True},
    {"hub_id": "h1", "device_id": "d_muon", "name": "muon", "is_online": False},
]
# The sessions the first hub lists for this client.
TERMINAL_SESSIONS = [
    {
        "hub_id": "h1",
        "session_id": "s1",
        "device_id": "d_lepton",
        "owner": "client:c1",
        "is_owned": True,
        "is_persistent": True,
        "is_shared": False,
        "attached_count": 0,
        "title": "zsh",
        "started_at": 1700000000,
    }
]
OFFICE_ROW = {
    "hub_id": "h2",
    "hub_name": "office",
    "binding_id": "c2",
    "gateway_url": "https://office.lan:8443",
    "software": "neutrino_hub/0.3.0",
    "connection": "connected",
    "is_pending": False,
    "last_error": None,
    "is_exit": False,
    "overlay": {
        "network": "",
        "networks": [],
        "state": "off",
        "stage": "",
        "is_waiting": False,
        "address": "",
        "error": None,
    },
    "jobs": dict(IDLE_JOBS),
}


class FakeClientPlatform(ClientPlatform):
    """A platform whose mounts are in memory and whose peer is scripted."""

    os_name = "linux"

    def __init__(self):
        self.peer = dict(SAME_USER)
        self.peer_error = None
        self.fs_calls = []
        self.fs_error = None
        self.attached = set()
        self.attach_calls = []
        self.detach_calls = []
        self.attach_error = None
        self.detach_error = None
        # Where the system places a volume when no location is given.
        self.volume_location = ""
        self.has_tooling = True
        self.opened_urls = []
        self.started = []
        self.start_error = None
        self.socket_path = ""
        self.answered = []
        self.on_answer = None
        self.answer_error = None
        self.answer_output = ""
        self.language = "en"

    def system_language(self) -> str:
        return self.language

    def control_socket_path(self) -> str:
        if self.socket_path:
            return self.socket_path
        return os.path.join(os.environ["XDG_RUNTIME_DIR"], "neutrino", "client.sock")

    def read_peer_identity(self, connection) -> dict:
        if self.peer_error is not None:
            raise self.peer_error
        return dict(self.peer)

    def list_directories(self, *, path: str) -> list:
        self.fs_calls.append(("list", path))
        if self.fs_error is not None:
            raise self.fs_error
        return ["docs", "media"]

    def make_directory(self, *, path: str) -> None:
        self.fs_calls.append(("mkdir", path))
        if self.fs_error is not None:
            raise self.fs_error
        # Only a POSIX-absolute path (the tmp_path the mount cases use) is
        # made on disk; a foreign-OS path a routes case passes is recorded
        # and left alone, so no test writes outside its tmp_path.
        if path.startswith("/"):
            os.makedirs(path, exist_ok=True)

    def has_mount_tooling(self) -> bool:
        return self.has_tooling

    def attach_share(self, *, share_url, location, credentials_path, port=0) -> str:
        self.attach_calls.append(
            {
                "share_url": share_url,
                "port": port,
                "location": location,
                "credentials_path": credentials_path,
            }
        )
        if self.attach_error is not None:
            raise self.attach_error
        attached_at = location or self.volume_location
        self.attached.add(attached_at)
        return attached_at

    def detach_share(self, *, location: str) -> None:
        self.detach_calls.append(location)
        if self.detach_error is not None:
            raise self.detach_error
        self.attached.discard(location)

    def is_share_attached(self, *, location: str) -> bool:
        return location in self.attached

    def open_url(self, url: str) -> None:
        self.opened_urls.append(url)

    def start_on_screen(self, argv: list):
        if self.start_error is not None:
            raise self.start_error
        process = FakeProcess(list(argv))
        self.started.append(process)
        return process

    def run_answering(self, argv: list, *, prompt, answer, timeout_s) -> tuple:
        if self.answer_error is not None:
            raise self.answer_error
        self.answered.append((list(argv), prompt, answer))
        if self.on_answer is not None:
            self.on_answer(list(argv))
        return 0, self.answer_output


class FakeConnectHub:
    """The hub's end of ``connect`` streams, played over real loopback sockets.

    Every open is recorded as ``(hub_id, args)``. The far end the hub would
    dial is ``far_port`` on the loopback, whatever the entry's payload names,
    so a byte that comes back proves it went through the stream and not to
    a device address. ``refusal`` closes every stream at once with that
    code, as the hub does when it judges the open; ``error`` is raised
    instead of opening, as for a hub that is not connected.
    """

    def __init__(self, far_port: int = 0):
        self.far_port = far_port
        self.opens = []
        self.refusal = ""
        self.error = None
        self.closed_here = []
        self._lock = threading.Lock()
        self._next_id = 1

    def open_connect(self, hub_id: str, args: dict):
        from neutrino_client.core.streams import ClientStream

        if self.error is not None:
            raise self.error
        with self._lock:
            stream_id = self._next_id
            self._next_id += 2
        self.opens.append((hub_id, dict(args)))
        if self.refusal:
            stream = ClientStream(stream_id=stream_id, kind="connect")
            stream.take_close(code=self.refusal, params={"service_id": "x"})
            return stream
        far = socket.create_connection(("127.0.0.1", self.far_port), timeout=5)
        far.settimeout(None)

        def send_bytes(frame: bytes) -> None:
            far.sendall(frame[4:])

        def close() -> None:
            self.closed_here.append(stream_id)
            try:
                far.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            far.close()

        stream = ClientStream(
            stream_id=stream_id,
            kind="connect",
            send_bytes=send_bytes,
            grant=lambda nbytes: None,
            close=close,
        )
        stream.take_credit(1 << 30)

        def pump() -> None:
            while True:
                try:
                    data = far.recv(65536)
                except OSError:
                    break
                if not data:
                    break
                stream.take_bytes(data)
            stream.take_close(code="", params={})

        threading.Thread(target=pump, daemon=True).start()
        return stream


def echo_server():
    """A real echo server on a loopback port of its own: ``(port, close)``."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def echo(connection) -> None:
        while True:
            try:
                data = connection.recv(4096)
            except OSError:
                break
            if not data:
                break
            connection.sendall(data)
        connection.close()

    def serve() -> None:
        while True:
            try:
                connection, _address = server.accept()
            except OSError:
                return
            threading.Thread(target=echo, args=(connection,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return port, server.close


def round_trip(port: int, payload: bytes) -> bytes:
    """Send bytes to a loopback port and read the same number back."""
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.sendall(payload)
    received = b""
    while len(received) < len(payload):
        chunk = client.recv(65536)
        if not chunk:
            break
        received += chunk
    client.close()
    return received


class FakeProcess:
    """A spawned viewer, remembered instead of run."""

    def __init__(self, argv: list):
        self.argv = argv
        self.returncode = None
        self.is_terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.is_terminated = True
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        return self.returncode if self.returncode is not None else 0

    def kill(self) -> None:
        self.returncode = -9


class FakeResident:
    """The resident the route table and the CLI talk to, scripted."""

    def __init__(self, *, platform=None):
        self.platform = platform if platform is not None else FakeClientPlatform()
        self.connected_links = []
        self.language_value = "en"
        self.theme_value = "dark"
        self.connect_error = None
        self.disconnected = []
        self.service_calls = []
        self.service_reply = {}
        self.service_error = None
        self.shows = 0
        self.shutdowns = 0
        self.is_shut_down = threading.Event()
        self.relaunches = 0
        self.is_bound = True
        self.hubs_value = [dict(HUB_ROW), dict(OFFICE_ROW)]
        self.reconnects = []
        self.refreshes = 0
        self.exits = []
        self.overlay_calls = []
        self.overlay_reply = {}
        self.forward_settings = []
        self.forward_reply = {}
        self.panel_opens = []
        self.panel_reply = {}
        self.clipboard_reply = {"text": "echo pasted\n"}
        self.clipboard_written = []
        self.clipboard_write_reply = {}
        self.notices_value = []
        self.terminal_calls = []
        self.terminal_reply = {"terminal_id": "t1"}
        self.session_reply = {}
        self.typed = []
        self.shown = [b"$ "]
        # The loopback port each forwarded entry listens on, by service key.
        self.forward_ports = {"h1/svc_tcp": 5432}
        self.states = {
            "mounts": [
                {
                    "record_id": "r1",
                    "hub_id": "h1",
                    "entry_id": "share_media",
                    "path": "/home/alice/nas/media",
                    "username": "alice",
                    "is_attached": True,
                    "state": "mounted",
                    "code": "",
                    "params": {},
                }
            ],
            "ai": {
                "is_enabled": True,
                "is_active": True,
                "state": "installed",
                "code": "",
                "params": {},
            },
            "ai_tool_configs": {"claude": {"default": "m1"}},
            "viewers": {},
        }

    def hostname(self) -> str:
        return "box"

    def language(self) -> str:
        return self.language_value

    def set_language(self, language: str) -> None:
        self.language_value = language

    def theme(self) -> str:
        return self.theme_value

    def set_theme(self, theme: str) -> None:
        self.theme_value = theme

    def terminal_font_size(self) -> int:
        return self.__dict__.get("font_size", 13)

    def set_terminal_font_size(self, size: int) -> None:
        self.font_size = size

    def platform_tuple(self) -> dict:
        return {"os": "linux", "family": "debian", "arch": "amd64"}

    def home(self) -> str:
        return "/home/alice"

    def mount_location_shape(self) -> str:
        return "path"

    def suggest_mount_location(self) -> str:
        return ""

    def mount_location_choices(self) -> list:
        return []

    def is_connected(self) -> bool:
        return self.is_bound

    def exit_hub_id(self) -> str:
        for hub in self.hubs():
            if hub.get("is_exit"):
                return hub["hub_id"]
        return ""

    def hubs(self) -> list:
        return json.loads(json.dumps(self.hubs_value)) if self.is_bound else []

    def service_entries(self) -> list:
        return json.loads(json.dumps(SERVICES)) if self.is_bound else []

    def entry_rows(self) -> list:
        return [
            dict(
                entry,
                job="",
                last_error=None,
                local_port="auto",
                forward=self.forward_ports.get(f"{entry['hub_id']}/{entry['id']}"),
            )
            for entry in self.service_entries()
        ]

    def notices(self) -> list:
        return [dict(notice) for notice in self.notices_value]

    def close_notice(self, notice_id: str) -> None:
        self.notices_value = [
            notice for notice in self.notices_value if notice.get("id") != notice_id
        ]

    def service_states(self) -> dict:
        return json.loads(json.dumps(self.states))

    def terminal_entries(self) -> list:
        return json.loads(json.dumps(TERMINALS)) if self.is_bound else []

    def terminal_sessions(self) -> list:
        return json.loads(json.dumps(TERMINAL_SESSIONS)) if self.is_bound else []

    def connect_overlay(self, hub_id: str) -> dict:
        self.overlay_calls.append(("connect", hub_id))
        return dict(self.overlay_reply)

    def cancel_overlay(self, hub_id: str) -> dict:
        self.overlay_calls.append(("cancel", hub_id))
        return dict(self.overlay_reply)

    def disconnect_overlay(self, hub_id: str) -> dict:
        self.overlay_calls.append(("disconnect", hub_id))
        return dict(self.overlay_reply)

    def read_clipboard(self) -> dict:
        return dict(self.clipboard_reply)

    def write_clipboard(self, text: str) -> dict:
        self.clipboard_written.append(text)
        return dict(self.clipboard_write_reply)

    def pick_overlay(self, hub_id: str, provider: str) -> dict:
        self.overlay_calls.append(("pick", hub_id, provider))
        return dict(self.overlay_reply)

    def open_terminal(
        self, hub_id: str, device_id: str, cols: int, rows: int, session_id=""
    ):
        call = ("open", hub_id, device_id, cols, rows)
        self.terminal_calls.append(call + ((session_id,) if session_id else ()))
        return dict(self.terminal_reply)

    def attach_terminal(self, terminal_id: str, read) -> None:
        self.terminal_calls.append(("attach", terminal_id))
        while True:
            data = read(4096)
            if not data:
                return
            self.typed.append(data)

    def terminal_output(self, terminal_id: str, write) -> None:
        self.terminal_calls.append(("output", terminal_id))
        for data in self.shown:
            write(data)

    def has_terminal(self, terminal_id: str) -> bool:
        return terminal_id == self.terminal_reply.get("terminal_id")

    def resize_terminal(self, terminal_id: str, cols: int, rows: int) -> dict:
        self.terminal_calls.append(("resize", terminal_id, cols, rows))
        return {}

    def terminal_result(self, terminal_id: str) -> dict:
        self.terminal_calls.append(("result", terminal_id))
        return {"exit_code": 0}

    def open_window_terminal(
        self, hub_id: str, device_id: str, cols: int, rows: int, session_id=""
    ):
        call = ("window", hub_id, device_id, cols, rows)
        self.terminal_calls.append(call + ((session_id,) if session_id else ()))
        return dict(self.terminal_reply)

    def persist_terminal(
        self, terminal_id: str, is_persistent: bool, is_shared: bool
    ) -> dict:
        self.terminal_calls.append(("persist", terminal_id, is_persistent, is_shared))
        return dict(self.session_reply)

    def stop_terminal_session(self, hub_id: str, session_id: str) -> dict:
        self.terminal_calls.append(("stop", hub_id, session_id))
        return dict(self.session_reply)

    def terminal_input(self, terminal_id: str, data: bytes) -> dict:
        if not self.has_terminal(terminal_id):
            return {"code": "unknown_terminal", "params": {}}
        self.typed.append(data)
        return {}

    def clear_terminal(self, terminal_id: str) -> dict:
        self.terminal_calls.append(("clear", terminal_id))
        if not self.has_terminal(terminal_id):
            return {"code": "unknown_terminal", "params": {}}
        return {}

    def open_panel(self, hub_id: str) -> dict:
        self.panel_opens.append(hub_id)
        return dict(self.panel_reply)

    def close_terminal(self, terminal_id: str) -> dict:
        self.terminal_calls.append(("close", terminal_id))
        if not self.has_terminal(terminal_id):
            return {"code": "unknown_terminal", "params": {}}
        return {}

    def list_directories(self, path: str) -> list:
        return self.platform.list_directories(path=path)

    def make_directory(self, path: str) -> None:
        self.platform.make_directory(path=path)

    def connect(self, link: str) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_links.append(link)
        self.is_bound = True

    def leave(self, hub_id: str = "") -> None:
        hub = self._hub(hub_id)
        self.disconnected.append(hub["hub_id"])
        self.hubs_value = [row for row in self.hubs_value if row is not hub]
        self.is_bound = bool(self.hubs_value)

    def reconnect(self, hub_id: str = "") -> None:
        hub = self._hub(hub_id)
        self.reconnects.append(hub_id)
        hub["connection"] = "connecting"

    def refresh(self) -> None:
        self.refreshes += 1

    def set_exit(self, hub_id: str) -> dict:
        rows = self.hubs_value if self.is_bound else []
        chosen = [row for row in rows if hub_id in (row["hub_id"], row["binding_id"])]
        if not chosen:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        if chosen[0]["connection"] != "connected":
            return {"code": "no_exit_hub", "params": {"hub_id": hub_id}}
        self.exits.append(chosen[0]["hub_id"])
        for row in rows:
            row["is_exit"] = row is chosen[0]
        return {}

    def request_show(self) -> None:
        self.shows += 1

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.is_shut_down.set()

    def arrange_relaunch(self) -> None:
        self.relaunches += 1

    def subscribe(self, watcher) -> None:
        self.__dict__.setdefault("watchers", []).append(watcher)

    def configure_forward(self, hub_id: str, entry_id: str, setting) -> dict:
        self.forward_settings.append((hub_id, entry_id, setting))
        return dict(self.forward_reply)

    def service_action(self, service_type: str, body: dict) -> dict:
        self.service_calls.append((service_type, dict(body)))
        if self.service_error is not None:
            raise self.service_error
        return dict(self.service_reply)

    def _hub(self, needle: str) -> dict:
        """The hub row a needle names, the way the resident resolves one."""
        rows = self.hubs_value if self.is_bound else []
        if not needle:
            if len(rows) == 1:
                return rows[0]
            raise KeyError(needle)
        for hub in rows:
            if needle in (hub["hub_id"], hub["binding_id"]):
                return hub
        raise KeyError(needle)


def completed(command=(), returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        list(command), returncode, stdout=stdout, stderr=stderr
    )
