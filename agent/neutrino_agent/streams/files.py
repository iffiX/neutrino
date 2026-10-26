"""The file kind: one directory listing.

One ``file`` stream is one listing, ``{op: list, path}``, and its result is
its close's params: the directory's entries, for the panel's path window.
Any other ``op`` is closed ``op_unknown``.

Paths are absolute and in the machine's own form, and the agent is root.
On Windows a listing of ``/`` or of no path is the machine's drives. A
stream that cannot be served at all is refused typed before it opens; one
that fails under way closes typed.

Not pure: reads the file system.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import stat
import string

from neutrino_agent.exceptions import StreamRefused

# The one ``op`` a ``file`` stream takes.
FILE_OP_LIST = "list"

KIND_FILE = "file"
KIND_DIR = "dir"
KIND_LINK = "link"
KIND_OTHER = "other"

# Whether this machine's paths are Windows paths, with drives.
IS_WINDOWS = os.name == "nt"
# The separator a listing names, by whether the machine is Windows.
FILE_SEPARATOR_WINDOWS = "\\"
FILE_SEPARATOR_POSIX = "/"
# The path a Windows listing reads as the list of drives, besides no path.
FILE_DRIVES_PATH = "/"


def entry_kind(mode: int) -> str:
    """One of the four kinds a listing names, from an lstat mode."""
    if stat.S_ISLNK(mode):
        return KIND_LINK
    if stat.S_ISDIR(mode):
        return KIND_DIR
    if stat.S_ISREG(mode):
        return KIND_FILE
    return KIND_OTHER


def _separator() -> str:
    return FILE_SEPARATOR_WINDOWS if IS_WINDOWS else FILE_SEPARATOR_POSIX


def _drives() -> list:
    """The machine's drive roots, such as ``C:\\``.

    ``os.listdrives`` exists from Python 3.12; before it, every letter whose
    root exists.
    """
    listdrives = getattr(os, "listdrives", None)
    if listdrives is not None:
        return list(listdrives())
    roots = [f"{letter}:{FILE_SEPARATOR_WINDOWS}" for letter in string.ascii_uppercase]
    return [root for root in roots if os.path.exists(root)]


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
    if isinstance(error, (NotADirectoryError, IsADirectoryError)):
        return "path_invalid"
    return "op_failed"


def open_file_stream(channel, args: dict):
    """The handler for one ``file`` stream.

    Args:
        channel: The stream's channel.
        args: ``{"op", "path"}``.

    Returns:
        The handler, not yet opened.

    Raises:
        StreamRefused: ``op_unknown {op}`` for any ``op`` but ``list``.
    """
    op = str(args.get("op", "") or "")
    if op != FILE_OP_LIST:
        raise StreamRefused("op_unknown", {"op": op})
    return FileListStream(channel, args)


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
        """Check the path names a directory here, or the drives on Windows.

        Raises:
            StreamRefused: ``path_invalid`` for a relative path or one that
                is no directory, ``path_missing`` for one that is not there.
        """
        if self._is_drive_list():
            return
        _require_absolute(self._path)
        if not os.path.exists(self._path):
            raise StreamRefused("path_missing", {"path": self._path})
        if not os.path.isdir(self._path):
            raise StreamRefused("path_invalid", {"path": self._path})

    def run(self) -> dict:
        """Read the directory.

        Returns:
            ``{"code", "params"}``, the params ``{"path", "separator",
            "entries"}`` with the path resolved, the machine's path
            separator, and each entry ``{"name", "path", "kind", "size",
            "modified_at", "mode"}``. On Windows a listing of ``/`` or of no
            path has ``path`` ``/`` and one ``dir`` entry per drive, its
            ``path`` the drive's root.
        """
        if self._is_drive_list():
            return _done(
                path=FILE_DRIVES_PATH,
                separator=_separator(),
                entries=[_drive_entry(root) for root in _drives()],
            )
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
        return _done(path=resolved, separator=_separator(), entries=entries)

    def _is_drive_list(self) -> bool:
        return IS_WINDOWS and self._path in ("", FILE_DRIVES_PATH)


def _drive_entry(root: str) -> dict:
    """One drive as a listing entry, named by its letter and colon."""
    return {
        "name": root.rstrip(FILE_SEPARATOR_WINDOWS + FILE_SEPARATOR_POSIX),
        "path": root,
        "kind": KIND_DIR,
        "size": 0,
        "modified_at": 0,
        "mode": 0,
    }


def _name_key(entry: dict) -> str:
    return entry["name"].lower()
