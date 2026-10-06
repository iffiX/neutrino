"""``nagent leave``: leave the hub, keeping the agent and its service."""

from neutrino_agent.cli.start import is_confirmed
from neutrino_agent.cli.status import STATUS_UNBOUND
from neutrino_agent.cli.wording import ai_tools_lines
from neutrino_agent.core import enrollment
from neutrino_agent.core.loop import Agent

LEAVE_QUESTION = (
    "leave the hub? This machine leaves the hub; the agent and its service "
    "stay [y/N] "
)


def main(*, is_forced: bool) -> int:
    """Leave the hub, after asking unless told not to.

    Args:
        is_forced: Leave without asking.

    Returns:
        Process exit status: 0 when the machine left, 1 when it is bound to
        no hub or the answer was no.
    """
    if not enrollment.is_bound():
        print(STATUS_UNBOUND)
        return 1
    if not is_forced and not is_confirmed(LEAVE_QUESTION):
        print("nothing changed")
        return 1
    for line in ai_tools_lines(Agent().leave()):
        print(line)
    print("left the hub; this machine keeps the agent and can join again")
    return 0
