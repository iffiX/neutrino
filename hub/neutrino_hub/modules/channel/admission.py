"""Admission: the check on a peer's protocol number at join and in hello."""

from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_PROTOCOL_TOO_NEW,
    CHANNEL_CODE_PROTOCOL_TOO_OLD,
    CHANNEL_PROTOCOL_UPDATE_ONLY,
    CHANNEL_ROLE_AGENT,
    PROTOCOL,
    PROTOCOL_MIN,
)


def admit(protocol: int) -> "dict | None":
    """Judge whether a peer speaking a protocol number may talk to this hub.

    Args:
        protocol: The number the peer's join or hello named.

    Returns:
        None when ``PROTOCOL_MIN <= protocol <= PROTOCOL``, else the
        refusal ``{"code", "params"}`` with ``{peer, hub, min}``.
    """
    params = {"peer": protocol, "hub": PROTOCOL, "min": PROTOCOL_MIN}
    if protocol < PROTOCOL_MIN:
        return {"code": CHANNEL_CODE_PROTOCOL_TOO_OLD, "params": params}
    if protocol > PROTOCOL:
        return {"code": CHANNEL_CODE_PROTOCOL_TOO_NEW, "params": params}
    return None


def is_update_only(role: str, protocol: int) -> bool:
    """Whether a hello that :func:`admit` refuses is admitted for the agent's
    own update alone.

    Args:
        role: The role the hello named.
        protocol: The number the hello named.

    Returns:
        True for an agent speaking ``CHANNEL_PROTOCOL_UPDATE_ONLY``, the
        number of 0.5.
    """
    return role == CHANNEL_ROLE_AGENT and protocol == CHANNEL_PROTOCOL_UPDATE_ONLY
