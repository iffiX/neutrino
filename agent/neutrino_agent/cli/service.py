"""``nagent service run`` and ``nagent service uninstall``: the entries the
system's service manager and the package's removal run.

``run`` is what the Windows service control manager starts. The dispatcher
is handed the process first, inside the manager's 30 seconds; the agent and
its control pipe are built once the service reports running. A stop only
asks the agent's loop to end, so the manager hears back at once; the
control pipe closes once the loop has ended. Its log goes to ``agent.log``
under the agent's log root, rotated.

``uninstall`` takes away what the agent's modules added in order to run and
to fence, and leaves what the machine serves: shares, accounts and the
modules' data stay. The deb's and the rpm's removal and the Windows
installer's removal run it, and an upgrade never does. On macOS, which has
no uninstaller, it removes the agent itself as well.
"""

import logging
import logging.handlers
import os
import sys
import threading

from neutrino_agent.ai_tools.applier import AiToolsApplier
from neutrino_agent.cli.start import is_confirmed
from neutrino_agent.constants import AGENT_WINDOWS_SERVICE_NAME
from neutrino_agent.control.server import ControlServer
from neutrino_agent.core.loop import Agent
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform
from neutrino_agent.platforms.windows_service import ServiceControlDispatcher

# --- config ---
SERVICE_LOG_MAX_BYTES = 1024 * 1024
SERVICE_LOG_BACKUP_COUNT = 3
SERVICE_LOG_FORMAT = "%(asctime)s %(message)s"
SERVICE_NOT_FROM_MANAGER = (
    "nagent service run is started by the service control manager; "
    "run nagent run in a terminal instead"
)
UNINSTALL_QUESTION = (
    "stop the agent and remove the units, launchd jobs, scheduled tasks and "
    "firewall rules its modules added? Shares and accounts stay [y/N] "
)
UNINSTALL_QUESTION_DARWIN = (
    "remove the agent from this Mac, with the launchd jobs and the fence its "
    "modules added? Shares, accounts, the binding and the state stay [y/N] "
)


def main_run() -> int:
    """Run the agent under the service control manager.

    Returns:
        Process exit status; 1 when the process was not started as a service.
    """
    platform = detect_platform()
    log = service_log(platform.agent_log_path())
    held: dict = {}
    is_stop_asked = threading.Event()

    def on_start() -> None:
        agent = Agent(log=log, platform=platform)
        control = ControlServer(agent=agent, platform=platform, log=log)
        held["agent"] = agent
        control.start()
        try:
            if not is_stop_asked.is_set():
                agent.run_forever()
        finally:
            control.stop()

    def on_stop() -> None:
        log("service stopping")
        is_stop_asked.set()
        agent = held.get("agent")
        if agent is not None:
            agent.stop()

    dispatcher = ServiceControlDispatcher(AGENT_WINDOWS_SERVICE_NAME, on_start, on_stop)
    try:
        dispatcher.run()
    except OSError as error:
        print(f"{SERVICE_NOT_FROM_MANAGER} ({error})", file=sys.stderr)
        return 1
    return 0


def main_uninstall(*, is_forced: bool) -> int:
    """Stop the agent, switch the accounts' AI tools back, and take away what its modules added.

    The service stops first, so no apply of its own runs beside the switch
    back.

    Args:
        is_forced: Go ahead without asking.

    Returns:
        Process exit status: 0 when the removal ran, 1 when the answer was
        no or the platform has nothing to remove.
    """
    platform = detect_platform()
    is_whole = "self_removal" in platform.capabilities
    question = UNINSTALL_QUESTION_DARWIN if is_whole else UNINSTALL_QUESTION
    if not is_forced and not is_confirmed(question):
        print("nothing changed")
        return 1
    try:
        platform.stop_agent_service()
        for switched in AiToolsApplier(platform=platform, log=print).switch_back_all():
            print(
                f"ai tools   {switched['account']}: "
                f"{switched['state']} {switched['code']}".rstrip()
            )
        removed = platform.remove_added()
        if is_whole:
            removed += platform.remove_agent_program()
    except PlatformUnsupportedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: the removal stopped: {error}", file=sys.stderr)
        return 1
    for name in removed:
        print(f"removed    {name}")
    return 0


def service_log(path: str):
    """A log callable that writes to the agent's log file.

    Args:
        path: The log file, ``agent.log`` under the log root.

    Returns:
        A callable taking one message.
    """
    logger = logging.Logger("neutrino_agent.service", logging.INFO)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=SERVICE_LOG_MAX_BYTES,
        backupCount=SERVICE_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(SERVICE_LOG_FORMAT))
    logger.addHandler(handler)

    def log(message: str) -> None:
        logger.info(str(message))

    return log
