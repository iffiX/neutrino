"""The seat on Linux: who is at the screen, and what a peer would wait on.

``loginctl`` names the sessions and their owners, a seated account's display
comes off its own processes in ``/proc``, the established connections come
from ``/proc/net/tcp``, and on Wayland the screen permission RustDesk holds
is read from the configuration it wrote.

Not pure: runs ``loginctl`` and reads ``/proc``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess

from neutrino_agent.modules import rustdesk
from neutrino_agent.rdp.constants import (
    RDP_ATTENTION_SCREEN_NOT_ALLOWED,
    RDP_GRAPHICAL_SESSION_TYPES,
    RDP_PROC_DIR,
    RDP_PROC_TCP_PATHS,
    RDP_SESSION_ENVIRONMENT_KEYS,
    RDP_SESSION_TIMEOUT_S,
    RDP_TCP_ESTABLISHED,
    RDP_WAYLAND_TOKEN_OPTION,
)

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None


def session_environment(account: str) -> "dict | None":
    """One seated account's display environment, off its own processes.

    Args:
        account: The seated account.

    Returns:
        The display variables, or None when no process of that account
        carries a display.
    """
    try:
        uid = pwd.getpwnam(account).pw_uid
    except KeyError:
        return None
    try:
        pids = sorted((p for p in os.listdir(RDP_PROC_DIR) if p.isdigit()), key=int)
    except OSError:
        return None
    for pid in pids:
        path = os.path.join(RDP_PROC_DIR, pid)
        try:
            if os.stat(path).st_uid != uid:
                continue
            with open(os.path.join(path, "environ"), "rb") as stream:
                raw = stream.read()
        except OSError:
            continue
        pairs = dict(
            item.split("=", 1)
            for item in raw.decode("utf-8", "replace").split("\0")
            if "=" in item
        )
        if not (pairs.get("DISPLAY") or pairs.get("WAYLAND_DISPLAY")):
            continue
        return {key: pairs[key] for key in RDP_SESSION_ENVIRONMENT_KEYS if key in pairs}
    return None


def has_desktop_session() -> bool:
    """Whether this machine has a desktop for RustDesk to share.

    Returns:
        True on a machine that cannot be asked, so only one that positively
        has no graphical session is refused.
    """
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    seated = graphical_accounts()
    return True if seated is None else bool(seated)


def graphical_accounts() -> "list | None":
    """The accounts signed in at this machine's screen.

    ``loginctl`` lists each session with its owner, and answers the type of
    every session it is asked about in the order it was asked.

    Returns:
        The owning accounts of the graphical sessions, or None on a box
        without ``loginctl``, which says nothing at all.
    """
    listed = _loginctl(["list-sessions", "--no-legend"])
    if listed is None:
        return None
    rows = [line.split() for line in listed.splitlines() if line.split()]
    if not rows:
        return []
    sessions = [row[0] for row in rows]
    owners = {row[0]: row[2] for row in rows if len(row) > 2}
    shown = _loginctl(["show-session", "--property=Type"] + sessions)
    if shown is None:
        return None
    types = [
        line.strip()[len("Type=") :]
        for line in shown.splitlines()
        if line.strip().startswith("Type=")
    ]
    named = []
    for session, kind in zip(sessions, types):
        owner = owners.get(session, "")
        if kind in RDP_GRAPHICAL_SESSION_TYPES and owner and owner not in named:
            named.append(owner)
    return named


def connected_count(port: int) -> int:
    """How many peers are connected to the direct port right now.

    Args:
        port: The local port a direct connection lands on.

    Returns:
        The number of established connections to it, zero on a machine whose
        connection table cannot be read.
    """
    total = 0
    for path in RDP_PROC_TCP_PATHS:
        try:
            with open(path, "r", encoding="utf-8") as stream:
                rows = stream.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 4 or fields[3] != RDP_TCP_ESTABLISHED:
                continue
            if _local_port(fields[1]) == port:
                total += 1
    return total


def is_wayland_seat() -> bool:
    """Whether this machine's screen is handed out through a portal."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    shown = _loginctl(["show-session", "--property=Type", "self"])
    if shown is None:
        return _session_types() == ["wayland"]
    return "wayland" in (shown or "")


def has_screen_permission(account_home: str) -> bool:
    """Whether RustDesk already holds this machine's screen permission.

    Args:
        account_home: The home of the account the share is for.

    Returns:
        True when the option is in a configuration RustDesk reads, and
        on a machine whose files cannot be read, which is not an
        invitation to nag.
    """
    for path in rustdesk.config_paths(account_home):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                if RDP_WAYLAND_TOKEN_OPTION in stream.read():
                    return True
        except OSError:
            continue
    return False


def _local_port(address: str) -> int:
    """The port out of one ``/proc/net/tcp`` address, -1 when it has none."""
    _, _, port = address.partition(":")
    try:
        return int(port, 16)
    except ValueError:
        return -1


def _loginctl(arguments: list):
    """What ``loginctl`` printed, or None when this machine cannot be asked."""
    try:
        result = subprocess.run(
            ["loginctl"] + arguments,
            capture_output=True,
            text=True,
            timeout=RDP_SESSION_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _session_types() -> list:
    """The types of this machine's graphical sessions.

    Returns:
        The types, empty where none is graphical or the machine cannot be
        asked.
    """
    listed = _loginctl(["list-sessions", "--no-legend"])
    if listed is None:
        return []
    sessions = [line.split()[0] for line in listed.splitlines() if line.split()]
    if not sessions:
        return []
    shown = _loginctl(["show-session", "--property=Type"] + sessions)
    if shown is None:
        return []
    return [
        line.strip()[len("Type=") :]
        for line in shown.splitlines()
        if line.strip().startswith("Type=")
        and line.strip()[len("Type=") :] in RDP_GRAPHICAL_SESSION_TYPES
    ]


class LinuxSeat:
    """The Linux seat, behind the seat seam the share host reads."""

    def graphical_accounts(self) -> "list | None":
        """The accounts signed in at the screen; None where nothing says."""
        return graphical_accounts()

    def has_desktop_session(self) -> bool:
        """Whether this machine has a desktop for RustDesk to share."""
        return has_desktop_session()

    def connected_count(self, port: int) -> int:
        """How many peers are connected to the direct port right now.

        Args:
            port: The local port a direct connection lands on.

        Returns:
            The number of established connections to it.
        """
        return connected_count(port)

    def screen_attention(self, account_home: str) -> str:
        """What a peer would wait on at a seated screen.

        Args:
            account_home: The home of the account the share is for.

        Returns:
            ``rdp_screen_not_allowed`` on a Wayland seat whose permission
            RustDesk does not hold, else empty.
        """
        if not is_wayland_seat():
            return ""
        if has_screen_permission(account_home):
            return ""
        return RDP_ATTENTION_SCREEN_NOT_ALLOWED

    def ask_for_permissions(self, account: str) -> None:
        """Ask the seated person for what RustDesk needs: nothing up front on
        Linux, where Wayland asks on the first connection.

        Args:
            account: The account the share is for.
        """
