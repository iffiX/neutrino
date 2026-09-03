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


def stored_client(config_dir) -> dict:
    data = json.loads((config_dir / "devices" / "devices.json").read_text())
    return data["devices"]["aa:bb:cc:dd:ee:01"]["client"]


def test_only_the_hash_reaches_the_device_file(config_dir):
    token = DeviceRegistry().issue_client_token("aa:bb:cc:dd:ee:01")

    client = stored_client(config_dir)
    assert client["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in (config_dir / "devices" / "devices.json").read_text()


def test_the_raw_token_still_authenticates(config_dir):
    registry = DeviceRegistry()
    token = registry.issue_client_token("aa:bb:cc:dd:ee:01")

    found = DeviceRegistry().find_by_client_token(token)
    assert found is not None and found.mac_address == "aa:bb:cc:dd:ee:01"
    assert DeviceRegistry().find_by_client_token("not-the-token") is None
    # The stored hash itself must not open the door.
    assert (
        DeviceRegistry().find_by_client_token(
            hashlib.sha256(token.encode()).hexdigest()
        )
        is None
    )


def test_a_reissued_token_invalidates_the_old_one(config_dir):
    registry = DeviceRegistry()
    old = registry.issue_client_token("aa:bb:cc:dd:ee:01")
    new = registry.issue_client_token("aa:bb:cc:dd:ee:01")

    assert DeviceRegistry().find_by_client_token(old) is None
    assert DeviceRegistry().find_by_client_token(new) is not None


def test_forgetting_the_client_drops_the_hash(config_dir):
    registry = DeviceRegistry()
    registry.annotate("aa:bb:cc:dd:ee:01", {"name": "kept"})
    token = registry.issue_client_token("aa:bb:cc:dd:ee:01")

    registry.forget_client("aa:bb:cc:dd:ee:01")

    assert stored_client(config_dir)["token_sha256"] is None
    assert DeviceRegistry().find_by_client_token(token) is None
    assert DeviceRegistry().get("aa:bb:cc:dd:ee:01").name == "kept"
