"""Admission: the check on a peer's protocol number at join and in hello."""

from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_PROTOCOL_TOO_NEW,
    CHANNEL_CODE_PROTOCOL_TOO_OLD,
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
