"""Two writers on one device file.

The panel is one process with many threads, and each write rewrites the
whole list. A writer holding an older snapshot must not put back what
another one deleted — name, SSH host and credential references intact —
nor undo a save that landed between its own read and write.
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
    """The stale registry was built before the delete; writing its own device
    must not write back the one that has gone."""
    stale = DeviceRegistry()

    DeviceRegistry().forget("aa:bb:cc:dd:ee:02")
    stale.issue_client_token("aa:bb:cc:dd:ee:01")

    assert names(DeviceRegistry()) == ["first"]


def test_a_write_from_a_stale_reader_does_not_undo_another_save(stored):
    stale = DeviceRegistry()

    DeviceRegistry().annotate("aa:bb:cc:dd:ee:02", {"name": "renamed"})
    stale.issue_client_token("aa:bb:cc:dd:ee:01")

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


def test_a_stored_ssh_host_is_a_credential_and_not_an_address(stored):
    """SSH installs the agent and drives power; where a machine is comes
    from the channel it beats on. A machine joined by an enrollment link has
    no SSH host and is no less located."""
    stored.annotate(
        "aa:bb:cc:dd:ee:01", {"ssh": {"host": "10.0.0.5", "username": "me"}}
    )

    device = DeviceRegistry().get("aa:bb:cc:dd:ee:01")

    assert device.has_ssh
    assert device.ipv4_address == ""
