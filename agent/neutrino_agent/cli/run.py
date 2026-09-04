"""``nagent run``: the agent in the foreground.

This is what the systemd unit, the launchd job and the Windows scheduled
task start.
"""

from neutrino_agent.agent import Agent
from neutrino_agent.mini_ui import MiniUiServer


def main(*, is_ui_served: bool) -> int:
    """Run the agent in the foreground.

    Args:
        is_ui_served: Serve the local page as well.

    Returns:
        Process exit status.
    """
    agent = Agent()
    if is_ui_served:
        MiniUiServer(agent=agent).start()
    agent.run_forever()
    return 0
