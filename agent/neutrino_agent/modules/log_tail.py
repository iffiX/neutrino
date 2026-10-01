"""The last lines of a log file, for a module's log where no journal keeps it.

Only the end of the file is read.

Not pure: reads files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os

from neutrino_agent.constants import AGENT_MODULE_LOG_TAIL_BYTES


def file_tail(path: str, lines: int, *, needle: str = "") -> list:
    """The last lines of one file, oldest first.

    Args:
        path: The file.
        lines: How many lines to return at most.
        needle: Text a line holds to be returned; empty returns every line.

    Returns:
        The non-blank lines, empty when the file cannot be read.
    """
    try:
        with open(path, "rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - AGENT_MODULE_LOG_TAIL_BYTES)
            stream.seek(start)
            data = stream.read()
    except OSError:
        return []
    held = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and held:
        held = held[1:]
    kept = [line for line in held if line.strip() and needle in line]
    return kept[-lines:] if lines > 0 else []
