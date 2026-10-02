"""Say what the hub runs on this box.

    nhub status

On Linux one line per unit of the hub: whether it is installed, running and
enabled. On macOS and Windows one line for the hub's one service, which runs
every daemon.
"""

import argparse
import sys

from neutrino_hub.platforms.constants import PLATFORM_SERVICE_RUNNING
from neutrino_hub.platforms.detect import hub_platform, is_linux, process_controller


def main() -> int:
    """Print the state of what the hub runs.

    Returns:
        Process exit status: 0 when the hub runs, 1 when it does not.
    """
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    if not is_linux():
        state = hub_platform().service_state()
        print(f"  hub service: {state}")
        return 0 if state == PLATFORM_SERVICE_RUNNING else 1
    is_running = False
    for status in process_controller().status_all():
        if not status.is_installed:
            print(f"  {status.name}: not installed")
            continue
        running = "running" if status.is_active else "stopped"
        enabled = "enabled" if status.is_enabled else "disabled"
        print(f"  {status.name}: {running}, {enabled}")
        is_running = is_running or (status.name == "web" and status.is_active)
    return 0 if is_running else 1


if __name__ == "__main__":
    sys.exit(main())
