"""The gateway's stored settings: a client key is sealed, or it is not kept."""

import json

import pytest

import neutrino_hub.utils.json_file
from neutrino_hub.modules.cliproxyapi.config import (
    CliproxyApiClientKey,
    CliproxyApiConfig,
)
from neutrino_hub.modules.cliproxyapi.ops import load_config, save_config
from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.utils.json_file import write_config
from tests.conftest import unlock_vault

CONFIG_RELATIVE = "cliproxyapi/cliproxyapi.json"


@pytest.fixture()
def box(tmp_path, monkeypatch):
    """A config root of its own, with the vault unlocked."""
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


def test_a_generated_key_seals_and_opens_again(box):
    key = CliproxyApiClientKey.generated("laptop")
    material = key.open_key()

    assert material
    assert key.name == "laptop"
    stored = key.to_dict()
    assert set(stored) == {"id", "name", "key_sealed", "created_at"}
    assert material not in json.dumps(stored)
    assert CliproxyApiClientKey.from_dict(stored).open_key() == material


def test_the_stored_file_carries_no_key_material(box):
    config = CliproxyApiConfig(client_keys=[CliproxyApiClientKey.generated("laptop")])
    material = config.client_keys[0].open_key()

    save_config(config)

    assert material not in (box / CONFIG_RELATIVE).read_text(encoding="utf-8")
    assert load_config().client_keys[0].open_key() == material


@pytest.mark.parametrize(
    "record",
    [
        {"id": "old", "name": "laptop", "key": "no-longer-a-shape"},
        {"id": "old", "name": "laptop"},
        {"id": "old", "name": "laptop", "key_sealed": {}},
        {"id": "old", "name": "laptop", "key_sealed": "not-an-object"},
    ],
)
def test_a_record_without_a_seal_is_dropped_on_load(box, record):
    kept = CliproxyApiClientKey.generated("desktop")
    write_config(
        CONFIG_RELATIVE,
        {"listen_port": 8317, "client_keys": [record, kept.to_dict()]},
    )

    loaded = load_config()

    assert loaded.listen_port == 8317
    assert [key.id for key in loaded.client_keys] == [kept.id]


def test_generating_a_key_needs_an_unlocked_vault(box, monkeypatch):
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_STATE_ROOT", box / "no-state"
    )
    with pytest.raises(VaultLockedError):
        CliproxyApiClientKey.generated("laptop")
