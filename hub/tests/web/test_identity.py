"""The hub's own identity: one id for its life, a name anybody can change.

What is pinned is that the file appears once with a uuid4 id and the
hostname for a name, that a second call keeps the id, that renaming touches
the name alone, and that a blank name is refused before it is written.
"""

import json
import uuid

import pytest

from neutrino_hub.web import identity
from neutrino_hub.web.identity import (
    ensure_hub_identity,
    hub_id,
    hub_name,
    set_hub_name,
)

HOSTNAME = "gateway"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(identity.socket, "gethostname", lambda: HOSTNAME)
    return tmp_path


def identity_file(config_dir) -> dict:
    return json.loads((config_dir / "web" / "identity.json").read_text())


def test_a_missing_identity_is_written_with_a_uuid_and_the_hostname(config_dir):
    is_written = ensure_hub_identity()

    assert is_written
    stored = identity_file(config_dir)
    assert set(stored) == {"id", "name"}
    assert uuid.UUID(hex=stored["id"]).version == 4
    assert stored["id"] == uuid.UUID(hex=stored["id"]).hex
    assert stored["name"] == HOSTNAME


def test_an_existing_identity_keeps_its_id(config_dir):
    ensure_hub_identity()
    first = hub_id()

    is_written = ensure_hub_identity()

    assert not is_written
    assert hub_id() == first


def test_the_id_and_the_name_read_back(config_dir):
    ensure_hub_identity()

    assert hub_id() == identity_file(config_dir)["id"]
    assert hub_name() == HOSTNAME


def test_renaming_changes_the_name_and_not_the_id(config_dir):
    ensure_hub_identity()
    first = hub_id()

    set_hub_name("  lab  ")

    assert hub_name() == "lab"
    assert hub_id() == first
    assert identity_file(config_dir) == {"id": first, "name": "lab"}


def test_a_blank_name_is_refused_and_nothing_is_written(config_dir):
    ensure_hub_identity()

    with pytest.raises(ValueError):
        set_hub_name("   ")

    assert hub_name() == HOSTNAME


def test_reading_before_setup_says_the_file_is_missing(config_dir):
    with pytest.raises(FileNotFoundError):
        hub_id()
