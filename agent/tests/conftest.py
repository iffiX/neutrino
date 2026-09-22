"""Suite-wide isolation and the shared fakes, defined once.

The autouse redirect keeps every store off the real machine: the binding
file, the machine's own state store, the credentials directory, the
configured marks and the package directory all land in ``tmp_path``. The
fakes here are the ones more than one directory drives: the control
channel's platform and agent, the injected clock, the link builder and the
log sink.
"""

import base64
import json

import pytest

import neutrino_agent.core.engine as engine_module
import neutrino_agent.core.enrollment as enrollment
import neutrino_agent.core.loop as loop_module
import neutrino_agent.core.store as store_module
import neutrino_agent.platforms.base as platforms_base_module
from neutrino_agent.platforms.base import AgentPlatform


@pytest.fixture(autouse=True)
def _isolated_machine_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(tmp_path / "agent.json"))
    monkeypatch.setattr(store_module, "AGENT_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(platforms_base_module, "AGENT_DATA_DIR_POSIX", str(tmp_path))
    monkeypatch.setattr(
        engine_module, "AGENT_CONFIGURED_DIR", str(tmp_path / "configured")
    )
    monkeypatch.setattr(loop_module, "AGENT_PACKAGE_DIR", str(tmp_path / "packages"))


@pytest.fixture(autouse=True)
def _isolated_network(monkeypatch):
    """The hub's name resolves to nothing and no route is looked at, unless a
    test says otherwise; a round waits nothing between addresses."""
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "")
    monkeypatch.setattr(enrollment, "default_source_address", lambda urls: "")
    monkeypatch.setattr(loop_module, "AGENT_ROTATE_DELAY_S", 0)


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


BINDING_ID = "dev-1"
BINDING_TOKEN = "tok"
MACHINE_ID = "machine-1"


def bind(path, url="http://127.0.0.1:9", fingerprint="", urls=None) -> None:
    """Write a complete binding file, the way a join leaves it.

    Args:
        path: The binding file.
        url: The address that last answered.
        fingerprint: The pinned fingerprint.
        urls: Every address the hub answers on; None writes a file of the
            0.3.0 shape, without the list.
    """
    binding = {
        "gateway_url": url,
        "id": BINDING_ID,
        "token": BINDING_TOKEN,
        "fingerprint": fingerprint,
        "machine_id": MACHINE_ID,
    }
    if urls is not None:
        binding["gateway_urls"] = list(urls)
    path.write_text(json.dumps(binding))


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
        self.joined_links = []
        self.is_left = False
        self.join_error = None
        self.error = None
        self.rdp_calls = []
        self.rdp_reply = {}
        self.rdp_error = None
        self.is_unshared = False
        self.is_socket_open = False
        self.sync_reply = {}
        self.syncs = 0
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

    def module_states(self) -> dict:
        return {
            "rustdesk": {
                "state": "installed",
                "is_active": False,
                "code": "",
                "params": {},
                "details": {},
            }
        }

    def state_hash(self) -> str:
        return "h1"

    def last_error(self):
        return self.error

    def is_online(self) -> bool:
        return self.is_socket_open

    def accounts(self) -> list:
        return ["alice", "bob"]

    def rdp_state(self) -> dict:
        return dict(self.share)

    def sync(self) -> dict:
        self.syncs += 1
        return dict(self.sync_reply)

    def rdp_share(self, *, account: str) -> dict:
        self.rdp_calls.append(account)
        if self.rdp_error is not None:
            raise self.rdp_error
        return dict(self.rdp_reply)

    def rdp_unshare(self) -> dict:
        self.is_unshared = True
        return dict(self.rdp_reply)

    def join(self, link):
        if self.join_error is not None:
            raise self.join_error
        self.joined_links.append(link)

    def leave(self):
        self.is_left = True
