"""Counting the devices on the gateway's own networks."""

from neutrino_hub.modules.devices import lan_scan
from neutrino_hub.modules.devices import lan_scan
from neutrino_hub.modules.devices.lan_scan import LanScanner, count_lan_neighbours
from neutrino_hub.modules.devices.registry import DeviceRegistry

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


# --- the neighbour table, read for the topology ------------------------------

NEIGHBOURS = """192.168.100.20 lladdr aa:bb:cc:00:00:01 REACHABLE
192.168.100.21 lladdr aa:bb:cc:00:00:02 STALE
192.168.100.22 lladdr aa:bb:cc:00:00:03 FAILED
192.168.100.23 INCOMPLETE
192.168.100.24 lladdr aa:bb:cc:00:00:04 INCOMPLETE
"""


class _Result:
    is_success = True
    stdout = NEIGHBOURS


def scanned(monkeypatch) -> dict:
    monkeypatch.setattr(lan_scan, "run", lambda command, **kwargs: _Result())
    found = LanScanner(lan_interfaces=["enp1s0"]).scan(is_active=False)
    return {device.ipv4_address: device for device in found}


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


def test_the_device_list_carries_the_neighbour_through(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(lan_scan, "run", lambda command, **kwargs: _Result())
    found = LanScanner(lan_interfaces=["enp1s0"]).scan(is_active=False)

    merged = {device.ipv4_address: device for device in DeviceRegistry().merged(found)}

    assert merged["192.168.100.21"].is_neighbour is True
    assert merged["192.168.100.21"].name is None


def test_elsewhere_a_scan_finds_nothing(elsewhere, tmp_path, monkeypatch):
    write_table(tmp_path, monkeypatch)

    assert count_lan_neighbours(["enp1s0"]) == 0
    assert LanScanner(lan_interfaces=["enp1s0"]).scan() == []
