"""Counting the devices on the gateway's own networks, and the LAN scan.

A scan covers the hub's exposed IPv4 segments in every mode, a network of at
most 256 addresses whole and of a larger one the /24 holding the hub's
address, and reads the IPv4 neighbour table alone.
"""

import ipaddress

from neutrino_hub.modules.devices import lan_scan
from neutrino_hub.modules.devices.lan_scan import (
    LanScanner,
    LanScanRange,
    count_lan_neighbours,
    lan_scan_ranges,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from tests.conftest import lan_entry, network_config, wan_entry

ARP_TABLE = """IP address       HW type     Flags       HW address            Mask     Device
192.168.100.2    0x1         0x2         02:00:5e:76:21:30     *        enp1s0
192.168.100.7    0x1         0x2         aa:bb:cc:dd:ee:ff     *        enp1s0
192.168.101.9    0x1         0x2         11:22:33:44:55:66     *        wlp3s0
192.168.100.9    0x1         0x0         00:00:00:00:00:00     *        enp1s0
198.51.100.129   0x1         0x2         02:00:5e:4c:c2:00     *        enp2s0
"""


def write_table(tmp_path, monkeypatch, text=ARP_TABLE):
    path = tmp_path / "arp"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(lan_scan, "PROC_NET_ARP", path)


def test_only_the_served_networks_are_counted(tmp_path, monkeypatch):
    """A neighbour on the uplink is the upstream network's, not the gateway's."""
    write_table(tmp_path, monkeypatch)

    assert count_lan_neighbours(["enp1s0"]) == 2


def test_every_served_interface_contributes(tmp_path, monkeypatch):
    write_table(tmp_path, monkeypatch)

    assert count_lan_neighbours(["enp1s0", "wlp3s0"]) == 3


def test_unresolved_entries_are_not_devices(tmp_path, monkeypatch):
    """An incomplete entry is an unanswered probe, not a machine that is there."""
    write_table(tmp_path, monkeypatch)

    assert count_lan_neighbours(["enp1s0"]) == 2


def test_a_box_serving_nothing_counts_nothing(tmp_path, monkeypatch):
    write_table(tmp_path, monkeypatch)

    assert count_lan_neighbours([]) == 0


def test_a_missing_table_is_not_an_error(tmp_path, monkeypatch):
    """This is read on every statistics frame; it must never be what breaks one."""
    monkeypatch.setattr(lan_scan, "PROC_NET_ARP", tmp_path / "absent")

    assert count_lan_neighbours(["enp1s0"]) == 0


def test_a_malformed_row_is_skipped_rather_than_fatal(tmp_path, monkeypatch):
    write_table(
        tmp_path,
        monkeypatch,
        "IP address HW type Flags HW address Mask Device\n"
        "garbage\n"
        "192.168.100.2 0x1 notahex 02:00:5e:76:21:30 * enp1s0\n"
        "192.168.100.3 0x1 0x2 02:00:5e:76:21:31 * enp1s0\n",
    )

    assert count_lan_neighbours(["enp1s0"]) == 1


# --- the ranges: the exposed IPv4 segments, a large network cut to its /24 ---


def test_a_network_of_at_most_256_addresses_is_covered_whole():
    ranges = lan_scan_ranges(
        [("enp1s0", "192.168.100.1/24"), ("enp1s0", "10.9.8.130/25")]
    )

    assert ranges == [
        LanScanRange(
            "enp1s0", ipaddress.ip_network("192.168.100.0/24"), "192.168.100.1"
        ),
        LanScanRange("enp1s0", ipaddress.ip_network("10.9.8.128/25"), "10.9.8.130"),
    ]


def test_a_larger_network_is_cut_to_the_24_that_holds_the_hubs_address():
    (covered,) = lan_scan_ranges([("enp1s0", "10.20.5.7/16")])

    assert covered.network == ipaddress.ip_network("10.20.5.0/24")
    assert covered.source_address == "10.20.5.7"


def test_no_ipv6_network_is_covered():
    assert (
        lan_scan_ranges([("enp1s0", "fd00:100::1/64"), ("enp1s0", "fe80::1/64")]) == []
    )


def test_a_network_is_covered_once_per_device():
    ranges = lan_scan_ranges(
        [
            ("enp1s0", "10.20.5.7/16"),
            ("enp1s0", "10.20.5.8/16"),
            ("wlp3s0", "10.20.5.9/16"),
        ]
    )

    assert [(covered.device, covered.source_address) for covered in ranges] == [
        ("enp1s0", "10.20.5.7"),
        ("wlp3s0", "10.20.5.9"),
    ]


# --- the sweep and the neighbour table, in every mode ---

NEIGHBOURS = """192.168.100.20 lladdr aa:bb:cc:00:00:01 REACHABLE
192.168.100.21 lladdr aa:bb:cc:00:00:02 STALE
192.168.100.22 lladdr aa:bb:cc:00:00:03 FAILED
192.168.100.23 INCOMPLETE
192.168.100.24 lladdr aa:bb:cc:00:00:04 INCOMPLETE
"""
SERVER_HELD = {
    "enp3s0": ["192.168.1.54/24", "10.20.5.7/16", "fd00:1::54/64", "fe80::54/64"],
    "enp5s0": ["172.16.9.2/24"],
}


class _Output:
    def __init__(self, stdout: str):
        self.is_success = True
        self.stdout = stdout


class _Commands:
    """``ip -4 neigh`` and ``arp-scan`` as a scan runs them, each one recorded."""

    def __init__(self, *, neighbours: str = "", answers: str = ""):
        self.neighbours = neighbours
        self.answers = answers
        self.commands: list = []

    def __call__(self, command: list, **kwargs) -> _Output:
        self.commands.append(list(command))
        return _Output(self.neighbours if command[0] == "ip" else self.answers)


def served():
    """A router hub serving one network, its uplink closed."""
    return network_config(
        wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1"), overlays=[]
    )


def server(*, overlays: list):
    """A server hub with one interface exposed and one closed."""
    return network_config(
        {"name": "enp3s0", "role": "disabled", "is_exposed": True},
        {"name": "enp5s0", "role": "disabled", "is_exposed": False},
        overlays=overlays,
        mode="server",
    )


def nothing_held() -> dict:
    return {}


def scanned(monkeypatch) -> dict:
    monkeypatch.setattr(lan_scan, "run", _Commands(neighbours=NEIGHBOURS))
    found = LanScanner(network=served(), read_held=nothing_held).scan(is_active=False)
    return {device.ipv4_address: device for device in found}


def test_a_router_sweeps_its_served_network_and_not_its_closed_uplink(monkeypatch):
    commands = _Commands()
    monkeypatch.setattr(lan_scan, "run", commands)

    LanScanner(network=served(), read_held=nothing_held).scan()

    assert commands.commands == [
        ["ip", "-4", "neigh", "show", "dev", "enp1s0"],
        [
            "arp-scan",
            "--interface=enp1s0",
            "--arpspa=192.168.100.1",
            "192.168.100.0/24",
        ],
    ]


def test_a_server_sweeps_each_exposed_ipv4_network_and_nothing_else(monkeypatch):
    """The /16 is cut to the /24 holding the hub's address, the IPv6 networks
    and the closed interface are not swept, and an overlay never is."""
    network = server(
        overlays=[{"provider": "easytier", "is_exposed": True, "is_enabled": True}]
    )
    (overlay,) = network.exposed_overlay_device_names
    held = {**SERVER_HELD, overlay: ["10.126.126.1/24"]}
    commands = _Commands()
    monkeypatch.setattr(lan_scan, "run", commands)

    LanScanner(network=network, read_held=held.copy).scan()

    assert commands.commands == [
        ["ip", "-4", "neigh", "show", "dev", "enp3s0"],
        ["arp-scan", "--interface=enp3s0", "--arpspa=192.168.1.54", "192.168.1.0/24"],
        ["arp-scan", "--interface=enp3s0", "--arpspa=10.20.5.7", "10.20.5.0/24"],
    ]


def test_a_neighbour_outside_every_range_is_not_listed(monkeypatch):
    """The kernel remembers a neighbour across the whole /16; the scan lists the
    /24 it covers."""
    commands = _Commands(
        neighbours="10.20.5.40 lladdr aa:bb:cc:00:00:05 REACHABLE\n"
        "10.20.9.9 lladdr aa:bb:cc:00:00:06 REACHABLE\n"
    )
    monkeypatch.setattr(lan_scan, "run", commands)

    found = LanScanner(network=server(overlays=[]), read_held=SERVER_HELD.copy).scan(
        is_active=False
    )

    assert [device.ipv4_address for device in found] == ["10.20.5.40"]


def test_a_device_answering_the_sweep_is_online(monkeypatch):
    commands = _Commands(answers="192.168.1.60\taa:bb:cc:00:00:07\tA Vendor\n")
    monkeypatch.setattr(lan_scan, "run", commands)

    found = LanScanner(network=server(overlays=[]), read_held=SERVER_HELD.copy).scan()

    assert [(device.ipv4_address, device.is_online) for device in found] == [
        ("192.168.1.60", True)
    ]


def test_nothing_exposed_scans_nothing(monkeypatch):
    commands = _Commands()
    monkeypatch.setattr(lan_scan, "run", commands)
    closed = network_config(
        {"name": "enp3s0", "role": "disabled", "is_exposed": False},
        overlays=[],
        mode="server",
    )

    assert LanScanner(network=closed, read_held=SERVER_HELD.copy).scan() == []
    assert commands.commands == []


def test_a_stale_neighbour_is_kept_as_a_neighbour_that_is_not_online(monkeypatch):
    """A phone asleep on the Wi-Fi goes STALE within a minute, and a topology
    that dropped it the moment it did lost every unnamed device on the page."""
    found = scanned(monkeypatch)

    assert found["192.168.100.21"].is_neighbour is True
    assert found["192.168.100.21"].is_online is False
    assert found["192.168.100.20"].is_neighbour is True
    assert found["192.168.100.20"].is_online is True


def test_a_failed_or_incomplete_neighbour_is_gone(monkeypatch):
    found = scanned(monkeypatch)

    assert set(found) == {"192.168.100.20", "192.168.100.21"}


# The same machine as `ip neigh` lists it with no family: its IPv4 neighbour
# first, then its link-local IPv6 one under the same MAC.
NEIGHBOURS_IPV4 = "192.168.100.30 lladdr 52:54:00:6d:07:8e REACHABLE\n"
NEIGHBOURS_IPV6 = "fe80::5054:ff:fe6d:78e lladdr 52:54:00:6d:07:8e REACHABLE\n"


class _IpNeigh:
    """``ip neigh``, listing the IPv6 neighbours too unless ``-4`` is given."""

    def __init__(self, command: list, **kwargs):
        self.is_success = True
        self.stdout = NEIGHBOURS_IPV4
        if "-4" not in command:
            self.stdout += NEIGHBOURS_IPV6


def test_an_ipv6_neighbour_is_never_a_devices_ipv4_address(monkeypatch):
    monkeypatch.setattr(lan_scan, "run", _IpNeigh)

    (found,) = LanScanner(network=served(), read_held=nothing_held).scan(
        is_active=False
    )

    assert found.mac_address == "52:54:00:6d:07:8e"
    assert found.ipv4_address == "192.168.100.30"


def test_the_device_list_carries_the_neighbour_through(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    found = scanned(monkeypatch).values()

    merged = {
        device.ipv4_address: device for device in DeviceRegistry().merged(list(found))
    }

    assert merged["192.168.100.21"].is_neighbour is True
    assert merged["192.168.100.21"].name is None


def test_elsewhere_a_scan_finds_nothing(elsewhere, tmp_path, monkeypatch):
    write_table(tmp_path, monkeypatch)
    commands = _Commands(neighbours=NEIGHBOURS)
    monkeypatch.setattr(lan_scan, "run", commands)

    assert count_lan_neighbours(["enp1s0"]) == 0
    assert LanScanner(network=served(), read_held=nothing_held).scan() == []
    assert commands.commands == []
