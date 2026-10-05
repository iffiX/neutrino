"""The seat on macOS: the console user, netstat, and the permissions dialog.

The account at the screen is the console user the system configuration
holds (``State:/Users/ConsoleUser``, asked through ``scutil``); the login
window, root and no name are nobody. Only when that store cannot be asked
is the owner of ``/dev/console`` read instead, which stays root under
auto-login while a person is signed in. The connected peers are the established rows ``netstat`` prints for
the direct port. A Mac shows a peer nothing until RustDesk holds both screen
recording and accessibility, which only somebody at that Mac can grant, and
the privacy database that records them is closed to root, so the seat reads
no grant and says nothing a peer would wait on. A share start puts a dialog
naming the two permissions on the screen instead, and opens the Screen
Recording pane of the system settings, both as the account in its session:
``launchctl asuser`` starts the agent's own ``step-down`` verb in the
session, which drops to the account and runs the program. A failure to
start either is logged.

Not pure: runs scutil, stat and netstat, and the dialog and the settings pane.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
import subprocess
import threading

try:
    import pwd
except ImportError:
    pwd = None

from neutrino_agent.rdp.constants import (
    RDP_DARWIN_AGENT_PROGRAM,
    RDP_DARWIN_CONSOLE_OWNER_COMMAND,
    RDP_DARWIN_CONSOLE_USER_QUERY,
    RDP_DARWIN_DIALOG_SCRIPT,
    RDP_DARWIN_DIALOG_TIMEOUT_S,
    RDP_DARWIN_ESTABLISHED,
    RDP_DARWIN_LAUNCHCTL,
    RDP_DARWIN_NETSTAT_COMMAND,
    RDP_DARWIN_NOBODY_NAMES,
    RDP_DARWIN_OPEN,
    RDP_DARWIN_OPEN_TIMEOUT_S,
    RDP_DARWIN_OSASCRIPT,
    RDP_DARWIN_SCREEN_RECORDING_PANE,
    RDP_DARWIN_SCUTIL,
    RDP_DARWIN_SESSION_PATH,
    RDP_DARWIN_STEP_DOWN_VERB,
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


def parse_console_user(text: str) -> tuple:
    """The account at the screen, from what ``scutil`` prints for
    ``State:/Users/ConsoleUser``.

    Args:
        text: What ``scutil`` printed.

    Returns:
        ``(name, uid)``; empty for nobody: the login window, root, no name,
        no uid, or no such key.
    """
    name = re.search(r"^\s*Name\s*:\s*(\S+)\s*$", text, re.MULTILINE)
    uid = re.search(r"^\s*UID\s*:\s*(\d+)\s*$", text, re.MULTILINE)
    if name is None or uid is None:
        return ()
    if name.group(1) in RDP_DARWIN_NOBODY_NAMES or int(uid.group(1)) == 0:
        return ()
    return name.group(1), int(uid.group(1))


def console_user() -> "tuple | None":
    """The account signed in at the Mac's screen.

    The system configuration's console user answers; the owner of
    ``/dev/console`` answers only when ``scutil`` cannot be asked.

    Returns:
        ``(name, uid)``; empty for nobody; None when neither can be asked.
    """
    try:
        result = subprocess.run(
            [RDP_DARWIN_SCUTIL],
            input=RDP_DARWIN_CONSOLE_USER_QUERY,
            capture_output=True,
            text=True,
            timeout=RDP_SESSION_TIMEOUT_S,
        )
        printed = result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        printed = None
    if printed is not None:
        return parse_console_user(printed)
    owner = _printed(RDP_DARWIN_CONSOLE_OWNER_COMMAND)
    if owner is None:
        return None
    words = owner.split()
    if len(words) != 2 or not words[1].isdigit():
        return ()
    if words[0] in RDP_DARWIN_NOBODY_NAMES or int(words[1]) == 0:
        return ()
    return words[0], int(words[1])


def in_session(uid: int, gid: int, command: list) -> list:
    """One command run as an account inside its own GUI session.

    ``launchctl asuser`` starts the agent's own ``step-down`` verb in the
    session; it drops to the account's groups, group and user, in that
    order, and runs the command. Both take root, which the agent is.

    Args:
        uid: The account's uid.
        gid: The account's primary group.
        command: The argument vector to run.

    Returns:
        The full argument vector.
    """
    return [
        RDP_DARWIN_LAUNCHCTL,
        "asuser",
        str(uid),
        RDP_DARWIN_AGENT_PROGRAM,
        RDP_DARWIN_STEP_DOWN_VERB,
        "--uid",
        str(uid),
        "--gid",
        str(gid),
        "--",
        *command,
    ]


def _run_logged(command: list, environment: dict, timeout_s: int, log) -> None:
    """Run one command to its end or its timeout; a failure is logged."""
    program = command[command.index("--") + 1] if "--" in command else command[0]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=environment,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return
    except (OSError, subprocess.SubprocessError) as error:
        log(f"rdp: {program} could not start: {error}")
        return
    if result.returncode != 0:
        said = " ".join((result.stderr or result.stdout or "").split())[:300]
        log(f"rdp: {program} exited {result.returncode}: {said}")


class DarwinSeat:
    """The macOS seat, behind the seat seam the share host reads."""

    def __init__(self, *, log=print):
        """
        Args:
            log: Where a command that would not start is said.
        """
        self._log = log

    def graphical_accounts(self) -> "list | None":
        """The account signed in at the screen, by :func:`console_user`.

        Returns:
            ``[account]``, empty for nobody, None where neither the system
            configuration nor the console can be asked.
        """
        seated = console_user()
        if seated is None:
            return None
        return [seated[0]] if seated else []

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
                target=_run_logged,
                args=(
                    in_session(entry.pw_uid, entry.pw_gid, command),
                    environment,
                    timeout_s,
                    self._log,
                ),
                daemon=True,
            ).start()
