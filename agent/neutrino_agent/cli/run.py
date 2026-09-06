"""``nagent run``: the agent in the foreground.

This is what the systemd unit and the launchd job start. The control socket
always serves — it is how ``nagent`` and ``nagent gui`` reach the running
agent.

Windows starts the same command with ``--windows-service``, which the service
control manager passes nothing else about: the loop is the same, wrapped in
the handshake a service process owes its manager.
"""

from neutrino_agent.constants import AGENT_SERVICE_NAME_WINDOWS
from neutrino_agent.control.server import ControlServer
from neutrino_agent.core.loop import Agent
from neutrino_agent.platforms.detect import detect_platform


def main(*, is_windows_service: bool = False) -> int:
    """Run the agent in the foreground.

    Args:
        is_windows_service: Whether the service control manager started this
            process and is waiting to be answered.

    Returns:
        Process exit status.
    """
    platform = detect_platform()
    agent = Agent(platform=platform)
    ControlServer(agent=agent, platform=platform).start()
    if is_windows_service:
        from neutrino_agent.platforms import windows_service

        windows_service.host_service(
            name=AGENT_SERVICE_NAME_WINDOWS, run=agent.run_forever
        )
        return 0
    agent.run_forever()
    return 0
