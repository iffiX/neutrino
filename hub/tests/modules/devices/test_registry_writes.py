"""Two writers on one device file.

An agent beats every five seconds and each beat rewrites the whole list, so
the window between somebody else's read and their write is never closed for
long. What used to happen in it: forget a device while a heartbeat was in
flight and the heartbeat's older snapshot put the device back — name, SSH
host and credential references intact — and the page's next poll showed it
as though nothing had been deleted.
"""

import pytest

from neutrino_hub.modules.devices.host_keys import host_pattern
from neutrino_hub.modules.devices.registry import DeviceRegistry


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def stored(config_dir):
    """A device file with two machines in it."""
    registry = DeviceRegistry()
    registry.annotate("aa:bb:cc:dd:ee:01", {"name": "first"})
    registry.annotate("aa:bb:cc:dd:ee:02", {"name": "second"})
    return registry


def names(registry: DeviceRegistry) -> list:
    return sorted(device.name for device in registry.all_stored())


def test_a_write_from_a_stale_reader_does_not_resurrect_what_another_deleted(stored):
    """The heartbeat's registry was built before the delete; writing its own
    device must not write back the one that has gone."""
    beating = DeviceRegistry()

    DeviceRegistry().forget("aa:bb:cc:dd:ee:02")
    beating.record_heartbeat("aa:bb:cc:dd:ee:01", version="0.1.0", seen_at="now")

    assert names(DeviceRegistry()) == ["first"]


def test_a_write_from_a_stale_reader_does_not_undo_another_save(stored):
    beating = DeviceRegistry()

    DeviceRegistry().annotate("aa:bb:cc:dd:ee:02", {"name": "renamed"})
    beating.record_heartbeat("aa:bb:cc:dd:ee:01", version="0.1.0", seen_at="now")

    assert names(DeviceRegistry()) == ["first", "renamed"]


def test_forgetting_one_device_keeps_the_host_key_another_still_uses(
    stored, tmp_path, monkeypatch
):
    """The key store is keyed by host and port, not by device. A machine whose
    MAC changed is two records on one address, and un-pinning the live one
    means the next connection trusts whatever answers there."""
    from neutrino_hub.modules.devices import registry as registry_module
    from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore

    known_hosts = tmp_path / "known_hosts"
    monkeypatch.setattr(
        registry_module,
        "DeviceHostKeyStore",
        lambda: DeviceHostKeyStore(path=known_hosts),
    )
    for mac in ("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"):
        DeviceRegistry().annotate(mac, {"ssh": {"host": "10.0.0.5", "port": 22}})
    known_hosts.write_text(f"{host_pattern('10.0.0.5', 22)} ssh-ed25519 AAAAC3Nz\n")

    DeviceRegistry().forget("aa:bb:cc:dd:ee:02")

    assert host_pattern("10.0.0.5", 22) in known_hosts.read_text()
