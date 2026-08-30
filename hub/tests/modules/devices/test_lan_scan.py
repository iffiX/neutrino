"""Counting the devices on the gateway's own networks."""

from neutrino_hub.modules.devices import lan_scan
from neutrino_hub.modules.devices.lan_scan import count_lan_neighbours

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
