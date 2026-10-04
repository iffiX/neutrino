"""How the hub's one service runs its own NetBird daemon outside Linux.

Given through the edition table: the daemon's start line, with its profile
under the state root, its log file, and where its own output goes, which is
not that file.
"""

from neutrino_hub.modules.netbird.constants import (
    NETBIRD_BINARY_PATH,
    NETBIRD_HUB_CONFIG_NAME,
    NETBIRD_HUB_STATE_DIR,
    NETBIRD_SUPERVISED_NAME,
)
from neutrino_hub.platforms.detect import hub_platform
from neutrino_hub.system.child_supervisor import ChildStartLine
from neutrino_hub.utils.constants import UTILS_LOG_ROOT

NETBIRD_LOG_NAME = "netbird.log"
NETBIRD_CONSOLE_LOG_NAME = "netbird_console"


def child_start_lines() -> dict:
    """The daemon's start line, for the hub's one service.

    Returns:
        ``netbird`` to its :class:`ChildStartLine`.
    """
    return {
        NETBIRD_SUPERVISED_NAME: ChildStartLine(
            argv=[
                str(NETBIRD_BINARY_PATH),
                "service",
                "run",
                "--config",
                str(NETBIRD_HUB_STATE_DIR / NETBIRD_HUB_CONFIG_NAME),
                "--log-file",
                str(UTILS_LOG_ROOT / NETBIRD_LOG_NAME),
                "--daemon-addr",
                hub_platform().netbird_daemon_address(),
            ],
            log_name=NETBIRD_CONSOLE_LOG_NAME,
        )
    }


def make_directories() -> None:
    """Make the directory the daemon keeps its profile in, as the service starts.

    Raises:
        OSError: When it cannot be made.
    """
    NETBIRD_HUB_STATE_DIR.mkdir(parents=True, exist_ok=True)
