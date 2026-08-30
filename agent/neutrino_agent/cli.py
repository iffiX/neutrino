"""Run the neutrino_agent agent.

This is what the systemd unit starts. An agent runs whether or not it has
joined a gateway yet: unenrolled, it serves only its own page at
http://127.0.0.1:8765, which is where the owner pastes the link that joins it.

    nagent
    nagent --once      # one heartbeat, for checking setup
    nagent --no-ui     # no local page, for headless boxes
"""

import argparse
import sys

from neutrino_agent import enrollment
from neutrino_agent.agent import Agent
from neutrino_agent.mini_ui import MiniUiServer


def main() -> int:
    """Start the agent.

    Returns:
        Process exit status: 0 on a clean stop, 1 when ``--once`` was asked
        for on a machine that has joined no gateway.
    """
    parser = argparse.ArgumentParser(prog="nagent", description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="send a single heartbeat and exit, for verifying an install",
    )
    parser.add_argument(
        "--no-ui", action="store_true", help="do not serve the local page"
    )
    args = parser.parse_args()

    agent = Agent()
    if args.once:
        if not enrollment.is_configured():
            print(
                "error: this machine has joined no gateway; open "
                "http://127.0.0.1:8765 and paste an enrollment link",
                file=sys.stderr,
            )
            return 1
        delay = agent.run_once()
        error = agent.last_error()
        if error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(f"heartbeat sent; the agent would next report in {delay}s")
        return 0

    if not args.no_ui:
        MiniUiServer(agent=agent).start()
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
