"""The device file: rows keyed by id, what a scan adds, and two writers on it.

A device is a row under an id the hub generates. A scan row is matched to a
device by any MAC the row stores, and one no row claims is shown under a
``scan:`` id until a person acts on it. The panel is one process with many
threads, and each write rewrites the whole list, so a writer holding an
older snapshot must not put back what another one deleted or undo a save
that landed between its own read and write.
"""

import json

import pytest

from neutrino_hub.modules.devices.host_keys import host_pattern
from neutrino_hub.modules.devices.lan_scan import DiscoveredDevice
from neutrino_hub.modules.devices.registry import DeviceRegistry, scan_id

MAC = "aa:bb:cc:dd:ee:01"
OTHER_MAC = "aa:bb:cc:dd:ee:02"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def stored(config_dir):
    """A device file with two machines in it, by id."""
    registry = DeviceRegistry()
    first = registry.create("first", link_mac=MAC).id
    second = registry.create("second").id
    return registry, first, second


def names(registry: DeviceRegistry) -> list:
    return sorted(device.name for device in registry.all_stored())


def rows(config_dir) -> dict:
    return json.loads((config_dir / "devices" / "devices.json").read_text())["devices"]


def scanned(mac: str, address: str = "192.168.100.9") -> DiscoveredDevice:
    return DiscoveredDevice(
        mac_address=mac, ipv4_address=address, vendor="Acme", is_online=True
    )


# --- the row ---


def test_a_created_device_is_a_row_under_a_generated_id(stored, config_dir):
    _, first, _ = stored

    assert len(first) == 32
    assert rows(config_dir)[first] == {
        "name": "first",
        "icon": None,
        "machine_id": "",
        "mac_addresses": [MAC],
        "link_mac": MAC,
        "ssh": None,
        "client": {"token_sha256": None},
        "shown_modules": [],
    }


def test_an_unknown_id_is_nobody(stored):
    registry, _, _ = stored

    assert registry.get("nonsense") is None
    with pytest.raises(KeyError):
        registry.annotate("nonsense", {"name": "x"})


def test_a_machine_id_finds_its_row(stored):
    registry, first, _ = stored
    registry.note_machine(first, machine_id="m-1")

    found = DeviceRegistry().find_by_machine_id("m-1")

    assert found is not None and found.id == first
    assert DeviceRegistry().find_by_machine_id("") is None
    assert DeviceRegistry().find_by_machine_id("m-9") is None


# --- what a report notes on the row ---


def test_note_machine_writes_only_when_something_is_new(stored, config_dir):
    registry, first, _ = stored
    path = config_dir / "devices" / "devices.json"
    before = path.read_text()

    assert registry.note_machine(first, link_mac=MAC) is False
    assert path.read_text() == before

    assert registry.note_machine(first, link_mac="AA-BB-CC-DD-EE-03") is True
    row = rows(config_dir)[first]
    assert row["mac_addresses"] == [MAC, "aa:bb:cc:dd:ee:03"]
    assert row["link_mac"] == "aa:bb:cc:dd:ee:03"


def test_note_machine_moves_the_link_mac_back_to_a_known_one(stored, config_dir):
    registry, first, _ = stored
    registry.note_machine(first, link_mac=OTHER_MAC)

    assert registry.note_machine(first, link_mac=MAC) is True

    row = rows(config_dir)[first]
    assert row["mac_addresses"] == [MAC, OTHER_MAC]
    assert row["link_mac"] == MAC


def test_note_machine_ignores_what_is_not_a_mac_or_a_row(stored, config_dir):
    registry, first, _ = stored

    assert registry.note_machine(first, link_mac="not-a-mac") is False
    assert registry.note_machine("nonsense", link_mac=OTHER_MAC) is False
    assert registry.note_machine(scan_id(OTHER_MAC), link_mac=OTHER_MAC) is False
    assert rows(config_dir)[first]["mac_addresses"] == [MAC]


# --- the scan ---


def test_a_scan_row_merges_into_the_device_that_stores_its_mac(stored):
    registry, first, _ = stored
    registry.note_machine(first, link_mac=OTHER_MAC)

    merged = DeviceRegistry().merged([scanned(OTHER_MAC, "192.168.100.12")])

    assert [device.id for device in merged if device.is_stored].count(first) == 1
    device = next(device for device in merged if device.id == first)
    assert device.ipv4_address == "192.168.100.12"
    assert device.vendor == "Acme"
    assert device.is_online is True
    assert not any(device.is_scan_row for device in merged)


def test_an_unclaimed_scan_row_carries_a_scan_id(stored):
    registry, first, second = stored

    merged = registry.merged([scanned("11:22:33:44:55:66")])

    assert [device.id for device in merged] == [
        first,
        second,
        scan_id("11:22:33:44:55:66"),
    ]
    row = merged[-1]
    assert row.is_scan_row and not row.is_stored
    assert row.mac_addresses == ["11:22:33:44:55:66"]
    assert row.link_mac == "11:22:33:44:55:66"
    assert row.ipv4_address == "192.168.100.9"


def test_a_scan_id_reads_as_a_blank_row_and_nothing_else_does(config_dir):
    registry = DeviceRegistry()

    row = registry.get("scan:AA-BB-CC-DD-EE-09")

    assert row is not None and row.id == "scan:aa:bb:cc:dd:ee:09"
    assert row.link_mac == "aa:bb:cc:dd:ee:09"
    assert registry.get("scan:nonsense") is None


def test_renaming_a_scan_row_adopts_it_under_an_id_of_its_own(stored, config_dir):
    registry, first, second = stored

    adopted = registry.annotate(scan_id("11:22:33:44:55:66"), {"name": "printer"})

    assert adopted.is_stored and adopted.name == "printer"
    assert adopted.mac_addresses == ["11:22:33:44:55:66"]
    assert set(rows(config_dir)) == {first, second, adopted.id}
    merged = DeviceRegistry().merged([scanned("11:22:33:44:55:66")])
    assert [device.id for device in merged if device.is_scan_row] == []
    assert next(d for d in merged if d.id == adopted.id).is_online is True


def test_the_module_tabs_a_device_shows_are_a_row_of_their_own(stored, config_dir):
    registry, first, _ = stored

    registry.annotate(first, {"shown_modules": ["samba", "podman"]})

    assert rows(config_dir)[first]["shown_modules"] == ["samba", "podman"]
    assert DeviceRegistry().get(first).shown_modules == ["samba", "podman"]
    registry.annotate(first, {"name": "renamed"})
    assert DeviceRegistry().get(first).shown_modules == ["samba", "podman"]


def test_adopting_a_stored_id_changes_nothing(stored, config_dir):
    registry, first, _ = stored
    before = rows(config_dir)

    assert registry.adopt(first).id == first
    assert rows(config_dir) == before


# --- two writers ---


def test_a_write_from_a_stale_reader_does_not_resurrect_what_another_deleted(stored):
    """The stale registry was built before the delete; writing its own device
    must not write back the one that has gone."""
    _, first, second = stored
    stale = DeviceRegistry()

    DeviceRegistry().forget(second)
    stale.issue_token(first)

    assert names(DeviceRegistry()) == ["first"]


def test_a_write_from_a_stale_reader_does_not_undo_another_save(stored):
    _, first, second = stored
    stale = DeviceRegistry()

    DeviceRegistry().annotate(second, {"name": "renamed"})
    stale.issue_token(first)

    assert names(DeviceRegistry()) == ["first", "renamed"]


def test_forgetting_one_device_keeps_the_host_key_another_still_uses(
    stored, tmp_path, monkeypatch
):
    """The key store is keyed by host and port, not by device. Two records on
    one address share a pin, and un-pinning the live one means the next
    connection trusts whatever answers there."""
    from neutrino_hub.modules.devices import registry as registry_module
    from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore

    _, first, second = stored
    known_hosts = tmp_path / "known_hosts"
    monkeypatch.setattr(
        registry_module,
        "DeviceHostKeyStore",
        lambda: DeviceHostKeyStore(path=known_hosts),
    )
    for device_id in (first, second):
        DeviceRegistry().annotate(device_id, {"ssh": {"host": "10.0.0.5", "port": 22}})
    known_hosts.write_text(f"{host_pattern('10.0.0.5', 22)} ssh-ed25519 AAAAC3Nz\n")

    DeviceRegistry().forget(second)

    assert host_pattern("10.0.0.5", 22) in known_hosts.read_text()


def test_a_stored_ssh_host_is_a_credential_and_not_an_address(stored):
    """SSH installs the agent and drives power; where a machine is comes
    from the channel it beats on."""
    registry, first, _ = stored
    registry.annotate(first, {"ssh": {"host": "10.0.0.5", "username": "me"}})

    device = DeviceRegistry().get(first)

    assert device.has_ssh
    assert device.ipv4_address == ""
