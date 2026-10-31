"""The icon sizes and containers every package carries.

The source PNGs are the repository's own. What is checked here is that an edge
of 16 or 1024 is the source file unchanged, that an edge between them is an
area average of the large file, that the assembled ``.ico`` and ``.icns`` carry
each size at the edge or under the type each entry claims, and that a source
that is not the PNG it claims is refused.
"""

import struct
import zlib

import pytest

from shared import icons

SETS = [("neutrino_client", "wink"), ("neutrino_hub", "open")]
ICNS_EDGES = {
    b"ic11": 32,
    b"ic12": 64,
    b"ic07": 128,
    b"ic13": 256,
    b"ic08": 256,
    b"ic14": 512,
    b"ic09": 512,
}


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


def _expand_is32(data):
    """The three colour planes of an ``is32`` entry, its runs expanded."""
    expanded = bytearray()
    offset = 0
    while offset < len(data):
        control = data[offset]
        offset += 1
        if control < 0x80:
            expanded += data[offset : offset + control + 1]
            offset += control + 1
        else:
            expanded += bytes([data[offset]]) * (control - 125)
            offset += 1
    return bytes(expanded)


@pytest.mark.parametrize("name, face", SETS)
@pytest.mark.parametrize("edge", [16, 1024])
def test_a_source_edge_is_the_file_itself(name, face, edge):
    source = icons.ICONS_DIR / name / f"wolf_{face}_{edge}.png"

    assert icons.png(edge, name, face) == source.read_bytes()


@pytest.mark.parametrize("name, face", SETS)
@pytest.mark.parametrize("edge", [32, 48, 256])
def test_an_edge_between_is_a_png_of_that_edge(name, face, edge):
    payload = icons.png(edge, name, face)

    assert payload.startswith(icons.PNG_SIGNATURE)
    assert struct.unpack(">II", payload[16:24]) == (edge, edge)


def test_a_scaled_pixel_is_the_average_of_its_area():
    rows = [[(100, 0, 0, 255), (200, 0, 0, 255)], [(100, 0, 0, 255), (200, 0, 0, 255)]]

    assert icons._area_average(2, [b"".join(map(bytes, row)) for row in rows], 1) == [
        bytes((150, 0, 0, 255))
    ]


def test_a_scaled_pixel_cut_by_its_bounds_counts_by_its_share():
    row = [(0, 0, 0, 255), (30, 0, 0, 255), (60, 0, 0, 255)]
    rows = [b"".join(map(bytes, row))] * 3

    scaled = icons._area_average(3, rows, 2)

    assert [tuple(line[:4]) for line in scaled] == [(10, 0, 0, 255)] * 2
    assert [tuple(line[4:8]) for line in scaled] == [(50, 0, 0, 255)] * 2


def test_a_transparent_pixel_adds_no_colour_to_an_average():
    rows = [[(0, 200, 0, 255), (255, 0, 0, 0)], [(0, 200, 0, 255), (255, 0, 0, 0)]]

    assert icons._area_average(2, [b"".join(map(bytes, row)) for row in rows], 1) == [
        bytes((0, 200, 0, 128))
    ]


def test_a_png_of_every_filter_type_reads_back():
    pixels = [bytes((10 * x, 20 * y, 7, 255)) for y in range(5) for x in range(4)]
    plain = [b"".join(pixels[y * 4 : y * 4 + 4]) for y in range(5)]
    filtered = bytearray()
    above = bytes(16)
    for kind, row in enumerate(plain):
        filtered.append(kind)
        for index, value in enumerate(row):
            left = row[index - 4] if index >= 4 else 0
            corner = above[index - 4] if index >= 4 else 0
            predicted = {
                0: 0,
                1: left,
                2: above[index],
                3: (left + above[index]) // 2,
                4: icons._paeth(left, above[index], corner),
            }[kind]
            filtered.append((value - predicted) & 0xFF)
        above = row
    payload = (
        icons.PNG_SIGNATURE
        + icons._png_chunk(
            b"IHDR", struct.pack(">IIBBBBB", 4, 5, *icons.PNG_RGBA_FORMAT)
        )
        + icons._png_chunk(b"IDAT", zlib.compress(bytes(filtered)))
        + icons._png_chunk(b"IEND", b"")
    )

    assert icons._decode(payload) == (4, plain)


def test_a_source_in_another_png_format_is_refused():
    payload = (
        icons.PNG_SIGNATURE
        + icons._png_chunk(
            b"IHDR", struct.pack(">IIBBBBB", 1, 1, *icons.PNG_RGB_FORMAT)
        )
        + icons._png_chunk(b"IEND", b"")
    )

    with pytest.raises(SystemExit) as refused:
        icons._decode(payload)

    assert "not 8-bit RGBA" in str(refused.value)


@pytest.mark.parametrize("name, face", SETS)
def test_the_windows_icon_carries_every_size_as_the_build_makes_it(
    tmp_path, name, face
):
    written = icons.write_ico(tmp_path / "bundle.ico", name=name, face=face)

    members = _members(written)
    assert sorted(members) == sorted(icons.ICO_EDGES)
    for edge in icons.ICO_EDGES:
        assert members[edge] == icons.png(edge, name, face)


def test_the_windows_icon_holds_the_hand_drawn_file_at_16(tmp_path):
    written = icons.write_ico(tmp_path / "bundle.ico")

    source = icons.ICONS_DIR / "neutrino_client" / "wolf_wink_16.png"
    assert _members(written)[16] == source.read_bytes()


def test_the_windows_icon_holds_the_edges_it_is_asked_for(tmp_path):
    written = icons.write_ico(tmp_path / "tray.ico", face="sleep", edges=(16, 32))

    assert sorted(_members(written)) == [16, 32]


def test_every_member_is_a_png_the_container_did_not_re_encode(tmp_path):
    written = icons.write_ico(tmp_path / "neutrino_client.ico")

    for payload in _members(written).values():
        assert payload.startswith(icons.PNG_SIGNATURE)


@pytest.mark.parametrize("name, face", SETS)
def test_the_macos_icon_holds_its_entries_in_order(tmp_path, name, face):
    written = icons.write_icns(tmp_path / "bundle.icns", name=name, face=face)

    assert [kind for kind, _size, _data in _entries(written)] == [
        b"is32",
        b"s8mk",
        b"ic11",
        b"ic12",
        b"ic07",
        b"ic13",
        b"ic08",
        b"ic14",
        b"ic09",
    ]


@pytest.mark.parametrize("name, face", SETS)
def test_each_macos_png_entry_holds_its_size_unchanged(tmp_path, name, face):
    written = icons.write_icns(tmp_path / "bundle.icns", name=name, face=face)

    for kind, size, payload in _entries(written):
        if kind not in ICNS_EDGES:
            continue
        source = icons.png(ICNS_EDGES[kind], name, face)
        assert size == len(source) + 8
        assert payload.startswith(icons.PNG_SIGNATURE)
        assert payload == source
        assert struct.unpack(">II", payload[16:24]) == (ICNS_EDGES[kind],) * 2


@pytest.mark.parametrize("name, face", SETS)
def test_the_macos_16_point_slot_holds_the_hand_drawn_pixels(tmp_path, name, face):
    written = icons.write_icns(tmp_path / "bundle.icns", name=name, face=face)

    entries = {kind: data for kind, _size, data in _entries(written)}
    _width, rows = icons._decode(icons.png(16, name, face))
    pixels = b"".join(rows)
    planes = _expand_is32(entries[b"is32"])
    assert planes == pixels[0::4] + pixels[1::4] + pixels[2::4]
    assert entries[b"s8mk"] == pixels[3::4]


@pytest.mark.parametrize("name, face", SETS)
def test_the_macos_icon_has_no_icp4_icp5_or_icp6_entry(tmp_path, name, face):
    written = icons.write_icns(tmp_path / "bundle.icns", name=name, face=face)

    kinds = {kind for kind, _size, _data in _entries(written)}
    assert not kinds & {b"icp4", b"icp5", b"icp6"}


def test_the_ios_icon_is_opaque_on_black(tmp_path):
    written = icons.write_opaque_png(tmp_path / "ios.png")

    payload = written.read_bytes()
    assert struct.unpack(">II", payload[16:24]) == (1024, 1024)
    assert payload[24:29] == bytes(icons.PNG_RGB_FORMAT)
    data = zlib.decompress(payload[payload.index(b"IDAT") + 4 :])
    stride = 1024 * 3 + 1
    assert data[1:4] == bytes(3)
    assert data[stride - 3 : stride] == bytes(3)
    assert len(data) == stride * 1024


def test_a_source_that_is_not_a_png_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path)
    source = tmp_path / "neutrino_client" / "wolf_wink_16.png"
    source.parent.mkdir()
    source.write_bytes(b"not a png at all")

    with pytest.raises(SystemExit) as refused:
        icons.write_ico(tmp_path / "out.ico", edges=(16,))

    assert "not a PNG" in str(refused.value)


def test_a_source_of_another_size_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path)
    source = tmp_path / "neutrino_client" / "wolf_wink_16.png"
    source.parent.mkdir()
    source.write_bytes(icons._encode(1, [bytes(4)], icons.PNG_RGBA_FORMAT))

    with pytest.raises(SystemExit) as refused:
        icons.png(16)

    assert "not 16x16" in str(refused.value)


def test_a_missing_source_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path / "empty")

    with pytest.raises(SystemExit) as refused:
        icons.write_ico(tmp_path / "out.ico")

    assert "no icon source" in str(refused.value)
