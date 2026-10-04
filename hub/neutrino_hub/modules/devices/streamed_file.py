"""A download written to disk as it arrives, hashed as it is written.

The module cache and the agent-package cache both fetch files of hundreds of
megabytes, and a hub can be a small box. A download goes into a temporary
file beside the place it is kept, in chunks, its SHA-256 taken on the way;
the caller judges it, then either puts it in place with one rename or
discards it. Whatever goes wrong while it is written, no part of it is left
on disk.

Not pure: writes files.
"""

import contextlib
import hashlib
import http.client
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_FETCH_CHUNK_BYTES,
    AGENT_MODULE_HEAD_BYTES,
)

PARTIAL_PREFIX = ".partial_"


class DownloadedFile:
    """One finished download in a temporary file, not yet in its place.

    Attributes:
        path: The temporary file.
        size: How many bytes it holds.
        sha256: Their digest, in hex.
        head: Its first bytes, for a check of what kind of file it is.
    """

    def __init__(self, *, path: Path, size: int, sha256: str, head: bytes):
        """
        Args:
            path: The temporary file.
            size: How many bytes it holds.
            sha256: Their digest, in hex.
            head: Its first bytes.
        """
        self.path = path
        self.size = size
        self.sha256 = sha256
        self.head = head

    def place(self, target: Path) -> None:
        """Move the file to where it is kept, in one rename.

        Args:
            target: Its place, in the same directory.

        Raises:
            OSError: When it cannot be moved; the temporary file is gone.
        """
        try:
            os.replace(self.path, target)
        except OSError:
            self.discard()
            raise

    def discard(self) -> None:
        """Delete the temporary file."""
        with contextlib.suppress(OSError):
            os.unlink(self.path)


def stream_to_file(
    response,
    directory: Path,
    *,
    limit: int,
    on_chunk: "Callable[..., None] | None" = None,
) -> DownloadedFile:
    """Write a response's body to a temporary file in chunks, up to one byte past a limit.

    Args:
        response: What ``urlopen`` answered; its ``Content-Length``, when
            present, is the total ``on_chunk`` is told.
        directory: Where the temporary file is made, beside the file's place.
        limit: The largest body taken; one byte more is read, so a caller
            sees a body past it by its size.
        on_chunk: Called with ``(received, total)`` after each chunk and
            with ``is_done=True`` once at the end; None tells nobody.

    Returns:
        The download.

    Raises:
        ConnectionError: When the body cannot be read to its end.
        OSError: When the file cannot be written.
    """
    try:
        total = int(response.headers.get("Content-Length", "") or 0)
    except (AttributeError, ValueError):
        total = 0
    handle, name = tempfile.mkstemp(prefix=PARTIAL_PREFIX, dir=directory)
    digest = hashlib.sha256()
    head = b""
    received = 0
    ceiling = limit + 1
    try:
        with os.fdopen(handle, "wb") as stream:
            while received < ceiling:
                try:
                    chunk = response.read(
                        min(AGENT_MODULE_FETCH_CHUNK_BYTES, ceiling - received)
                    )
                except (OSError, http.client.HTTPException) as error:
                    raise ConnectionError(f"the download broke off: {error}") from error
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                if len(head) < AGENT_MODULE_HEAD_BYTES:
                    head += chunk[: AGENT_MODULE_HEAD_BYTES - len(head)]
                received += len(chunk)
                if on_chunk is not None:
                    on_chunk(received, total)
        if on_chunk is not None:
            on_chunk(received, total, is_done=True)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
    return DownloadedFile(
        path=Path(name), size=received, sha256=digest.hexdigest(), head=head
    )


def file_sha256(path: Path) -> str:
    """A file's SHA-256, read in chunks.

    Args:
        path: The file.

    Returns:
        The digest, in hex.

    Raises:
        OSError: When it cannot be read.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(AGENT_MODULE_FETCH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
