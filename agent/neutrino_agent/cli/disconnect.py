"""``nagent disconnect``: leave the hub, keeping the agent and its page."""

from neutrino_agent import enrollment
from neutrino_agent.agent import Agent
from neutrino_agent.cli.status import STATUS_UNBOUND


def main() -> int:
    """Leave the hub.

    Returns:
        Process exit status.
    """
    if not enrollment.is_configured():
        print(STATUS_UNBOUND)
        return 1
    Agent().disconnect()
    print("left the hub; this machine keeps the agent and can join again")
    return 0
