"""The last lines of a log file, and the mask every journal passes through.

Only the end of the file is read. The file is opened for reading alone,
which on Windows shares it with the handle the agent's logging writes
through. :func:`mask_secrets` hides a token in a URL's query and a token
printed on a line of its own.

Not pure: reads files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re

from neutrino_agent.constants import (
    AGENT_MODULE_LOG_SEARCH_BYTES,
    AGENT_MODULE_LOG_TAIL_BYTES,
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


def file_tail(path: str, lines: int, *, needle: str = "") -> list:
    """The last lines of one file, oldest first.

    Args:
        path: The file.
        lines: How many lines to return at most.
        needle: Text a line holds to be returned; empty returns every line.

    Returns:
        The non-blank lines. With a needle the read reaches further back,
        so lines about one module are found among many others.

    Raises:
        OSError: When the file cannot be read.
    """
    limit = AGENT_MODULE_LOG_SEARCH_BYTES if needle else AGENT_MODULE_LOG_TAIL_BYTES
    with open(path, "rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        start = max(0, size - limit)
        stream.seek(start)
        data = stream.read()
    held = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and held:
        held = held[1:]
    kept = [line for line in held if line.strip() and needle in line]
    return kept[-lines:] if lines > 0 else []
