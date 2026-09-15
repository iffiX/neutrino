"""The file kind: a listing, a download, an upload, the small operations.

One ``file`` stream is one operation, named by its ``op``, and its result
is its close's params. A listing closes with its entries; a download sends
the file's bytes, or a gzip tar of a directory, and closes with how many;
an upload takes the hub's bytes into a temporary file beside the target,
granting credit as each piece is written, and renames it into place once
every announced byte is there; an operation makes a directory, renames or
removes, and closes.

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
from neutrino_agent.exceptions import StreamRefused

# What one ``file`` stream may do, by its ``op``.
FILE_OP_LIST = "list"
FILE_OP_DOWNLOAD = "download"
FILE_OP_UPLOAD = "upload"
FILE_OP_RENAME = "rename"
FILE_OP_REMOVE = "remove"
FILE_OP_DIRECTORY_CREATE = "directory_create"
FILE_OP_DIRECTORY_DOWNLOAD = "directory_download"
# The small operations, served by one class.
FILE_OPS = (FILE_OP_RENAME, FILE_OP_REMOVE, FILE_OP_DIRECTORY_CREATE)

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
    return {"code": "", "params": dict(fields)}


def _failed(code: str, **params) -> dict:
    return {"code": code, "params": params}


def _error_code(error: OSError) -> str:
    if isinstance(error, FileNotFoundError):
        return "path_missing"
    if isinstance(error, (FileExistsError, NotADirectoryError, IsADirectoryError)):
        return "path_invalid"
    return "op_failed"


def open_file_stream(channel, args: dict):
    """The handler for one ``file`` stream, by its ``op``.

    Args:
        channel: The stream's channel.
        args: ``{"op", "path", ...}``, the rest being the operation's own.

    Returns:
        The handler, not yet opened.

    Raises:
        StreamRefused: ``verb_unknown`` naming an ``op`` outside the table.
    """
    op = str(args.get("op", "") or "")
    if op == FILE_OP_LIST:
        return FileListStream(channel, args)
    if op == FILE_OP_DOWNLOAD:
        return FileDownloadStream(channel, args)
    if op == FILE_OP_DIRECTORY_DOWNLOAD:
        return FileDownloadStream(channel, dict(args, is_archived=True))
    if op == FILE_OP_UPLOAD:
        return FileUploadStream(channel, args)
    if op in FILE_OPS:
        return FileOpStream(channel, args)
    raise StreamRefused("verb_unknown", {"op": op})


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
            ``{"code", "params"}``, the params ``{"path", "entries"}`` with
            the path resolved and each entry ``{"name", "path", "kind",
            "size", "modified_at", "mode"}``.
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

        Returns:
            ``{"code", "params"}``, the params ``{"size"}``: how many bytes
            went up.
        """
        try:
            if self._is_archived:
                return _done(size=self._send_archive())
            return _done(size=self._send_file())
        except OSError as error:
            return _failed(_error_code(error), path=self._path)

    def _send_file(self) -> int:
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
            ``{"code", "params"}``: empty params on success; ``write_failed``
            when more bytes came than announced, the hub closed early, or
            the disk refused.
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
        """Write the hub's bytes until the announced size is there.

        One window of credit opens the transfer; each piece written grants
        as much again, so a large upload never waits on this side.
        """
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
    """One small operation: make a directory, rename, or remove."""

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
            StreamRefused: ``verb_unknown`` naming an operation outside the
                three, ``path_invalid`` for a relative path.
        """
        if self._op not in FILE_OPS:
            raise StreamRefused("verb_unknown", {"op": self._op})
        _require_absolute(self._path)
        if self._op == FILE_OP_RENAME:
            _require_absolute(self._new_path)

    def run(self) -> dict:
        """Carry the operation out.

        Returns:
            ``{"code", "params"}``: empty params on success; ``path_missing``,
            ``path_invalid`` or ``op_failed`` when the file system refused.
        """
        try:
            if self._op == FILE_OP_DIRECTORY_CREATE:
                os.mkdir(self._path)
            elif self._op == FILE_OP_RENAME:
                os.rename(self._path, self._new_path)
            elif os.path.isdir(self._path) and not os.path.islink(self._path):
                shutil.rmtree(self._path)
            else:
                os.remove(self._path)
        except OSError as error:
            return _failed(_error_code(error), path=self._path, detail=str(error)[:200])
        return _done()
