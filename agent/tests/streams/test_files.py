"""The file channel over trees under ``tmp_path``.

What these pin: a listing's shape and its resolved path, a file download
announcing its size before its bytes, a directory download as a gzip tar
that unpacks to the tree, an upload landing by rename with the announced
size honoured and every refusal typed, and the three operations with a
directory delete that is recursive.
"""

import io
import os
import stat
import tarfile

import pytest

from neutrino_agent.streams.channel import StreamRefused
from neutrino_agent.streams.files import (
    FileDownloadStream,
    FileListStream,
    FileOpStream,
    FileUploadStream,
)
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


# --- listing ---


def test_a_listing_names_every_entry_with_its_kind(tree):
    channel = FakeChannel()

    closed = served(FileListStream(channel, {"path": str(tree / "docs")}))

    assert closed["code"] == ""
    assert closed["path"] == os.path.realpath(tree / "docs")
    by_name = {entry["name"]: entry for entry in closed["entries"]}
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
    assert [entry["name"] for entry in closed["entries"]] == sorted(
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


# --- download ---


def test_a_file_download_announces_its_size_then_sends_its_bytes(tree):
    channel = FakeChannel()

    closed = served(
        FileDownloadStream(channel, {"path": str(tree / "docs" / "note.txt")})
    )

    assert channel.events == [{"size": 5}]
    assert channel.output() == b"hello"
    assert closed == {"code": "", "params": {}, "size": 5}


def test_a_directory_download_is_a_gzip_tar_of_the_tree(tree):
    channel = FakeChannel()

    closed = served(FileDownloadStream(channel, {"path": str(tree / "docs")}))

    assert channel.events == []
    assert closed["size"] == len(channel.output())
    with tarfile.open(fileobj=io.BytesIO(channel.output()), mode="r:gz") as archive:
        names = sorted(archive.getnames())
        inner = archive.extractfile("docs/deep/inner.bin").read()
    assert "docs/note.txt" in names
    assert "docs/deep/inner.bin" in names
    assert inner == b"\x00\x01\x02"


def test_a_file_asked_for_as_an_archive_is_packed_under_its_name(tree):
    channel = FakeChannel()

    served(
        FileDownloadStream(
            channel, {"path": str(tree / "docs" / "note.txt"), "is_archived": True}
        )
    )

    with tarfile.open(fileobj=io.BytesIO(channel.output()), mode="r:gz") as archive:
        assert archive.getnames() == ["note.txt"]


def test_a_download_of_what_is_not_there_is_refused(tree):
    missing = refusal(FileDownloadStream(FakeChannel(), {"path": str(tree / "x")}))
    assert missing.code == "path_missing"
    assert refusal(FileDownloadStream(FakeChannel(), {"path": "x"})).code == (
        "path_invalid"
    )


# --- upload ---


def upload(channel, path, size, chunks) -> dict:
    for chunk in chunks:
        channel.feed(("data", chunk))
    return served(FileUploadStream(channel, {"path": str(path), "size": size}))


def test_an_upload_lands_by_rename_once_every_byte_is_there(tree):
    channel = FakeChannel()
    target = tree / "docs" / "new" / "file.bin"

    closed = upload(channel, target, 6, [b"abc", b"def"])

    assert closed == {"code": "", "params": {}}
    assert target.read_bytes() == b"abcdef"
    assert [name for name in os.listdir(target.parent) if name.startswith(".")] == []
    assert channel.credits[0] > 0
    assert channel.credits[1:] == [3, 3]
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_an_upload_over_an_existing_file_keeps_its_mode(tree):
    target = tree / "docs" / "note.txt"
    target.chmod(0o600)

    upload(FakeChannel(), target, 3, [b"new"])

    assert target.read_text() == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_more_bytes_than_announced_is_refused_and_leaves_nothing(tree):
    target = tree / "docs" / "big.bin"

    closed = upload(FakeChannel(), target, 2, [b"abc"])

    assert closed["code"] == "write_failed"
    assert closed["params"]["detail"] == "oversize"
    assert not target.exists()
    assert [name for name in os.listdir(tree / "docs") if name.startswith(".")] == []


def test_a_hub_closing_early_leaves_nothing(tree):
    channel = FakeChannel()
    channel.feed(("data", b"ab"))
    channel.close_from_hub()
    target = tree / "docs" / "partial.bin"

    closed = served(FileUploadStream(channel, {"path": str(target), "size": 10}))

    assert closed["code"] == "write_failed"
    assert closed["params"]["detail"] == "closed"
    assert not target.exists()


def test_an_upload_onto_a_directory_or_a_bad_path_is_refused(tree):
    exists = refusal(
        FileUploadStream(FakeChannel(), {"path": str(tree / "docs"), "size": 1})
    )
    assert exists.code == "file_exists"
    relative = refusal(FileUploadStream(FakeChannel(), {"path": "x", "size": 1}))
    assert relative.code == "path_invalid"
    bad_size = refusal(
        FileUploadStream(FakeChannel(), {"path": str(tree / "a"), "size": -1})
    )
    assert bad_size.code == "path_invalid"
    under_file = refusal(
        FileUploadStream(
            FakeChannel(), {"path": str(tree / "docs" / "note.txt" / "x"), "size": 1}
        )
    )
    assert under_file.code == "path_invalid"


# --- operations ---


def op(**args) -> dict:
    return served(FileOpStream(FakeChannel(), args))


def test_mkdir_makes_one_directory(tree):
    assert op(op="mkdir", path=str(tree / "made")) == {"code": "", "params": {}}
    assert (tree / "made").is_dir()

    again = op(op="mkdir", path=str(tree / "made"))
    assert again["code"] == "path_invalid"
    missing_parent = op(op="mkdir", path=str(tree / "no" / "such"))
    assert missing_parent["code"] == "path_missing"


def test_rename_moves_a_path(tree):
    closed = op(
        op="rename",
        path=str(tree / "docs" / "note.txt"),
        new_path=str(tree / "docs" / "sub" / "moved.txt"),
    )

    assert closed["code"] == ""
    assert (tree / "docs" / "sub" / "moved.txt").read_text() == "hello"
    assert not (tree / "docs" / "note.txt").exists()
    gone = op(op="rename", path=str(tree / "gone"), new_path=str(tree / "x"))
    assert gone["code"] == "path_missing"


def test_delete_removes_a_file_a_link_and_a_directory_recursively(tree):
    assert op(op="delete", path=str(tree / "docs" / "link"))["code"] == ""
    assert (tree / "docs" / "note.txt").exists()
    assert op(op="delete", path=str(tree / "docs" / "note.txt"))["code"] == ""
    assert op(op="delete", path=str(tree / "docs"))["code"] == ""
    assert not (tree / "docs").exists()
    assert op(op="delete", path=str(tree / "docs"))["code"] == "path_missing"


def test_an_operation_outside_the_three_or_off_a_relative_path_is_refused(tree):
    assert refusal(FileOpStream(FakeChannel(), {"op": "chmod", "path": "/x"})).code == (
        "op_failed"
    )
    assert refusal(FileOpStream(FakeChannel(), {"op": "mkdir", "path": "x"})).code == (
        "path_invalid"
    )
    relative_target = refusal(
        FileOpStream(FakeChannel(), {"op": "rename", "path": "/x", "new_path": "y"})
    )
    assert relative_target.code == "path_invalid"
