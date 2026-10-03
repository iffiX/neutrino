"""``nagent run``: the agent in the foreground.

This is the entry the systemd unit and the LaunchDaemon start; a person
starts and stops the service with ``nagent start`` and ``nagent stop``. The
control socket always serves: it is how ``nagent`` reaches the running agent.
SIGTERM ends the process at once: the agent holds nothing that needs a
graceful stop.
"""

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
    try:
        agent.run_forever()
    finally:
        control.stop()
    return 0
