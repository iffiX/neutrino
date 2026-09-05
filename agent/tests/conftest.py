"""Suite-wide isolation and the shared fakes, defined once.

The autouse redirect keeps every store off the real machine: the binding
file, the service-choice store and the mount credentials directory all land
in ``tmp_path``. The fakes here are the ones more than one directory
drives: the control channel's platform and agent, the injected clock, the
link builder and the log sink.
"""

import base64
import json

import pytest

import neutrino_agent.core.enrollment as enrollment
import neutrino_agent.services.file as file_module
import neutrino_agent.services.store as store_module
from neutrino_agent.platforms.base import AgentPlatform

ROOT = {"account": "root", "uid": 0, "is_privileged": True}
ALICE = {"account": "alice", "uid": 1000, "is_privileged": False}

SERVICES = [
    {
        "id": "ai",
        "type": "ai",
        "title": "AI tools",
        "payload": {
            "endpoint": "http://hub:8080",
            "protocol": "anthropic",
            "models": ["m1"],
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
]


@pytest.fixture(autouse=True)
def _isolated_machine_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(tmp_path / "agent.json"))
    monkeypatch.setattr(
        store_module, "AGENT_SERVICE_STORE_PATH", str(tmp_path / "services.json")
    )
    monkeypatch.setattr(
        file_module,
        "AGENT_MOUNT_CREDENTIALS_DIR",
        str(tmp_path / "mount_credentials"),
    )


@pytest.fixture
def config_path(tmp_path):
    """The binding file the autouse redirect already points the agent at."""
    return tmp_path / "agent.json"


class Clock:
    """An injected clock: time moves only when a test says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def link_for(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def discard(message: str) -> None:
    """Swallow the log lines."""


def bind(path, url="http://127.0.0.1:9") -> None:
    path.write_text(json.dumps({"gateway_url": url, "token": "tok"}))


class FakeControlPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self):
        self.peer = dict(ROOT)
        self.peer_error = None
        self.fs_calls = []
        self.fs_error = None

    def human_accounts(self) -> list:
        return ["alice", "bob"]

    def read_peer_identity(self, connection) -> dict:
        if self.peer_error is not None:
            raise self.peer_error
        return self.peer

    def list_directories(self, *, account: str, path: str) -> list:
        self.fs_calls.append(("list", account, path))
        if self.fs_error is not None:
            raise self.fs_error
        return ["docs", "media"]

    def make_directory(self, *, account: str, path: str) -> None:
        self.fs_calls.append(("mkdir", account, path))
        if self.fs_error is not None:
            raise self.fs_error


class FakeControlAgent:
    def __init__(self):
        self.requested = []
        self.connected_links = []
        self.is_disconnected = False
        self.connect_error = None
        self.service_calls = []
        self.service_reply = {}
        self.operation_payload = None

    def platform(self) -> dict:
        return {"os": "linux", "family": "debian", "arch": "x86_64"}

    def catalog(self) -> dict:
        # Modules arrive already resolved for this platform: the hub read
        # the manifest and picked the entry, so `entry` is the machine's
        # whole basis for knowing the module runs here at all.
        return {
            "modules": {
                "openssh_server": {
                    "title": "OpenSSH server",
                    "description": "",
                    "kind": "openssh",
                    "is_builtin": True,
                    "platform_key": "linux",
                    "entry": {},
                    "verify": "",
                    "package": "openssh_server",
                }
            },
            "services": SERVICES,
        }

    def service_entries(self) -> list:
        return list(SERVICES)

    def module_states(self) -> dict:
        return {"openssh_server": {"state": "enabled", "is_active": False}}

    def pending_module_requests(self) -> dict:
        return {}

    def last_error(self):
        return None

    def operation(self):
        return self.operation_payload

    def accounts(self) -> list:
        return ["alice", "bob"]

    def ai_targets(self) -> dict:
        return {"alice": True, "bob": False}

    def ai_states(self) -> dict:
        return {
            "alice": {
                "state": "installed",
                "code": "",
                "params": {},
                "is_active": True,
            },
            "bob": {"state": "absent", "code": "", "params": {}, "is_active": False},
        }

    def ai_tool_configs(self) -> dict:
        return {"claude": {"default": "m1"}}

    def account_home(self, account) -> str:
        return "/root" if account == "root" else f"/home/{account}"

    def service_states(self) -> dict:
        return {
            "forwards": {"svc_tcp": {"local_port": 5432, "is_active": True}},
            "mounts": [
                {
                    "record_id": "r1",
                    "entry_id": "hub_share_media",
                    "path": "/home/alice/nas/media",
                    "account": "alice",
                    "is_attached": True,
                    "code": "",
                    "params": {},
                }
            ],
        }

    def service_action(self, service_type, *, account, is_privileged, body) -> dict:
        self.service_calls.append((service_type, account, is_privileged, dict(body)))
        return dict(self.service_reply)

    def request_module(self, name, *, is_enabled=None, is_activated=None):
        self.requested.append((name, is_enabled, is_activated))

    def connect(self, link):
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_links.append(link)

    def disconnect(self):
        self.is_disconnected = True
