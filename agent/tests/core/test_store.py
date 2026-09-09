"""The machine's own state store: atomic, 0600, and free of secrets."""

import json
import os

import pytest

from neutrino_agent.core.store import MachineStateStore

SHARE = {
    "share_id": "s9",
    "is_shared": True,
    "port": 21118,
    "account": "alice",
}


@pytest.fixture
def store(tmp_path):
    return MachineStateStore(path=str(tmp_path / "state.json"))


def test_the_share_record_round_trips(store):
    assert store.rdp_share() == {}

    store.set_rdp_share(SHARE)
    assert store.rdp_share() == SHARE

    store.clear_rdp_share()
    assert store.rdp_share() == {}


def test_the_access_password_never_reaches_the_file(store, tmp_path):
    store.set_rdp_share(dict(SHARE, password="s3cret"))  # scan: allow

    text = (tmp_path / "state.json").read_text()
    assert "s3cret" not in text  # scan: allow
    assert "password" not in text
    assert "password" not in store.rdp_share()


def test_the_file_is_written_0600_and_atomically(store, tmp_path):
    store.set_rdp_share(SHARE)

    path = tmp_path / "state.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert not os.path.exists(str(path) + ".tmp")


def test_a_write_that_changes_nothing_writes_nothing(store, tmp_path):
    store.set_rdp_share(SHARE)
    path = tmp_path / "state.json"
    stamp = path.stat().st_mtime_ns

    store.set_rdp_share(SHARE)

    assert path.stat().st_mtime_ns == stamp


def test_an_unreadable_file_reads_as_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    store = MachineStateStore(path=str(path))

    assert store.rdp_share() == {}

    store.set_rdp_share(SHARE)
    assert store.rdp_share() == SHARE
    assert isinstance(json.loads(path.read_text()), dict)
