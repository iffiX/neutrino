"""The window and program icons each format wants, made from one source.

``images/icons`` holds the project's PNGs and is the only place an icon is
drawn. Linux packages install those files as they are; Windows wants one
``.ico`` and macOS one ``.icns``, so both are assembled here at build time
rather than committed as a second copy of the same artwork.

Both containers carry the PNGs unchanged: Windows reads PNG in every ``.ico``
member, and macOS in the ``.icns`` entries ``ICNS_TYPES`` names. Nothing is
re-encoded and no imaging library is needed.

Not pure: reads the icon sources and writes files.
"""

import struct
from pathlib import Path

ICONS_DIR = Path(__file__).resolve().parents[3] / "images" / "icons"
# The client's icon set; the hub's builds ask for ``neutrino_hub``.
DEFAULT_ICON_NAME = "neutrino"

# The edges each container carries; an edge the source set lacks is left out
# rather than scaled up. For macOS, each entry's four-letter type and the edge
# of the source PNG it holds, in the order written.
ICO_EDGES = (16, 32, 48, 64, 128, 256)
ICNS_TYPES = (
    (b"ic11", 32),  # 16x16@2x
    (b"ic12", 64),  # 32x32@2x
    (b"ic07", 128),  # 128x128
    (b"ic13", 256),  # 128x128@2x
    (b"ic08", 256),  # 256x256
    (b"ic14", 512),  # 256x256@2x
    (b"ic09", 512),  # 512x512
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_ico(target: Path, name: str = DEFAULT_ICON_NAME) -> Path:
    """Assemble the Windows icon.

    Args:
        target: The ``.ico`` to write.
        name: The icon set, the stem the PNGs under ``images/icons`` share:
            ``neutrino`` for the client's plain mark, ``neutrino_hub`` for
            the hub's.

    Returns:
        The path written.

    Raises:
        SystemExit: When the source set holds none of the edges.
    """
    members = [
        (edge, _source(edge, name))
        for edge in ICO_EDGES
        if _source(edge, name) is not None
    ]
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


def write_icns(target: Path, name: str = DEFAULT_ICON_NAME) -> Path:
    """Assemble the macOS icon.

    The 16 and 32 point slots are the @2x entries ``ic11`` and ``ic12``,
    holding the 32 and 64 pixel sources: macOS shows PNG under ``icp4``,
    ``icp5`` or ``icp6`` as noise at those sizes.

    Args:
        target: The ``.icns`` to write.
        name: The icon set, the stem the PNGs under ``images/icons`` share:
            ``neutrino`` for the client's plain mark, ``neutrino_hub`` for
            the hub's.

    Returns:
        The path written.

    Raises:
        SystemExit: When the source set holds none of the edges.
    """
    members = b""
    for kind, edge in ICNS_TYPES:
        payload = _source(edge, name)
        if payload is None:
            continue
        members += kind + struct.pack(">I", len(payload) + 8) + payload
    if not members:
        raise SystemExit(f"no icon sources under {ICONS_DIR}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"icns" + struct.pack(">I", len(members) + 8) + members)
    return target


def _source(edge: int, name: str = DEFAULT_ICON_NAME) -> "bytes | None":
    """One source icon's bytes, checked to be the PNG it claims.

    Args:
        edge: The square edge in pixels.
        name: The icon set's stem.

    Returns:
        The file's bytes, or None when the set has no icon that size.

    Raises:
        SystemExit: When the file is not a PNG of that size.
    """
    path = ICONS_DIR / f"{name}_{edge}.png"
    if not path.is_file():
        return None
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise SystemExit(f"{path} is not a PNG")
    width, height = struct.unpack(">II", payload[16:24])
    if (width, height) != (edge, edge):
        raise SystemExit(f"{path} is {width}x{height}, not {edge}x{edge}")
    return payload
