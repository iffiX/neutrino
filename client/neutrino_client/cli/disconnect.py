"""``nclient disconnect``: leave the hub.

The hub is told first, but one that cannot be reached does not hold the
person: the binding goes either way, and a running resident lets go of
everything on its next poll.
"""

from neutrino_client.cli import wording
from neutrino_client.constants import CLIENT_LEAVE_PATH
from neutrino_client.core import enrollment
from neutrino_client.core.channel import (
    GatewayHttpChannel,
    GatewayUnreachable,
    GatewayUntrusted,
)

LEAVE_WORDS = "left the hub; this person can join again with a fresh link"


def main() -> int:
    """Leave the hub.

    Returns:
        Process exit status.
    """
    config = enrollment.load_config()
    if not (config.get("gateway_url") and config.get("token")):
        print(wording.NOT_JOINED)
        return 1
    channel = GatewayHttpChannel(
        gateway_url=str(config.get("gateway_url", "")),
        token=str(config.get("token", "")),
        fingerprint=str(config.get("fingerprint", "")),
    )
    try:
        channel.post(CLIENT_LEAVE_PATH, {})
    except (GatewayUnreachable, GatewayUntrusted, RuntimeError):
        pass
    enrollment.disconnect()
    print(LEAVE_WORDS)
    return 0
