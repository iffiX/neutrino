"""The file channel's one listing, over trees under ``tmp_path``.

What these pin: the ``file`` kind serving ``list`` alone and refusing every
other ``op`` ``op_unknown``, a listing's shape and its resolved path in the
close's params, the machine's separator, the drives of a Windows machine
for ``/``, and every refusal typed.
"""

import os
import stat

import pytest

from neutrino_agent.exceptions import StreamRefused
from neutrino_agent.streams import files
from neutrino_agent.streams.files import FileListStream, open_file_stream
from tests.streams.fake_channel import FakeChannel


def refusal(stream) -> StreamRefused:
    with pytest.raises(StreamRefused) as refused:
        stream.open()
    return refused.value


def served(stream) -> dict:
    stream.open()
    return stream.run()


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.txt").write_text("hello")
    (tmp_path / "docs" / "deep").mkdir()
    (tmp_path / "docs" / "deep" / "inner.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / "docs" / "link").symlink_to(tmp_path / "docs" / "note.txt")
    (tmp_path / "docs" / "sub").mkdir()
    return tmp_path


# --- the entry ---


def test_the_entry_serves_a_listing(tree):
    docs = str(tree / "docs")

    assert type(open_file_stream(FakeChannel(), {"op": "list", "path": docs})) is (
        FileListStream
    )


@pytest.mark.parametrize(
    "op",
    [
        "download",
        "upload",
        "rename",
        "remove",
        "directory_create",
        "directory_download",
        "",
    ],
)
def test_every_op_but_a_listing_is_refused_op_unknown(tree, op):
    with pytest.raises(StreamRefused) as refused:
        open_file_stream(FakeChannel(), {"op": op, "path": str(tree / "docs")})

    assert (refused.value.code, refused.value.params) == ("op_unknown", {"op": op})


# --- listing ---


def test_a_listing_names_every_entry_with_its_kind(tree):
    channel = FakeChannel()

    closed = served(FileListStream(channel, {"path": str(tree / "docs")}))

    assert closed["code"] == ""
    assert set(closed["params"]) == {"path", "separator", "entries"}
    assert closed["params"]["path"] == os.path.realpath(tree / "docs")
    by_name = {entry["name"]: entry for entry in closed["params"]["entries"]}
    assert set(by_name) == {"note.txt", "deep", "link", "sub"}
    assert by_name["note.txt"]["kind"] == "file"
    assert by_name["note.txt"]["size"] == 5
    assert by_name["note.txt"]["path"] == os.path.realpath(tree / "docs" / "note.txt")
    assert by_name["deep"]["kind"] == "dir"
    assert by_name["link"]["kind"] == "link"
    assert by_name["note.txt"]["modified_at"] > 0
    assert by_name["note.txt"]["mode"] == stat.S_IMODE(
        (tree / "docs" / "note.txt").stat().st_mode
    )
    assert [entry["name"] for entry in closed["params"]["entries"]] == sorted(
        by_name, key=str.lower
    )
    assert channel.sent == []


def test_a_listing_of_a_missing_or_relative_or_file_path_is_refused(tree):
    assert refusal(FileListStream(FakeChannel(), {"path": "docs"})).code == (
        "path_invalid"
    )
    missing = refusal(FileListStream(FakeChannel(), {"path": str(tree / "nope")}))
    assert missing.code == "path_missing"
    assert missing.params == {"path": str(tree / "nope")}
    on_file = refusal(
        FileListStream(FakeChannel(), {"path": str(tree / "docs" / "note.txt")})
    )
    assert on_file.code == "path_invalid"


def test_a_listing_names_the_machines_separator(tree):
    closed = served(FileListStream(FakeChannel(), {"path": str(tree / "docs")}))

    assert closed["params"]["separator"] == "/"


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(files, "IS_WINDOWS", True)
    monkeypatch.setattr(os, "listdrives", lambda: ["C:\\", "D:\\"], raising=False)


@pytest.mark.parametrize("path", ["/", ""])
def test_a_windows_listing_of_the_root_is_one_entry_per_drive(windows, path):
    closed = served(FileListStream(FakeChannel(), {"path": path}))

    assert closed["code"] == ""
    assert closed["params"]["path"] == "/"
    assert closed["params"]["separator"] == "\\"
    assert [
        (entry["name"], entry["path"], entry["kind"])
        for entry in closed["params"]["entries"]
    ] == [("C:", "C:\\", "dir"), ("D:", "D:\\", "dir")]


def test_a_windows_machine_before_listdrives_probes_each_letter(monkeypatch):
    monkeypatch.setattr(files, "IS_WINDOWS", True)
    monkeypatch.delattr(os, "listdrives", raising=False)
    monkeypatch.setattr(files.os.path, "exists", lambda path: path in {"C:\\"})

    closed = served(FileListStream(FakeChannel(), {"path": "/"}))

    assert [entry["path"] for entry in closed["params"]["entries"]] == ["C:\\"]


def test_a_linux_listing_of_the_root_is_the_root_directory(tree):
    closed = served(FileListStream(FakeChannel(), {"path": "/"}))

    assert closed["params"]["path"] == "/"
    assert "C:" not in {entry["name"] for entry in closed["params"]["entries"]}
