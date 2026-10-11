"""The root-only records of a module's instances.

What these pin: a record is written whole, mode 0600, in a directory only
the agent reads; only the fields the store names are kept; an unreadable
file is left out; and a record is forgotten by account.
"""

import os
import stat

from neutrino_agent.modules.shared.record_store import InstanceRecordStore

FIELDS = ("account", "port", "secret")


def test_a_record_is_kept_whole_and_root_only(tmp_path):
    store = InstanceRecordStore(directory=str(tmp_path / "records"), fields=FIELDS)

    store.write({"account": "ann", "port": 8443, "secret": "s", "extra": 1})

    path = tmp_path / "records" / "ann.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert store.read("ann") == {"account": "ann", "port": 8443, "secret": "s"}
    assert store.read("bob") == {}
    assert store.accounts() == ["ann"]


def test_an_unreadable_record_is_left_out_and_a_temporary_one_unlisted(tmp_path):
    store = InstanceRecordStore(directory=str(tmp_path), fields=FIELDS)
    store.write({"account": "ann", "port": 1, "secret": "s"})
    (tmp_path / "bob.json").write_text("not json")
    (tmp_path / ".record_x").write_text("{}")

    assert [record["account"] for record in store.read_all()] == ["ann"]
    assert store.accounts() == ["ann", "bob"]


def test_a_record_is_forgotten_by_account(tmp_path):
    store = InstanceRecordStore(directory=str(tmp_path), fields=FIELDS)
    store.write({"account": "ann", "port": 1, "secret": "s"})

    store.remove("ann")
    store.remove("ghost")

    assert store.read_all() == []


def test_a_missing_directory_holds_no_records(tmp_path):
    store = InstanceRecordStore(directory=str(tmp_path / "none"), fields=FIELDS)

    assert store.read_all() == []
    assert store.accounts() == []
