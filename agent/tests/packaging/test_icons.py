"""The two icon containers, assembled from the one source set.

Windows wants a .ico and macOS an .icns; both may carry PNG members, so
nothing is re-encoded and the bytes in each are the project's own artwork,
byte for byte.
"""

import struct

import pytest

import icons

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_ico(path):
    """Every entry in an .ico, as (edge, bytes).

    Args:
        path: The file to read.

    Returns:
        One pair per member, in the order the directory lists them.
    """
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    members = []
    for index in range(count):
        entry = data[6 + 16 * index : 22 + 16 * index]
        width, _, _, _, planes, bits, size, offset = struct.unpack("<BBBBHHII", entry)
        members.append((width or 256, planes, bits, data[offset : offset + size]))
    return members


def read_icns(path):
    """Every entry in an .icns, as (type, bytes).

    Args:
        path: The file to read.

    Returns:
        One pair per member, in the order they are stored.
    """
    data = path.read_bytes()
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    members = []
    at = 8
    while at < len(data):
        kind = data[at : at + 4]
        length = struct.unpack(">I", data[at + 4 : at + 8])[0]
        members.append((kind, data[at + 8 : at + length]))
        at += length
    return members


def test_the_windows_icon_carries_every_size_the_source_set_has(tmp_path):
    members = read_ico(icons.write_ico(tmp_path / "agent.ico"))

    assert [edge for edge, _, _, _ in members] == [16, 32, 48, 64, 128, 256]
    for _, planes, bits, image in members:
        assert (planes, bits) == (1, 32)
        assert image.startswith(PNG_SIGNATURE)


def test_the_windows_icon_carries_the_source_bytes_unchanged(tmp_path):
    members = read_ico(icons.write_ico(tmp_path / "agent.ico"))

    for edge, _, _, image in members:
        assert image == (icons.ICONS_DIR / f"neutrino_{edge}.png").read_bytes()


def test_the_macos_icon_names_each_size_by_its_own_type(tmp_path):
    members = read_icns(icons.write_icns(tmp_path / "agent.icns"))

    assert [kind for kind, _ in members] == [
        b"icp4",
        b"icp5",
        b"icp6",
        b"ic07",
        b"ic08",
        b"ic09",
    ]
    for _, image in members:
        assert image.startswith(PNG_SIGNATURE)


def test_the_macos_icon_carries_the_source_bytes_unchanged(tmp_path):
    members = dict(read_icns(icons.write_icns(tmp_path / "agent.icns")))
    types = {kind: edge for edge, kind in icons.ICNS_TYPES.items()}

    for kind, image in members.items():
        assert image == (icons.ICONS_DIR / f"neutrino_{types[kind]}.png").read_bytes()


def test_a_source_that_is_not_the_size_it_claims_is_refused(tmp_path, monkeypatch):
    """The directory entry says the size; a file whose name lies about it
    would put a wrong one there."""
    sources = tmp_path / "icons"
    sources.mkdir()
    (sources / "neutrino_16.png").write_bytes(
        PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 32, 32)
    )
    monkeypatch.setattr(icons, "ICONS_DIR", sources)

    with pytest.raises(SystemExit) as refused:
        icons.write_ico(tmp_path / "agent.ico")

    assert "16x16" in str(refused.value)


def test_a_source_that_is_not_a_png_is_refused(tmp_path, monkeypatch):
    sources = tmp_path / "icons"
    sources.mkdir()
    (sources / "neutrino_32.png").write_bytes(b"GIF89a")
    monkeypatch.setattr(icons, "ICONS_DIR", sources)

    with pytest.raises(SystemExit) as refused:
        icons.write_icns(tmp_path / "agent.icns")

    assert "not a PNG" in str(refused.value)


def test_no_source_at_all_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path / "empty")

    with pytest.raises(SystemExit):
        icons.write_ico(tmp_path / "agent.ico")
