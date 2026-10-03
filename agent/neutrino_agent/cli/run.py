"""``nagent run``: the agent in the foreground.

This is the entry the systemd unit and the LaunchDaemon start; a person
starts and stops the service with ``nagent start`` and ``nagent stop``. The
control socket always serves: it is how ``nagent`` reaches the running agent.
SIGTERM ends the process at once: the agent holds nothing that needs a
graceful stop.
"""

import functools

from neutrino_agent.cli.service import service_log
from neutrino_agent.control.server import ControlServer
from neutrino_agent.core.loop import Agent
from neutrino_agent.platforms.detect import detect_platform

# The system whose service manager hands the process a log file rather than
# a journal, so the agent writes that file itself; a print would sit in a
# block buffer until the process ends.
FILE_LOGGED_OS = "darwin"


def main() -> int:
    """Run the agent in the foreground.

    Returns:
        Process exit status.
    """
    platform = detect_platform()
    log = log_sink(platform)
    agent = Agent(platform=platform, log=log)
    control = ControlServer(agent=agent, platform=platform, log=log)
    control.start()
    try:
        agent.run_forever()
    finally:
        control.stop()
    return 0


def log_sink(platform):
    """Where the running agent's lines go.

    Args:
        platform: The running platform.

    Returns:
        The agent's log file on macOS, a line-flushed print elsewhere, where
        the journal reads the process's output.
    """
    if platform.os_name == FILE_LOGGED_OS:
        return service_log(platform.agent_log_path())
    return functools.partial(print, flush=True)
