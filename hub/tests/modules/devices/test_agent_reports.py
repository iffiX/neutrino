"""What the hub keeps of a hello, a report, and a socket ending.

A hello and a report land in the runtime's memory, keyed by the device's
id. The address is the report's ``network.link.address``, the socket's peer
standing in and being recorded when the report names none; the MAC the
socket runs on is noted on the device's row. The desktop share is recorded
against the device the token resolved to, at the address the hub holds, and
withdrawn when the machine stops or its socket ends.
"""

from types import SimpleNamespace

import pytest

from neutrino_hub.modules.devices import agent_reports
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import DeviceRegistry, ManagedDevice
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from tests.conftest import StubDesiredStates, StubPublishedServices

DEVICE = "device-one"
LINK_MAC = "aa:bb:cc:dd:ee:ff"


class FakeRuntime:
    def __init__(self, lans=()):
        self.device_metrics = {}
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_accounts = {}
        self.device_interfaces = {}
        self.device_address = {}
        self.device_hub_host = {}
        self.device_last_error = {}
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
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so the row a report notes on is here."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def box(config_dir):
    return (
        FakeRuntime(lans=[("192.168.100.1", "192.168.100.0/24")]),
        ManagedDevice(id=DEVICE, name="testbox"),
    )


def hello(**fields) -> dict:
    body = {
        "type": "hello",
        "token": "t",
        "client_version": "0.2.0",
        "wire": 5,
        "hostname": "box",
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
        "accounts": ["alice"],
        "state_hash": "",
    }
    body.update(fields)
    return body


def network(address: str = "192.168.100.12", mac: str = LINK_MAC) -> dict:
    """The ``network`` section a report carries."""
    return {
        "link": {"interface": "enp1s0", "mac": mac, "address": address},
        "interfaces": [
            {"name": "enp1s0", "mac": mac, "addresses": [address]},
            {
                "name": "docker0",
                "mac": "02:42:00:00:00:01",
                "addresses": ["172.17.0.1"],
            },
        ],
    }


def report(**fields) -> dict:
    body = {
        "type": "report",
        "metrics": {"cpu_percent": 4.0},
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
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

    assert runtime.device_platform[DEVICE]["arch"] == "amd64"
    assert runtime.device_hostname[DEVICE] == "box"
    assert runtime.device_accounts[DEVICE] == ["alice"]
    assert runtime.device_address[DEVICE] == "192.168.100.7"
    assert runtime.device_hub_host[DEVICE] == "192.168.100.1"


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
    assert runtime.device_hub_host[DEVICE] == "192.168.122.92"


# --- the address ---


def test_the_address_is_the_one_the_socket_leaves_by():
    assert (
        agent_reports.link_address(network("10.9.0.2"), "192.168.100.7") == "10.9.0.2"
    )


def test_the_peer_stands_in_when_the_report_names_no_address():
    assert agent_reports.link_address({}, "192.168.100.7") == "192.168.100.7"
    assert agent_reports.link_address(network(address=""), "10.9.0.2") == "10.9.0.2"
    assert agent_reports.link_address({"link": "nonsense"}, "10.9.0.2") == "10.9.0.2"


def test_a_report_records_the_link_address_and_the_interfaces(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"

    agent_reports.record_report(runtime, device, report(network=network("10.9.0.2")))

    assert runtime.device_address[DEVICE] == "10.9.0.2"
    assert [entry["name"] for entry in runtime.device_interfaces[DEVICE]] == [
        "enp1s0",
        "docker0",
    ]


def test_a_report_without_a_network_keeps_the_recorded_peer(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"

    agent_reports.record_report(runtime, device, report())

    assert runtime.device_address[DEVICE] == "192.168.100.7"
    assert DEVICE not in runtime.device_interfaces


# --- the row ---


def test_a_report_notes_the_link_mac_on_the_stored_row(box):
    runtime, device = box
    stored = DeviceRegistry().create("testbox")

    agent_reports.record_report(runtime, stored, report(network=network()))

    row = DeviceRegistry().get(stored.id)
    assert row.mac_addresses == [LINK_MAC]
    assert row.link_mac == LINK_MAC


def test_a_report_naming_no_link_mac_writes_nothing(box, config_dir):
    runtime, device = box
    stored = DeviceRegistry().create("testbox")
    path = config_dir / "devices" / "devices.json"
    before = path.read_text()

    agent_reports.record_report(runtime, stored, report(network=network(mac="")))
    agent_reports.record_report(runtime, stored, report())

    assert path.read_text() == before


# --- report ---


def test_a_report_lands_in_memory(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"

    agent_reports.record_report(
        runtime,
        device,
        report(last_error={"code": "hub_unreachable", "params": {"detail": "x"}}),
    )

    assert runtime.device_metrics[DEVICE] == {"cpu_percent": 4.0}
    assert runtime.device_modules[DEVICE] == {"rustdesk": {"state": "installed"}}
    assert runtime.device_accounts[DEVICE] == ["alice", "bob"]
    assert runtime.device_last_error[DEVICE] == {
        "code": "hub_unreachable",
        "params": {"detail": "x"},
    }


def test_a_report_without_an_error_clears_the_stored_one(box):
    runtime, device = box
    runtime.device_last_error[DEVICE] = {"code": "mount_failed", "params": {}}

    agent_reports.record_report(runtime, device, report())

    assert DEVICE not in runtime.device_last_error


def test_a_report_settles_a_standing_failure_when_the_software_turned_up(box):
    runtime, device = box
    runtime.agent_module_orders._failures[(DEVICE, "rustdesk")] = "old-order"

    agent_reports.record_report(runtime, device, report())

    assert runtime.agent_module_orders.failure_for(DEVICE, "rustdesk") is None


def test_a_report_declaring_a_share_records_it_at_the_held_address(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"
    runtime.device_hostname[DEVICE] = "box"

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
    assert (share.device_id, share.share_id, share.host, share.port) == (
        DEVICE,
        "s1",
        "192.168.100.7",
        21118,
    )
    assert share.hostname == "box"
    assert (share.account, share.connected_count) == ("pat", 2)
    assert runtime.published_services.refreshes == 1


def test_a_share_that_names_no_account_or_viewers_carries_neither(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"

    agent_reports.record_report(
        runtime, device, report(rdp={"is_shared": True, "share_id": "s1"})
    )

    (share,) = runtime.device_shares.live()
    assert (share.account, share.connected_count) == ("", 0)


# --- the seat password ---


def test_a_machine_reporting_the_host_installed_is_given_a_seat_password(box):
    runtime, device = box

    agent_reports.record_report(runtime, device, report())

    assert runtime.desired_states.ensured == [DEVICE]


def test_a_machine_whose_package_lacks_the_host_is_given_none(box):
    runtime, device = box

    agent_reports.record_report(
        runtime, device, report(modules={"rustdesk": {"state": "absent"}})
    )
    agent_reports.record_report(runtime, device, report(modules={}))

    assert runtime.desired_states.ensured == []


def test_a_report_that_stops_sharing_withdraws_the_share(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"
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
    runtime.device_address[DEVICE] = "192.168.100.7"
    agent_reports.record_report(
        runtime, device, report(rdp={"is_shared": True, "share_id": "s1"})
    )

    agent_reports.record_offline(runtime, device)

    assert runtime.device_shares.live() == []
