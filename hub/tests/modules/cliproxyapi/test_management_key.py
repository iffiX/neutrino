"""The key the panel unlocks the AI gateway's management API with.

Machine state, not a credential anybody types: it is generated once, sealed
under the vault's data key beside the module's configuration, and unsealed
into a state file the panel reads. What is pinned here is the one case that
broke a real box — a sealed key left over from a vault that no longer exists.
"""

import json

import pytest

from neutrino_hub.modules.cliproxyapi import management_key
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_MANAGEMENT_KEY_AAD,
)
from neutrino_hub.modules.credentials.vault import seal_bytes
from tests.conftest import unlock_vault


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A box with an open vault, a config directory and a state root."""
    unlock_vault(monkeypatch, tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config)
    return config, tmp_path / "state"


def test_the_key_is_generated_once_and_then_left_alone(box):
    config, _ = box

    assert management_key.ensure_management_key() is True
    stored = (config / "cliproxyapi/management_key.sealed").read_text()

    assert management_key.ensure_management_key() is False
    assert (config / "cliproxyapi/management_key.sealed").read_text() == stored


def test_the_working_copy_is_the_key_the_panel_reads(box):
    _, state = box
    management_key.ensure_management_key()

    path = management_key.write_working_key()

    assert path.read_text(encoding="utf-8").strip() != ""
    assert path.stat().st_mode & 0o777 == 0o600
    assert management_key.read_management_key() == path.read_text().strip()


def test_a_key_sealed_under_a_vault_this_box_no_longer_has_is_minted_again(box):
    """A reset clears the data key; a sealed key that outlived it would turn
    the management API off for good."""
    config, _ = box
    sealed_path = config / "cliproxyapi/management_key.sealed"
    sealed_path.parent.mkdir(parents=True, exist_ok=True)
    sealed_path.write_text(
        json.dumps(
            {
                "nonce": "AAAAAAAAAAAAAAAAAAAAAA==",
                "data": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
            }
        )
    )

    assert management_key.ensure_management_key() is True
    assert management_key.write_working_key().read_text().strip() != ""


def test_the_panels_read_heals_a_missing_working_copy(box):
    _, state = box
    management_key.ensure_management_key()
    management_key.write_working_key().unlink()

    assert management_key.read_management_key() == ""
    assert management_key.resolve_management_key() != ""


def test_a_key_that_opens_is_the_one_that_stays(box):
    config, _ = box
    key = "a" * 64
    sealed_path = config / "cliproxyapi/management_key.sealed"
    sealed_path.parent.mkdir(parents=True, exist_ok=True)
    sealed_path.write_text(
        json.dumps(seal_bytes(key.encode(), CLIPROXYAPI_MANAGEMENT_KEY_AAD))
    )

    assert management_key.ensure_management_key() is False
    assert management_key.resolve_management_key() == key
