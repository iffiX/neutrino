"""Ordering release versions.

The hub and the agent share a version and are released together, so version
comparisons decide who must move: a newer agent is turned away, an older one
updates itself. Both decisions need the dotted integers, not the string.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


def parse_version(text: str) -> "tuple | None":
    """The dotted integers of a release version, for ordering.

    Args:
        text: A version like ``0.1.0``; a ``+suffix`` is ignored.

    Returns:
        The numeric parts as a tuple, or None when the text holds none.
    """
    base = (text or "").split("+", 1)[0].strip()
    if not base:
        return None
    parts = []
    for piece in base.split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    return tuple(parts)
