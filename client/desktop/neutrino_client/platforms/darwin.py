"""The macOS platform behind the contract.

The client runs as the person and asks the system to mount an SMB share as
a network volume, the one the Finder's Connect to Server makes: ``osascript``
runs ``mount volume`` with the script on its standard input, so the
password is on no argument vector, and the system picks the mount point
under ``/Volumes``, read back from the mount table. ``diskutil unmount``
ejects it. The control channel is a
Unix socket in the person's client directory, whose peer identity comes
from the kernel's ``LOCAL_PEERCRED``. An EasyTier network is asked of the
EasyTier daemon over its socket, which needs no administrator.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import re
import select
import shutil
import struct
import subprocess
import urllib.parse

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_client.constants import (
    CLIENT_AGENT_PROGRAM_DIR_DARWIN,
    CLIENT_CLIPBOARD_TIMEOUT_S,
    CLIENT_CONTROL_SOCKET_NAME,
    CLIENT_EASYTIER_SOCKET_PATH_DARWIN,
    CLIENT_EASYTIER_STATE_DIR_DARWIN,
    CLIENT_LOG_DIR_DARWIN,
)
from neutrino_client.exceptions import ShareAttachError
from neutrino_client.platforms.base import (
    ClientPlatform,
    read_share_credentials,
    run_on_pty,
    run_quietly,
    share_parts,
)
from neutrino_client.platforms.posix_terminal import PosixRawTerminal
from neutrino_client.words import language_for_tag

DARWIN_CONFIG_DIR = os.path.join("Library", "Application Support", "Neutrino", "client")
DARWIN_LOG_DIR = os.path.join("Library", "Logs", "Neutrino", "client")

# The socket option level and name for the peer's credentials, and the
# ``struct xucred`` it answers with: a version, the uid, then the groups.
SOL_LOCAL = 0
LOCAL_PEERCRED = 0x0001
LOCAL_PEERPID = 0x0002
XUCRED_FORMAT = "II"
XUCRED_SIZE = 76

MOUNT_SCRIPT_COMMAND = ["osascript", "-"]
# The script waits on the system's own dialogs; one killed under a dialog
# leaves NetAuthSysAgent unable to mount until it restarts.
MOUNT_SCRIPT_TIMEOUT_S = 600
UNMOUNT_TOOL = "diskutil"
UNMOUNT_TIMEOUT_S = 60
# What osascript prints for each way ``mount volume`` refuses, in the order
# they are told apart; the first found names the refusal. Anything else is
# ``mount_failed`` with osascript's own words.
MOUNT_VOLUME_REFUSALS = (
    # afpUserNotAuth: the server refused the username or password.
    ("(-5023)", "share_login_rejected"),
    # afpAccessDenied: this login may not use the share.
    ("(-5000)", "share_access_denied"),
    # afpMiscErr, after the system's alert: the server has no share by this name.
    ("(-5014)", "share_not_found"),
    # fnfErr: the server has no share by this name.
    ("(-43)", "share_not_found"),
    # ioErr: the server did not answer.
    ("(-36)", "share_unreachable"),
    ("Connection failed", "share_unreachable"),
    # userCanceledErr: the person dismissed the system's dialog.
    ("(-128)", "mount_not_authorized"),
)
# What stands in for the password in any words passed on.
PASSWORD_MASK = "***"
MOUNT_TABLE_TOOL = "mount"
MOUNT_TABLE_TIMEOUT_S = 10
# How ``mount`` prints one line: ``//alice@hub/media on /Volumes/media
# (smbfs, nodev, nosuid, mounted by alice)``.
MOUNT_TABLE_LINE = re.compile(
    r"^(?P<source>.+?) on (?P<location>.+) \((?P<options>[^()]*)\)$"
)
# The source of an SMB line: ``//[user[:password]@]host/share``.
MOUNT_TABLE_SMB_SOURCE = re.compile(r"^//(?:[^@/]*@)?(?P<host>[^/]+)/(?P<share>.+)$")

LANGUAGE_COMMAND = ["defaults", "read", "-g", "AppleLanguages"]
LANGUAGE_TIMEOUT_S = 5
# The first quoted entry of the array ``defaults`` prints.
LANGUAGE_ENTRY = re.compile(r'"([^"]+)"')

# The platform UUID the firmware reports; the agent reads the same.
MACHINE_ID_COMMAND = ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]
MACHINE_ID_TIMEOUT_S = 10
MACHINE_ID_ENTRY = re.compile(r'"IOPlatformUUID"\s*=\s*"([^"]+)"')

OPEN_TOOL = "open"
OPEN_TIMEOUT_S = 10

PASTE_TOOL = "pbpaste"
COPY_TOOL = "pbcopy"


def mount_volume_script(*, host: str, share: str, username: str, password: str) -> str:
    """The AppleScript that asks the system to mount a share as a volume.

    Args:
        host: The server, with ``:<port>`` after it for a port of its own.
        share: The share's name.
        username: The share's own username; empty mounts as a guest.
        password: The share's own password.

    Returns:
        One ``mount volume`` line.
    """
    login = f"{urllib.parse.quote(username, safe='')}@" if username else ""
    url = f"smb://{login}{host}/{urllib.parse.quote(share, safe='')}"
    script = f"mount volume {_applescript_text(url)}"
    if username:
        script += f" as user name {_applescript_text(username)}"
    return script + f" with password {_applescript_text(password)}\n"


def _mount_volume_refusal(output: str) -> str:
    """The typed refusal osascript's words name, ``mount_failed`` for none."""
    lowered = output.lower()
    for phrase, code in MOUNT_VOLUME_REFUSALS:
        if phrase.lower() in lowered:
            return code
    return "mount_failed"


def _applescript_text(value: str) -> str:
    """A value as an AppleScript string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _without_password(text: str, password: str) -> str:
    """Words to pass on, the password masked wherever it appears."""
    if not password:
        return text
    return text.replace(password, PASSWORD_MASK)


class DarwinPlatform(ClientPlatform):
    """macOS behind the platform contract."""

    os_name = "darwin"
    mount_location_shape = "volume"

    def config_dir(self) -> str:
        """``~/Library/Application Support/Neutrino/client``."""
        return os.path.join(self.home(), DARWIN_CONFIG_DIR)

    def log_dir(self) -> str:
        """``~/Library/Logs/Neutrino/client``."""
        return os.path.join(self.home(), DARWIN_LOG_DIR)

    def os_machine_id(self) -> str:
        """The platform UUID the firmware reports."""
        try:
            result = run_quietly(MACHINE_ID_COMMAND, timeout_s=MACHINE_ID_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return ""
        found = MACHINE_ID_ENTRY.search(result.stdout or "")
        return found.group(1) if result.returncode == 0 and found else ""

    def agent_program_dir(self) -> str:
        """``/Library/Application Support/Neutrino/agent/app``."""
        return CLIENT_AGENT_PROGRAM_DIR_DARWIN

    def system_language(self) -> str:
        """The first of the languages this account prefers, as set in
        System Settings.

        Returns:
            One of ``CLIENT_LANGUAGES``; the environment's locale where
            ``defaults`` cannot be asked.
        """
        try:
            result = run_quietly(LANGUAGE_COMMAND, timeout_s=LANGUAGE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return super().system_language()
        found = LANGUAGE_ENTRY.search(result.stdout or "")
        if result.returncode != 0 or found is None:
            return super().system_language()
        return language_for_tag(found.group(1))

    def control_socket_path(self) -> str:
        """``~/Library/Application Support/Neutrino/client/client.sock``."""
        return os.path.join(self.config_dir(), CLIENT_CONTROL_SOCKET_NAME)

    def read_peer_identity(self, connection) -> dict:
        """The peer's identity, from the kernel's ``LOCAL_PEERCRED``.

        Args:
            connection: The accepted socket.

        Returns:
            ``{"account", "uid", "is_same_user"}``.
        """
        data = connection.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, XUCRED_SIZE)
        _version, uid = struct.unpack_from(XUCRED_FORMAT, data)
        try:
            account = pwd.getpwuid(uid).pw_name if pwd is not None else str(uid)
        except KeyError:
            account = str(uid)
        return {"account": account, "uid": uid, "is_same_user": uid == os.getuid()}

    def daemon_peer(self, connection) -> dict:
        """A daemon socket's peer, from ``LOCAL_PEERCRED`` and ``LOCAL_PEERPID``.

        Args:
            connection: The accepted socket.

        Returns:
            ``{"account", "pid"}``.

        Raises:
            OSError: When the socket carries no credentials.
        """
        identity = self.read_peer_identity(connection)
        pid = connection.getsockopt(SOL_LOCAL, LOCAL_PEERPID)
        return {"account": identity["account"], "pid": pid}

    def watch_process(self, pid: int) -> "DarwinProcessWatch":
        """A kqueue watch on one running process's exit.

        Args:
            pid: The process id.

        Returns:
            The watch.

        Raises:
            OSError: When the process does not run.
        """
        return DarwinProcessWatch(pid)

    def validate_mount_location(self, *, location: str) -> "dict | None":
        """Accept any location: the system picks the mount point.

        Args:
            location: The proposed location; empty on this platform.

        Returns:
            None.
        """
        return None

    def prepare_mount_location(self, *, location: str) -> "dict | None":
        """A volume needs no preparation: the system makes its mount point."""
        return None

    def has_mount_tooling(self) -> bool:
        """Whether ``osascript`` is on this machine."""
        return shutil.which(MOUNT_SCRIPT_COMMAND[0]) is not None

    def attach_share(
        self, *, share_url: str, location: str, credentials_path: str, port: int = 0
    ) -> str:
        """Ask the system to mount an SMB share as a network volume.

        The script goes to ``osascript`` on its standard input. A share the
        mount table already lists for the same host, port and share is
        taken as mounted where it is.

        Args:
            share_url: The share, as ``//host/name``.
            port: The port the server answers SMB on; 0 for its own.
            location: Unused; the system picks the mount point.
            credentials_path: The credentials file.

        Returns:
            The mount point the system gave, read from the mount table.

        Raises:
            ShareAttachError: ``credentials_missing`` without the file; the
                refusal osascript's words name, ``share_login_rejected`` for
                a wrong username or password among them; ``mount_timed_out``
                when the script does not finish in time; ``mount_failed``
                with osascript's own words, the password masked, for
                anything else.
        """
        host, share = share_parts(share_url)
        if not host or not share:
            raise ShareAttachError("mount_failed", detail="unreadable share url")
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        if port:
            host = f"{host}:{int(port)}"
        mounted = self._volume_location(host, share)
        if mounted:
            return mounted
        username, password = read_share_credentials(credentials_path)
        script = mount_volume_script(
            host=host, share=share, username=username, password=password
        )
        try:
            result = run_quietly(
                MOUNT_SCRIPT_COMMAND,
                input=script,
                timeout_s=MOUNT_SCRIPT_TIMEOUT_S,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            raise ShareAttachError("mount_timed_out")
        except (OSError, subprocess.SubprocessError) as error:
            detail = _without_password(str(error), password)[:200]
            raise ShareAttachError("mount_failed", detail=detail)
        if result.returncode != 0:
            output = _without_password(result.stderr or result.stdout or "", password)
            raise ShareAttachError(
                _mount_volume_refusal(output), detail=output.strip()[-200:]
            )
        mounted = self._volume_location(host, share)
        if not mounted:
            raise ShareAttachError(
                "mount_failed", detail=f"//{host}/{share} is not in the mount table"
            )
        return mounted

    def detach_share(self, *, location: str) -> None:
        """Eject the volume at a mount point with ``diskutil unmount``.

        Args:
            location: The mount point.

        Raises:
            ShareAttachError: ``unmount_failed`` with the tool's own words.
        """
        try:
            result = run_quietly(
                [UNMOUNT_TOOL, "unmount", location], timeout_s=UNMOUNT_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("unmount_failed", detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("unmount_failed", detail=detail)

    def is_share_attached(self, *, location: str) -> bool:
        """Whether anything is mounted at a location, read from ``mount``.

        Args:
            location: The mount point; empty before the system gave one.

        Returns:
            True when the mount table names it.
        """
        if not location:
            return False
        for _source, mounted_at, _options in self._mount_table():
            if mounted_at == location:
                return True
        return False

    def open_url(self, url: str) -> None:
        """Open a link with ``open``, which hands it to the default browser.

        Args:
            url: The link.
        """
        try:
            run_quietly([OPEN_TOOL, url], timeout_s=OPEN_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            super().open_url(url)

    def read_clipboard(self) -> str:
        """The text on the clipboard, from ``pbpaste``.

        Returns:
            The text; empty when the clipboard holds none.

        Raises:
            OSError: When ``pbpaste`` cannot run, fails, or takes too long.
        """
        try:
            result = run_quietly(
                [PASTE_TOOL], timeout_s=CLIENT_CLIPBOARD_TIMEOUT_S, encoding="utf-8"
            )
        except subprocess.SubprocessError as error:
            raise OSError(f"{PASTE_TOOL}: {error}") from error
        if result.returncode != 0:
            raise OSError(f"{PASTE_TOOL}: {(result.stderr or '').strip()[:200]}")
        return result.stdout or ""

    def write_clipboard(self, text: str) -> None:
        """Put text on the clipboard with ``pbcopy``.

        Args:
            text: The text.

        Raises:
            OSError: When ``pbcopy`` cannot run, fails, or takes too long.
        """
        try:
            result = run_quietly(
                [COPY_TOOL],
                input=text,
                timeout_s=CLIENT_CLIPBOARD_TIMEOUT_S,
                encoding="utf-8",
            )
        except subprocess.SubprocessError as error:
            raise OSError(f"{COPY_TOOL}: {error}") from error
        if result.returncode != 0:
            raise OSError(f"{COPY_TOOL}: {(result.stderr or '').strip()[:200]}")

    def raw_terminal(self) -> PosixRawTerminal:
        """Standard input in raw mode."""
        return PosixRawTerminal()

    def easytier_daemon_address(self) -> str:
        """``/var/run/neutrino/client/easytier.sock``."""
        return CLIENT_EASYTIER_SOCKET_PATH_DARWIN

    def easytier_state_dir(self) -> str:
        """``/Library/Application Support/Neutrino/client/state/easytier``."""
        return CLIENT_EASYTIER_STATE_DIR_DARWIN

    def easytier_log_dir(self) -> str:
        """``/Library/Logs/Neutrino/client``."""
        return CLIENT_LOG_DIR_DARWIN

    def run_answering(
        self, argv: list, *, prompt: str, answer: str, timeout_s: float
    ) -> tuple:
        """Run a program on a pseudo-terminal and answer one prompt.

        Args:
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long the whole run may take.

        Returns:
            ``(returncode, output)``; 127 when the program could not start.

        Raises:
            PlatformUnsupportedError: Where this interpreter has no pty.
        """
        return run_on_pty(argv, prompt=prompt, answer=answer, timeout_s=timeout_s)

    def _mount_table(self) -> list:
        """The mount table as ``(source, location, options)``; empty when unreadable."""
        try:
            result = run_quietly([MOUNT_TABLE_TOOL], timeout_s=MOUNT_TABLE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []
        rows = []
        for line in (result.stdout or "").splitlines():
            found = MOUNT_TABLE_LINE.match(line.strip())
            if found is not None:
                rows.append(found.group("source", "location", "options"))
        return rows

    def _volume_location(self, host: str, share: str) -> str:
        """Where the mount table has an SMB volume of a host's share; empty for none.

        Args:
            host: The server, with ``:<port>`` after it for a port of its own.
            share: The share's name.
        """
        for source, mounted_at, options in self._mount_table():
            found = MOUNT_TABLE_SMB_SOURCE.match(source)
            if not options.startswith("smbfs") or found is None:
                continue
            listed_share = urllib.parse.unquote(found.group("share"))
            if (
                found.group("host").lower() == host.lower()
                and listed_share.lower() == share.lower()
            ):
                return mounted_at
        return ""


class DarwinProcessWatch:
    """One process the daemon waits on, through a kqueue exit event."""

    def __init__(self, pid: int):
        """
        Args:
            pid: The process id.

        Raises:
            OSError: When the process does not run.
        """
        self._queue = select.kqueue()
        self._has_ended = False
        try:
            self._queue.control(
                [
                    select.kevent(
                        pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD,
                        fflags=select.KQ_NOTE_EXIT,
                    )
                ],
                0,
            )
        except OSError:
            self._queue.close()
            raise

    def is_running(self) -> bool:
        """Whether the process has not ended.

        Returns:
            True while it runs.
        """
        if self._has_ended or self._queue.closed:
            return False
        if self._queue.control(None, 1, 0):
            self._has_ended = True
        return not self._has_ended

    def close(self) -> None:
        """Let the queue go. Idempotent."""
        self._queue.close()
