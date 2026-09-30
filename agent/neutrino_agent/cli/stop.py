"""``nagent stop``: stop the agent's service.

Linux asks systemd, Windows the service control manager, macOS launchd.
The service stays installed and starts again at the next boot, and the
binding is kept; leaving the hub is ``nagent leave``.
"""

import sys

from neutrino_agent.cli.start import is_confirmed
from neutrino_agent.cli.status import service_state, settled_service_state
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

STOP_QUESTION = (
    "stop the agent's service? The hub loses this machine until it starts "
    "again [y/N] "
)
STOP_NO_SERVICE = "error: this machine has no agent service to stop"
# The states that say the service is down.
STOPPED_STATES = ("stopped", "inactive", "failed")


def main(*, is_forced: bool) -> int:
    """Stop the agent's service, after asking unless told not to.

    Args:
        is_forced: Stop without asking.

    Returns:
        Process exit status: 0 when the service is down afterwards, 1 when
        it is not or the answer was no.
    """
    state = service_state()
    if state in STOPPED_STATES:
        print(f"service    {state}")
        return 0
    if not is_forced and not is_confirmed(STOP_QUESTION):
        print("nothing changed")
        return 1
    try:
        detect_platform().stop_agent_service()
    except PlatformUnsupportedError:
        print(STOP_NO_SERVICE, file=sys.stderr)
        return 1
    state = settled_service_state()
    print(f"service    {state}")
    if state not in STOPPED_STATES:
        print("error: the service did not stop", file=sys.stderr)
        return 1
    return 0
