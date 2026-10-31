"""The Remote desktop module's records.

What these pin: a record written whole reads back, a missing one reads
empty and its removal is no error, and a write or a removal waits for a
read that holds the record open.
"""

import json
import threading

import pytest

import neutrino_agent.modules.remote_desktop.records as records_module
from neutrino_agent.modules.remote_desktop.records import (
    read_json,
    remove_json,
    write_json,
)


def write_second(path: str) -> None:
    write_json(path, {"share_id": "s2"})


def test_a_record_reads_back_and_a_removed_one_reads_empty(tmp_path):
    path = str(tmp_path / "registered.json")

    write_json(path, {"share_id": "s1"})

    assert read_json(path) == {"share_id": "s1"}
    remove_json(path)
    remove_json(path)
    assert read_json(path) == {}


@pytest.mark.parametrize(
    "change, kept",
    [
        (write_second, {"share_id": "s2"}),
        (remove_json, {}),
    ],
)
def test_a_change_waits_for_a_read_that_holds_the_record_open(
    tmp_path, monkeypatch, change, kept
):
    path = str(tmp_path / "registered.json")
    write_json(path, {"share_id": "s1"})
    reading, released = threading.Event(), threading.Event()
    loaded = json.load

    def slow_load(stream):
        reading.set()
        released.wait(5)
        return loaded(stream)

    monkeypatch.setattr(records_module.json, "load", slow_load)
    reader = threading.Thread(target=read_json, args=(path,))
    reader.start()
    assert reading.wait(5)
    writer = threading.Thread(target=change, args=(path,))
    writer.start()
    writer.join(0.2)

    assert writer.is_alive()
    released.set()
    reader.join(5)
    writer.join(5)
    monkeypatch.setattr(records_module.json, "load", loaded)
    assert read_json(path) == kept
