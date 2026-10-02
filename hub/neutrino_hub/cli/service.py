"""Run the hub as the Windows service.

    nhub service run          # what the service control manager starts

The dispatcher is handed the process first, inside the manager's 30
seconds; the panel and its children start once the service reports running,
as ``nhub run`` starts them. The process's own output goes to ``web.log``
under the log root, which is the panel's journal there. A stop ends the
panel and every child before the service reports stopped.
"""

import argparse
import sys
import threading

from neutrino_hub.cli import run as run_command
from neutrino_hub.platforms.constants import (
    PLATFORM_OS_WINDOWS,
    PLATFORM_WINDOWS_SERVICE_NAME,
)
from neutrino_hub.platforms.detect import hub_os, process_controller
from neutrino_hub.platforms.windows_service import ServiceControlDispatcher
from neutrino_hub.system.constants import (
    SYSTEM_CHILD_LOG_MAX_BYTES,
    SYSTEM_CHILD_LOG_SUFFIX,
    SYSTEM_SUPERVISED_WEB,
)
from neutrino_hub.utils.constants import UTILS_LOG_ROOT

# --- config ---
# How long a stop waits for the panel and its children to end.
SERVICE_STOP_WAIT_S = 30
SERVICE_NOT_FROM_MANAGER = (
    "nhub service run is started by the service control manager; "
    "run nhub start in an administrator PowerShell instead"
)
SERVICE_NOT_WINDOWS = "nhub service run is the Windows service; run nhub run here"


def main() -> int:
    """Run the hub under the service control manager.

    Returns:
        Process exit status; 1 when the process was not started as a
        service, 2 off Windows.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("verb", choices=("run",), help="what to do")
    parser.parse_args()
    if hub_os() != PLATFORM_OS_WINDOWS:
        print(f"error: {SERVICE_NOT_WINDOWS}", file=sys.stderr)
        return 2
    ended = threading.Event()

    def on_start() -> None:
        _write_output_to_log()
        try:
            sys.argv = ["nhub run"]
            run_command.main()
        finally:
            ended.set()

    def on_stop() -> None:
        run_command.stop_serving()
        ended.wait(SERVICE_STOP_WAIT_S)
        process_controller().shutdown()

    dispatcher = ServiceControlDispatcher(
        PLATFORM_WINDOWS_SERVICE_NAME, on_start, on_stop
    )
    try:
        dispatcher.run()
    except OSError as error:
        print(f"error: {SERVICE_NOT_FROM_MANAGER} ({error})", file=sys.stderr)
        return 1
    return 0


def _write_output_to_log() -> None:
    """Point this process's output at ``web.log``, kept once when it grew too big."""
    UTILS_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    path = UTILS_LOG_ROOT / f"{SYSTEM_SUPERVISED_WEB}{SYSTEM_CHILD_LOG_SUFFIX}"
    if path.is_file() and path.stat().st_size > SYSTEM_CHILD_LOG_MAX_BYTES:
        path.replace(path.with_name(path.name + ".1"))
    stream = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
