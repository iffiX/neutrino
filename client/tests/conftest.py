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
import subprocess
import threading

import pytest

import neutrino_client.core.enrollment as enrollment
from neutrino_client.platforms.base import ClientPlatform
from neutrino_client.platforms.darwin import DarwinPlatform
from neutrino_client.platforms.linux import LinuxPlatform
from neutrino_client.platforms.windows import WindowsPlatform

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
    (tmp_path / "home").mkdir()


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
    """An enrollment link over one payload; ``role`` defaults to client."""
    body = {"role": "client", **payload}
    encoded = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def discard(message: str) -> None:
    """Swallow the log lines."""


BINDING = {
    "id": "c1",
    "name": "box",
    "hub_id": "h1",
    "hub_name": "home",
    "gateway_url": "http://127.0.0.1:9",
    "fingerprint": "",
    "token": "tok",
}
OFFICE_BINDING = {
    "id": "c2",
    "name": "box",
    "hub_id": "h2",
    "hub_name": "office",
    "gateway_url": "https://office.lan:8443",
    "fingerprint": "",
    "token": "tok2",
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


HUB_ROW = {
    "hub_id": "h1",
    "hub_name": "home",
    "hub_software": "neutrino_hub/0.3.0",
    "binding_id": "c1",
    "name": "box",
    "gateway_url": "https://hub.lan:8443",
    "connection_state": "connected",
    "is_disabled": False,
    "is_exit": True,
    "last_error": None,
}
OFFICE_ROW = {
    "hub_id": "h2",
    "hub_name": "office",
    "hub_software": "neutrino_hub/0.3.0",
    "binding_id": "c2",
    "name": "box",
    "gateway_url": "https://office.lan:8443",
    "connection_state": "connected",
    "is_disabled": False,
    "is_exit": False,
    "last_error": None,
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
        self.has_tooling = True
        self.opened_urls = []
        self.started = []
        self.start_error = None
        self.socket_path = ""
        self.answered = []
        self.on_answer = None
        self.answer_error = None
        self.language = "en"

    def system_language(self) -> str:
        return self.language

    def control_socket_path(self) -> str:
        if self.socket_path:
            return self.socket_path
        return os.path.join(os.environ["XDG_RUNTIME_DIR"], "neutrino_client.sock")

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

    def attach_share(self, *, share_url, location, credentials_path) -> None:
        self.attach_calls.append(
            {
                "share_url": share_url,
                "location": location,
                "credentials_path": credentials_path,
            }
        )
        if self.attach_error is not None:
            raise self.attach_error
        self.attached.add(location)

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
        return 0, ""


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
        self.is_bound = True
        self.hubs_value = [dict(HUB_ROW), dict(OFFICE_ROW)]
        self.reconnects = []
        self.states = {
            "forwards": {"h1/svc_tcp": {"local_port": 5432, "is_active": True}},
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

    def service_states(self) -> dict:
        return json.loads(json.dumps(self.states))

    def list_directories(self, path: str) -> list:
        return self.platform.list_directories(path=path)

    def make_directory(self, path: str) -> None:
        self.platform.make_directory(path=path)

    def connect(self, link: str) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_links.append(link)
        self.is_bound = True

    def disconnect(self, hub_id: str = "") -> None:
        hub = self._hub(hub_id)
        self.disconnected.append(hub["hub_id"])
        self.hubs_value = [row for row in self.hubs_value if row is not hub]
        self.is_bound = bool(self.hubs_value)

    def reconnect(self, hub_id: str = "") -> None:
        hub = self._hub(hub_id)
        self.reconnects.append(hub_id)
        hub["connection_state"] = "reconnecting"

    def request_show(self) -> None:
        self.shows += 1

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.is_shut_down.set()

    def subscribe(self, watcher) -> None:
        self.__dict__.setdefault("watchers", []).append(watcher)

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
