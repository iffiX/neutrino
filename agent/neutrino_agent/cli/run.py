"""``nagent run``: the agent in the foreground.

This is what the systemd unit, the launchd job and the Windows scheduled
task start. The control socket always serves — it is how ``nagent`` and
``nagent ui`` reach the running agent; ``--no-ui`` only withholds the
loopback page.
"""

from neutrino_agent.control.server import ControlServer
from neutrino_agent.core.loop import Agent
from neutrino_agent.platforms.detect import detect_platform


def main(*, is_ui_served: bool) -> int:
    """Run the agent in the foreground.

    Args:
        is_ui_served: Serve the loopback page as well as the socket.

    Returns:
        Process exit status.
    """
    platform = detect_platform()
    agent = Agent(platform=platform)
    ControlServer(agent=agent, platform=platform, is_page_served=is_ui_served).start()
    agent.run_forever()
    return 0
