"""The agent-facing API: joining, beating, and leaving.

The registry is replaced with one held in memory, so what is exercised is the
request path — that a machine can introduce itself with a ticket, that a
heartbeat carries the desired modules and the per-account AI credentials
back, and that an agent saying goodbye stops the panel treating the device as
managed while keeping everything its owner typed.
"""

import hashlib
import tempfile
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.cliproxyapi.ops import load_config as load_cliproxyapi_config
from neutrino_hub.modules.devices.agent_module_cache import AgentModuleArtifact
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.constants import AGENT_WIRE_GENERATION
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.routers import agent as agent_router
from tests.conftest import unlock_vault

MAC = "aa:bb:cc:dd:ee:ff"

CATALOG = {
    "modules": {"anydesk": {"name": "anydesk", "kind": "package"}},
    "services": [{"id": "ai", "type": "ai", "title": "AI gateway"}],
}
CATALOG_HASH = "hash123"


class FakeRegistry:
    """A registry of one device, in memory."""

    instance = None

    def __init__(self):
        # The router builds its own registry per request, so state lives on
        # the class rather than the instance.
        FakeRegistry.instance = self

    @classmethod
    def reset(cls, device: ManagedDevice) -> None:
        cls.device = device

    def get(self, mac_address):
        if mac_address.lower() == FakeRegistry.device.mac_address:
            return FakeRegistry.device
        return ManagedDevice(mac_address=mac_address.lower())

    def find_by_client_token(self, token):
        stored = FakeRegistry.device.client.token_sha256
        presented = hashlib.sha256(token.encode()).hexdigest()
        return FakeRegistry.device if stored and stored == presented else None

    def record_heartbeat(self, mac_address, *, version, seen_at):
        FakeRegistry.device.client.version = version
        FakeRegistry.device.client.last_seen = seen_at

    def set_module(self, mac_address, module, is_enabled=None, is_activated=None):
        wanted = FakeRegistry.device.client.modules.setdefault(
            module, {"is_enabled": False, "is_activated": False}
        )
        if is_enabled is not None:
            wanted["is_enabled"] = is_enabled
        if is_activated is not None:
            wanted["is_activated"] = is_activated
        wanted["failed"] = None
        return FakeRegistry.device

    def set_module_failure(self, mac_address, module, failure):
        wanted = FakeRegistry.device.client.modules.setdefault(
            module, {"is_enabled": False, "is_activated": False}
        )
        wanted["failed"] = dict(failure) if failure else None

    def set_ai_key_id(self, mac_address, account, key_id):
        if key_id is None:
            FakeRegistry.device.client.ai_key_ids.pop(account, None)
        else:
            FakeRegistry.device.client.ai_key_ids[account] = key_id

    def annotate(self, mac_address, annotation):
        FakeRegistry.device.name = annotation.get("name")
        return FakeRegistry.device

    def issue_client_token(self, mac_address):
        FakeRegistry.device.client.token_sha256 = hashlib.sha256(
            b"issued-token"
        ).hexdigest()
        return "issued-token"

    def forget_client(self, mac_address):
        client = FakeRegistry.device.client
        client.token_sha256 = None
        client.version = None
        client.last_seen = None
        client.modules = {}


class StubCatalogCache:
    def __init__(self):
        self.asked_hosts: list[str] = []
        self.asked_platforms: list[dict] = []

    def catalog(self, *, device_host, platform=None):
        self.asked_hosts.append(device_host)
        self.asked_platforms.append(dict(platform or {}))
        return CATALOG, CATALOG_HASH


class StubModuleCache:
    """A cache that answers at once and never reaches a vendor."""

    def __init__(self):
        self.asked: list = []

    def artifact(self, *, name, manifest, platform):
        self.asked.append((name, dict(platform)))
        return AgentModuleArtifact(
            key=f"{name}-key", path=Path("/nonexistent"), digest="d", package_kind="deb"
        )


class StubServedModels:
    def first_model(self, *, port, client_key):
        return "claude-sonnet-4-5"


class FakeRuntime:
    """Only the parts of the runtime these routes touch."""

    def __init__(self):
        self.client_metrics = {}
        self.client_modules = {}
        self.client_platform = {}
        self.client_hostname = {}
        self.client_accounts = {}
        self.client_last_error = {}
        self.client_command_results = {}
        self.enrollments = {}
        self.settings = {"listen_port": 80}
        self.device_catalog = StubCatalogCache()
        self.served_models = StubServedModels()
        self.agent_modules = StubModuleCache()
        self.device_install_locks = DeviceInstallLocks()
        # A short wait: no agent reports in these tests, and a worker that
        # sat on its device's lock for the real half hour would leak a
        # thread per case.
        self.agent_module_orders = AgentModuleController(
            cache=self.agent_modules, locks=self.device_install_locks, timeout_s=1.0
        )

    def take_client_commands(self, mac_address):
        return []

    def forget_client_state(self, mac_address):
        key = mac_address.lower()
        for held in (
            self.client_metrics,
            self.client_modules,
            self.client_platform,
            self.client_hostname,
            self.client_accounts,
            self.client_last_error,
            self.client_command_results,
        ):
            held.pop(key, None)
        self.agent_module_orders.forget(key)

    def network(self):
        return _EmptyNetwork()


class _EmptyNetwork:
    lan_interfaces: list = []


@pytest.fixture()
def api(monkeypatch):
    device = ManagedDevice(
        mac_address=MAC,
        name="testbox",
        ssh={"host": "10.0.0.5", "username": "me"},
        client=DeviceClientInfo(
            token_sha256=hashlib.sha256(b"device-token").hexdigest(),
            last_seen="2026-01-01T00:00:00+00:00",
        ),
    )
    FakeRegistry.reset(device)
    monkeypatch.setattr(agent_router, "DeviceRegistry", FakeRegistry)
    # Pinned so the version comparisons below are about the protocol, not
    # about what the checkout happens to be versioned.
    monkeypatch.setattr(agent_router, "HUB_VERSION", "1.2.3")

    app = FastAPI()
    app.include_router(agent_router.router)
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime, device


@pytest.fixture()
def ai_box(api, monkeypatch, tmp_path):
    """The api fixture plus a real config dir and an unlocked vault."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    write_config("cliproxyapi/cliproxyapi.json", {"listen_port": 8317})
    return api


def beat_body(**extra) -> dict:
    body = {
        "token": "device-token",
        "hostname": "testbox",
        "wire": AGENT_WIRE_GENERATION,
        "client_version": "0.3.0",
    }
    body.update(extra)
    return body


def test_heartbeat_reports_are_recorded_and_the_catalog_shipped(api):
    client, runtime, device = api
    device.client.modules = {"anydesk": True}

    response = client.post(
        "/api/agent/heartbeat",
        json=beat_body(
            metrics={"cpu_percent": 4.0},
            platform={"os": "linux", "family": "debian", "arch": "amd64"},
            catalog_hash="stale",
            modules={"anydesk": {"state": "installed"}},
        ),
    )

    assert response.status_code == 200
    body = response.json()
    # Nothing was asked for, so nothing is ordered: a stored wish is not a
    # standing instruction the way the desired-state map was.
    assert body["module_orders"] == []
    # A stale hash gets both halves of the catalog; a matching one would not.
    assert body["catalog"] == CATALOG
    assert body["catalog_hash"] == CATALOG_HASH
    assert runtime.client_metrics[MAC]["cpu_percent"] == 4.0
    assert runtime.client_modules[MAC]["anydesk"]["state"] == "installed"
    assert runtime.client_platform[MAC]["arch"] == "amd64"


def test_a_matching_catalog_hash_is_not_reshipped(api):
    client, _, _ = api

    response = client.post(
        "/api/agent/heartbeat", json=beat_body(catalog_hash=CATALOG_HASH)
    )

    assert response.json()["catalog"] is None
    assert response.json()["catalog_hash"] == CATALOG_HASH


def test_heartbeat_applies_a_toggle_made_on_the_machine(api):
    client, runtime, device = api

    response = client.post(
        "/api/agent/heartbeat",
        json=beat_body(module_requests={"anydesk": {"is_enabled": True}}),
    )

    assert response.status_code == 200
    assert device.client.modules["anydesk"]["is_enabled"] is True
    # The machine's own page enters by the controller's door, so a toggle
    # there becomes an order exactly as the drawer's button would.
    order = runtime.agent_module_orders.open_order_for(MAC, "anydesk")
    assert order is not None
    assert order.action == "install"


def test_accounts_and_last_error_land_in_the_runtime(api):
    client, runtime, _ = api

    response = client.post(
        "/api/agent/heartbeat",
        json=beat_body(
            accounts=["alice", "bob"],
            last_error={"code": "mount_failed", "params": {"share": "media"}},
        ),
    )

    assert response.status_code == 200
    assert runtime.client_accounts[MAC] == ["alice", "bob"]
    assert runtime.client_last_error[MAC] == {
        "code": "mount_failed",
        "params": {"share": "media"},
    }


def test_a_beat_without_an_error_clears_the_stored_one(api):
    client, runtime, _ = api
    runtime.client_last_error[MAC] = {"code": "mount_failed", "params": {}}

    client.post("/api/agent/heartbeat", json=beat_body(last_error=None))

    assert MAC not in runtime.client_last_error


def test_turning_an_account_on_generates_its_key_and_answers_it(ai_box):
    client, _, device = ai_box

    response = client.post(
        "/api/agent/heartbeat", json=beat_body(ai_targets={"alice": True})
    )

    assert response.status_code == 200
    answered = response.json()["ai_accounts"]["alice"]
    stored = load_cliproxyapi_config().client_keys
    assert [key.name for key in stored] == ["testbox/alice"]
    assert device.client.ai_key_ids == {"alice": stored[0].id}
    assert answered["api_key"] == stored[0].open_key()
    assert answered["base_url"].endswith(":8317")
    assert answered["model"] == "claude-sonnet-4-5"


def test_a_second_beat_reuses_the_pair_key(ai_box):
    client, _, device = ai_box

    client.post("/api/agent/heartbeat", json=beat_body(ai_targets={"alice": True}))
    first_id = device.client.ai_key_ids["alice"]
    client.post("/api/agent/heartbeat", json=beat_body(ai_targets={"alice": True}))

    assert device.client.ai_key_ids["alice"] == first_id
    assert [key.id for key in load_cliproxyapi_config().client_keys] == [first_id]


def test_two_accounts_get_two_keys(ai_box):
    client, _, device = ai_box

    response = client.post(
        "/api/agent/heartbeat",
        json=beat_body(ai_targets={"alice": True, "bob": True}),
    )

    answered = response.json()["ai_accounts"]
    assert set(answered) == {"alice", "bob"}
    assert answered["alice"]["api_key"] != answered["bob"]["api_key"]
    stored = load_cliproxyapi_config().client_keys
    assert sorted(key.name for key in stored) == ["testbox/alice", "testbox/bob"]
    assert set(device.client.ai_key_ids) == {"alice", "bob"}


def test_turning_an_account_off_revokes_its_key(ai_box):
    client, _, device = ai_box
    client.post(
        "/api/agent/heartbeat", json=beat_body(ai_targets={"alice": True, "bob": True})
    )
    bob_key_id = device.client.ai_key_ids["bob"]

    response = client.post(
        "/api/agent/heartbeat",
        json=beat_body(ai_targets={"alice": True, "bob": False}),
    )

    answered = response.json()["ai_accounts"]
    assert set(answered) == {"alice"}
    assert "bob" not in device.client.ai_key_ids
    stored_ids = [key.id for key in load_cliproxyapi_config().client_keys]
    assert bob_key_id not in stored_ids
    assert device.client.ai_key_ids["alice"] in stored_ids


def test_a_dangling_ai_key_id_is_reissued_on_the_next_heartbeat(ai_box):
    """A key revoked on the gateway leaves the mapping dangling; the device
    gets a fresh one rather than a dead credential."""
    client, _, device = ai_box
    device.client.ai_key_ids = {"alice": "dropped"}

    response = client.post(
        "/api/agent/heartbeat", json=beat_body(ai_targets={"alice": True})
    )

    assert response.status_code == 200
    reissued = device.client.ai_key_ids["alice"]
    assert reissued != "dropped"
    stored = load_cliproxyapi_config().client_keys
    assert [key.id for key in stored] == [reissued]
    assert response.json()["ai_accounts"]["alice"]["api_key"] == stored[0].open_key()


def test_a_locked_vault_does_not_fail_the_beat(api, monkeypatch, tmp_path):
    """The one rule of the AI path: a vault with no data key costs the beat
    its ai_accounts, never its answer."""
    client, _, device = api
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    # A state root with no vault.key: sealing raises VaultLockedError.
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    write_config("cliproxyapi/cliproxyapi.json", {"listen_port": 8317})

    response = client.post(
        "/api/agent/heartbeat", json=beat_body(ai_targets={"alice": True})
    )

    assert response.status_code == 200
    assert response.json()["ai_accounts"] == {}
    assert device.client.ai_key_ids == {}


def test_no_targets_means_no_ai_accounts_and_no_config_read(api):
    client, _, _ = api

    response = client.post("/api/agent/heartbeat", json=beat_body())

    assert response.status_code == 200
    assert response.json()["ai_accounts"] == {}


def test_unknown_token_is_refused(api):
    client, _, _ = api
    response = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "nonsense",
            "hostname": "x",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "0.3.0",
        },
    )
    assert response.status_code == 401


def test_a_command_outcome_is_retained_for_the_drawer(api):
    client, runtime, _ = api

    response = client.post(
        "/api/agent/result",
        json={"token": "device-token", "id": "reboot", "exit_code": 0, "output": "ok"},
    )

    assert response.status_code == 200
    outcome = runtime.client_command_results[MAC]["reboot"]
    assert outcome["exit_code"] == 0
    assert outcome["output"] == "ok"
    assert outcome["finished_at"]


def test_a_repeated_command_keeps_only_the_last_outcome(api):
    client, runtime, _ = api

    client.post(
        "/api/agent/result",
        json={"token": "device-token", "id": "reboot", "exit_code": 1, "output": "no"},
    )
    client.post(
        "/api/agent/result",
        json={"token": "device-token", "id": "reboot", "exit_code": 0, "output": "ok"},
    )

    assert runtime.client_command_results[MAC]["reboot"]["exit_code"] == 0


def test_a_result_with_an_unknown_token_is_refused(api):
    client, runtime, _ = api
    response = client.post(
        "/api/agent/result",
        json={"token": "nonsense", "id": "reboot", "exit_code": 0},
    )
    assert response.status_code == 401
    assert runtime.client_command_results == {}


def test_leaving_drops_the_agent_but_keeps_the_device(api):
    client, runtime, device = api
    runtime.client_metrics[MAC] = {"cpu_percent": 4.0}
    runtime.client_modules[MAC] = {"anydesk": {"state": "installed"}}
    runtime.client_accounts[MAC] = ["alice"]
    runtime.client_last_error[MAC] = {"code": "mount_failed", "params": {}}

    response = client.post("/api/agent/leave", json={"token": "device-token"})

    assert response.status_code == 200
    assert device.client.token_sha256 is None
    # What the owner gave it survives; only the agent is gone.
    assert device.name == "testbox"
    assert device.ssh == {"host": "10.0.0.5", "username": "me"}
    assert runtime.client_metrics == {}
    assert runtime.client_modules == {}
    assert runtime.client_accounts == {}
    assert runtime.client_last_error == {}


def test_leaving_with_an_unknown_token_is_refused(api):
    client, _, device = api
    response = client.post("/api/agent/leave", json={"token": "nonsense"})
    assert response.status_code == 401
    assert device.client.token_sha256 is not None


def test_enrolling_with_a_ticket_issues_a_token(api):
    client, runtime, device = api
    runtime.enrollments["ticket"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "hostname": "laptop",
            "platform": {"os": "windows", "family": "", "arch": "amd64"},
        },
    )

    assert response.status_code == 200
    assert response.json()["token"] == "issued-token"
    # The ticket is single-use.
    assert "ticket" not in runtime.enrollments


def test_a_ticket_spent_twice_is_refused_the_second_time(api):
    client, runtime, _ = api
    runtime.enrollments["once"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }
    body = {
        "wire": AGENT_WIRE_GENERATION,
        "enrollment_token": "once",
        "device_id": "abc123",
        "hostname": "laptop",
    }

    assert client.post("/api/agent/enroll", json=body).status_code == 200
    assert client.post("/api/agent/enroll", json=body).status_code == 401


def test_expired_ticket_is_refused(api):
    client, runtime, _ = api
    runtime.enrollments["old"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() - 1,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "old",
            "device_id": "abc123",
        },
    )

    assert response.status_code == 401


def test_an_unbound_enrollment_lands_on_the_device_its_mac_names(api):
    """The machine reports its MACs, so an unbound link folds it into the row
    a scan or an SSH setup already made instead of generating a second record."""
    client, runtime, device = api
    runtime.enrollments["t1"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 60,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "t1",
            "device_id": "abc123",
            "mac_addresses": ["11:22:33:44:55:66", "AA:BB:CC:DD:EE:FF"],
        },
    )

    assert response.status_code == 200
    assert response.json()["mac_address"] == device.mac_address


def test_an_unknown_reported_mac_still_keys_by_mac(api):
    """A real MAC, even an unknown one, is what a later scan merges by."""
    client, runtime, _ = api
    runtime.enrollments["t2"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 60,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "t2",
            "device_id": "abc123",
            "mac_addresses": ["11:22:33:44:55:66"],
        },
    )

    assert response.json()["mac_address"] == "11:22:33:44:55:66"


def test_replies_carry_the_hub_version(api):
    client, runtime, _ = api
    runtime.enrollments["ticket"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }

    beaten = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "x",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "1.2.3",
        },
    )
    enrolled = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "1.2.3",
        },
    )

    assert beaten.json()["hub_version"] == "1.2.3"
    assert enrolled.json()["hub_version"] == "1.2.3"


def test_a_newer_agent_is_turned_away_with_a_code(api):
    """A 409, never a 401: the token was fine, so the refusal must not feed
    the agent's self-unbind counter."""
    client, _, device = api

    refused = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "x",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "1.3.0",
        },
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "agent_newer_than_hub",
        "params": {"hub_version": "1.2.3", "agent_version": "1.3.0"},
    }
    # The token survives, so a beat from a matching build still lands.
    assert device.client.token_sha256 == hashlib.sha256(b"device-token").hexdigest()
    accepted = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "x",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "1.2.3",
        },
    )
    assert accepted.status_code == 200


def test_a_newer_agent_cannot_spend_an_enrollment_ticket(api):
    client, runtime, _ = api
    runtime.enrollments["ticket"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 600,
    }

    refused = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "ticket",
            "device_id": "abc123",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "2.0.0",
        },
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "agent_newer_than_hub"
    # The link is still whole for the machine that will use it properly.
    assert "ticket" in runtime.enrollments


def test_an_older_agent_still_beats(api):
    client, _, _ = api

    response = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "x",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "1.0.0",
        },
    )

    assert response.status_code == 200


def test_an_unparseable_version_refuses_nothing(api):
    client, _, _ = api

    response = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "x",
            "wire": AGENT_WIRE_GENERATION,
            "client_version": "wat",
        },
    )

    assert response.status_code == 200


def test_the_package_endpoint_serves_the_bytes_and_their_digest(
    api, monkeypatch, tmp_path
):
    client, _, _ = api
    baked = tmp_path / "neutrino-agent_9.9.9_all.deb"
    baked.write_bytes(b"!<arch>agent-bytes")
    monkeypatch.setattr(agent_router, "agent_packages", lambda: {"deb": baked})

    response = client.post(
        "/api/agent/package", json={"token": "device-token", "family": "deb"}
    )

    assert response.status_code == 200
    assert response.content == b"!<arch>agent-bytes"
    expected = hashlib.sha256(b"!<arch>agent-bytes").hexdigest()
    assert response.headers["x-checksum-sha256"] == expected


def test_the_package_endpoint_refuses_an_unknown_token(api, monkeypatch, tmp_path):
    client, _, _ = api
    baked = tmp_path / "neutrino-agent_9.9.9_all.deb"
    baked.write_bytes(b"!<arch>agent-bytes")
    monkeypatch.setattr(agent_router, "agent_packages", lambda: {"deb": baked})

    response = client.post(
        "/api/agent/package", json={"token": "nonsense", "family": "deb"}
    )

    assert response.status_code == 401


def test_a_family_the_hub_has_no_package_for_is_a_coded_conflict(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(agent_router, "agent_packages", lambda: {})

    response = client.post(
        "/api/agent/package", json={"token": "device-token", "family": "rpm"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "agent_package_missing"}


def test_the_reply_wire_carries_the_module_names(api):
    client, _, _ = api

    body = client.post("/api/agent/heartbeat", json=beat_body()).json()

    assert {"module_orders", "catalog_hash", "ai_accounts", "hub_version"} <= set(body)
    # The shapes this generation replaced must not come back.
    assert "desired_modules" not in body
    assert "desired_functions" not in body


def test_the_catalog_is_composed_for_the_address_the_device_reaches(api):
    client, runtime, _ = api

    client.post("/api/agent/heartbeat", json=beat_body())

    assert runtime.device_catalog.asked_hosts == ["192.168.100.1"]


def test_nothing_usable_reported_keys_by_machine_id(api):
    client, runtime, _ = api
    runtime.enrollments["t3"] = {
        "name": "",
        "mac_address": None,
        "expires_at": time.time() + 60,
    }

    response = client.post(
        "/api/agent/enroll",
        json={
            "wire": AGENT_WIRE_GENERATION,
            "enrollment_token": "t3",
            "device_id": "abc123",
            "mac_addresses": ["not-a-mac"],
        },
    )

    assert response.json()["mac_address"] == "id:abc123"


def test_a_beat_from_another_wire_generation_is_told_to_reinstall(api):
    client, runtime, device = api
    reply = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "x",
            "wire": 1,
            "client_version": "0.1.0",
        },
    )

    assert reply.status_code == 409
    detail = reply.json()["detail"]
    assert detail["code"] == "agent_wire_stale"
    assert detail["params"]["agent_wire"] == 1
    assert detail["params"]["hub_wire"] >= 2


def test_a_pre_generation_beat_reads_as_wire_zero(api):
    client, runtime, device = api
    reply = client.post(
        "/api/agent/heartbeat",
        json={
            "token": "device-token",
            "hostname": "x",
            "client_version": "0.1.0",
        },
    )

    assert reply.status_code == 409
    assert reply.json()["detail"]["params"]["agent_wire"] == 0


def test_an_enrollment_from_another_wire_generation_is_refused(api):
    client, runtime, device = api
    reply = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": "whatever",
            "device_id": "abc",
            "wire": 99,
            "client_version": "0.1.0",
        },
    )

    assert reply.status_code == 409
    assert reply.json()["detail"]["code"] == "agent_wire_stale"


def _beat(**fields):
    body = {
        "token": "device-token",
        "hostname": "x",
        "wire": 3,
        "client_version": "0.1.0",
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
    }
    body.update(fields)
    return body


def test_a_wish_nobody_attempted_is_carried_out_after_a_restart(api):
    """The queue is memory and a restart may lose an order; the decision it
    came from is on disk, and a beat is where the hub notices the gap."""
    client, runtime, device = api
    FakeRegistry.device.client.modules["anydesk"] = {
        "is_enabled": True,
        "is_activated": False,
        "failed": None,
    }

    reply = client.post(
        "/api/agent/heartbeat",
        json=_beat(modules={"anydesk": {"state": "absent"}}),
    )

    assert reply.status_code == 200
    assert [order["module"] for order in reply.json()["module_orders"]] == ["anydesk"]


def test_a_wish_a_refusal_stands_against_waits_for_a_person(api):
    """The rule this must not break: a refused order is never retried by a
    tick, a beat, or a restart — only by somebody asking again."""
    client, runtime, device = api
    FakeRegistry.device.client.modules["anydesk"] = {
        "is_enabled": True,
        "is_activated": False,
        "failed": {"code": "vendor_served_a_page", "params": {}},
    }

    reply = client.post(
        "/api/agent/heartbeat",
        json=_beat(modules={"anydesk": {"state": "absent"}}),
    )

    assert reply.status_code == 200
    assert reply.json()["module_orders"] == []


def test_a_refusal_is_written_down_where_a_restart_still_finds_it(api):
    """Orders die with the process; the refusal that closed one must not,
    or the next beat reads an unattempted wish and asks again."""
    client, runtime, device = api
    FakeRegistry.device.client.modules["anydesk"] = {
        "is_enabled": True,
        "is_activated": False,
        "failed": None,
    }
    order = runtime.agent_module_orders.ask(
        mac_address=MAC.lower(),
        module="anydesk",
        manifest={"kind": "package", "platforms": {"linux": {"url": "u"}}},
        platform={"os": "linux", "family": "debian", "arch": "amd64"},
        action="install",
        reported_state="absent",
    )

    client.post(
        "/api/agent/heartbeat",
        json=_beat(
            modules={"anydesk": {"state": "absent"}},
            module_results=[
                {
                    "id": order.id,
                    "module": "anydesk",
                    "state": "failed",
                    "code": "install_failed",
                    "params": {},
                    "output": "dpkg: error",
                }
            ],
        ),
    )

    stored = FakeRegistry.device.client.modules["anydesk"]
    assert stored["failed"] == {"code": "install_failed", "params": {}}
