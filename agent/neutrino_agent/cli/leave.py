"""``nagent leave``: leave the hub, keeping the agent and its service."""

from neutrino_agent.cli.status import STATUS_UNBOUND
from neutrino_agent.core import enrollment
from neutrino_agent.core.loop import Agent


def main() -> int:
    """Leave the hub.

    Returns:
        Process exit status.
    """
    if not enrollment.is_bound():
        print(STATUS_UNBOUND)
        return 1
    Agent().leave()
    print("left the hub; this machine keeps the agent and can join again")
    return 0
