"""``nagent run``: the agent in the foreground.

This is the entry the systemd unit and the LaunchDaemon start; a person
starts and stops the service with ``nagent start`` and ``nagent stop``. The
control socket always serves: it is how ``nagent`` reaches the running agent.
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
    ControlServer(agent=agent, platform=platform).start()
    agent.run_forever()
    return 0
