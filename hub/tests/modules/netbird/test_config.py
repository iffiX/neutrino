"""The kept setup key: sealed in its file, empty when missing, shut when locked."""

import json

import pytest

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.netbird.config import (
    NetbirdConfig,
    read_stored,
    write_stored,
)
from tests.conftest import unlock_vault

SETUP_KEY = "A1B2C3D4-0000-4000-8000-000000000000"  # scan: allow


@pytest.fixture
def config_dir(monkeypatch, tmp_path):
    """A ``config/`` under tmp_path."""
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", directory)
    return directory


def test_the_file_holds_the_key_sealed(monkeypatch, tmp_path, config_dir):
    unlock_vault(monkeypatch, tmp_path)
    config = NetbirdConfig()
    config.set_setup_key(SETUP_KEY, "https://netbird.example.org")

    write_stored(config)

    text = (config_dir / "netbird" / "netbird.json").read_text()
    assert SETUP_KEY not in text
    assert json.loads(text)["management_url"] == "https://netbird.example.org"
    stored = read_stored()
    assert stored.has_setup_key
    assert stored.setup_key() == SETUP_KEY


def test_a_missing_file_reads_as_no_key(config_dir):
    stored = read_stored()

    assert not stored.has_setup_key
    assert stored.setup_key() == ""
    assert stored.management_url == ""


def test_a_locked_vault_refuses_to_open_the_key(monkeypatch, tmp_path, config_dir):
    unlock_vault(monkeypatch, tmp_path)
    config = NetbirdConfig()
    config.set_setup_key(SETUP_KEY, "")
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path / "nowhere"
    )

    with pytest.raises(VaultLockedError):
        config.setup_key()
