"""Suite-wide isolation and the shared fakes, defined once.

The autouse redirect keeps every store off the real machine: the binding
file, the machine's own state store and the credentials directory all land
in ``tmp_path``. The fakes here are the ones more than one directory
drives: the control channel's platform and agent, the injected clock, the
link builder and the log sink.
"""

import base64
import json

import pytest

import neutrino_agent.core.enrollment as enrollment
import neutrino_agent.core.store as store_module
import neutrino_agent.platforms.base as platforms_base_module
from neutrino_agent.platforms.base import AgentPlatform


@pytest.fixture(autouse=True)
def _isolated_machine_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(tmp_path / "agent.json"))
    monkeypatch.setattr(store_module, "AGENT_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(platforms_base_module, "AGENT_DATA_DIR_POSIX", str(tmp_path))


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

    def human_accounts(self) -> list:
        return ["alice", "bob"]

    def agent_service_start_hint(self) -> str:
        return "sudo systemctl enable --now neutrino_agent.service"


class FakeSocketPlatform(FakeControlPlatform):
    """The control platform plus the socket path the CLI commands ask for."""

    def __init__(self, socket_path: str):
        self._socket_path = socket_path

    def control_socket_path(self) -> str:
        return self._socket_path


class FakeControlAgent:
    def __init__(self):
        self.requested = []
        self.connected_links = []
        self.is_disconnected = False
        self.connect_error = None
        self.rdp_calls = []
        self.rdp_reply = {}
        self.rdp_error = None
        self.is_unshared = False
        self.operation_payload = None
        self.share = {
            "is_shared": False,
            "state": "not_shared",
            "port": 21118,
            "account": "",
            "attention": "",
            "rustdesk_id": "123456789",
            "has_password": False,
        }

    def platform(self) -> dict:
        return {"os": "linux", "family": "debian", "arch": "x86_64"}

    def catalog(self) -> dict:
        # Modules arrive already resolved for this platform: the hub read
        # the manifest and picked the entry, so `entry` is the machine's
        # whole basis for knowing the module runs here at all.
        return {
            "modules": {
                "rustdesk": {
                    "title": "RustDesk",
                    "description": "",
                    "kind": "rustdesk",
                    "installer": "hub",
                    "source": "rustdesk/rustdesk",
                    "license": "AGPL-3.0",
                    "corresponding_source": "https://github.com/rustdesk/rustdesk",
                    "platform_key": "linux-debian-amd64",
                    "entry": {"package_kind": "deb"},
                    "verify": "",
                    "package": "rustdesk",
                }
            }
        }

    def module_states(self) -> dict:
        return {"rustdesk": {"state": "installed"}}

    def pending_module_requests(self) -> dict:
        return {}

    def last_error(self):
        return None

    def operation(self):
        return self.operation_payload

    def accounts(self) -> list:
        return ["alice", "bob"]

    def rdp_state(self) -> dict:
        return dict(self.share)

    def request_module(self, name, *, is_enabled=None):
        self.requested.append((name, is_enabled))

    def rdp_share(self, *, account: str, password: str) -> dict:
        self.rdp_calls.append((account, password))
        if self.rdp_error is not None:
            raise self.rdp_error
        return dict(self.rdp_reply)

    def rdp_unshare(self) -> dict:
        self.is_unshared = True
        return dict(self.rdp_reply)

    def connect(self, link):
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_links.append(link)

    def disconnect(self):
        self.is_disconnected = True
