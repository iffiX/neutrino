"""The seat on macOS: the console's owner, netstat, and the privacy grants.

The account at the screen owns ``/dev/console``; at the login window root
does. The connected peers are the established rows ``netstat`` prints for
the direct port. A Mac shows a peer nothing until RustDesk holds both screen
recording and accessibility, which only somebody at that Mac can grant, so
the grants are read from the system's privacy database and a share says
``rdp_permissions_needed`` until both are there. A database this process
cannot read says the same: the share never claims a grant it did not see.

Not pure: runs stat and netstat and reads the privacy database.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import sqlite3
import subprocess

from neutrino_agent.rdp.constants import (
    RDP_ATTENTION_PERMISSIONS_NEEDED,
    RDP_DARWIN_CONSOLE_OWNER_COMMAND,
    RDP_DARWIN_ESTABLISHED,
    RDP_DARWIN_LOGIN_WINDOW_OWNER,
    RDP_DARWIN_NETSTAT_COMMAND,
    RDP_DARWIN_RUSTDESK_BUNDLE_ID,
    RDP_DARWIN_TCC_ALLOWED,
    RDP_DARWIN_TCC_DATABASE,
    RDP_DARWIN_TCC_SERVICES,
    RDP_SESSION_TIMEOUT_S,
)
from neutrino_agent.rdp.netstat import established_count

# The grants RustDesk holds among the two it needs.
DARWIN_TCC_QUERY = (
    "SELECT service FROM access WHERE lower(client) = ? AND auth_value = ? "
    "AND service IN ({})".format(", ".join("?" for _ in RDP_DARWIN_TCC_SERVICES))
)


def _printed(command) -> "str | None":
    """One command's standard output, None when it fails or is missing."""
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=RDP_SESSION_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def granted_services(database: str) -> "set | None":
    """The privacy grants RustDesk holds among the two it needs.

    Args:
        database: The privacy database.

    Returns:
        The granted service names, None when the database cannot be read.
    """
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = connection.execute(
            DARWIN_TCC_QUERY,
            (
                RDP_DARWIN_RUSTDESK_BUNDLE_ID,
                RDP_DARWIN_TCC_ALLOWED,
                *RDP_DARWIN_TCC_SERVICES,
            ),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return {row[0] for row in rows}


class DarwinSeat:
    """The macOS seat, behind the seat seam the share host reads."""

    def __init__(self, *, tcc_database: str = RDP_DARWIN_TCC_DATABASE):
        """
        Args:
            tcc_database: The privacy database the grants are read from.
        """
        self._tcc_database = tcc_database

    def graphical_accounts(self) -> "list | None":
        """The account that owns the console.

        Returns:
            ``[account]``, empty at the login window, None where the console
            cannot be asked.
        """
        printed = _printed(RDP_DARWIN_CONSOLE_OWNER_COMMAND)
        if printed is None:
            return None
        owner = printed.strip()
        if not owner or owner == RDP_DARWIN_LOGIN_WINDOW_OWNER:
            return []
        return [owner]

    def has_desktop_session(self) -> bool:
        """Whether there is a desktop to share: always, on a Mac."""
        return True

    def connected_count(self, port: int) -> int:
        """How many peers are connected to the direct port right now.

        Args:
            port: The local port a direct connection lands on.

        Returns:
            The number of established connections to it, zero when netstat
            cannot be run.
        """
        printed = _printed(RDP_DARWIN_NETSTAT_COMMAND)
        if printed is None:
            return 0
        return established_count(
            printed, port, established=RDP_DARWIN_ESTABLISHED, separator="."
        )

    def screen_attention(self, account_home: str) -> str:
        """Whether RustDesk holds both privacy grants a peer needs.

        Args:
            account_home: The home of the account the share is for.

        Returns:
            Empty when both are granted, ``rdp_permissions_needed`` when
            either is missing or the database cannot be read.
        """
        granted = granted_services(self._tcc_database)
        if granted is None or not set(RDP_DARWIN_TCC_SERVICES) <= granted:
            return RDP_ATTENTION_PERMISSIONS_NEEDED
        return ""
