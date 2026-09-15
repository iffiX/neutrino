"""Heartbeat tokens: the raw one goes to the device, only its hash to disk."""

import hashlib
import json

import pytest

from neutrino_hub.modules.devices.registry import DeviceRegistry


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def device_id(config_dir) -> str:
    return DeviceRegistry().create("box").id


def stored_client(config_dir, device_id: str) -> dict:
    data = json.loads((config_dir / "devices" / "devices.json").read_text())
    return data["devices"][device_id]["client"]


def test_only_the_hash_reaches_the_device_file(config_dir, device_id):
    token = DeviceRegistry().issue_token(device_id)

    client = stored_client(config_dir, device_id)
    assert client["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in (config_dir / "devices" / "devices.json").read_text()
    # Presence is runtime state: no version, no last-seen stamp on disk.
    assert set(client) == {"token_sha256"}


def test_the_raw_token_still_authenticates(config_dir, device_id):
    token = DeviceRegistry().issue_token(device_id)

    found = DeviceRegistry().find_by_token(token)
    assert found is not None and found.id == device_id
    assert DeviceRegistry().find_by_token("not-the-token") is None
    # The stored hash itself must not open the door.
    assert (
        DeviceRegistry().find_by_token(hashlib.sha256(token.encode()).hexdigest())
        is None
    )


def test_a_reissued_token_invalidates_the_old_one(config_dir, device_id):
    registry = DeviceRegistry()
    old = registry.issue_token(device_id)
    new = registry.issue_token(device_id)

    assert DeviceRegistry().find_by_token(old) is None
    assert DeviceRegistry().find_by_token(new) is not None


def test_a_token_is_issued_to_stored_rows_only(config_dir):
    with pytest.raises(KeyError):
        DeviceRegistry().issue_token("nonsense")
    with pytest.raises(KeyError):
        DeviceRegistry().issue_token("scan:aa:bb:cc:dd:ee:ff")


def test_dropping_the_token_keeps_the_row(config_dir, device_id):
    registry = DeviceRegistry()
    token = registry.issue_token(device_id)

    registry.drop_token(device_id)

    assert stored_client(config_dir, device_id)["token_sha256"] is None
    assert DeviceRegistry().find_by_token(token) is None
    assert DeviceRegistry().get(device_id).name == "box"
