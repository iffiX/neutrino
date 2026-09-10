"""The window and program icons each format wants, made from one source.

``images/icons`` holds the project's PNGs and is the only place an icon is
drawn. Linux packages install those files as they are; Windows wants one
``.ico`` and macOS one ``.icns``, so both are assembled here at build time
rather than committed as a second copy of the same artwork.

Both containers may carry PNG members directly — Windows has accepted them
since Vista, macOS since 10.7 — so nothing is re-encoded and no imaging
library is needed.

Not pure: reads the icon sources and writes files.
"""

import struct
from pathlib import Path

ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "images" / "icons"

# The edges each container carries, and for macOS the four-letter type that
# names one. Sizes above what the source set holds are left out rather than
# scaled up.
ICO_EDGES = (16, 32, 48, 64, 128, 256)
ICNS_TYPES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_ico(target: Path) -> Path:
    """Assemble the Windows icon.

    Args:
        target: The ``.ico`` to write.

    Returns:
        The path written.

    Raises:
        SystemExit: When the source set holds none of the edges.
    """
    members = [(edge, _source(edge)) for edge in ICO_EDGES if _source(edge) is not None]
    if not members:
        raise SystemExit(f"no icon sources under {ICONS_DIR}")

    header = struct.pack("<HHH", 0, 1, len(members))
    offset = len(header) + 16 * len(members)
    directory = b""
    images = b""
    for edge, payload in members:
        # 256 is written as 0: the field is one byte and the format says so.
        directory += struct.pack(
            "<BBBBHHII",
            edge % 256,
            edge % 256,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        images += payload
        offset += len(payload)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + directory + images)
    return target


def write_icns(target: Path) -> Path:
    """Assemble the macOS icon.

    Args:
        target: The ``.icns`` to write.

    Returns:
        The path written.

    Raises:
        SystemExit: When the source set holds none of the edges.
    """
    members = b""
    for edge, kind in sorted(ICNS_TYPES.items()):
        payload = _source(edge)
        if payload is None:
            continue
        members += kind + struct.pack(">I", len(payload) + 8) + payload
    if not members:
        raise SystemExit(f"no icon sources under {ICONS_DIR}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"icns" + struct.pack(">I", len(members) + 8) + members)
    return target


def _source(edge: int) -> "bytes | None":
    """One source icon's bytes, checked to be the PNG it claims.

    Args:
        edge: The square edge in pixels.

    Returns:
        The file's bytes, or None when the set has no icon that size.

    Raises:
        SystemExit: When the file is not a PNG of that size.
    """
    path = ICONS_DIR / f"neutrino_{edge}.png"
    if not path.is_file():
        return None
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise SystemExit(f"{path} is not a PNG")
    width, height = struct.unpack(">II", payload[16:24])
    if (width, height) != (edge, edge):
        raise SystemExit(f"{path} is {width}x{height}, not {edge}x{edge}")
    return payload
