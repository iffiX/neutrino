"""How ``nhub run`` starts the proxy core, given through the edition table.

``nhub run --only-xray`` runs xray as its child through the log filter,
which is what its unit starts on Linux; a plain ``nhub run`` starts it as a
child; outside Linux the hub's one service holds its start line.
"""

import os
import signal
import subprocess
import sys
import time

from neutrino_hub.modules.xray.constants import (
    XRAY_ASSET_DIR,
    XRAY_ASSET_ENV,
    XRAY_BINARY,
    XRAY_CONFIG_PATH,
    XRAY_SUPERVISED_NAME,
)
from neutrino_hub.modules.xray.log_filter import XrayLogFilter
from neutrino_hub.system.child_supervisor import ChildStartLine


def child_start_lines() -> dict:
    """The proxy core's start line, for the hub's one service.

    Returns:
        ``xray`` to its :class:`ChildStartLine`.
    """
    return {
        XRAY_SUPERVISED_NAME: ChildStartLine(
            argv=[XRAY_BINARY, "run", "-config", str(XRAY_CONFIG_PATH)],
            env={XRAY_ASSET_ENV: str(XRAY_ASSET_DIR)},
        )
    }


def run_xray() -> int:
    """Run the proxy core as a child, writing on the lines its log filter keeps.

    The child takes the unit's account and its ambient capabilities.

    Returns:
        xray's exit status.

    Raises:
        OSError: When the binary cannot be run.
    """
    return filter_child(
        [XRAY_BINARY, "run", "-config", str(XRAY_CONFIG_PATH)],
        {XRAY_ASSET_ENV: str(XRAY_ASSET_DIR)},
        sys.stdout,
    )


def filter_child(argv: list, env: dict, output) -> int:
    """Run one program and write on each line of its output the log filter keeps.

    A SIGTERM or SIGINT this process receives goes on to the child.

    Args:
        argv: The program and its arguments.
        env: Variables added to this process's environment.
        output: Where the kept lines are written.

    Returns:
        The child's exit status, 128 and the signal's number for a child a
        signal ended.

    Raises:
        OSError: When the program cannot be run.
    """
    child = subprocess.Popen(
        argv,
        env={**os.environ, **env},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    def pass_on(number, _frame) -> None:
        child.send_signal(number)

    # The handlers this process had, put back once the child ended.
    held = {
        number: signal.signal(number, pass_on)
        for number in (signal.SIGTERM, signal.SIGINT)
    }
    keeper = XrayLogFilter()
    try:
        for line in child.stdout:
            if keeper.is_kept(line, now=time.monotonic()):
                output.write(line)
                output.flush()
        code = child.wait()
    finally:
        for number, handler in held.items():
            signal.signal(number, handler)
    return 128 - code if code < 0 else code


# ``nhub run --only-<name>`` for the proxy's daemon.
RUN_ONLY = {XRAY_SUPERVISED_NAME: run_xray}
# The children a plain ``nhub run`` starts on Linux, by the binary each needs.
RUN_CHILDREN = {XRAY_SUPERVISED_NAME: XRAY_BINARY}
