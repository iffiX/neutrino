"""The 7z archive inside an installer, read by the agent itself.

What these pin: the archive is found behind an installer's own bytes and a
false signature whose start header's CRC does not hold; a header compressed
with LZMA is read; folders of BCJ and LZMA2, of LZMA holding several files,
and plain copies decode to the bytes 7-Zip packed, each file with its Unix
mode, an empty file and an empty directory made; a file whose CRC differs,
a coder the reader does not decode, a name outside the directory and an
installer with no archive are refused. The archives under
``seven_zip_archives/`` were made by p7zip 16.02 from the tree below.
"""

import os
import random
import struct
import zlib
from pathlib import Path

import pytest

from neutrino_agent.modules.shared import seven_zip
from neutrino_agent.modules.shared.seven_zip import extract_embedded

ARCHIVES = Path(__file__).parent / "seven_zip_archives"
# A stand-in for the installer's own code before its data: a PE head, then
# the signature with a start header whose CRC does not hold.
INSTALLER_HEAD = (
    b"MZ" + b"\x90" * 510 + seven_zip.SEVEN_ZIP_SIGNATURE + b"\x00" * 40 + b"\xcc" * 300
)


def packed_tree() -> dict:
    """The files the archives were made from, by path, with their bytes."""
    rng = random.Random(7)
    inner = (
        bytes(rng.randrange(256) for _ in range(3000)) + b"\xe8\x00\x10\x00\x00" * 40
    )
    return {
        "top.txt": b"top level\n",
        "dir/inner.bin": inner,
        "dir/sub/notes.md": b"# notes\n" * 50,
        "dir/zero.txt": b"",
    }


def installer(tmp_path, name: str, archive: bytes = b"") -> str:
    path = tmp_path / f"{name}.exe"
    path.write_bytes(
        INSTALLER_HEAD + (archive or (ARCHIVES / f"{name}.7z").read_bytes())
    )
    return str(path)


@pytest.mark.parametrize("name", ["nonsolid", "solid", "copy"])
def test_each_archive_decodes_to_the_packed_bytes(tmp_path, name):
    target = tmp_path / "out"

    names = extract_embedded(installer(tmp_path, name), str(target))

    for relative, content in packed_tree().items():
        assert (target / relative).read_bytes() == content
    assert (target / "empty").is_dir()
    assert not any((target / "empty").iterdir())
    assert sorted(names) == sorted(
        ["dir", "dir/sub", "empty", "top.txt", "dir/inner.bin", "dir/sub/notes.md"]
        + ["dir/zero.txt"]
    )
    assert os.stat(target / "top.txt").st_mode & 0o777 == 0o664


def test_a_false_signature_before_the_archive_is_passed_over(tmp_path):
    path = installer(tmp_path, "nonsolid")
    with open(path, "rb") as stream:
        assert seven_zip._find_archive(stream) == len(INSTALLER_HEAD)


def test_a_signature_across_two_reads_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(seven_zip, "SEVEN_ZIP_READ_BYTES", 517)
    path = installer(tmp_path, "solid")

    with open(path, "rb") as stream:
        assert seven_zip._find_archive(stream) == len(INSTALLER_HEAD)
    extract_embedded(path, str(tmp_path / "out"))
    assert (tmp_path / "out" / "dir" / "inner.bin").read_bytes() == (
        packed_tree()["dir/inner.bin"]
    )


def test_a_file_whose_crc_differs_is_refused(tmp_path):
    archive = bytearray((ARCHIVES / "copy.7z").read_bytes())
    data_at = archive.index(b"top level\n")
    archive[data_at] ^= 0x01

    with pytest.raises(ValueError, match="CRC"):
        extract_embedded(
            installer(tmp_path, "copy", bytes(archive)), str(tmp_path / "o")
        )


def test_an_installer_with_no_archive_is_refused(tmp_path):
    path = tmp_path / "plain.exe"
    path.write_bytes(b"MZ" + b"\x00" * 4096)

    with pytest.raises(ValueError, match="no 7z archive"):
        extract_embedded(str(path), str(tmp_path / "out"))


def test_a_coder_the_reader_does_not_decode_is_refused():
    import lzma

    with pytest.raises(ValueError, match="040108"):
        seven_zip._filter(lzma, "040108", b"")
    with pytest.raises(ValueError, match="several streams"):
        seven_zip._read_folder(
            seven_zip._Reader(bytes([0x01, 0x14, 0x03, 0x03, 0x01, 0x1B]))
        )


@pytest.mark.parametrize(
    "name", ["../up.txt", "/etc/x", "a/../../b", "C:/x", "\\\\host\\x"]
)
def test_a_name_outside_the_directory_is_refused(tmp_path, name):
    with pytest.raises(ValueError, match="outside"):
        seven_zip._target(str(tmp_path), name)


def test_a_backslash_name_lands_under_its_folders(tmp_path):
    assert seven_zip._target(str(tmp_path), "resources\\kernel\\k.exe") == os.path.join(
        str(tmp_path), "resources", "kernel", "k.exe"
    )


def test_seven_zip_numbers_read_as_7_zip_writes_them():
    reader = seven_zip._Reader(bytes([0x7F, 0x80, 0x80, 0xC0, 0x34, 0x12]))
    assert reader.number() == 0x7F
    assert reader.number() == 0x80
    assert reader.number() == 0x1234


def test_the_start_header_crc_decides(tmp_path):
    body = struct.pack("<QQI", 0, 0, 0)
    good = seven_zip.SEVEN_ZIP_SIGNATURE + b"\x00\x04"
    good += struct.pack("<I", zlib.crc32(body)) + body
    path = tmp_path / "f"
    path.write_bytes(b"xx" + good)
    with open(path, "rb") as stream:
        assert seven_zip._is_start_header(stream, 2)
        assert not seven_zip._is_start_header(stream, 0)
