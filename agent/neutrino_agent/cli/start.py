"""``nagent start``: start the agent's service.

Linux asks systemd, Windows the service control manager, macOS launchd.
The binding is not touched: a machine that joined no hub runs a service
that reports to nobody until ``nagent join``.
"""

import sys

from neutrino_agent.cli.status import service_state, settled_service_state
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

START_QUESTION = "start the agent's service? [y/N] "
START_NO_SERVICE = "error: this machine has no agent service to start"
NO_TERMINAL_LINE = (
    "error: no terminal to answer on; run it again with --yes to go ahead "
    "without asking"
)


def main(*, is_forced: bool) -> int:
    """Start the agent's service, after asking unless told not to.

    Args:
        is_forced: Start without asking.

    Returns:
        Process exit status: 0 when the service runs afterwards, 1 when it
        does not or the answer was no.
    """
    if service_state() == "running":
        print("service    running")
        return 0
    if not is_forced and not is_confirmed(START_QUESTION):
        print("nothing changed")
        return 1
    platform = detect_platform()
    try:
        platform.start_agent_service()
    except PlatformUnsupportedError:
        print(START_NO_SERVICE, file=sys.stderr)
        return 1
    state = settled_service_state()
    print(f"service    {state}")
    if state != "running":
        hint = platform.agent_service_start_hint()
        if hint:
            print(f"the service did not start; try: {hint}", file=sys.stderr)
        return 1
    return 0


def is_confirmed(question: str) -> bool:
    """Ask one yes-or-no question on the terminal.

    With no terminal on stdin nothing is asked: one line on stderr says that
    ``--yes`` goes ahead without asking.

    Args:
        question: The question, ending in ``[y/N]``.

    Returns:
        True only for ``y`` or ``yes``; no input and no terminal are a no.
    """
    if sys.stdin is None or not sys.stdin.isatty():
        print(NO_TERMINAL_LINE, file=sys.stderr)
        return False
    try:
        answer = input(question)
    except EOFError:
        print()
        return False
    return answer.strip().lower() in ("y", "yes")
