"""The seat on macOS: the console's owner, netstat, and the permissions dialog.

The account at the screen owns ``/dev/console``; at the login window root
does. The connected peers are the established rows ``netstat`` prints for
the direct port. A Mac shows a peer nothing until RustDesk holds both screen
recording and accessibility, which only somebody at that Mac can grant, and
the privacy database that records them is closed to root, so the seat reads
no grant and says nothing a peer would wait on. A share start puts a dialog
naming the two permissions on the screen instead, and opens the Screen
Recording pane of the system settings, both as the account in its session.

Not pure: runs stat and netstat, and the dialog and the settings pane.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess
import threading

try:
    import pwd
except ImportError:
    pwd = None

from neutrino_agent.rdp.constants import (
    RDP_DARWIN_CHROOT,
    RDP_DARWIN_CONSOLE_OWNER_COMMAND,
    RDP_DARWIN_DIALOG_SCRIPT,
    RDP_DARWIN_DIALOG_TIMEOUT_S,
    RDP_DARWIN_ESTABLISHED,
    RDP_DARWIN_LAUNCHCTL,
    RDP_DARWIN_LOGIN_WINDOW_OWNER,
    RDP_DARWIN_NETSTAT_COMMAND,
    RDP_DARWIN_OPEN,
    RDP_DARWIN_OPEN_TIMEOUT_S,
    RDP_DARWIN_OSASCRIPT,
    RDP_DARWIN_SCREEN_RECORDING_PANE,
    RDP_DARWIN_SESSION_PATH,
    RDP_SESSION_TIMEOUT_S,
)
from neutrino_agent.rdp.netstat import established_count


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


def in_session(uid: int, gid: int, account: str, command: list) -> list:
    """One command run as an account inside its own GUI session.

    ``launchctl asuser`` puts the command in the session, and ``chroot``
    onto ``/`` drops it to the account and its primary group alone; both
    take root, which the agent is.

    Args:
        uid: The account's uid.
        gid: The account's primary group.
        account: The account's name.
        command: The argument vector to run.

    Returns:
        The full argument vector.
    """
    return [
        RDP_DARWIN_LAUNCHCTL,
        "asuser",
        str(uid),
        RDP_DARWIN_CHROOT,
        "-u",
        account,
        "-g",
        str(gid),
        "-G",
        str(gid),
        "/",
        *command,
    ]


def _run_quietly(command: list, environment: dict, timeout_s: int) -> None:
    """Run one command to its end or its timeout, whatever it answers."""
    try:
        subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return


class DarwinSeat:
    """The macOS seat, behind the seat seam the share host reads."""

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
        """What a peer would wait on at a seated screen: nothing a Mac lets
        root read.

        Args:
            account_home: The home of the account the share is for.

        Returns:
            Empty.
        """
        return ""

    def ask_for_permissions(self, account: str) -> None:
        """Put the permissions dialog and the Screen Recording pane on the
        account's screen, and return without waiting for either.

        Args:
            account: The account at the screen.
        """
        if not account or pwd is None:
            return
        try:
            entry = pwd.getpwnam(account)
        except KeyError:
            return
        environment = {
            "HOME": entry.pw_dir,
            "USER": account,
            "LOGNAME": account,
            "PATH": RDP_DARWIN_SESSION_PATH,
        }
        asked = (
            (
                [RDP_DARWIN_OSASCRIPT, "-e", RDP_DARWIN_DIALOG_SCRIPT],
                RDP_DARWIN_DIALOG_TIMEOUT_S,
            ),
            (
                [RDP_DARWIN_OPEN, RDP_DARWIN_SCREEN_RECORDING_PANE],
                RDP_DARWIN_OPEN_TIMEOUT_S,
            ),
        )
        for command, timeout_s in asked:
            threading.Thread(
                target=_run_quietly,
                args=(
                    in_session(entry.pw_uid, entry.pw_gid, account, command),
                    environment,
                    timeout_s,
                ),
                daemon=True,
            ).start()
