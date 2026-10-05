"""The largest messages the channel carries, against the agent port's cap.

A hub at the edge of a home's size is built here: 64 managed machines, each
with every module and 32 shares, 256 published entries, every terminal and
both overlays, and a machine whose report carries a failed step's output.
Each message the hub sends or receives in that hub is measured as the JSON
the wire carries, and the cap stays at least four times the largest.
"""

import json

import pytest

from neutrino_hub.modules.channel.constants import (
    CHANNEL_CHUNK_BYTES,
    CHANNEL_MESSAGE_BYTES_MAX,
)
from neutrino_hub.modules.clients.constants import CLIENT_PERMISSION_KINDS
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.catalog import load_module_manifests
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.collector import resolve_entries
from neutrino_hub.web import channel_state
from tests.conftest import FakeChannelSessions, unlock_vault
from tests.web.test_channel_state import LAN, OVERLAY

MACHINES = 64
SHARES = 32
SERVICES = 256
SESSIONS_PER_MACHINE = 4
ACCOUNTS = 32
INTERFACES = 16
URLS = 8
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}
# What the agent bounds a failed step's output and a command's output to.
STEP_OUTPUT_CHARS = 16 * 1024
COMMAND_OUTPUT_CHARS = 64 * 1024
JOURNAL_LINES = 200
LINE = "x" * 160


def text(length: int, seed: str = "") -> str:
    """Printable text of one length, the way a log line or a title reads."""
    base = f"{seed} the quick brown fox jumps over the lazy dog 0123456789 "
    return (base * (length // len(base) + 1))[:length]


def wire_size(frame: dict) -> int:
    """The bytes one frame takes as the JSON a peer sends."""
    return len(json.dumps(frame).encode("utf-8"))


class Services:
    def __init__(self, entries):
        self.entries = entries

    def entries_for(self, scope):
        return resolve_entries(
            self.entries,
            device_hosts={},
            hub_addresses={"192.168.100.1"},
            hub_host=scope.hub_address,
        )


class LargeRuntime:
    """The parts of the runtime the two state documents read."""

    def __init__(self, devices: list):
        kinds = ("web", "port", "file", "rdp", "ai")
        entries = []
        for index in range(SERVICES):
            device = devices[index % len(devices)]
            kind = kinds[index % len(kinds)]
            entries.append(
                {
                    "id": f"{kind}_{index:04d}_{device.id}",
                    "type": kind,
                    "title": text(48, f"entry {index}"),
                    "payload": {
                        "url": f"http://192.168.100.{index % 250 + 2}:{8000 + index}"
                        f"/{text(40, 'path').replace(' ', '_')}",
                        "host": f"192.168.100.{index % 250 + 2}",
                        "port": 8000 + index,
                        "share": f"share_{index}",
                        "endpoint": f"http://192.168.100.1:8317/v1/{index}",
                    },
                    "is_healthy": True,
                    "source": "device",
                    "description": text(120, "description"),
                    "description_code": "",
                    "description_params": {"account": f"account_{index}"},
                    "record_id": None,
                    "detail_code": None,
                    "device_id": device.id,
                }
            )
        self.published_services = Services(entries)
        self.agent_sessions = FakeChannelSessions(online=[d.id for d in devices])
        self.client_scope: dict = {}
        self.client_reached: dict = {}
        self.device_hostname = {d.id: text(32, d.id) for d in devices}
        self.device_address = {
            d.id: f"192.168.100.{i + 2}" for i, d in enumerate(devices)
        }

    def host_scopes(self):
        return [LAN, OVERLAY]

    def overlay_networks(self):
        return {}


@pytest.fixture
def large_hub(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    registry = DeviceRegistry()
    devices = []
    for index in range(MACHINES):
        device = registry.create(text(32, f"machine {index}"))
        registry.issue_token(device.id)
        devices.append(registry.get(device.id))
    sessions = [
        {
            "session_id": f"{device.id}-{number}",
            "device_id": device.id,
            "account": f"account_{number}",
            "started_at": "2026-10-05T12:00:00+00:00",
            "title": text(64, "title"),
            "owner": f"client:{number}",
            "is_attached": True,
            "is_persistent": True,
            "is_shared": True,
            "attached_count": 3,
        }
        for device in devices
        for number in range(SESSIONS_PER_MACHINE)
    ]
    monkeypatch.setattr(channel_state, "sessions_for", lambda runtime, viewer: sessions)
    urls = [f"https://192.168.{n}.1:8443" for n in range(URLS)]
    monkeypatch.setattr(channel_state, "channel_urls", lambda runtime: list(urls))
    overlays = [
        {"kind": "netbird", "setup_key": text(36), "management_url": text(64)},
        {"kind": "easytier", "network_name": text(64), "secret": text(64)},
    ]
    monkeypatch.setattr(
        channel_state.channel_overlay,
        "overlay_materials",
        lambda runtime: list(overlays),
    )
    return LargeRuntime(devices), devices, urls


def largest_client_state(runtime) -> dict:
    clients = ClientRegistry()
    client_id = clients.create("everything")
    clients.set_permission(client_id, list(CLIENT_PERMISSION_KINDS))
    runtime.client_scope[client_id] = LAN
    return {"type": "state", **channel_state.client_state(runtime, client_id)}


def largest_agent_state(device, urls: list) -> dict:
    store = DesiredStateStore()
    for name in load_module_manifests():
        store.set_want(device.id, name, "running")
    store.write(
        device.id,
        "samba",
        {
            "shares": [
                {
                    "name": f"share_{n}",
                    "path": f"/srv/{text(48, 'path').replace(' ', '_')}",
                    "comment": text(64, "comment"),
                    "users": [f"account_{u}" for u in range(8)],
                    "is_read_only": False,
                }
                for n in range(SHARES)
            ],
            "users": [f"account_{u}" for u in range(ACCOUNTS)],
        },
    )
    store.write(
        device.id,
        "podman",
        {
            "containers": [
                {
                    "name": f"container_{n}",
                    "image": f"docker.io/library/{text(32, 'image').replace(' ', '')}",
                    "ports": [f"{9000 + n * 4 + p}:{80 + p}" for p in range(4)],
                    "env": {f"VARIABLE_{v}": text(48) for v in range(8)},
                    "volumes": [f"/srv/data_{n}_{v}:/data/{v}" for v in range(4)],
                }
                for n in range(SHARES)
            ]
        },
    )
    desired, state_hash = store.compose(
        device.id,
        PLATFORM,
        address="192.168.100.2",
        allowed_subnets=[f"192.168.{n}.0/24" for n in range(URLS)],
        urls=urls,
        hub_address="192.168.100.1",
    )
    return {"type": "state", "hash": state_hash, **desired}


def largest_agent_report() -> dict:
    """An agent's report with every section full and one step failed."""
    modules = {
        name: {
            "state": "running",
            "is_active": True,
            "code": "",
            "params": {},
            "details": {"note": text(256)},
        }
        for name in load_module_manifests()
    }
    modules["samba"]["details"] = {
        "global": {f"option {n}": text(48) for n in range(40)},
        "shares": [
            {f"option {n}": text(48) for n in range(10)} | {"name": f"share_{s}"}
            for s in range(SHARES)
        ],
        "users": [f"account_{u}" for u in range(ACCOUNTS)],
        "sessions": [
            {"user": f"account_{u}", "machine": f"192.168.100.{u}", "share": "s"}
            for u in range(ACCOUNTS)
        ],
    }
    modules["podman"]["details"] = {
        "containers": [
            {
                "id": text(64),
                "name": f"container_{n}",
                "image": text(64),
                "status": text(32),
                "ports": [f"0.0.0.0:{9000 + n}->80/tcp"] * 4,
            }
            for n in range(SHARES)
        ]
    }
    modules["gitea"] = {
        "state": "failed",
        "is_active": False,
        "code": "install_failed",
        "params": {"output": text(STEP_OUTPUT_CHARS, "apt")},
        "details": {},
    }
    return {
        "type": "report",
        "state_hash": "0" * 16,
        "machine": {
            "hostname": text(64),
            "platform": PLATFORM,
            "accounts": [
                {"name": f"account_{n}", "uid": 1000 + n, "home": f"/home/a{n}"}
                for n in range(ACCOUNTS)
            ],
            "metrics": {f"metric_{n}": n * 1.5 for n in range(64)},
            "sessions": [
                {
                    "session_id": f"s{n}",
                    "account": f"account_{n}",
                    "started_at": "2026-10-05T12:00:00+00:00",
                    "title": text(64),
                    "owner": "hub",
                    "is_attached": True,
                    "is_persistent": True,
                    "is_shared": False,
                    "attached_count": 1,
                }
                for n in range(ACCOUNTS)
            ],
        },
        "network": {
            "interfaces": [
                {
                    "name": f"enp{n}s0",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "addresses": [f"192.168.{n}.2/24", f"fe80::{n}/64"],
                    "is_up": True,
                }
                for n in range(INTERFACES)
            ]
        },
        "modules": modules,
        "desktop": {"is_shared": True, "port": 21118},
        "error": {
            "code": "reinstall_failed",
            "params": {"exit_code": 1, "output": text(4 * 1024)},
        },
    }


def largest_command_close() -> dict:
    """A command's close: its whole output and a journal's lines."""
    return {
        "type": "close",
        "stream": 7,
        "code": "",
        "params": {
            "exit_code": 0,
            "output": text(COMMAND_OUTPUT_CHARS, "output"),
            "result": {"lines": [LINE] * JOURNAL_LINES},
        },
    }


def test_the_message_cap_is_four_times_the_largest_message(large_hub):
    runtime, devices, urls = large_hub
    sizes = {
        "client state": wire_size(largest_client_state(runtime)),
        "agent state": wire_size(largest_agent_state(devices[0], urls)),
        "agent report": wire_size(largest_agent_report()),
        "command close": wire_size(largest_command_close()),
        "data frame": CHANNEL_CHUNK_BYTES + 4,
    }
    print(sizes)

    assert max(sizes.values()) * 4 <= CHANNEL_MESSAGE_BYTES_MAX
