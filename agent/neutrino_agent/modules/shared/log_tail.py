"""The last lines of a log file, and the mask every journal passes through.

Only the end of the file is read. The file is opened for reading alone,
which on Windows shares it with the handle the agent's logging writes
through, following no link at its last level and waiting on no pipe. A
file its program has not written yet reads as no lines.
A file in an account's place is read as that account
(:func:`account_file_tail`). :func:`mask_secrets` hides a token in a URL's
query and a token printed on a line of its own.

Not pure: reads files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import stat

from neutrino_agent.constants import (
    AGENT_MODULE_LOG_SEARCH_BYTES,
    AGENT_MODULE_LOG_TAIL_BYTES,
)

# How a log file is opened: no link followed at its last level and no wait
# on a pipe.
LOG_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_BINARY", 0)
)
# What a masked token reads as.
SECRET_MASK = "***"
# A token in a URL's query: ``?tkn=...``, ``&token=...``.
SECRET_QUERY_PATTERN = re.compile(
    r"([?&](?:tkn|token|connection-token)=)[^&#\s\"'<>]+", re.IGNORECASE
)
# A token on a line of its own, after the prefix a log puts before the text,
# which ends in ``: ``: one word of at least 20 letters, digits, ``-`` or
# ``_`` holding a digit.
SECRET_LINE_PATTERN = re.compile(
    r"^((?:.*:[ \t]+)?)(?=[A-Za-z_-]*\d)[A-Za-z0-9_-]{20,}[ \t]*$", re.MULTILINE
)


def mask_secrets(text: str) -> str:
    """The text with every token it shows replaced by ``***``.

    Args:
        text: A journal's or an installer's output, one or more lines.

    Returns:
        The text, a URL's ``tkn``, ``token`` or ``connection-token`` value
        and a line that is one token after its prefix masked.
    """
    text = SECRET_QUERY_PATTERN.sub(r"\1" + SECRET_MASK, text)
    return SECRET_LINE_PATTERN.sub(r"\1" + SECRET_MASK, text)


def file_tail(path: str, lines: int, *, needle: str = "", skipped: str = "") -> list:
    """The last lines of one file, oldest first.

    Args:
        path: The file.
        lines: How many lines to return at most.
        needle: Text a line holds to be returned; empty returns every line.
        skipped: A pattern matched at a line's start; a line it matches is
            left out. Empty leaves none out.

    Returns:
        The non-blank lines; none while the file does not exist. With a
        needle the read reaches further back, so lines about one module are
        found among many others.

    Raises:
        OSError: When the file exists and cannot be read, or the path is a
            link or no file.
    """
    limit = tail_limit(needle)
    try:
        descriptor = os.open(path, LOG_READ_FLAGS)
    except FileNotFoundError:
        return []
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(f"{path} is no file")
        size = stream.seek(0, os.SEEK_END)
        start = max(0, size - limit)
        stream.seek(start)
        data = stream.read()
    return tail_lines(data, start > 0, lines, needle=needle, skipped=skipped)


def account_file_tail(files, path: str, lines: int) -> list:
    """The last lines of one file in an account's place, read as the account, oldest first.

    Args:
        files: The :class:`AccountFiles` of the account whose place holds
            the file.
        path: The file.
        lines: How many lines to return at most.

    Returns:
        The non-blank lines; none while the file does not exist.

    Raises:
        OSError: When the file exists and cannot be read.
        ModuleApplyError: When it cannot be read as the account.
    """
    held = files.read_tail(path, tail_limit())
    if held is None:
        return []
    size, data = held
    return tail_lines(data, size > len(data), lines)


def tail_limit(needle: str = "") -> int:
    """How many bytes of a log's end are read: more when a needle is looked for. Pure."""
    return AGENT_MODULE_LOG_SEARCH_BYTES if needle else AGENT_MODULE_LOG_TAIL_BYTES


def tail_lines(
    data: bytes, is_cut: bool, lines: int, *, needle: str = "", skipped: str = ""
) -> list:
    """The last lines of a log's end, oldest first. Pure.

    Args:
        data: The end of the file.
        is_cut: Whether the file holds more before it; its first line, a
            part of one, is then left out.
        lines: How many lines to return at most.
        needle: Text a line holds to be returned; empty returns every line.
        skipped: A pattern matched at a line's start; a line it matches is
            left out. Empty leaves none out.

    Returns:
        The non-blank lines.
    """
    held = data.decode("utf-8", errors="replace").splitlines()
    if is_cut and held:
        held = held[1:]
    kept = [
        line
        for line in held
        if line.strip() and needle in line and not (skipped and re.match(skipped, line))
    ]
    return kept[-lines:] if lines > 0 else []
