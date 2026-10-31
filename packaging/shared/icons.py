"""The program icons each format wants, made from one source.

``images/icons/<icon set>/`` holds each face as ``wolf_<face>_1024.png`` and a
hand-drawn ``wolf_<face>_16.png``, and is the only place an icon is drawn. A
package asks here for a PNG at one edge, the Windows ``.ico``, the macOS
``.icns`` or the iOS icon. An edge of 16 is the hand-drawn file and an edge of
1024 the large one, both unchanged. An edge between them is an area average of
the large one, made at build time and never committed.

The module uses the standard library alone, so every build container and
runner can run it.

Not pure: reads the icon sources and writes files.
"""

import functools
import itertools
import struct
import zlib
from pathlib import Path

ICONS_DIR = Path(__file__).resolve().parents[2] / "images" / "icons"
# The client's icon set and its default face. The hub's builds name their own.
DEFAULT_ICON_NAME = "neutrino_client"
DEFAULT_ICON_FACE = "wink"

# The hand-drawn edge and the edge every other size is scaled from.
ICON_EDGE_DRAWN = 16
ICON_EDGE_LARGE = 1024

ICO_EDGES = (16, 32, 48, 64, 128, 256)
# Each ``.icns`` PNG entry's four-letter type and the edge it holds, in the
# order written. The hand-drawn edge goes under ``is32`` and ``s8mk``.
ICNS_TYPES = (
    (b"ic11", 32),  # 16x16@2x
    (b"ic12", 64),  # 32x32@2x
    (b"ic07", 128),  # 128x128
    (b"ic13", 256),  # 128x128@2x
    (b"ic08", 256),  # 256x256
    (b"ic14", 512),  # 256x256@2x
    (b"ic09", 512),  # 512x512
)
# The longest literal run of one ``is32`` control byte.
ICNS_LITERAL_RUN = 128

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The IHDR fields of an 8-bit RGBA image with no interlacing.
PNG_RGBA_FORMAT = (8, 6, 0, 0, 0)
PNG_RGB_FORMAT = (8, 2, 0, 0, 0)
CHANNEL_MAX = 255


def png(
    edge: int, name: str = DEFAULT_ICON_NAME, face: str = DEFAULT_ICON_FACE
) -> bytes:
    """One face as a PNG at one edge.

    Args:
        edge: The square edge in pixels, from 16 to 1024.
        name: The icon set, the directory under ``images/icons``.
        face: The face, such as ``wink``.

    Returns:
        The PNG's bytes: the file itself at 16 and 1024, an area average of
        the 1024 file between them.

    Raises:
        SystemExit: When a source is missing, or is not a PNG of its size.
    """
    if edge in (ICON_EDGE_DRAWN, ICON_EDGE_LARGE):
        return _source(edge, name, face)
    return _scaled(edge, name, face)


def write_png(
    target: Path,
    edge: int,
    name: str = DEFAULT_ICON_NAME,
    face: str = DEFAULT_ICON_FACE,
) -> Path:
    """Write one face as a PNG at one edge.

    Args:
        target: The file to write.
        edge: The square edge in pixels.
        name: The icon set.
        face: The face.

    Returns:
        The path written.

    Raises:
        SystemExit: When a source is missing, or is not a PNG of its size.
    """
    payload = png(edge, name, face)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def write_ico(
    target: Path,
    name: str = DEFAULT_ICON_NAME,
    face: str = DEFAULT_ICON_FACE,
    edges: tuple = ICO_EDGES,
) -> Path:
    """Assemble a Windows icon. Every member is a PNG.

    Args:
        target: The ``.ico`` to write.
        name: The icon set.
        face: The face.
        edges: The edges it holds, in the order written.

    Returns:
        The path written.

    Raises:
        SystemExit: When a source is missing, or is not a PNG of its size.
    """
    members = [(edge, png(edge, name, face)) for edge in edges]
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


def write_icns(
    target: Path,
    name: str = DEFAULT_ICON_NAME,
    face: str = DEFAULT_ICON_FACE,
) -> Path:
    """Assemble a macOS icon.

    The 16 point slot holds the hand-drawn file under ``is32`` and ``s8mk``.
    The 16 and 32 point @2x slots are ``ic11`` and ``ic12``, holding the 32
    and 64 pixel sizes: macOS shows PNG under ``icp4``, ``icp5`` or ``icp6``
    as noise at those sizes.

    Args:
        target: The ``.icns`` to write.
        name: The icon set.
        face: The face.

    Returns:
        The path written.

    Raises:
        SystemExit: When a source is missing, or is not a PNG of its size.
    """
    members = _icns_entries_drawn(name, face)
    for kind, edge in ICNS_TYPES:
        members += _icns_entry(kind, png(edge, name, face))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"icns" + struct.pack(">I", len(members) + 8) + members)
    return target


def write_opaque_png(
    target: Path,
    name: str = DEFAULT_ICON_NAME,
    face: str = DEFAULT_ICON_FACE,
) -> Path:
    """Write a face at 1024 on opaque black with no alpha, as iOS takes it.

    Args:
        target: The file to write.
        name: The icon set.
        face: The face.

    Returns:
        The path written.

    Raises:
        SystemExit: When a source is missing, or is not a PNG of its size.
    """
    width, rows = _pixels(ICON_EDGE_LARGE, name, face)
    opaque = []
    for row in rows:
        alpha = row[3::4]
        line = bytearray(width * 3)
        for channel in range(3):
            line[channel::3] = bytes(
                (value * cover + CHANNEL_MAX // 2) // CHANNEL_MAX
                for value, cover in zip(row[channel::4], alpha)
            )
        opaque.append(bytes(line))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_encode(width, opaque, PNG_RGB_FORMAT))
    return target


def _icns_entry(kind: bytes, payload: bytes) -> bytes:
    """One ``.icns`` entry: its type, its size with the header, its data."""
    return kind + struct.pack(">I", len(payload) + 8) + payload


def _icns_entries_drawn(name: str, face: str) -> bytes:
    """The hand-drawn file as ``is32`` colour and ``s8mk`` alpha entries.

    Args:
        name: The icon set.
        face: The face.

    Returns:
        The two entries' bytes.

    Raises:
        SystemExit: When the file is missing or is not a PNG of its size.
    """
    _width, rows = _pixels(ICON_EDGE_DRAWN, name, face)
    pixels = b"".join(rows)
    colour = b""
    for channel in range(3):
        values = pixels[channel::4]
        for start in range(0, len(values), ICNS_LITERAL_RUN):
            run = values[start : start + ICNS_LITERAL_RUN]
            colour += bytes([len(run) - 1]) + run
    return _icns_entry(b"is32", colour) + _icns_entry(b"s8mk", pixels[3::4])


def _source(edge: int, name: str, face: str) -> bytes:
    """One source file's bytes, checked to be the PNG it claims.

    Args:
        edge: The file's edge, 16 or 1024.
        name: The icon set.
        face: The face.

    Returns:
        The file's bytes.

    Raises:
        SystemExit: When the file is missing or is not a PNG of that size.
    """
    path = ICONS_DIR / name / f"wolf_{face}_{edge}.png"
    if not path.is_file():
        raise SystemExit(f"no icon source {path}")
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise SystemExit(f"{path} is not a PNG")
    width, height = struct.unpack(">II", payload[16:24])
    if (width, height) != (edge, edge):
        raise SystemExit(f"{path} is {width}x{height}, not {edge}x{edge}")
    return payload


@functools.lru_cache(maxsize=None)
def _pixels(edge: int, name: str, face: str) -> tuple:
    """One source file's pixels.

    Args:
        edge: The file's edge, 16 or 1024.
        name: The icon set.
        face: The face.

    Returns:
        ``(width, rows)``, each row the RGBA bytes of one line.

    Raises:
        SystemExit: When the file is missing, is not a PNG of that size, or
            is not 8-bit RGBA with no interlacing.
    """
    return _decode(_source(edge, name, face))


@functools.lru_cache(maxsize=None)
def _scaled(edge: int, name: str, face: str) -> bytes:
    """The large file averaged down to one edge, as a PNG.

    Args:
        edge: The square edge in pixels.
        name: The icon set.
        face: The face.

    Returns:
        The PNG's bytes.

    Raises:
        SystemExit: When the file is missing, or is not a PNG of its size.
    """
    width, rows = _pixels(ICON_EDGE_LARGE, name, face)
    return _encode(edge, _area_average(width, rows, edge), PNG_RGBA_FORMAT)


def _decode(payload: bytes) -> tuple:
    """Read an 8-bit RGBA PNG with no interlacing.

    Args:
        payload: The PNG's bytes.

    Returns:
        ``(width, rows)``, each row the RGBA bytes of one line.

    Raises:
        SystemExit: When the PNG has another format.
    """
    offset = len(PNG_SIGNATURE)
    width = height = 0
    compressed = b""
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        kind = payload[offset + 4 : offset + 8]
        data = payload[offset + 8 : offset + 8 + length]
        offset += length + 12
        if kind == b"IHDR":
            width, height, *form = struct.unpack(">IIBBBBB", data)
            if tuple(form) != PNG_RGBA_FORMAT:
                raise SystemExit(f"an icon source is not 8-bit RGBA: {form}")
        elif kind == b"IDAT":
            compressed += data
    filtered = zlib.decompress(compressed)
    stride = width * 4
    rows = []
    above = bytes(stride)
    for line in range(height):
        start = line * (stride + 1)
        above = _unfilter(
            filtered[start], filtered[start + 1 : start + 1 + stride], above
        )
        rows.append(above)
    return width, rows


def _unfilter(kind: int, line: bytes, above: bytes) -> bytes:
    """Undo one PNG row's filter.

    Args:
        kind: The filter type, 0 to 4.
        line: The filtered row.
        above: The row above, unfiltered.

    Returns:
        The row's bytes.
    """
    if kind == 0:
        return line
    if kind == 2:
        return bytes((value + up) & 0xFF for value, up in zip(line, above))
    row = bytearray(line)
    for index in range(len(row)):
        left = row[index - 4] if index >= 4 else 0
        up = above[index]
        if kind == 1:
            predicted = left
        elif kind == 3:
            predicted = (left + up) // 2
        else:
            corner = above[index - 4] if index >= 4 else 0
            predicted = _paeth(left, up, corner)
        row[index] = (row[index] + predicted) & 0xFF
    return bytes(row)


def _paeth(left: int, up: int, corner: int) -> int:
    """The PNG Paeth predictor: the neighbour nearest ``left + up - corner``."""
    estimate = left + up - corner
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_corner = abs(estimate - corner)
    if distance_left <= distance_up and distance_left <= distance_corner:
        return left
    return up if distance_up <= distance_corner else corner


def _area_average(width: int, rows: list, edge: int) -> list:
    """Scale a square RGBA image down, each pixel the average of its area.

    Colour is averaged weighted by alpha, so a transparent pixel adds no
    colour to an edge.

    Args:
        width: The source's edge.
        rows: The source's rows of RGBA bytes.
        edge: The target's edge.

    Returns:
        The target's rows of RGBA bytes.
    """
    bounds = [(index * width / edge) for index in range(edge + 1)]
    wholes = [min(int(bound), width - 1) for bound in bounds]
    fractions = [bound - whole for bound, whole in zip(bounds, wholes)]
    channels = []
    for channel in range(4):
        across = [
            _average_line(
                [
                    value * cover if channel < 3 else cover
                    for value, cover in zip(row[channel::4], row[3::4])
                ],
                wholes,
                fractions,
            )
            for row in rows
        ]
        channels.append(
            [_average_line(column, wholes, fractions) for column in zip(*across)]
        )
    scale = width / edge
    area = scale * scale
    target = []
    for line in range(edge):
        row = bytearray(edge * 4)
        for column in range(edge):
            summed_alpha = channels[3][column][line]
            alpha = summed_alpha / area
            row[column * 4 + 3] = min(CHANNEL_MAX, round(alpha))
            if summed_alpha <= 0:
                continue
            for channel in range(3):
                row[column * 4 + channel] = min(
                    CHANNEL_MAX, round(channels[channel][column][line] / summed_alpha)
                )
        target.append(bytes(row))
    return target


def _average_line(values, wholes: list, fractions: list) -> list:
    """The sum of each target pixel's span over one line of source values.

    Args:
        values: The line's source values.
        wholes: Each target boundary's whole source index.
        fractions: Each target boundary's fraction past that index.

    Returns:
        One sum per target pixel, each counting a cut pixel by its share.
    """
    summed = list(itertools.accumulate(values, initial=0))
    cuts = [
        summed[whole] + fraction * (summed[whole + 1] - summed[whole])
        for whole, fraction in zip(wholes, fractions)
    ]
    return [after - before for before, after in zip(cuts, cuts[1:])]


def _encode(width: int, rows: list, form: tuple) -> bytes:
    """Write rows as a PNG, unfiltered.

    Args:
        width: The image's width.
        rows: The rows' bytes.
        form: The IHDR fields after the size.

    Returns:
        The PNG's bytes.
    """
    header = struct.pack(">IIBBBBB", width, len(rows), *form)
    data = zlib.compress(b"".join(b"\0" + row for row in rows), 9)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", data)
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    """One PNG chunk with its length and checksum."""
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )
