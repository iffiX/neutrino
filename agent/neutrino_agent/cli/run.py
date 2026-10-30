"""``nagent run``: the agent in the foreground.

This is the entry the systemd unit and the LaunchDaemon start; a person
starts and stops the service with ``nagent start`` and ``nagent stop``. The
control socket always serves: it is how ``nagent`` reaches the running agent.
SIGTERM asks the agent to stop, so its relays close and their firewall rules
go before the process ends.
"""

import signal
import sys
import threading

from neutrino_agent.cli.service import service_log
from neutrino_agent.control.server import ControlServer
from neutrino_agent.core.loop import Agent
from neutrino_agent.platforms.detect import detect_platform

# The system whose service manager hands the process a log file rather than
# a journal, so the agent writes that file itself; a print would sit in a
# block buffer until the process ends.
FILE_LOGGED_OS = "darwin"
# Every line the running agent prints is written under this lock. Two threads
# printing at once otherwise put one line's text before another's newline.
_PRINT_LOCK = threading.Lock()


def main() -> int:
    """Run the agent in the foreground.

    Returns:
        Process exit status.
    """
    platform = detect_platform()
    log = log_sink(platform)
    agent = Agent(platform=platform, log=log)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: agent.stop())
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
        The agent's log file on macOS, :func:`print_line` elsewhere, where
        the journal reads the process's output.
    """
    if platform.os_name == FILE_LOGGED_OS:
        return service_log(platform.agent_log_path())
    return print_line


def print_line(message) -> None:
    """Print one message and its newline in one write, flushed.

    Args:
        message: The line, without its newline.
    """
    with _PRINT_LOCK:
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()
