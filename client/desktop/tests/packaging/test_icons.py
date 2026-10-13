"""The icon containers the Windows and macOS installers carry, member for member.

The source PNGs are the repository's own; what is checked here is that the
assembled ``.ico`` and ``.icns`` carry each of them unchanged, at the edge or
under the type each entry claims, and that a source that is not the PNG it
claims is refused.
"""

import struct

import pytest

import icons


def _members(path):
    """Every image in an assembled ``.ico``, by the edge it is filed under.

    Args:
        path: The written container.

    Returns:
        ``{edge: bytes}``.
    """
    data = path.read_bytes()
    _reserved, kind, count = struct.unpack("<HHH", data[:6])

    assert kind == 1

    found = {}
    for index in range(count):
        entry = data[6 + 16 * index : 6 + 16 * (index + 1)]
        width, _height, _colors, _reserved, _planes, _bits, size, offset = (
            struct.unpack("<BBBBHHII", entry)
        )
        found[width or 256] = data[offset : offset + size]
    return found


def _entries(path):
    """Every entry of an assembled ``.icns``, in the order written.

    Args:
        path: The written container.

    Returns:
        ``[(type, size field, data)]``.
    """
    data = path.read_bytes()
    magic, length = struct.unpack(">4sI", data[:8])

    assert magic == b"icns"
    assert length == len(data)

    found = []
    offset = 8
    while offset < len(data):
        kind, size = struct.unpack(">4sI", data[offset : offset + 8])
        found.append((kind, size, data[offset + 8 : offset + size]))
        offset += size
    return found


def test_the_windows_icon_carries_every_source_size_unchanged(tmp_path):
    written = icons.write_ico(tmp_path / "neutrino_client.ico")

    members = _members(written)
    for edge in icons.ICO_EDGES:
        source = icons.ICONS_DIR / f"neutrino_{edge}.png"
        if not source.is_file():
            continue
        assert members[edge] == source.read_bytes()


def test_every_member_is_a_png_the_container_did_not_re_encode(tmp_path):
    written = icons.write_ico(tmp_path / "neutrino_client.ico")

    for payload in _members(written).values():
        assert payload.startswith(icons.PNG_SIGNATURE)


@pytest.mark.parametrize("name", ["neutrino", "neutrino_hub"])
def test_the_macos_icon_holds_the_png_entries_in_order(tmp_path, name):
    written = icons.write_icns(tmp_path / "bundle.icns", name=name)

    assert [kind for kind, _size, _data in _entries(written)] == [
        b"ic11",
        b"ic12",
        b"ic07",
        b"ic13",
        b"ic08",
        b"ic14",
        b"ic09",
    ]


@pytest.mark.parametrize("name", ["neutrino", "neutrino_hub"])
def test_each_macos_entry_holds_its_source_png_unchanged(tmp_path, name):
    edges = {
        b"ic11": 32,
        b"ic12": 64,
        b"ic07": 128,
        b"ic13": 256,
        b"ic08": 256,
        b"ic14": 512,
        b"ic09": 512,
    }
    written = icons.write_icns(tmp_path / "bundle.icns", name=name)

    for kind, size, payload in _entries(written):
        source = (icons.ICONS_DIR / f"{name}_{edges[kind]}.png").read_bytes()
        assert size == len(source) + 8
        assert payload.startswith(icons.PNG_SIGNATURE)
        assert payload == source
        assert struct.unpack(">II", payload[16:24]) == (edges[kind], edges[kind])


@pytest.mark.parametrize("name", ["neutrino", "neutrino_hub"])
def test_the_macos_icon_has_no_icp4_icp5_or_icp6_entry(tmp_path, name):
    written = icons.write_icns(tmp_path / "bundle.icns", name=name)

    kinds = {kind for kind, _size, _data in _entries(written)}
    assert not kinds & {b"icp4", b"icp5", b"icp6"}


def test_a_source_that_is_not_a_png_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path)
    (tmp_path / "neutrino_32.png").write_bytes(b"not a png at all")

    with pytest.raises(SystemExit) as refused:
        icons.write_ico(tmp_path / "out.ico")

    assert "not a PNG" in str(refused.value)


def test_a_source_set_with_nothing_in_it_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path / "empty")

    with pytest.raises(SystemExit) as refused:
        icons.write_ico(tmp_path / "out.ico")

    assert "no icon sources" in str(refused.value)
