"""``nagent connect``: join the hub an enrollment link names."""

import os
import sys

from neutrino_agent.cli.status import service_state
from neutrino_agent.core import enrollment
from neutrino_agent.core.loop import Agent
from neutrino_agent.exceptions import EnrollmentError, PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform


def main(link: str, *, is_forced: bool) -> int:
    """Join the hub the link names.

    Args:
        link: The enrollment link.
        is_forced: Replace an existing binding without asking.

    Returns:
        Process exit status.
    """
    link = link.strip()
    if not link:
        try:
            link = input("paste the enrollment link: ").strip()
        except EOFError:
            link = ""
    if not link:
        print("error: no link was given", file=sys.stderr)
        return 1
    bound_to = enrollment.load_config().get("gateway_url", "")
    if bound_to and not is_forced:
        answer = input(f"this machine is bound to {bound_to}; replace it? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("nothing changed")
            return 1
    try:
        Agent().connect(link)
    except EnrollmentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"joined {enrollment.load_config().get('gateway_url', '')}")
    if service_state() != "running":
        platform = detect_platform()
        try:
            platform.start_agent_service()
        except PlatformUnsupportedError:
            pass
        state = service_state()
        print(f"service    {state}")
        if state != "running":
            hint = platform.agent_service_start_hint()
            if hint:
                print(f"start it for heartbeats: {hint}", file=sys.stderr)
    return 0
