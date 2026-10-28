"""The 7z archive inside a publisher's NSIS installer, unpacked by the agent itself.

An NSIS installer made by electron-builder carries the app as a 7z archive
stored whole among its data. The archive is found by its signature, whose
start header's CRC must hold, and read with the standard library's lzma:
its header, often itself compressed, then each folder's files, decoded as
they stream out and each checked against its CRC. A folder is one coder,
LZMA, LZMA2 or a plain copy, or a branch filter before one, as 7-Zip's BCJ
for x86. Nothing in the installer runs.

Not pure: reads the installer and writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import struct
import zlib

# The archive's signature, the size of its start header, and how much of the
# installer is read at once while looking for it.
SEVEN_ZIP_SIGNATURE = b"7z\xbc\xaf\x27\x1c"
SEVEN_ZIP_START_HEADER_BYTES = 32
SEVEN_ZIP_READ_BYTES = 1 << 20
# The largest header the reader takes.
SEVEN_ZIP_HEADER_LIMIT_BYTES = 64 << 20
# The coders the reader decodes, by id.
CODER_COPY = "00"
CODER_LZMA = "030101"
CODER_LZMA2 = "21"
CODER_BCJ_X86 = "03030103"
# The property ids of the header the reader acts on.
ID_END = 0x00
ID_HEADER = 0x01
ID_MAIN_STREAMS = 0x04
ID_FILES = 0x05
ID_PACK_INFO = 0x06
ID_UNPACK_INFO = 0x07
ID_SUBSTREAMS = 0x08
ID_SIZE = 0x09
ID_CRC = 0x0A
ID_FOLDER = 0x0B
ID_UNPACK_SIZE = 0x0C
ID_UNPACK_STREAMS = 0x0D
ID_EMPTY_STREAM = 0x0E
ID_EMPTY_FILE = 0x0F
ID_NAME = 0x11
ID_ATTRIBUTES = 0x15
ID_ENCODED_HEADER = 0x17
# A Unix mode in the high half of a file's attributes.
UNIX_ATTRIBUTE_FLAG = 0x8000


def extract_embedded(path: str, directory: str) -> list:
    """Unpack the 7z archive an installer carries whole into a directory.

    Args:
        path: The installer.
        directory: Where its files go; made when it is not there.

    Returns:
        The archive's names, in its order.

    Raises:
        ValueError: When no archive is found, it is malformed, it names a
            path outside the directory, a coder is not one the reader
            decodes, or a file's CRC differs.
        OSError: When a file cannot be read or written.
    """
    import lzma

    with open(path, "rb") as stream:
        base = _find_archive(stream)
        stream.seek(base + 12)
        offset, size = struct.unpack("<QQ", stream.read(16))
        if size > SEVEN_ZIP_HEADER_LIMIT_BYTES:
            raise ValueError(f"the archive's header is {size} bytes")
        stream.seek(base + SEVEN_ZIP_START_HEADER_BYTES + offset)
        reader = _Reader(stream.read(size))
        kind = reader.number()
        if kind == ID_ENCODED_HEADER:
            info = _read_streams(reader)
            if not info["folders"]:
                raise ValueError("the archive's header names no folder")
            folder = info["folders"][0]
            stream.seek(base + SEVEN_ZIP_START_HEADER_BYTES + info["pack_pos"])
            decoder = _FolderDecoder(lzma, stream, info["pack_sizes"][0], folder)
            reader = _Reader(decoder.read(_main_size(folder)))
            kind = reader.number()
        if kind != ID_HEADER:
            raise ValueError(f"the archive's header starts with {kind}")
        streams, files = _read_header(reader)
        return _write_files(lzma, stream, base, streams, files, directory)


class _Reader:
    """A header's bytes, read by 7z's own number and bit-vector forms."""

    def __init__(self, data: bytes):
        self._data = data
        self._at = 0

    def byte(self) -> int:
        if self._at >= len(self._data):
            raise ValueError("the archive's header ends early")
        value = self._data[self._at]
        self._at += 1
        return value

    def take(self, size: int) -> bytes:
        if self._at + size > len(self._data):
            raise ValueError("the archive's header ends early")
        value = self._data[self._at : self._at + size]
        self._at += size
        return value

    def skip_to(self, end: int) -> None:
        self._at = end

    @property
    def at(self) -> int:
        return self._at

    def number(self) -> int:
        """One 7z number: a first byte whose high bits count the bytes after it."""
        first = self.byte()
        mask = 0x80
        value = 0
        for index in range(8):
            if first & mask == 0:
                return value | ((first & (mask - 1)) << (8 * index))
            value |= self.byte() << (8 * index)
            mask >>= 1
        return value

    def uint32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def bits(self, count: int) -> list:
        found = []
        current = mask = 0
        for _ in range(count):
            if mask == 0:
                current, mask = self.byte(), 0x80
            found.append(bool(current & mask))
            mask >>= 1
        return found

    def defined(self, count: int) -> list:
        return [True] * count if self.byte() else self.bits(count)

    def digests(self, count: int) -> list:
        return [self.uint32() if is_held else None for is_held in self.defined(count)]


class _FolderDecoder:
    """One folder's bytes, decoded from its packed stream as they are asked for."""

    def __init__(self, lzma, stream, pack_size: int, folder: dict):
        self._stream = stream
        self._left = pack_size
        chain = _filter_chain(lzma, folder)
        self._decoder = (
            lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=chain)
            if chain
            else None
        )
        self._lzma_error = lzma.LZMAError

    def read(self, size: int) -> bytes:
        """Exactly so many decoded bytes.

        Raises:
            ValueError: When the packed stream ends first or does not decode.
            OSError: When the installer cannot be read.
        """
        parts = []
        got = 0
        while got < size:
            piece = self._next(min(size - got, SEVEN_ZIP_READ_BYTES))
            parts.append(piece)
            got += len(piece)
        return b"".join(parts)

    def _next(self, size: int) -> bytes:
        if self._decoder is None:
            piece = self._input(size)
            if not piece:
                raise ValueError("a folder of the archive ends early")
            return piece
        while True:
            chunk = (
                self._input(SEVEN_ZIP_READ_BYTES) if self._decoder.needs_input else b""
            )
            if self._decoder.needs_input and not chunk:
                raise ValueError("a folder of the archive ends early")
            try:
                piece = self._decoder.decompress(chunk, max_length=size)
            except (self._lzma_error, EOFError) as error:
                raise ValueError(f"a folder of the archive does not decode: {error}")
            if piece:
                return piece

    def _input(self, size: int) -> bytes:
        taken = self._stream.read(min(size, self._left))
        self._left -= len(taken)
        return taken


def _find_archive(stream) -> int:
    """Where the archive starts: the first signature whose start header's CRC holds."""
    stream.seek(0)
    offset = 0
    carried = b""
    while True:
        block = stream.read(SEVEN_ZIP_READ_BYTES)
        if not block:
            raise ValueError("the installer holds no 7z archive")
        data = carried + block
        start = offset - len(carried)
        at = data.find(SEVEN_ZIP_SIGNATURE)
        while at >= 0:
            if _is_start_header(stream, start + at):
                return start + at
            at = data.find(SEVEN_ZIP_SIGNATURE, at + 1)
        carried = data[-(len(SEVEN_ZIP_SIGNATURE) - 1) :]
        offset += len(block)
        stream.seek(offset)


def _is_start_header(stream, at: int) -> bool:
    """Whether a signature at one offset begins a start header whose CRC holds."""
    stream.seek(at)
    header = stream.read(SEVEN_ZIP_START_HEADER_BYTES)
    if len(header) < SEVEN_ZIP_START_HEADER_BYTES:
        return False
    return zlib.crc32(header[12:]) == struct.unpack("<I", header[8:12])[0]


def _read_header(reader: _Reader) -> tuple:
    """The main streams and the files of a plain header."""
    streams = {"pack_pos": 0, "pack_sizes": [], "folders": [], "sizes": []}
    files = []
    while True:
        kind = reader.number()
        if kind == ID_END:
            return streams, files
        if kind == ID_MAIN_STREAMS:
            streams = _read_streams(reader)
        elif kind == ID_FILES:
            files = _read_files(reader)
        else:
            raise ValueError(f"the archive's header holds {kind}")


def _read_streams(reader: _Reader) -> dict:
    """Where the packed streams are, the folders that decode them, and each file's size and CRC."""
    info = {"pack_pos": 0, "pack_sizes": [], "folders": [], "sizes": [], "crcs": []}
    counts = None
    while True:
        kind = reader.number()
        if kind == ID_END:
            break
        if kind == ID_PACK_INFO:
            info["pack_pos"], info["pack_sizes"] = _read_pack_info(reader)
        elif kind == ID_UNPACK_INFO:
            info["folders"] = _read_unpack_info(reader)
        elif kind == ID_SUBSTREAMS:
            counts, info["sizes"], info["crcs"] = _read_substreams(
                reader, info["folders"]
            )
        else:
            raise ValueError(f"the archive's streams hold {kind}")
    if counts is None:
        info["sizes"] = [_main_size(folder) for folder in info["folders"]]
        info["crcs"] = [folder.get("crc") for folder in info["folders"]]
        counts = [1] * len(info["folders"])
    info["counts"] = counts
    return info


def _read_pack_info(reader: _Reader) -> tuple:
    pack_pos = reader.number()
    count = reader.number()
    sizes = [0] * count
    while True:
        kind = reader.number()
        if kind == ID_END:
            return pack_pos, sizes
        if kind == ID_SIZE:
            sizes = [reader.number() for _ in range(count)]
        elif kind == ID_CRC:
            reader.digests(count)
        else:
            raise ValueError(f"the archive's pack info holds {kind}")


def _read_unpack_info(reader: _Reader) -> list:
    if reader.number() != ID_FOLDER:
        raise ValueError("the archive's unpack info names no folder")
    count = reader.number()
    if reader.byte():
        raise ValueError("the archive's folders are kept elsewhere")
    folders = [_read_folder(reader) for _ in range(count)]
    if reader.number() != ID_UNPACK_SIZE:
        raise ValueError("the archive's folders name no size")
    for folder in folders:
        folder["sizes"] = [reader.number() for _ in folder["coders"]]
    while True:
        kind = reader.number()
        if kind == ID_END:
            return folders
        if kind == ID_CRC:
            for folder, digest in zip(folders, reader.digests(count)):
                folder["crc"] = digest
        else:
            raise ValueError(f"the archive's unpack info holds {kind}")


def _read_folder(reader: _Reader) -> dict:
    """One folder: its coders, each with one stream in and one out, and how they are bound."""
    coders = []
    for _ in range(reader.number()):
        flags = reader.byte()
        coder_id = reader.take(flags & 0x0F).hex()
        if flags & 0x10:
            raise ValueError(
                f"the archive uses the coder {coder_id} of several streams"
            )
        properties = reader.take(reader.number()) if flags & 0x20 else b""
        coders.append({"id": coder_id, "properties": properties})
    bonds = [(reader.number(), reader.number()) for _ in range(len(coders) - 1)]
    return {"coders": coders, "bonds": bonds}


def _read_substreams(reader: _Reader, folders: list) -> tuple:
    """How many files each folder holds, each file's size, and each file's CRC."""
    counts = [1] * len(folders)
    kind = reader.number()
    if kind == ID_UNPACK_STREAMS:
        counts = [reader.number() for _ in folders]
        kind = reader.number()
    sizes = []
    for folder, count in zip(folders, counts):
        if count == 0:
            continue
        listed = [reader.number() for _ in range(count - 1)] if kind == ID_SIZE else []
        sizes.extend(listed + [_main_size(folder) - sum(listed)])
    if kind == ID_SIZE:
        kind = reader.number()
    known = [
        folder.get("crc") if count == 1 and folder.get("crc") is not None else None
        for folder, count in zip(folders, counts)
    ]
    crcs = []
    while kind != ID_END:
        if kind != ID_CRC:
            raise ValueError(f"the archive's substreams hold {kind}")
        unknown = sum(count for count, digest in zip(counts, known) if digest is None)
        listed = iter(reader.digests(unknown))
        crcs = []
        for count, digest in zip(counts, known):
            if digest is not None:
                crcs.append(digest)
            else:
                crcs.extend(next(listed) for _ in range(count))
        kind = reader.number()
    if not crcs:
        for count, digest in zip(counts, known):
            crcs.extend([digest] * count if count == 1 else [None] * count)
    return counts, sizes, crcs


def _read_files(reader: _Reader) -> list:
    """Each file's name, whether it holds data, whether it is a directory, and its mode."""
    count = reader.number()
    empty_stream = [False] * count
    empty_file = []
    names = []
    attributes = [None] * count
    while True:
        kind = reader.number()
        if kind == ID_END:
            break
        size = reader.number()
        end = reader.at + size
        if kind == ID_EMPTY_STREAM:
            empty_stream = reader.bits(count)
        elif kind == ID_EMPTY_FILE:
            empty_file = reader.bits(sum(empty_stream))
        elif kind == ID_NAME:
            if reader.byte():
                raise ValueError("the archive's names are kept elsewhere")
            text = reader.take(size - 1).decode("utf-16-le")
            names = text.split("\x00")[:count]
        elif kind == ID_ATTRIBUTES:
            defined = reader.defined(count)
            if reader.byte():
                raise ValueError("the archive's attributes are kept elsewhere")
            attributes = [reader.uint32() if is_held else None for is_held in defined]
        reader.skip_to(end)
    if len(names) != count:
        raise ValueError("the archive names fewer files than it holds")
    files = []
    empty_index = 0
    for index, name in enumerate(names):
        is_directory = False
        if empty_stream[index]:
            is_file = empty_index < len(empty_file) and empty_file[empty_index]
            is_directory = not is_file
            empty_index += 1
        attribute = attributes[index]
        mode = None
        if attribute is not None and attribute & UNIX_ATTRIBUTE_FLAG:
            mode = (attribute >> 16) & 0o777
        files.append(
            {
                "name": name,
                "has_data": not empty_stream[index],
                "is_directory": is_directory,
                "mode": mode,
            }
        )
    return files


def _main_size(folder: dict) -> int:
    """The size of what a folder decodes to: its one output no coder takes in."""
    return folder["sizes"][_main_coder(folder)]


def _main_coder(folder: dict) -> int:
    bound = {out_index for _, out_index in folder["bonds"]}
    for index in range(len(folder["coders"])):
        if index not in bound:
            return index
    raise ValueError("a folder of the archive has no output")


def _filter_chain(lzma, folder: dict) -> list:
    """lzma's raw filter chain for a folder, the outermost coder first; empty for a plain copy."""
    order = [_main_coder(folder)]
    bonds = dict(folder["bonds"])
    while order[-1] in bonds:
        order.append(bonds[order[-1]])
    if len(order) != len(folder["coders"]):
        raise ValueError("a folder of the archive binds its coders in no chain")
    chain = []
    for index in order:
        coder = folder["coders"][index]
        chain.extend(_filter(lzma, coder["id"], coder["properties"]))
    return chain


def _filter(lzma, coder_id: str, properties: bytes) -> list:
    """One coder as lzma's filter, none for a copy."""
    if coder_id == CODER_COPY:
        return []
    if coder_id == CODER_BCJ_X86:
        return [{"id": lzma.FILTER_X86}]
    if coder_id == CODER_LZMA2 and len(properties) == 1:
        exponent = properties[0]
        dictionary = (
            0xFFFFFFFF
            if exponent >= 40
            else (2 | (exponent & 1)) << (exponent // 2 + 11)
        )
        return [{"id": lzma.FILTER_LZMA2, "dict_size": dictionary}]
    if coder_id == CODER_LZMA and len(properties) == 5:
        value = properties[0]
        return [
            {
                "id": lzma.FILTER_LZMA1,
                "lc": value % 9,
                "lp": (value // 9) % 5,
                "pb": value // 45,
                "dict_size": struct.unpack("<I", properties[1:5])[0],
            }
        ]
    raise ValueError(
        f"the archive uses the coder {coder_id}, which the agent does not decode"
    )


def _write_files(lzma, stream, base: int, streams: dict, files: list, directory: str):
    """Write every file of the archive under the directory, each checked against its CRC."""
    root = os.path.realpath(directory)
    os.makedirs(root, exist_ok=True)
    targets = [_target(root, entry["name"]) for entry in files]
    for entry, target in zip(files, targets):
        if entry["is_directory"]:
            os.makedirs(target, exist_ok=True)
        elif not entry["has_data"]:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            open(target, "wb").close()
    with_data = [
        (entry, target) for entry, target in zip(files, targets) if entry["has_data"]
    ]
    if len(with_data) != len(streams["sizes"]):
        raise ValueError("the archive's files and streams do not match")
    position = base + SEVEN_ZIP_START_HEADER_BYTES + streams["pack_pos"]
    pack_index = 0
    file_index = 0
    for folder, count in zip(streams["folders"], streams["counts"]):
        size = streams["pack_sizes"][pack_index]
        stream.seek(position)
        decoder = _FolderDecoder(lzma, stream, size, folder)
        for _ in range(count):
            entry, target = with_data[file_index]
            _write_one(
                decoder,
                target,
                streams["sizes"][file_index],
                streams["crcs"][file_index] if streams["crcs"] else None,
                entry,
            )
            file_index += 1
        position += size
        pack_index += 1
    return [entry["name"] for entry in files]


def _write_one(decoder, target: str, size: int, crc, entry: dict) -> None:
    """Write one file's bytes as they decode, then check its CRC."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    found = 0
    left = size
    with open(target, "wb") as output:
        while left:
            piece = decoder.read(min(left, SEVEN_ZIP_READ_BYTES))
            output.write(piece)
            found = zlib.crc32(piece, found)
            left -= len(piece)
    if crc is not None and found != crc:
        raise ValueError(f"{entry['name']} does not match its CRC")
    if entry["mode"] is not None:
        os.chmod(target, entry["mode"])


def _target(root: str, name: str) -> str:
    """Where one name lands under the root; a name outside it is refused."""
    parts = [part for part in name.replace("\\", "/").split("/") if part]
    if not parts or name.startswith(("/", "\\")) or ":" in parts[0]:
        raise ValueError(f"the archive names a path outside it: {name}")
    if any(part in (".", "..") for part in parts):
        raise ValueError(f"the archive names a path outside it: {name}")
    return os.path.join(root, *parts)
