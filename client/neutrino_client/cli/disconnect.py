"""``nclient disconnect``: leave the hub.

The hub is told first, but one that cannot be reached does not hold the
person: the binding goes either way, and a running resident lets go of
everything on its next poll.
"""

from neutrino_client.cli import wording
from neutrino_client.core import enrollment
from neutrino_client.exceptions import (
    GatewayRefused,
    GatewayUnreachable,
    GatewayUntrusted,
)

LEAVE_WORDS = "left the hub; this person can join again with a fresh link"


def main() -> int:
    """Leave the hub.

    Returns:
        Process exit status.
    """
    held = enrollment.bindings()
    if not held:
        print(wording.NOT_JOINED)
        return 1
    binding = held[0]
    try:
        enrollment.leave(binding)
    except (GatewayRefused, GatewayUnreachable, GatewayUntrusted):
        pass
    enrollment.remove_binding(binding["id"])
    print(LEAVE_WORDS)
    return 0
