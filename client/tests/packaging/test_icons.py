"""The icon container the Windows installer carries, member for member.

The source PNGs are the repository's own; what is checked here is that the
assembled ``.ico`` carries each of them unchanged, at the edge its directory
entry claims, and that a source that is not the PNG it claims is refused.
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
