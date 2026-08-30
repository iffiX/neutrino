"""Remembering a device's host key, and refusing to quietly change it.

The gateway types stored sudo passwords into these sessions, so the question
these pin is not "can we connect" but "are we sure this is the same machine we
connected to last time".
"""

from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore, host_pattern

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterialForTests"
OTHER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDifferentKeyMaterialHere"


def store(tmp_path) -> DeviceHostKeyStore:
    """A store backed by a file of its own."""
    return DeviceHostKeyStore(path=tmp_path / "known_hosts")


def test_a_device_that_has_never_been_seen_has_no_key(tmp_path):
    keys = store(tmp_path)
    assert keys.has("192.168.100.2", 22) is False
    assert keys.known_hosts_for("192.168.100.2", 22) is None


def test_the_first_key_seen_is_recorded(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 22, KEY)
    assert keys.has("192.168.100.2", 22) is True
    assert KEY.encode() in keys.known_hosts_for("192.168.100.2", 22)


def test_a_second_key_never_replaces_the_first(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 22, KEY)
    keys.learn("192.168.100.2", 22, OTHER_KEY)
    recorded = keys.known_hosts_for("192.168.100.2", 22).decode()
    assert KEY in recorded
    assert OTHER_KEY not in recorded


def test_forgetting_lets_a_rebuilt_machine_be_learned_again(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 22, KEY)
    keys.forget("192.168.100.2", 22)
    assert keys.has("192.168.100.2", 22) is False

    keys.learn("192.168.100.2", 22, OTHER_KEY)
    assert OTHER_KEY.encode() in keys.known_hosts_for("192.168.100.2", 22)


def test_devices_do_not_see_each_others_keys(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 22, KEY)
    keys.learn("192.168.100.3", 22, OTHER_KEY)

    assert KEY.encode() in keys.known_hosts_for("192.168.100.2", 22)
    assert OTHER_KEY.encode() not in keys.known_hosts_for("192.168.100.2", 22)
    assert keys.has("192.168.100.3", 22) is True


def test_forgetting_one_device_leaves_the_others(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 22, KEY)
    keys.learn("192.168.100.3", 22, OTHER_KEY)
    keys.forget("192.168.100.2", 22)

    assert keys.has("192.168.100.2", 22) is False
    assert keys.has("192.168.100.3", 22) is True


def test_the_same_host_on_another_port_is_another_device(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 22, KEY)
    assert keys.has("192.168.100.2", 2222) is False


def test_ports_are_written_the_way_openssh_writes_them():
    assert host_pattern("192.168.100.2", 22) == "192.168.100.2"
    assert host_pattern("192.168.100.2", 2222) == "[192.168.100.2]:2222"


def test_the_file_is_readable_by_ssh_and_nobody_else(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 2222, KEY)

    path = tmp_path / "known_hosts"
    assert path.read_text() == f"[192.168.100.2]:2222 {KEY}\n"
    assert path.stat().st_mode & 0o777 == 0o600


def test_comments_and_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "known_hosts"
    path.write_text(f"# written by hand\n\n192.168.100.2 {KEY}\n")
    keys = DeviceHostKeyStore(path=path)

    assert keys.has("192.168.100.2", 22) is True
    assert keys.known_hosts_for("192.168.100.2", 22).decode().startswith("192.168")


def test_an_empty_key_is_not_recorded(tmp_path):
    keys = store(tmp_path)
    keys.learn("192.168.100.2", 22, "   ")
    assert keys.has("192.168.100.2", 22) is False
