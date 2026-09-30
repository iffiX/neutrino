"""The client's own file helpers: read what may be absent, write atomically.

Every write lands through a temporary file in the same directory followed by
``os.replace``. Every read answers empty rather than raising, because a file
the person has not made yet is an ordinary state rather than a failure.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import contextlib
import json
import os
import tempfile


def read_text(path: str) -> str:
    """Read one file.

    Args:
        path: The file to read.

    Returns:
        The text, empty when the file is absent or unreadable.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return ""


def read_json(path: str) -> dict:
    """Read one JSON object.

    Args:
        path: The file to read.

    Returns:
        The object, empty when the file is absent, unreadable, or holds
        anything but an object.
    """
    try:
        data = json.loads(read_text(path) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def write_text(path: str, text: str, mode: "int | None" = None) -> None:
    """Write one file atomically, its parent directories made on the way.

    Args:
        path: The file to write.
        text: What to write.
        mode: Permission bits to set on the file; None leaves the default.

    Raises:
        OSError: When the file cannot be written.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except OSError:
        remove_file(temporary)
        raise


def write_json(path: str, data: dict) -> None:
    """Write one JSON object atomically.

    Args:
        path: The file to write.
        data: The object to write.

    Raises:
        OSError: When the file cannot be written.
    """
    write_text(path, json.dumps(data, indent=2))


def remove_file(path: str) -> None:
    """Delete one file, absent being fine.

    Args:
        path: The file to delete.
    """
    try:
        os.unlink(path)
    except OSError:
        pass


@contextlib.contextmanager
def temporary_file(text: str, suffix: str = ""):
    """A file carrying some text for as long as the block runs.

    Args:
        text: What the file holds.
        suffix: The file name's suffix.

    Yields:
        The file's path.
    """
    descriptor, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        yield path
    finally:
        remove_file(path)
