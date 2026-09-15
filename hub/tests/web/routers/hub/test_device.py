"""The Devices page: the list, the ssh block, wake, the seat password, the
services block, the agent install and the reinstall, forgetting and renaming,
the remote desktop, and the enrolment link.

Every route names its device in the body or the query. What the sections pin
is written above each.
"""

import base64
import json
import time
from types import SimpleNamespace

import asyncssh
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.agent_package import AgentPackageCache
from neutrino_hub.modules.devices.constants import SSH_UNREACHABLE_STATUS
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.devices.registry import (
    DeviceClientInfo,
    DeviceRegistry,
    ManagedDevice,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web.constants import WEB_EVENT_DEVICE_REPORT
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.models import DeviceRequest
from neutrino_hub.web.routers.hub import device as devices_router
from neutrino_hub.web.task_stream import TaskStreamRegistry
from tests.conftest import (
    FakeChannelSessions,
    lan_entry,
    network_config,
    unlock_vault,
    wan_entry,
)
from tests.web.device_api_box import (
    DEVICE,
    FINGERPRINT,
    BoxRegistry,
    device_box,
)

DEVICE_PATH = "/api/hub/device"
SET_PATH = "/api/hub/device/set"
SERVICE_PATH = "/api/hub/device/service"
ENROLLMENT_PATH = "/api/hub/device/enrollment/create"
LINK_MAC = "aa:bb:cc:dd:ee:ff"
LOGIN_PASSWORD = "a-password"  # scan: allow
TYPED_PASSWORD = "typed-now"  # scan: allow
SUDO_PASSWORD = "a-sudo-password"  # scan: allow


def stored_key() -> str:
    key = asyncssh.generate_private_key("ssh-ed25519")
    return (
        KeyRegistry()
        .add(name="a key", private_key=key.export_private_key().decode())
        .id
    )


# --- the list: what one device carries into the panel's two sections ---


class ListRegistry:
    """The one device the list is built from."""

    device: ManagedDevice

    def merged(self, discovered: list) -> list:
        return [ListRegistry.device]

    def get(self, device_id: str):
        return ListRegistry.device if device_id == ListRegistry.device.id else None

    def annotate(self, device_id: str, payload: dict) -> ManagedDevice:
        if "name" in payload:
            ListRegistry.device.name = payload["name"]
        return ListRegistry.device


class FakeScanner:
    """A sweep that finds nothing, so the stored device is all there is."""

    def __init__(self, *, lan_interfaces):
        self.lan_interfaces = lan_interfaces

    def scan(self, *, is_active: bool) -> list:
        return []


class ListRuntime:
    def __init__(self):
        self.events = PanelEventBus()
        self.device_metrics = {}
        self.device_address = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_last_error = {}
        self.device_modules = {}
        self.device_shares = DeviceShareRegistry()
        self.agent_sessions = FakeChannelSessions()

    def network(self):
        return _EmptyNetwork()


class _EmptyNetwork:
    lan_device_names: list = []
    lan_interfaces: list = []
    device_facing_device_names: list = []
    device_facing_interfaces: list = []


@pytest.fixture
def listed(monkeypatch):
    ListRegistry.device = ManagedDevice(
        id=DEVICE,
        name="xenode",
        machine_id="machine-xenode",
        mac_addresses=[LINK_MAC, "11:22:33:44:55:66"],
        link_mac=LINK_MAC,
        ipv4_address="192.168.100.2",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", ListRegistry)
    monkeypatch.setattr(devices_router, "LanScanner", FakeScanner)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = ListRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_a_device_carries_its_id_and_the_facts_its_agent_reported(listed):
    client, _ = listed

    device = client.get(DEVICE_PATH).json()["devices"][0]

    assert device["id"] == DEVICE
    assert device["machine_id"] == "machine-xenode"
    assert device["mac_addresses"] == [LINK_MAC, "11:22:33:44:55:66"]
    assert device["link_mac"] == LINK_MAC
    assert "mac_address" not in device


def test_a_managed_device_carries_the_platform_its_agent_reported(listed):
    client, runtime = listed
    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }

    device = client.get(DEVICE_PATH).json()["devices"][0]

    assert device["client"]["platform_os"] == "linux"
    assert device["client"]["platform_arch"] == "amd64"


def test_a_platform_nobody_has_reported_reads_as_unknown(listed):
    """The panel holds it in memory only, so it is absent until the agent beats
    again after a restart. Null, never a guess."""
    client, _ = listed

    device = client.get(DEVICE_PATH).json()["devices"][0]

    assert device["client"]["platform_os"] is None
    assert device["client"]["platform_arch"] is None


def test_a_device_with_no_agent_has_no_client_block(listed):
    client, runtime = listed
    ListRegistry.device.client = DeviceClientInfo()
    runtime.device_platform[DEVICE] = {"os": "windows", "arch": "amd64"}

    device = client.get(DEVICE_PATH).json()["devices"][0]

    assert device["client"] is None


def test_an_id_no_device_has_is_refused_typed(listed):
    client, _ = listed

    response = client.post(SET_PATH, json={"device_id": "nonsense", "name": "x"})

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "device_unknown",
        "params": {"device_id": "nonsense"},
    }


def test_renaming_a_device_keeps_its_platform(listed):
    """The page redraws the tile from this answer. Built without the platform,
    a managed tile loses its chip until the next poll."""
    client, runtime = listed
    runtime.device_platform[DEVICE] = {"os": "linux", "arch": "amd64"}

    answer = client.post(SET_PATH, json={"device_id": DEVICE, "name": "renamed"}).json()

    assert answer["name"] == "renamed"
    assert answer["client"]["platform_os"] == "linux"


def test_the_version_and_the_stamp_come_from_the_session_registry(listed):
    client, runtime = listed
    runtime.agent_sessions.versions[DEVICE] = "0.3.0"
    runtime.agent_sessions.ended_at[DEVICE] = "2026-01-01T00:00:00+00:00"

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["client"]["version"] == "0.3.0"
    assert device["client"]["last_seen"] == "2026-01-01T00:00:00+00:00"
    assert device["client"]["is_online"] is False


def test_a_device_not_seen_since_the_panel_started_has_no_version_or_stamp(listed):
    """Presence lives in memory alone. A managed device the hub has not
    heard from is still managed, with nothing to say about when it was
    last here."""
    client, _ = listed

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["client"]["is_managed"] is True
    assert device["client"]["version"] is None
    assert device["client"]["last_seen"] is None
    assert device["client"]["is_version_mismatched"] is False


def test_a_device_is_at_the_address_its_channel_comes_from(listed):
    """SSH is for installing and power, never for locating: an agent joined
    by a link has no stored host and is no less reachable."""
    client, runtime = listed
    runtime.device_address[DEVICE] = "192.168.100.7"

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["ipv4_address"] == "192.168.100.7"


def test_the_ssh_block_carries_its_references_and_no_password_field(listed):
    client, _ = listed
    ListRegistry.device.ssh = {
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        "auth": "password",
        "key_id": None,
        "login_id": "abc123",
    }

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["has_ssh"] is True
    assert device["ssh"] == {
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        "auth": "password",
        "key_id": None,
        "key_name": None,
        "login_id": "abc123",
        "sudo_login_id": None,
    }


# --- the desktop the machine says it is sharing ---


def test_a_device_sharing_its_desktop_carries_the_share_it_declared(listed):
    client, runtime = listed
    runtime.device_modules[DEVICE] = {"rustdesk": {"state": "installed"}}
    runtime.device_shares.declare(
        device_id=DEVICE,
        share_id="s1",
        hostname="xenode",
        host="192.168.100.2",
        port=21118,
        attention="rdp_nobody_seated",
        account="pat",
        connected_count=2,
    )

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["client"]["rdp"] == {
        "is_shared": True,
        "account": "pat",
        "port": 21118,
        "attention": "rdp_nobody_seated",
        "connected_count": 2,
        "is_available": True,
    }


def test_a_device_sharing_nothing_says_so_without_a_port_or_an_account(listed):
    client, runtime = listed
    runtime.device_modules[DEVICE] = {"rustdesk": {"state": "installed"}}

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["client"]["rdp"] == {
        "is_shared": False,
        "account": "",
        "port": 0,
        "attention": "",
        "connected_count": 0,
        "is_available": True,
    }


def test_a_package_built_without_the_host_reads_unavailable(listed):
    """Only a machine reporting the row absent says so. One nobody has heard
    from says nothing either way, and the card stands as it always did."""
    client, runtime = listed
    runtime.device_modules[DEVICE] = {"rustdesk": {"state": "absent"}}

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["client"]["rdp"]["is_available"] is False

    runtime.device_modules[DEVICE] = {}

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["client"]["rdp"]["is_available"] is True


def test_another_machines_share_is_not_shown_on_this_device(listed):
    client, runtime = listed
    runtime.device_shares.declare(
        device_id="another-device",
        share_id="s2",
        hostname="other",
        host="192.168.100.9",
        port=21118,
        account="sam",
    )

    (device,) = client.get(DEVICE_PATH).json()["devices"]

    assert device["client"]["rdp"]["is_shared"] is False


# --- the ssh block: credential references stored and echoed, never a secret ---


class SshRuntime:
    def __init__(self):
        self.events = PanelEventBus()
        self.device_metrics = {}
        self.device_address = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_last_error = {}
        self.device_modules = {}
        self.agent_sessions = FakeChannelSessions()


@pytest.fixture
def ssh_api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    device_id = DeviceRegistry().create("xenode").id
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = SshRuntime
    with TestClient(app) as client:
        yield client, tmp_path, device_id


def stored_password(password: str) -> str:
    record = SecretVault().add(
        kind="login", name="a password", secret={"password": password}
    )
    return record.id


def annotate(client, device_id: str, ssh: dict):
    return client.post(
        SET_PATH,
        json={
            "device_id": device_id,
            "name": "xenode",
            "ssh": {"host": "192.168.100.2", "port": 22, "username": "iffi", **ssh},
        },
    )


def test_valid_references_are_stored_and_echoed(ssh_api):
    client, tmp_path, device_id = ssh_api
    login_id = stored_password(LOGIN_PASSWORD)

    saved = annotate(client, device_id, {"auth": "password", "login_id": login_id})

    assert saved.status_code == 200
    view = saved.json()["ssh"]
    assert view["login_id"] == login_id
    assert "password" not in view
    assert "sudo_password_id" not in view
    assert "sudo_password" not in view

    stored = json.loads((tmp_path / "devices" / "devices.json").read_text())
    block = stored["devices"][device_id]["ssh"]
    assert block == {
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        "auth": "password",
        "key_id": None,
        "login_id": login_id,
        "sudo_login_id": None,
    }


def test_a_key_reference_is_stored_and_named(ssh_api):
    client, _, device_id = ssh_api
    key_id = stored_key()

    saved = annotate(client, device_id, {"auth": "key", "key_id": key_id})

    assert saved.status_code == 200
    view = saved.json()["ssh"]
    assert view["key_id"] == key_id
    assert view["key_name"] == "a key"
    assert view["login_id"] is None


def test_a_bogus_login_id_is_refused(ssh_api):
    client, _, device_id = ssh_api

    refused = annotate(client, device_id, {"auth": "password", "login_id": "absent"})

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "login_id"},
    }
    assert DeviceRegistry().get(device_id).ssh is None


def test_a_login_id_offered_as_a_key_is_refused(ssh_api):
    client, _, device_id = ssh_api
    login_id = stored_password(LOGIN_PASSWORD)

    refused = annotate(client, device_id, {"auth": "key", "key_id": login_id})

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "key_id"},
    }


# --- wake: where a magic packet goes, whose MAC it carries, one refusal ---


class WakeRuntime:
    def __init__(self, network: RouterNetworkConfig):
        self._network = network

    def network(self) -> RouterNetworkConfig:
        return self._network


class WakeRegistry:
    device: ManagedDevice

    def get(self, device_id: str):
        return WakeRegistry.device if device_id == WakeRegistry.device.id else None


@pytest.fixture
def sleeping(monkeypatch):
    """One stored device whose agent last ran on the LAN MAC."""
    WakeRegistry.device = ManagedDevice(
        id=DEVICE, name="box", mac_addresses=[LINK_MAC], link_mac=LINK_MAC
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", WakeRegistry)


@pytest.fixture
def gateway(monkeypatch, sleeping):
    """A router with one served network and an exposed overlay on it."""
    network = network_config(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "easytier", "is_exposed": True}],
    )
    monkeypatch.setattr(
        devices_router, "device_addresses", lambda: {"easytier": "10.126.126.2/24"}
    )
    del sleeping
    return WakeRuntime(network)


def test_the_packet_goes_to_the_served_network_and_never_the_overlay(
    gateway, monkeypatch
):
    sent = []
    monkeypatch.setattr(
        devices_router,
        "send_magic_packet",
        lambda mac, *, broadcast_address: sent.append((mac, broadcast_address)),
    )

    result = devices_router.wake(DeviceRequest(device_id=DEVICE), runtime=gateway)

    assert result.is_sent is True
    assert sent == [(LINK_MAC, "192.168.100.255")]
    assert "10.126.126" not in result.message


def test_a_device_that_never_reported_a_mac_is_refused(gateway, monkeypatch):
    WakeRegistry.device.link_mac = ""
    monkeypatch.setattr(
        devices_router, "send_magic_packet", lambda mac, *, broadcast_address: None
    )

    with pytest.raises(HTTPException) as refused:
        devices_router.wake(DeviceRequest(device_id=DEVICE), runtime=gateway)

    assert refused.value.status_code == 409
    assert refused.value.detail == {
        "code": "wol_no_mac",
        "params": {"device_id": DEVICE},
    }


def test_an_unknown_device_is_refused_typed(gateway):
    with pytest.raises(HTTPException) as refused:
        devices_router.wake(DeviceRequest(device_id="nonsense"), runtime=gateway)

    assert refused.value.status_code == 404
    assert refused.value.detail["code"] == "device_unknown"


def test_the_overlay_still_counts_for_reaching_the_hub(gateway):
    assert devices_router._facing_cidrs(gateway) == [
        "192.168.100.1/24",
        "10.126.126.2/24",
    ]
    assert devices_router._facing_cidrs(gateway, is_overlay_included=False) == [
        "192.168.100.1/24"
    ]


def test_one_domain_refusing_does_not_stop_the_others(monkeypatch, sleeping):
    network = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1"),
    )
    monkeypatch.setattr(devices_router, "device_addresses", lambda: {})

    def send(mac, *, broadcast_address):
        if broadcast_address.startswith("192.168.100."):
            raise OSError(126, "Required key not available")

    monkeypatch.setattr(devices_router, "send_magic_packet", send)

    result = devices_router.wake(
        DeviceRequest(device_id=DEVICE), runtime=WakeRuntime(network)
    )

    assert result.is_sent is True
    assert result.message == "magic packet sent to 192.168.101.255"


def test_every_domain_refusing_is_the_failure_it_says(monkeypatch, sleeping):
    network = network_config(lan_entry("enp1s0", address="192.168.100.1"))
    monkeypatch.setattr(devices_router, "device_addresses", lambda: {})

    def send(mac, *, broadcast_address):
        raise OSError(126, "Required key not available")

    monkeypatch.setattr(devices_router, "send_magic_packet", send)

    result = devices_router.wake(
        DeviceRequest(device_id=DEVICE), runtime=WakeRuntime(network)
    )

    assert result.is_sent is False
    assert "192.168.100.255" in result.message
    assert "Required key" in result.message


# --- the seat password: reset, sealed, and handed down ---


SEAT_PASSWORD_PATH = "/api/hub/device/desktop/seat_password/reset"


class RdpRegistry:
    device: ManagedDevice

    def get(self, device_id: str):
        return RdpRegistry.device if device_id == RdpRegistry.device.id else None


class RdpRuntime:
    """The runtime as this one route reaches for it."""

    def __init__(self, online=()):
        self.events = PanelEventBus()
        self.agent_sessions = FakeChannelSessions(online)
        self.desired_states = DesiredStateStore()

    def push_desired_state(self, key: str) -> None:
        desired, state_hash = self.desired_states.compose(key, {})
        self.agent_sessions.push_state_from_thread(key, state_hash, desired)


@pytest.fixture
def rdp_api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "resolved_modules", lambda platform: {})
    unlock_vault(monkeypatch, tmp_path)
    RdpRegistry.device = ManagedDevice(
        id=DEVICE,
        name="xenode",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", RdpRegistry)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = RdpRuntime(online=[DEVICE])
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_a_reset_generates_a_password_and_pushes_the_state_carrying_it(rdp_api):
    client, runtime = rdp_api
    runtime.desired_states.ensure_seat_password(DEVICE)
    before = runtime.desired_states.seat_password(DEVICE)

    answer = client.post(SEAT_PASSWORD_PATH, json={"device_id": DEVICE})

    assert answer.status_code == 200
    assert answer.json() == {}
    after = runtime.desired_states.seat_password(DEVICE)
    assert after != before
    key, _, desired = runtime.agent_sessions.pushes[-1]
    assert key == DEVICE
    assert desired["rdp"] == {"seat_password": after}


def test_a_reset_tells_the_panel_the_device_moved(rdp_api):
    client, runtime = rdp_api
    events = []
    runtime.events.publish = lambda event_type, key="", data=None: events.append(
        (event_type, key)
    )

    client.post(SEAT_PASSWORD_PATH, json={"device_id": DEVICE})

    assert (WEB_EVENT_DEVICE_REPORT, DEVICE) in events


def test_a_machine_with_no_channel_is_refused_and_keeps_its_password(rdp_api):
    client, runtime = rdp_api
    runtime.desired_states.ensure_seat_password(DEVICE)
    before = runtime.desired_states.seat_password(DEVICE)
    runtime.agent_sessions.online.clear()

    answer = client.post(SEAT_PASSWORD_PATH, json={"device_id": DEVICE})

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_offline", "params": {}}
    assert runtime.desired_states.seat_password(DEVICE) == before
    assert runtime.agent_sessions.pushes == []


# --- the services block: what it reads, and what it may ask ---


class ServiceRegistry:
    device: ManagedDevice

    def get(self, device_id: str):
        return (
            ServiceRegistry.device if device_id == ServiceRegistry.device.id else None
        )


class StubCatalog:
    """Answers the same composed catalog the agent would be served."""

    def __init__(self):
        self.asked = []

    def catalog(self, *, device_host: str, platform: dict):
        self.asked.append((device_host, dict(platform)))
        entries = [
            {"id": "hub_share_media", "type": "file", "title": "Media"},
            {"id": "web_gitea", "type": "web", "title": "Gitea"},
        ]
        return {"modules": {}, "services": entries}, "hash"


class ServiceRuntime:
    def __init__(self):
        self.device_accounts = {}
        self.device_address = {}
        self.device_hub_host = {}
        self.device_platform = {}
        self.device_catalog = StubCatalog()
        self.agent_sessions = FakeChannelSessions(online=[DEVICE])


@pytest.fixture
def service_api(monkeypatch):
    ServiceRegistry.device = ManagedDevice(
        id=DEVICE,
        name="testbox",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", ServiceRegistry)
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = ServiceRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_a_device_that_never_beat_reads_empty_rather_than_erroring(service_api):
    client, _runtime = service_api

    answer = client.get(SERVICE_PATH, params={"device_id": DEVICE}).json()

    assert answer == {
        "accounts": [],
        "entries": [],
        "ai_targets": {},
        "ai_states": {},
        "mounts": [],
        "rdp": {},
        "mount_location_shape": "path",
        "mount_location_suggestion": "",
    }


def test_the_view_is_the_devices_own_catalog(service_api):
    client, runtime = service_api
    runtime.device_hub_host[DEVICE] = "192.168.100.1"
    runtime.device_platform[DEVICE] = {"os": "linux"}
    runtime.device_accounts[DEVICE] = ["pat", "sam"]

    answer = client.get(SERVICE_PATH, params={"device_id": DEVICE}).json()

    assert [entry["id"] for entry in answer["entries"]] == [
        "hub_share_media",
        "web_gitea",
    ]
    assert answer["accounts"] == ["pat", "sam"]
    # The catalog is composed for the address the device itself reaches the
    # hub on, so entry URLs match what the machine's own page shows.
    assert runtime.device_catalog.asked == [("192.168.100.1", {"os": "linux"})]


def test_a_share_runs_with_its_account_and_password(service_api):
    """The access password rides inside the one ask; nothing hub-side keeps
    it, and the verb is the path's."""
    client, runtime = service_api

    answer = client.post(
        f"{SERVICE_PATH}/share",
        json={
            "device_id": DEVICE,
            "service_type": "rdp",
            "body": {"account": "pat", "password": "pw"},
        },
    )

    assert answer.status_code == 200
    assert answer.json()["command_id"].startswith("service-rdp-")
    ((_key, _action, args),) = runtime.agent_sessions.commands
    assert args == {
        "service_type": "rdp",
        "body": {"action": "share", "account": "pat", "password": "pw"},  # scan: allow
    }


def test_an_unshare_is_the_paired_verb(service_api):
    client, runtime = service_api

    answer = client.post(
        f"{SERVICE_PATH}/unshare", json={"device_id": DEVICE, "service_type": "rdp"}
    )

    assert answer.status_code == 200
    ((_key, _action, args),) = runtime.agent_sessions.commands
    assert args["body"] == {"action": "unshare"}


@pytest.mark.parametrize("service_type", ["ai", "file", "web"])
def test_a_type_the_page_cannot_share_is_refused_typed(service_api, service_type):
    client, runtime = service_api

    answer = client.post(
        f"{SERVICE_PATH}/share",
        json={"device_id": DEVICE, "service_type": service_type},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {"code": "unknown_request", "params": {}}
    assert runtime.agent_sessions.commands == []


def test_a_device_without_a_socket_takes_no_ask(service_api):
    client, runtime = service_api
    runtime.agent_sessions.online.clear()

    answer = client.post(
        f"{SERVICE_PATH}/share", json={"device_id": DEVICE, "service_type": "rdp"}
    )

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "agent_offline", "params": {}}
    assert runtime.agent_sessions.commands == []


# --- the agent install: its credentials, its pre-flight, and the reinstall ---


class InstallRuntime:
    instance = None

    def __init__(self, packages_dir):
        self.events = PanelEventBus()
        self.settings = {}
        self.tasks = TaskStreamRegistry()
        self.device_metrics = {}
        self.device_address = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_last_error = {}
        self.device_modules = {}
        self.enrollments = {}
        self.agent_sessions = FakeChannelSessions()
        self.agent_packages = AgentPackageCache(
            root=packages_dir / "agent_cache",
            manifest_path=packages_dir / "agent_packages.json",
            pinned_dir=packages_dir / "devices" / "packages",
        )

    def network(self):
        return SimpleNamespace(lan_interfaces=[], primary_lan_address="192.168.100.1")


@pytest.fixture
def install_api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    device_id = DeviceRegistry().create("xenode").id
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = InstallRuntime(tmp_path)
    InstallRuntime.instance = runtime
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, tmp_path, device_id


def stored_login() -> str:
    return (
        SecretVault()
        .add(kind="login", name="a password", secret={"password": LOGIN_PASSWORD})
        .id
    )


def probe_answers(monkeypatch, code: int, output: str):
    async def run_once(self, command, *, timeout_s=20, input_text=None):
        return code, output

    monkeypatch.setattr(devices_router.DeviceSshOperator, "run_once", run_once)


def capture_install(monkeypatch) -> dict:
    """Record what the install is started with, running nothing."""
    captured: dict = {}

    def install_client(self, *, packages, enrollment_link, sudo_password=None):
        captured["credentials"] = self._credentials
        captured["sudo_password"] = sudo_password

        async def lines():
            yield "[installed]\n"

        return lines()

    monkeypatch.setattr(
        devices_router.DeviceSshOperator, "install_client", install_client
    )
    return captured


def hub_carries_a_package(tmp_path, monkeypatch):
    packages = tmp_path / "devices" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    (packages / "neutrino-agent_0.1.0_amd64.deb").write_bytes(b"deb")
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["https://192.168.100.1:8443"]
    )
    monkeypatch.setattr(devices_router, "certificate_fingerprint", lambda: "ab" * 32)


def install(client, device_id: str, **fields):
    body = {
        "device_id": device_id,
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        **fields,
    }
    return client.post(f"{DEVICE_PATH}/agent/install", json=body)


def stored_ssh(tmp_path, device_id: str) -> dict:
    stored = json.loads((tmp_path / "devices" / "devices.json").read_text())
    return stored["devices"][device_id]["ssh"]


def ready(monkeypatch, tmp_path):
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, 0, "Linux")
    return capture_install(monkeypatch)


# --- the credential sources ---


def test_a_stored_key_is_the_credential_and_the_block_records_it(
    install_api, monkeypatch
):
    client, tmp_path, device_id = install_api
    captured = ready(monkeypatch, tmp_path)
    key_id = stored_key()

    started = install(client, device_id, key_id=key_id, sudo_password=SUDO_PASSWORD)

    assert started.status_code == 200
    assert started.json()["task_id"]
    assert stored_ssh(tmp_path, device_id) == {
        "host": "192.168.100.2",
        "port": 22,
        "username": "iffi",
        "auth": "key",
        "key_id": key_id,
        "login_id": None,
        "sudo_login_id": None,
    }
    assert captured["credentials"].private_key
    assert captured["credentials"].password is None
    assert captured["sudo_password"] == SUDO_PASSWORD


def test_the_sudo_login_is_opened_from_the_vault_and_referenced(
    install_api, monkeypatch
):
    client, tmp_path, device_id = install_api
    captured = ready(monkeypatch, tmp_path)
    key_id = stored_key()
    sudo_id = stored_login()

    started = install(client, device_id, key_id=key_id, sudo_login_id=sudo_id)

    assert started.status_code == 200
    assert captured["sudo_password"] == LOGIN_PASSWORD
    assert stored_ssh(tmp_path, device_id)["sudo_login_id"] == sudo_id
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != "vault.json":
            assert LOGIN_PASSWORD.encode() not in path.read_bytes()


def test_a_stale_sudo_login_is_refused(install_api, monkeypatch):
    client, tmp_path, device_id = install_api
    ready(monkeypatch, tmp_path)

    refused = install(client, device_id, key_id=stored_key(), sudo_login_id="deadbeef")

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "sudo_login_id"},
    }


def test_a_stored_login_is_opened_from_the_vault(install_api, monkeypatch):
    client, tmp_path, device_id = install_api
    captured = ready(monkeypatch, tmp_path)
    login_id = stored_login()

    started = install(client, device_id, login_id=login_id)

    assert started.status_code == 200
    assert stored_ssh(tmp_path, device_id)["auth"] == "password"
    assert stored_ssh(tmp_path, device_id)["login_id"] == login_id
    assert captured["credentials"].password == LOGIN_PASSWORD
    assert captured["sudo_password"] is None


def test_a_typed_password_is_used_and_stored_nowhere_unless_asked(
    install_api, monkeypatch
):
    client, tmp_path, device_id = install_api
    captured = ready(monkeypatch, tmp_path)

    started = install(
        client, device_id, password=TYPED_PASSWORD, sudo_password=SUDO_PASSWORD
    )

    assert started.status_code == 200
    assert captured["credentials"].password == TYPED_PASSWORD
    block = stored_ssh(tmp_path, device_id)
    assert block["login_id"] is None and block["auth"] == "password"
    assert SecretVault().list_records(kind="login") == []
    for path in tmp_path.rglob("*"):
        if path.is_file():
            text = path.read_bytes()
            assert TYPED_PASSWORD.encode() not in text
            assert SUDO_PASSWORD.encode() not in text


def test_a_typed_password_saved_becomes_a_login_the_block_names(
    install_api, monkeypatch
):
    client, tmp_path, device_id = install_api
    captured = ready(monkeypatch, tmp_path)

    started = install(
        client,
        device_id,
        password=TYPED_PASSWORD,
        is_password_saved=True,
        sudo_password=SUDO_PASSWORD,
    )

    assert started.status_code == 200
    (record,) = SecretVault().list_records(kind="login")
    assert record.name == "iffi@192.168.100.2"
    assert SecretVault().open(record.id) == {
        "username": "iffi",
        "password": TYPED_PASSWORD,
    }
    assert stored_ssh(tmp_path, device_id)["login_id"] == record.id
    assert captured["credentials"].password == TYPED_PASSWORD
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SUDO_PASSWORD.encode() not in path.read_bytes()


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"key_id": "k", "login_id": "l"},
        {"key_id": "k", "password": "p"},
        {"password": "p", "host": ""},
        {"password": "p", "username": ""},
    ],
)
def test_anything_but_one_credential_source_is_refused(
    install_api, monkeypatch, fields
):
    client, tmp_path, device_id = install_api
    ready(monkeypatch, tmp_path)

    refused = install(client, device_id, **fields)

    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "install_credentials_invalid"
    assert DeviceRegistry().get(device_id).ssh is None


def test_a_stale_credential_id_is_refused_by_field(install_api, monkeypatch):
    client, tmp_path, device_id = install_api
    ready(monkeypatch, tmp_path)

    refused = install(client, device_id, login_id="absent")

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "login_id"},
    }


# --- the pre-flight ---


def test_a_non_linux_device_is_refused_before_any_task(install_api, monkeypatch):
    client, tmp_path, device_id = install_api
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, 0, "Darwin")

    refused = install(client, device_id, login_id=stored_login())

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "unsupported_remote_install",
        "params": {"os": "Darwin"},
    }


def test_an_unanswered_probe_starts_the_task(install_api, monkeypatch):
    client, tmp_path, device_id = install_api
    hub_carries_a_package(tmp_path, monkeypatch)
    probe_answers(monkeypatch, SSH_UNREACHABLE_STATUS, "Connection refused")
    capture_install(monkeypatch)

    started = install(client, device_id, login_id=stored_login())

    assert started.status_code == 200
    assert started.json()["task_id"]


def test_a_hub_with_no_agent_package_refuses_with_a_code(install_api, monkeypatch):
    client, _, device_id = install_api
    probe_answers(monkeypatch, 0, "Linux")

    refused = install(client, device_id, login_id=stored_login())

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "agent_package_missing", "params": {}}


def test_the_install_ticket_binds_to_the_device(install_api, monkeypatch):
    """The SSH install walks the same enrollment path a pasted link does."""
    client, tmp_path, device_id = install_api
    ready(monkeypatch, tmp_path)

    started = install(client, device_id, login_id=stored_login())

    assert started.status_code == 200
    tickets = list(InstallRuntime.instance.enrollments.values())
    assert tickets and tickets[-1]["device_id"] == device_id


def test_installing_on_a_scan_row_stores_it_under_an_id_of_its_own(
    install_api, monkeypatch
):
    client, tmp_path, _ = install_api
    ready(monkeypatch, tmp_path)

    started = install(client, "scan:aa:bb:cc:dd:ee:09", login_id=stored_login())

    assert started.status_code == 200
    (adopted,) = [d for d in DeviceRegistry().all_stored() if d.name != "xenode"]
    assert adopted.mac_addresses == ["aa:bb:cc:dd:ee:09"]
    assert adopted.ssh["host"] == "192.168.100.2"
    tickets = list(InstallRuntime.instance.enrollments.values())
    assert tickets[-1]["device_id"] == adopted.id


# --- the reinstall ---


def test_a_reinstall_with_no_channel_is_409(install_api):
    client, _, device_id = install_api

    refused = client.post(
        f"{DEVICE_PATH}/agent/reinstall", json={"device_id": device_id}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "agent_offline", "params": {}}


def test_a_reinstall_on_a_live_agent_runs_the_command_as_a_task(install_api):
    client, _, device_id = install_api
    sessions = InstallRuntime.instance.agent_sessions
    sessions.online.add(device_id)
    sessions.scripts["command"] = lambda args: (
        [],
        {"exit_code": 0, "code": "", "params": {}, "output": "reinstall launched\n"},
    )

    started = client.post(
        f"{DEVICE_PATH}/agent/reinstall", json={"device_id": device_id}
    )

    assert started.status_code == 200
    # The command runs as a task on its own thread; the stream opens after
    # the answer.
    deadline = time.monotonic() + 5
    while not sessions.streams and time.monotonic() < deadline:
        time.sleep(0.02)
    (stream,) = sessions.streams
    assert stream.kind == "command"
    assert stream.args == {"action": "reinstall", "args": {}}


# --- reinstall follows the machine's record ---


class Session:
    def __init__(self):
        self.report = {}
        self.reported_at = "now"


class Presence:
    """A sessions stand-in: each look hands out a scripted (session, record)."""

    def __init__(self, looks):
        self.looks = list(looks)
        self.outcome = {
            "exit_code": 0,
            "code": "",
            "params": {},
            "output": "reinstall launched\n",
        }

    def get(self, key):
        session, record = self.looks.pop(0) if len(self.looks) > 1 else self.looks[0]
        if session is not None:
            session.report = {"last_reinstall": record} if record else {}
        return session

    def version_of(self, key):
        return "9.9.9"

    async def open_stream(self, key, kind, args):
        return _ClosedStream(self.outcome)


class _ClosedStream:
    def __init__(self, info):
        self.close_info = info

    async def recv(self):
        return None


RECORD = {
    "package": "neutrino-agent_0.1.0_amd64.deb",
    "kind": "deb",
    "started_at": "2026-09-10T00:00:00Z",
    "finished_at": "2026-09-10T00:00:04Z",
    "exit_code": 0,
    "output": "Unpacking neutrino-agent (0.1.0) over (0.1.0)\nSetting up neutrino-agent (0.1.0)\n",
}


def drain_reinstall(monkeypatch, presence, **overrides):
    import asyncio

    monkeypatch.setattr(devices_router, "WEB_REINSTALL_POLL_S", 0.0)
    monkeypatch.setattr(devices_router, "WEB_REINSTALL_RETURN_TIMEOUT_S", 2.0)
    for name, value in overrides.items():
        monkeypatch.setattr(devices_router, name, value)
    runtime = SimpleNamespace(agent_sessions=presence)

    async def drain():
        return [line async for line in devices_router._reinstall_stream(runtime, "dev")]

    return asyncio.run(drain())


def test_reinstall_prints_the_record_the_returning_agent_carries(monkeypatch):
    old, new = Session(), Session()
    lines = drain_reinstall(
        monkeypatch, Presence([(old, None), (old, None), (old, None), (new, RECORD)])
    )

    assert lines[0] == "reinstall launched\n"
    assert "agent 9.9.9 reconnected\n" in lines
    assert "Setting up neutrino-agent (0.1.0)\n" in "".join(lines)
    assert lines[-1] == "[exit 0]\n"


def test_a_failed_install_is_reported_on_the_socket_that_stayed(monkeypatch):
    old = Session()
    failed = dict(RECORD, exit_code=1, output="dpkg: error: broken\n")
    lines = drain_reinstall(
        monkeypatch, Presence([(old, None), (old, None), (old, failed)])
    )

    assert "agent 9.9.9 reconnected\n" not in lines
    assert "dpkg: error: broken\n" in lines
    assert lines[-1] == '{"code": "reinstall_failed", "params": {"exit_code": 1}}\n'


def test_a_stale_record_from_before_the_launch_is_not_the_answer(monkeypatch):
    old, new = Session(), Session()
    lines = drain_reinstall(
        monkeypatch,
        Presence([(old, RECORD), (old, RECORD), (new, RECORD)]),
        WEB_REINSTALL_REPORT_TIMEOUT_S=0.0,
    )

    assert lines[-1] == "reinstalled, no installer record from this agent\n"


def test_an_old_agent_that_returns_without_a_record_is_named(monkeypatch):
    old, new = Session(), Session()
    lines = drain_reinstall(
        monkeypatch,
        Presence([(old, None), (old, None), (new, None)]),
        WEB_REINSTALL_REPORT_TIMEOUT_S=0.0,
    )

    assert "agent 9.9.9 reconnected\n" in lines
    assert lines[-1] == "reinstalled, no installer record from this agent\n"


def test_nothing_reported_in_time_is_typed(monkeypatch):
    old = Session()
    lines = drain_reinstall(
        monkeypatch, Presence([(old, None)]), WEB_REINSTALL_RETURN_TIMEOUT_S=0.0
    )

    assert lines[-1] == '{"code": "reinstall_not_reported", "params": {}}\n'


# --- the box: forgetting, renaming, the remote desktop, the enrolment link ---


@pytest.fixture
def box_api(monkeypatch):
    client, runtime = device_box(monkeypatch, devices_router)
    monkeypatch.setattr(devices_router, "certificate_fingerprint", lambda: FINGERPRINT)
    with client:
        yield client, runtime


def test_forgetting_a_device_drops_what_was_queued_for_it(box_api, monkeypatch):
    """What is held for a forgotten device goes with its row."""
    client, runtime = box_api
    monkeypatch.setattr(BoxRegistry, "forget", lambda self, mac: None, raising=False)
    runtime.pending[DEVICE] = ["shutdown"]
    runtime.device_modules[DEVICE] = {"fakedesk": {"state": "installed"}}

    removed = client.post(f"{DEVICE_PATH}/remove", json={"device_id": DEVICE})

    assert removed.status_code == 200

    assert runtime.pending == {}
    assert runtime.device_modules == {}


@pytest.mark.parametrize("device_id", ["hello", "scan:nonsense", "", "12345"])
def test_an_id_no_device_has_is_refused(box_api, device_id):
    client, _ = box_api

    response = client.post(SET_PATH, json={"device_id": device_id, "name": "nonsense"})

    assert response.status_code == 404


def test_renaming_a_scan_row_answers_the_device_it_became(box_api):
    client, _ = box_api

    answer = client.post(
        SET_PATH, json={"device_id": "scan:aa:bb:cc:dd:ee:09", "name": "printer"}
    )

    assert answer.status_code == 200
    assert answer.json()["id"] == "adopted-id"
    assert answer.json()["name"] == "printer"
    assert answer.json()["link_mac"] == "aa:bb:cc:dd:ee:09"


def test_an_unknown_remote_desktop_product_is_refused_at_once(box_api):
    """`set_password_stream` is an async generator, so calling it runs none of
    its body: the refusal it documents used to surface minutes later as a
    failed task rather than as this answer."""
    client, _ = box_api
    BoxRegistry.device.ssh = {"host": "10.0.0.5", "username": "me"}

    response = client.post(
        f"{DEVICE_PATH}/remote_desktop/password/set",
        json={
            "device_id": DEVICE,
            "product": "anydsk",
            "password": "hunter2hunter2",  # scan: allow
        },
    )

    assert response.status_code == 400


def test_renaming_a_device_keeps_its_monitor_alive(box_api):
    """The page redraws the tile from this answer. Built with no metrics, it
    reads as a machine that went offline the moment somebody renamed it."""
    client, runtime = box_api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_metrics[DEVICE] = {"cpu_percent": 12.5, "memory_percent": 40.0}

    answer = client.post(SET_PATH, json={"device_id": DEVICE, "name": "renamed"}).json()

    assert answer["name"] == "renamed"
    assert answer["client"]["cpu_percent"] == 12.5


def test_a_link_that_cannot_be_built_generates_no_ticket(box_api, monkeypatch):
    """The ticket is a join secret. One nobody was ever shown is one lying
    around until the panel restarts."""
    client, runtime = box_api
    monkeypatch.setattr(devices_router, "_agent_urls", lambda runtime: [])

    response = client.post(ENROLLMENT_PATH, json={"name": "laptop"})

    assert response.status_code == 400
    assert runtime.enrollments == {}


def test_a_link_generated_for_a_device_binds_to_that_device(box_api, monkeypatch):
    """The per-device link on an unmanaged card: the machine that pastes it
    joins as the device already on the page."""
    client, runtime = box_api
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["http://192.168.8.1:8080"]
    )

    response = client.post(
        ENROLLMENT_PATH,
        json={"name": "xenode", "device_id": DEVICE},
    )

    assert response.status_code == 200
    ticket = runtime.enrollments[response.json()["token"]]
    assert ticket["device_id"] == DEVICE
    assert ticket["name"] == "xenode"


def test_a_link_generated_for_a_scan_row_stores_it_and_binds_to_the_new_row(
    box_api, monkeypatch
):
    client, runtime = box_api
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["http://192.168.8.1:8080"]
    )

    response = client.post(
        ENROLLMENT_PATH,
        json={"name": "", "device_id": "scan:aa:bb:cc:dd:ee:09"},
    )

    assert response.status_code == 200
    ticket = runtime.enrollments[response.json()["token"]]
    assert ticket["device_id"] == "adopted-id"


def test_a_link_for_an_unknown_device_is_refused_typed(box_api, monkeypatch):
    client, runtime = box_api
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["http://192.168.8.1:8080"]
    )

    response = client.post(ENROLLMENT_PATH, json={"name": "", "device_id": "nonsense"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "device_unknown"
    assert runtime.enrollments == {}


def test_the_link_is_one_shell_safe_token(box_api, monkeypatch):
    """base64url end to end: no character a shell splits or a URL escapes,
    and the payload decodes to every address plus the ticket."""
    client, runtime = box_api
    monkeypatch.setattr(
        devices_router,
        "_agent_urls",
        lambda runtime: ["http://192.168.8.1:8080", "http://10.0.0.1:8080"],
    )

    answer = client.post(ENROLLMENT_PATH, json={"name": "laptop"}).json()

    link = answer["link"]
    assert link.startswith("neutrino://enroll/")
    payload_text = link.removeprefix("neutrino://enroll/")
    assert not any(character in payload_text for character in "?&%#;|<> '\"=")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    assert payload["urls"] == ["http://192.168.8.1:8080", "http://10.0.0.1:8080"]
    assert payload["token"] == answer["token"]
    assert payload["fp"] == FINGERPRINT
    assert payload["role"] == "agent"


def test_a_lapsed_ticket_is_swept_when_the_next_one_is_generated(box_api, monkeypatch):
    client, runtime = box_api
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["http://192.168.8.1:8080"]
    )
    runtime.enrollments["stale"] = {"expires_at": 0.0}

    response = client.post(ENROLLMENT_PATH, json={"name": "laptop"})

    assert response.status_code == 200
    assert "stale" not in runtime.enrollments
    assert len(runtime.enrollments) == 1
