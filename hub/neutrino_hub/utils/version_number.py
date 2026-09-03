"""Ordering release versions.

The hub and the agent share a version and are released together, so version
comparisons decide who must move: a newer agent is turned away, an older one
updates itself. Both decisions need the dotted integers, not the string.
"""


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
