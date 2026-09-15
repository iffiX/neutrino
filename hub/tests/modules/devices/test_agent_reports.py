"""What the hub keeps of a hello, a report, and a socket ending.

A hello and a report land in the runtime's memory, keyed by the device's
id. A report is read by its sections: ``machine`` for the hostname, the
platform, the accounts and the metrics; ``network`` for the link address,
with the socket's peer standing in and being recorded when the report
names none, and the MAC the socket runs on, noted on the device's row;
``modules``, where a module the hub wanted absent and the machine now
reports absent is dropped from the device's file and the state pushed
again; ``desktop`` and ``error``. The desktop share is recorded
against the device the token resolved to, at the address the hub holds,
and withdrawn when the machine stops or its socket ends.
"""

from types import SimpleNamespace

import pytest

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_AGENT
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.devices import agent_reports
from neutrino_hub.modules.devices.registry import DeviceRegistry, ManagedDevice
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from tests.conftest import StubDesiredStates, StubPublishedServices

DEVICE = "device-one"
LINK_MAC = "aa:bb:cc:dd:ee:ff"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}


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
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
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


def report(**sections) -> dict:
    body = {
        "type": "report",
        "state_hash": "",
        "machine": {
            "hostname": "box",
            "platform": PLATFORM,
            "accounts": ["alice", "bob"],
            "metrics": {"cpu_percent": 4.0},
        },
        "modules": {"rustdesk": {"state": "installed", "is_active": False}},
        "desktop": {"is_shared": False},
        "error": None,
    }
    body.update(sections)
    return body


# --- hello ---


def test_a_hello_records_the_name_and_the_peer_as_the_address(box):
    runtime, device = box

    agent_reports.record_hello(
        runtime,
        device,
        name="box",
        peer_host="192.168.100.7",
        reached_host="192.168.100.1",
    )

    assert runtime.device_hostname[DEVICE] == "box"
    assert runtime.device_address[DEVICE] == "192.168.100.7"
    assert runtime.device_hub_host[DEVICE] == "192.168.100.1"


def test_the_device_host_is_the_address_it_reached_off_any_served_lan(box):
    runtime, device = box

    agent_reports.record_hello(
        runtime,
        device,
        name="box",
        peer_host="100.64.0.9",
        reached_host="192.168.122.92",
    )

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

    agent_reports.record_report(
        runtime, device, report(network=network("10.9.0.2")), peer_host="192.168.9.9"
    )

    assert runtime.device_address[DEVICE] == "10.9.0.2"
    assert [entry["name"] for entry in runtime.device_interfaces[DEVICE]] == [
        "enp1s0",
        "docker0",
    ]


def test_a_report_naming_no_address_records_the_peer(box):
    runtime, device = box

    agent_reports.record_report(runtime, device, report(), peer_host="192.168.100.7")

    assert runtime.device_address[DEVICE] == "192.168.100.7"
    assert DEVICE not in runtime.device_interfaces


def test_a_report_without_a_network_keeps_the_recorded_address(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"

    agent_reports.record_report(runtime, device, report())

    assert runtime.device_address[DEVICE] == "192.168.100.7"


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


# --- the sections ---


def test_a_report_lands_in_memory_by_section(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"

    agent_reports.record_report(
        runtime,
        device,
        report(error={"code": "hub_unreachable", "params": {"detail": "x"}}),
    )

    assert runtime.device_hostname[DEVICE] == "box"
    assert runtime.device_platform[DEVICE] == PLATFORM
    assert runtime.device_metrics[DEVICE] == {"cpu_percent": 4.0}
    assert runtime.device_modules[DEVICE] == {
        "rustdesk": {"state": "installed", "is_active": False}
    }
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


def test_a_module_wanted_absent_and_reported_absent_is_dropped_and_the_state_pushed(
    box,
):
    runtime, device = box
    runtime.desired_states.wants[(DEVICE, "samba")] = "absent"
    runtime.desired_states.wants[(DEVICE, "gitea")] = "absent"
    runtime.desired_states.wants[(DEVICE, "podman")] = "running"

    agent_reports.record_report(
        runtime,
        device,
        report(
            modules={
                "samba": {"state": "absent"},
                "gitea": {"state": "uninstalling"},
                "podman": {"state": "absent"},
            }
        ),
    )

    assert runtime.desired_states.forgotten == [(DEVICE, "samba")]
    assert runtime.desired_states.want_of(DEVICE, "gitea") == "absent"
    assert runtime.desired_states.want_of(DEVICE, "podman") == "running"
    assert runtime.pushed == [DEVICE]


def test_a_report_naming_nothing_absent_that_the_hub_wants_absent_pushes_nothing(
    box,
):
    runtime, device = box
    runtime.desired_states.wants[(DEVICE, "samba")] = "running"

    agent_reports.record_report(
        runtime, device, report(modules={"samba": {"state": "absent"}})
    )

    assert runtime.desired_states.forgotten == []
    assert runtime.pushed == []


def test_a_report_declaring_a_share_records_it_at_the_held_address(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"
    runtime.device_hostname[DEVICE] = "box"

    agent_reports.record_report(
        runtime,
        device,
        report(
            desktop={
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
        runtime, device, report(desktop={"is_shared": True, "share_id": "s1"})
    )

    (share,) = runtime.device_shares.live()
    assert (share.account, share.connected_count) == ("", 0)


# --- the seat password ---


@pytest.mark.parametrize("state", ["installed", "stopped", "running"])
def test_a_machine_with_the_host_present_is_given_a_seat_password(box, state):
    runtime, device = box

    agent_reports.record_report(
        runtime, device, report(modules={"rustdesk": {"state": state}})
    )

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
        runtime, device, report(desktop={"is_shared": True, "share_id": "s1"})
    )

    agent_reports.record_report(runtime, device, report(desktop={"is_shared": False}))

    assert runtime.device_shares.live() == []
    assert runtime.published_services.refreshes == 2


def test_a_share_with_no_address_to_pair_it_with_is_not_declared(box):
    runtime, device = box

    agent_reports.record_report(
        runtime, device, report(desktop={"is_shared": True, "share_id": "s1"})
    )

    assert runtime.device_shares.live() == []


# --- the socket ending ---


def test_a_socket_ending_withdraws_the_share(box):
    runtime, device = box
    runtime.device_address[DEVICE] = "192.168.100.7"
    agent_reports.record_report(
        runtime, device, report(desktop={"is_shared": True, "share_id": "s1"})
    )

    agent_reports.record_offline(runtime, device)

    assert runtime.device_shares.live() == []
