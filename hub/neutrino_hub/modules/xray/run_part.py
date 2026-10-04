"""How ``nhub run`` starts the proxy core, given through the edition table.

``nhub run --only-xray`` becomes xray, which is what its unit starts on
Linux; a plain ``nhub run`` starts it as a child; outside Linux the hub's
one service holds its start line.
"""

import os

from neutrino_hub.modules.xray.constants import (
    XRAY_ASSET_DIR,
    XRAY_ASSET_ENV,
    XRAY_BINARY,
    XRAY_CONFIG_PATH,
    XRAY_SUPERVISED_NAME,
)
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


def exec_xray() -> int:
    """Become the proxy core.

    Replaces this process rather than forking one, so the unit's account and
    capabilities carry straight into the binary and nothing lingers between
    systemd and the daemon it is watching.

    Returns:
        Never; the process is replaced.

    Raises:
        OSError: When the binary cannot be run.
    """
    os.environ[XRAY_ASSET_ENV] = XRAY_ASSET_DIR
    os.execv(XRAY_BINARY, [XRAY_BINARY, "run", "-config", str(XRAY_CONFIG_PATH)])
    return 1


# ``nhub run --only-<name>`` for the proxy's daemon.
RUN_ONLY = {XRAY_SUPERVISED_NAME: exec_xray}
# The children a plain ``nhub run`` starts on Linux, by the binary each needs.
RUN_CHILDREN = {XRAY_SUPERVISED_NAME: XRAY_BINARY}
