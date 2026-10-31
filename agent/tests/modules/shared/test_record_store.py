"""The root-only records of a module's instances.

What these pin: a record is written whole, mode 0600, in a directory only
the agent reads; only the fields the store names are kept; an unreadable
file is left out; a record is forgotten by account; a retired record
keeps its port alone, read by nobody but the kept ports; and a write waits
for a read that holds the record open.
"""

import json
import os
import stat
import threading

import neutrino_agent.modules.shared.record_store as record_store_module
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


def test_a_retired_record_keeps_its_port_alone_and_is_read_by_nobody(tmp_path):
    store = InstanceRecordStore(directory=str(tmp_path), fields=FIELDS)
    store.write({"account": "ann", "port": 3001, "secret": "s"})
    store.write({"account": "bob", "port": 3002, "secret": "t"})

    store.retire("ann")

    assert json.loads((tmp_path / "ann.json").read_text()) == {
        "account": "ann",
        "port": 3001,
        "is_retired": True,
    }
    assert [record["account"] for record in store.read_all()] == ["bob"]
    assert store.read("ann") == {}
    assert store.kept_ports() == {"ann": 3001, "bob": 3002}


def test_a_record_with_no_port_is_forgotten_whole_when_retired(tmp_path):
    store = InstanceRecordStore(directory=str(tmp_path), fields=FIELDS)
    store.write({"account": "ann", "port": 0, "secret": "s"})

    store.retire("ann")

    assert os.listdir(tmp_path) == []


def test_a_sealed_store_seals_each_file_before_writing_into_it(tmp_path):
    sealed: list = []

    def seal(path):
        sealed.append((os.path.basename(path), os.path.getsize(path)))

    store = InstanceRecordStore(
        directory=str(tmp_path), fields=("account", "port", "secret"), seal=seal
    )

    store.write({"account": "ann", "port": 6810, "secret": "s"})

    assert len(sealed) == 1
    assert sealed[0][0].startswith(".record_")
    assert sealed[0][1] == 0
    assert store.read("ann") == {"account": "ann", "port": 6810, "secret": "s"}


def test_a_write_waits_for_a_read_that_holds_the_record_open(tmp_path, monkeypatch):
    store = InstanceRecordStore(directory=str(tmp_path), fields=FIELDS)
    store.write({"account": "ann", "port": 1, "secret": "s"})
    reading, released = threading.Event(), threading.Event()
    loaded = json.load

    def slow_load(stream):
        reading.set()
        released.wait(5)
        return loaded(stream)

    monkeypatch.setattr(record_store_module.json, "load", slow_load)
    reader = threading.Thread(target=store.read_all)
    reader.start()
    assert reading.wait(5)
    writer = threading.Thread(
        target=store.write, args=({"account": "ann", "port": 2, "secret": "s"},)
    )
    writer.start()
    writer.join(0.2)

    assert writer.is_alive()
    released.set()
    reader.join(5)
    writer.join(5)
    monkeypatch.setattr(record_store_module.json, "load", loaded)
    assert store.read("ann")["port"] == 2
