"""The file channel: a listing, a download, an upload, the small operations.

Each is one stream. A listing closes with its entries; a download sends the
file's bytes, or a gzip tar of a directory, and closes with how many; an
upload takes the hub's bytes into a temporary file beside the target and
renames it into place once every announced byte is there; an operation
makes, renames or deletes and closes.

Paths are absolute, and the agent is root. A stream that cannot be served
at all is refused typed before it opens; one that fails under way closes
typed.

Not pure: reads and writes the file system.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import shutil
import stat
import tarfile
import tempfile

from neutrino_agent.constants import AGENT_WS_CHUNK_BYTES, AGENT_WS_STREAM_CREDIT_BYTES
from neutrino_agent.streams.channel import StreamRefused

FILE_OPS = ("mkdir", "rename", "delete")

KIND_FILE = "file"
KIND_DIR = "dir"
KIND_LINK = "link"
KIND_OTHER = "other"

# The mode an uploaded file lands with when nothing stood at its path.
UPLOAD_MODE = 0o644


def entry_kind(mode: int) -> str:
    """One of the four kinds a listing names, from an lstat mode."""
    if stat.S_ISLNK(mode):
        return KIND_LINK
    if stat.S_ISDIR(mode):
        return KIND_DIR
    if stat.S_ISREG(mode):
        return KIND_FILE
    return KIND_OTHER


def _require_absolute(path: str) -> None:
    if not path or not os.path.isabs(path):
        raise StreamRefused("path_invalid", {"path": path})


def _done(**fields) -> dict:
    return {"code": "", "params": {}, **fields}


def _failed(code: str, **params) -> dict:
    return {"code": code, "params": params}


def _error_code(error: OSError) -> str:
    if isinstance(error, FileNotFoundError):
        return "path_missing"
    if isinstance(error, (FileExistsError, NotADirectoryError, IsADirectoryError)):
        return "path_invalid"
    return "op_failed"


class FileListStream:
    """One directory's entries, closed with the stream."""

    def __init__(self, channel, args: dict):
        """
        Args:
            channel: The stream's channel.
            args: ``{"path"}``, the directory.
        """
        self._channel = channel
        self._path = str(args.get("path", ""))

    def open(self) -> None:
        """Check the path names a directory here.

        Raises:
            StreamRefused: ``path_invalid`` for a relative path or one that
                is no directory, ``path_missing`` for one that is not there.
        """
        _require_absolute(self._path)
        if not os.path.exists(self._path):
            raise StreamRefused("path_missing", {"path": self._path})
        if not os.path.isdir(self._path):
            raise StreamRefused("path_invalid", {"path": self._path})

    def run(self) -> dict:
        """Read the directory.

        Returns:
            ``{"path", "entries"}`` with the path resolved, each entry
            ``{"name", "path", "kind", "size", "modified_at", "mode"}``.
        """
        resolved = os.path.realpath(self._path)
        entries = []
        try:
            with os.scandir(resolved) as listing:
                for entry in listing:
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append(
                        {
                            "name": entry.name,
                            "path": os.path.join(resolved, entry.name),
                            "kind": entry_kind(info.st_mode),
                            "size": int(info.st_size),
                            "modified_at": int(info.st_mtime),
                            "mode": stat.S_IMODE(info.st_mode),
                        }
                    )
        except OSError as error:
            return _failed(_error_code(error), path=resolved)
        entries.sort(key=_name_key)
        return _done(path=resolved, entries=entries)


def _name_key(entry: dict) -> str:
    return entry["name"].lower()


class _ChannelWriter:
    """A file-like whose writes go up the stream, counting bytes."""

    def __init__(self, channel):
        self._channel = channel
        self.size = 0

    def write(self, data: bytes) -> int:
        """Send one piece of the archive."""
        self._channel.send_bytes(data)
        self.size += len(data)
        return len(data)


class FileDownloadStream:
    """One file's bytes, or a gzip tar of a directory, sent up the stream."""

    def __init__(self, channel, args: dict):
        """
        Args:
            channel: The stream's channel.
            args: ``{"path", "is_archived"}``. A directory is always sent
                as an archive; a file is, only when asked.
        """
        self._channel = channel
        self._path = str(args.get("path", ""))
        self._is_archived = bool(args.get("is_archived", False))

    def open(self) -> None:
        """Check the path names a file or directory here.

        Raises:
            StreamRefused: ``path_missing`` for a path that is not there,
                ``path_invalid`` for a relative one or a special file.
        """
        _require_absolute(self._path)
        if not os.path.exists(self._path):
            raise StreamRefused("path_missing", {"path": self._path})
        if os.path.isdir(self._path):
            self._is_archived = True
        elif not os.path.isfile(self._path):
            raise StreamRefused("path_invalid", {"path": self._path})

    def run(self) -> dict:
        """Send the bytes.

        A plain file announces its size in one event before the first byte,
        so the hub can promise a length; an archive's size is known only
        once it is done.

        Returns:
            ``{"size"}``, how many bytes went up.
        """
        try:
            if self._is_archived:
                return _done(size=self._send_archive())
            return _done(size=self._send_file())
        except OSError as error:
            return _failed(_error_code(error), path=self._path)

    def _send_file(self) -> int:
        size = os.path.getsize(self._path)
        self._channel.event(size=size)
        sent = 0
        with open(self._path, "rb") as source:
            while True:
                chunk = source.read(AGENT_WS_CHUNK_BYTES)
                if not chunk:
                    break
                self._channel.send_bytes(chunk)
                sent += len(chunk)
        return sent

    def _send_archive(self) -> int:
        writer = _ChannelWriter(self._channel)
        name = os.path.basename(self._path.rstrip("/")) or "archive"
        with tarfile.open(fileobj=writer, mode="w|gz") as archive:
            archive.add(self._path, arcname=name)
        return writer.size


class FileUploadStream:
    """The hub's bytes, into a temporary file, then renamed into place."""

    def __init__(self, channel, args: dict):
        """
        Args:
            channel: The stream's channel.
            args: ``{"path", "size"}``, the target and how many bytes come.
        """
        self._channel = channel
        self._path = str(args.get("path", ""))
        self._size = args.get("size")

    def open(self) -> None:
        """Check the target can be written, making missing parents.

        Raises:
            StreamRefused: ``path_invalid`` for a relative path, a bad size
                or a parent that is no directory; ``file_exists`` when a
                directory stands at the target.
        """
        _require_absolute(self._path)
        if not isinstance(self._size, int) or self._size < 0:
            raise StreamRefused("path_invalid", {"path": self._path})
        if os.path.isdir(self._path):
            raise StreamRefused("file_exists", {"path": self._path})
        parent = os.path.dirname(self._path) or "/"
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError:
            raise StreamRefused("path_invalid", {"path": self._path})

    def run(self) -> dict:
        """Take the bytes and put the file in place.

        Returns:
            Empty on success; ``write_failed`` when more bytes came than
            announced, the hub closed early, or the disk refused.
        """
        parent = os.path.dirname(self._path) or "/"
        name = os.path.basename(self._path)
        try:
            handle = tempfile.NamedTemporaryFile(
                dir=parent, prefix=f".{name}.", suffix=".part", delete=False
            )
        except OSError as error:
            return _failed("write_failed", path=self._path, detail=str(error)[:200])
        temporary = handle.name
        try:
            with handle:
                refusal = self._receive(handle)
                if refusal is not None:
                    return refusal
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, self._target_mode())
            os.replace(temporary, self._path)
        except OSError as error:
            return _failed("write_failed", path=self._path, detail=str(error)[:200])
        finally:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
        return _done()

    def _receive(self, handle) -> "dict | None":
        """Write the hub's bytes until the announced size is there."""
        self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
        received = 0
        while received < self._size:
            item = self._channel.recv()
            if item is None:
                continue
            if item[0] == "close":
                return _failed("write_failed", path=self._path, detail="closed")
            if item[0] != "data":
                continue
            received += len(item[1])
            if received > self._size:
                return _failed("write_failed", path=self._path, detail="oversize")
            handle.write(item[1])
            self._channel.offer_credit(len(item[1]))
        return None

    def _target_mode(self) -> int:
        try:
            return stat.S_IMODE(os.stat(self._path).st_mode)
        except OSError:
            return UPLOAD_MODE


class FileOpStream:
    """One small operation: make a directory, rename, or delete."""

    def __init__(self, channel, args: dict):
        """
        Args:
            channel: The stream's channel.
            args: ``{"op", "path", "new_path"}``; ``new_path`` for a rename.
        """
        self._channel = channel
        self._op = str(args.get("op", ""))
        self._path = str(args.get("path", ""))
        self._new_path = str(args.get("new_path", ""))

    def open(self) -> None:
        """Check the operation and its paths.

        Raises:
            StreamRefused: ``op_failed`` naming an operation outside the
                three, ``path_invalid`` for a relative path.
        """
        if self._op not in FILE_OPS:
            raise StreamRefused("op_failed", {"op": self._op})
        _require_absolute(self._path)
        if self._op == "rename":
            _require_absolute(self._new_path)

    def run(self) -> dict:
        """Carry the operation out.

        Returns:
            Empty on success; ``path_missing``, ``path_invalid`` or
            ``op_failed`` when the file system refused.
        """
        try:
            if self._op == "mkdir":
                os.mkdir(self._path)
            elif self._op == "rename":
                os.rename(self._path, self._new_path)
            elif os.path.isdir(self._path) and not os.path.islink(self._path):
                shutil.rmtree(self._path)
            else:
                os.remove(self._path)
        except OSError as error:
            return _failed(_error_code(error), path=self._path, detail=str(error)[:200])
        return _done()
