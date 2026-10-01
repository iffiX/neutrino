"""``nagent service run``: the agent as the Windows service.

This is what the service control manager starts. The dispatcher is handed
the process first, inside the manager's 30 seconds; the agent and its
control pipe are built once the service reports running. Its log goes to
``agent.log`` under the agent's data root, rotated.
"""

import logging
import logging.handlers
import os
import sys

from neutrino_agent.constants import AGENT_WINDOWS_LOG_NAME, AGENT_WINDOWS_SERVICE_NAME
from neutrino_agent.control.server import ControlServer
from neutrino_agent.core.loop import Agent
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


def main_run() -> int:
    """Run the agent under the service control manager.

    Returns:
        Process exit status; 1 when the process was not started as a service.
    """
    platform = detect_platform()
    log = service_log(platform.agent_data_dir())
    held: dict = {}

    def on_start() -> None:
        agent = Agent(log=log, platform=platform)
        control = ControlServer(agent=agent, platform=platform, log=log)
        held["control"] = control
        control.start()
        agent.run_forever()

    def on_stop() -> None:
        log("service stopping")
        control = held.get("control")
        if control is not None:
            control.stop()

    dispatcher = ServiceControlDispatcher(AGENT_WINDOWS_SERVICE_NAME, on_start, on_stop)
    try:
        dispatcher.run()
    except OSError as error:
        print(f"{SERVICE_NOT_FROM_MANAGER} ({error})", file=sys.stderr)
        return 1
    return 0


def service_log(data_dir: str):
    """A log callable that writes to ``agent.log`` under the data root.

    Args:
        data_dir: The agent's data root.

    Returns:
        A callable taking one message.
    """
    logger = logging.Logger("neutrino_agent.service", logging.INFO)
    os.makedirs(data_dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(data_dir, AGENT_WINDOWS_LOG_NAME),
        maxBytes=SERVICE_LOG_MAX_BYTES,
        backupCount=SERVICE_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(SERVICE_LOG_FORMAT))
    logger.addHandler(handler)

    def log(message: str) -> None:
        logger.info(str(message))

    return log
