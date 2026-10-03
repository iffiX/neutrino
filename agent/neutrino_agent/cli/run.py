"""``nagent run``: the agent in the foreground.

This is the entry the systemd unit and the LaunchDaemon start; a person
starts and stops the service with ``nagent start`` and ``nagent stop``. The
control socket always serves: it is how ``nagent`` reaches the running agent.
On macOS, launchd's SIGTERM asks the loop to end, and the process exits at
most ``AGENT_SERVICE_STOP_WAIT_S`` later whether or not it has.
"""

import os
import signal
import sys
import threading

from neutrino_agent.constants import AGENT_SERVICE_STOP_WAIT_S
from neutrino_agent.control.server import ControlServer
from neutrino_agent.core.loop import Agent
from neutrino_agent.platforms.detect import detect_platform


def main() -> int:
    """Run the agent in the foreground.

    Returns:
        Process exit status.
    """
    platform = detect_platform()
    agent = Agent(platform=platform)
    control = ControlServer(agent=agent, platform=platform)
    control.start()
    if sys.platform == "darwin":
        _stop_on_terminate(agent)
    try:
        agent.run_forever()
    finally:
        control.stop()
    return 0


def _stop_on_terminate(agent) -> None:
    """Make SIGTERM a stop of the loop, with a deadline for the process."""

    def on_terminate(signum, frame) -> None:
        agent.stop()
        deadline = threading.Timer(AGENT_SERVICE_STOP_WAIT_S, os._exit, args=(0,))
        deadline.daemon = True
        deadline.start()

    signal.signal(signal.SIGTERM, on_terminate)
