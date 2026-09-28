"""What one client is allowed, by kind.

A kind is a published service type, joining the hub's overlay, or opening a
shell on a managed machine. A client follows the default set unless it has a
set of its own. Pure functions: the registry is read by the caller.
"""

from neutrino_hub.modules.clients.constants import CLIENT_PERMISSION_KINDS


def permission_kinds(kinds) -> list:
    """A set of permission kinds in the one order every surface lists them.

    Args:
        kinds: The kinds, in any order, repeats allowed.

    Returns:
        The kinds, each once, in :data:`CLIENT_PERMISSION_KINDS` order.

    Raises:
        ValueError: If one of them is not a permission kind.
    """
    chosen = set(kinds)
    unknown = sorted(chosen - set(CLIENT_PERMISSION_KINDS))
    if unknown:
        raise ValueError(f"{unknown[0]!r} is not a permission kind")
    return [kind for kind in CLIENT_PERMISSION_KINDS if kind in chosen]


def permitted_kinds(registry, client) -> frozenset:
    """The kinds one client is allowed now.

    Args:
        registry: The :class:`ClientRegistry` holding the default set.
        client: The client.

    Returns:
        Its own set when it has one, else the default set.
    """
    if client.permission is not None:
        return frozenset(client.permission)
    return frozenset(registry.default_permission())


def permitted_entries(entries: list, kinds) -> list:
    """The published entries whose type is among the allowed kinds.

    Args:
        entries: The published entries, each with a ``type``.
        kinds: The allowed kinds.

    Returns:
        The entries allowed, in their given order.
    """
    return [entry for entry in entries if entry["type"] in kinds]
