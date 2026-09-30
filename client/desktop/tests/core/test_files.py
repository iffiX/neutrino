"""The file helpers: absent reads answer empty, writes land whole.

A file the person has not made yet reads as empty rather than raising, and
every write goes through a temporary file beside its target, so a reader
never sees half of one.
"""

import json
import os

import pytest

from neutrino_client.core.files import (
    read_json,
    read_text,
    remove_file,
    temporary_file,
    write_json,
    write_text,
)


def test_an_absent_file_reads_empty(tmp_path):
    assert read_text(str(tmp_path / "gone")) == ""
    assert read_json(str(tmp_path / "gone")) == {}
    assert read_text(str(tmp_path)) == ""
    assert read_json(str(tmp_path)) == {}


def test_text_round_trips(tmp_path):
    path = str(tmp_path / "deep" / "notes.txt")

    write_text(path, "hello\n")

    assert read_text(path) == "hello\n"


def test_json_round_trips_and_refuses_what_is_not_an_object(tmp_path):
    path = str(tmp_path / "state.json")

    write_json(path, {"a": 1})

    assert read_json(path) == {"a": 1}
    assert json.loads(read_text(path)) == {"a": 1}

    write_text(path, "[1, 2]")
    assert read_json(path) == {}

    write_text(path, "not json at all")
    assert read_json(path) == {}


def test_a_write_replaces_what_was_there_and_leaves_no_leftovers(tmp_path):
    directory = tmp_path / "store"
    path = str(directory / "state.json")
    write_text(path, "first")

    write_text(path, "second")

    assert read_text(path) == "second"
    assert os.listdir(str(directory)) == ["state.json"]


def test_a_write_can_set_the_permission_bits(tmp_path):
    path = str(tmp_path / "credentials")

    write_text(path, "username=u\n", mode=0o600)

    assert os.stat(path).st_mode & 0o777 == 0o600


def test_a_write_into_a_place_that_refuses_it_raises(tmp_path):
    occupied = tmp_path / "occupied"
    occupied.write_text("a file, not a directory")

    with pytest.raises(OSError):
        write_text(str(occupied / "file"), "text")


def test_removing_a_file_that_is_not_there_is_fine(tmp_path):
    path = str(tmp_path / "gone")
    write_text(path, "text")

    remove_file(path)
    remove_file(path)

    assert not os.path.exists(path)


def test_a_temporary_file_carries_the_text_and_goes_away():
    with temporary_file("script\n", suffix=".ps1") as path:
        assert read_text(path) == "script\n"
        assert path.endswith(".ps1")
        kept = path

    assert not os.path.exists(kept)


def test_a_temporary_file_goes_away_even_when_the_block_raises():
    kept = ""
    with pytest.raises(ValueError):
        with temporary_file("script\n") as path:
            kept = path
            raise ValueError("refused")

    assert kept and not os.path.exists(kept)
