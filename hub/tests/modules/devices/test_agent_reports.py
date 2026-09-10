"""What the hub keeps of a hello, a report, and a socket ending.

A hello and a report land in the runtime's memory, and the seat password is
the one thing either writes. The address is the one on the machine's
identity MAC, the peer standing in when nothing matches; the desktop share
is recorded against the device the token resolved to, at the address the
hub holds, and withdrawn when the machine stops or its socket ends.
"""

from types import SimpleNamespace

import pytest

from neutrino_hub.modules.devices import agent_reports
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import ManagedDevice
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from tests.conftest import StubDesiredStates, StubPublishedServices

MAC = "aa:bb:cc:dd:ee:ff"


class FakeRuntime:
    def __init__(self, lans=()):
        self.client_metrics = {}
        self.client_modules = {}
        self.client_platform = {}
        self.client_hostname = {}
        self.client_accounts = {}
        self.client_address = {}
        self.client_device_host = {}
        self.client_last_error = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.desired_states = StubDesiredStates()
        self.agent_module_orders = AgentModuleController(
            cache=None, locks=DeviceInstallLocks()
        )
        self.agent_sessions = AgentSessionRegistry()
        self.pushed: list = []
        self._lans = [
            SimpleNamespace(lan=SimpleNamespace(address=address, cidr=cidr))
            for address, cidr in lans
        ]

    def network(self):
        return SimpleNamespace(lan_interfaces=self._lans)

    def push_desired_state(self, key):
        self.pushed.append(key)


@pytest.fixture
def box():
    return (
        FakeRuntime(lans=[("192.168.100.1", "192.168.100.0/24")]),
        ManagedDevice(mac_address=MAC, name="testbox"),
    )


def hello(**fields) -> dict:
    body = {
        "type": "hello",
        "token": "t",
        "client_version": "0.2.0",
        "wire": 5,
        "hostname": "box",
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        "addresses": [],
        "accounts": ["alice"],
        "state_hash": "",
    }
    body.update(fields)
    return body


def report(**fields) -> dict:
    body = {
        "type": "report",
        "metrics": {"cpu_percent": 4.0},
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        "addresses": [],
        "accounts": ["alice", "bob"],
        "modules": {"rustdesk": {"state": "installed"}},
        "state_hash": "",
        "state_error": None,
        "rdp": {"is_shared": False},
        "last_error": None,
    }
    body.update(fields)
    return body


# --- hello ---


def test_a_hello_records_the_machine_in_memory(box):
    runtime, device = box

    agent_reports.record_hello(
        runtime,
        device,
        hello(),
        peer_host="192.168.100.7",
        reached_host="192.168.100.1",
    )

    assert runtime.client_platform[MAC]["arch"] == "amd64"
    assert runtime.client_hostname[MAC] == "box"
    assert runtime.client_accounts[MAC] == ["alice"]
    assert runtime.client_address[MAC] == "192.168.100.7"
    assert runtime.client_device_host[MAC] == "192.168.100.1"


def test_the_address_is_the_one_on_the_identity_mac(box):
    runtime, device = box

    agent_reports.record_hello(
        runtime,
        device,
        hello(
            addresses=[
                {"mac": "11:22:33:44:55:66", "address": "10.9.0.2"},
                {"mac": MAC.upper(), "address": "192.168.100.12"},
            ]
        ),
        peer_host="10.9.0.2",
        reached_host="",
    )

    assert runtime.client_address[MAC] == "192.168.100.12"


def test_the_device_host_is_the_address_it_reached_off_any_served_lan(box):
    runtime, device = box

    agent_reports.record_hello(
        runtime,
        device,
        hello(),
        peer_host="100.64.0.9",
        reached_host="192.168.122.92",
    )

    # Off every served LAN, the address the machine connected to is the truth.
    assert runtime.client_device_host[MAC] == "192.168.122.92"


# --- report ---


def test_a_report_lands_in_memory(box):
    runtime, device = box
    runtime.client_address[MAC] = "192.168.100.7"

    agent_reports.record_report(
        runtime,
        device,
        report(last_error={"code": "hub_unreachable", "params": {"detail": "x"}}),
    )

    assert runtime.client_metrics[MAC] == {"cpu_percent": 4.0}
    assert runtime.client_modules[MAC] == {"rustdesk": {"state": "installed"}}
    assert runtime.client_accounts[MAC] == ["alice", "bob"]
    assert runtime.client_last_error[MAC] == {
        "code": "hub_unreachable",
        "params": {"detail": "x"},
    }


def test_a_report_without_an_error_clears_the_stored_one(box):
    runtime, device = box
    runtime.client_last_error[MAC] = {"code": "mount_failed", "params": {}}

    agent_reports.record_report(runtime, device, report())

    assert MAC not in runtime.client_last_error


def test_a_report_settles_a_standing_failure_when_the_software_turned_up(box):
    runtime, device = box
    runtime.agent_module_orders._failures[(MAC, "rustdesk")] = "old-order"

    agent_reports.record_report(runtime, device, report())

    assert runtime.agent_module_orders.failure_for(MAC, "rustdesk") is None


def test_a_report_declaring_a_share_records_it_at_the_held_address(box):
    runtime, device = box
    runtime.client_address[MAC] = "192.168.100.7"
    runtime.client_hostname[MAC] = "box"

    agent_reports.record_report(
        runtime,
        device,
        report(
            rdp={
                "is_shared": True,
                "share_id": "s1",
                "port": 21118,
                "account": "pat",
                "connected_count": 2,
            }
        ),
    )

    (share,) = runtime.device_shares.live()
    assert (share.mac_address, share.share_id, share.host, share.port) == (
        MAC,
        "s1",
        "192.168.100.7",
        21118,
    )
    assert share.hostname == "box"
    assert (share.account, share.connected_count) == ("pat", 2)
    assert runtime.published_services.refreshes == 1


def test_a_share_that_names_no_account_or_viewers_carries_neither(box):
    runtime, device = box
    runtime.client_address[MAC] = "192.168.100.7"

    agent_reports.record_report(
        runtime, device, report(rdp={"is_shared": True, "share_id": "s1"})
    )

    (share,) = runtime.device_shares.live()
    assert (share.account, share.connected_count) == ("", 0)


# --- the seat password ---


def test_a_machine_reporting_the_host_installed_is_given_a_seat_password(box):
    runtime, device = box

    agent_reports.record_report(runtime, device, report())

    assert runtime.desired_states.ensured == [MAC]


def test_a_machine_whose_package_lacks_the_host_is_given_none(box):
    runtime, device = box

    agent_reports.record_report(
        runtime, device, report(modules={"rustdesk": {"state": "absent"}})
    )
    agent_reports.record_report(runtime, device, report(modules={}))

    assert runtime.desired_states.ensured == []


def test_a_report_that_stops_sharing_withdraws_the_share(box):
    runtime, device = box
    runtime.client_address[MAC] = "192.168.100.7"
    agent_reports.record_report(
        runtime, device, report(rdp={"is_shared": True, "share_id": "s1"})
    )

    agent_reports.record_report(runtime, device, report(rdp={"is_shared": False}))

    assert runtime.device_shares.live() == []
    assert runtime.published_services.refreshes == 2


def test_a_share_with_no_address_to_pair_it_with_is_not_declared(box):
    runtime, device = box

    agent_reports.record_report(
        runtime, device, report(rdp={"is_shared": True, "share_id": "s1"})
    )

    assert runtime.device_shares.live() == []


# --- the socket ending ---


def test_a_socket_ending_withdraws_the_share(box):
    runtime, device = box
    runtime.client_address[MAC] = "192.168.100.7"
    agent_reports.record_report(
        runtime, device, report(rdp={"is_shared": True, "share_id": "s1"})
    )

    agent_reports.record_offline(runtime, device)

    assert runtime.device_shares.live() == []
