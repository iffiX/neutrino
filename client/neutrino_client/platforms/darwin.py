"""The macOS platform behind the contract.

The client runs as the person, and macOS lets a person mount an SMB share
under their own home with no root: ``mount_smbfs`` attaches it and
``umount`` takes it down. The login stays off every argument vector: the
share is named as ``//user@host/share`` and the password is typed at the
tool's own prompt on a pseudo-terminal of its own. The control channel is a
Unix socket under the person's Caches directory, whose peer identity comes
from the kernel's ``LOCAL_PEERCRED``. An EasyTier network's file is put in
place by root through an administrator prompt, the one step here that asks
for one, which also starts or stops the EasyTier launchd job.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import re
import shlex
import shutil
import struct
import subprocess
import urllib.parse

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_client.constants import (
    CLIENT_CONTROL_SOCKET_NAME,
    CLIENT_EASYTIER_CONFIG_DIR_DARWIN,
    CLIENT_EASYTIER_CONFIG_SUFFIX,
    CLIENT_EASYTIER_LAUNCHD_LABEL,
    CLIENT_LAUNCHD_DAEMONS_DIR,
    CLIENT_OVERLAY_DIR_NAME,
)
from neutrino_client.core import files
from neutrino_client.core.easytier_config import is_network_name
from neutrino_client.exceptions import OverlayControlError, ShareAttachError
from neutrino_client.platforms.base import (
    ClientPlatform,
    easytier_file_text,
    read_share_credentials,
    run_on_pty,
    run_quietly,
    share_parts,
)
from neutrino_client.platforms.posix_terminal import PosixRawTerminal
from neutrino_client.words import language_for_tag

DARWIN_CONFIG_DIR = os.path.join("Library", "Application Support", "Neutrino Client")
DARWIN_SOCKET_DIR = os.path.join("Library", "Caches", "neutrino_client")

# The socket option level and name for the peer's credentials, and the
# ``struct xucred`` it answers with: a version, the uid, then the groups.
SOL_LOCAL = 0
LOCAL_PEERCRED = 0x0001
XUCRED_FORMAT = "II"
XUCRED_SIZE = 76

SMB_MOUNT_TOOL = "mount_smbfs"
SMB_UNMOUNT_TOOL = "umount"
SMB_MOUNT_TIMEOUT_S = 120
# What mount_smbfs prints before it reads the password.
SMB_PASSWORD_PROMPT = "Password"
# What mount_smbfs prints for each way a share refuses, in the order they
# are told apart; the first phrase found names the refusal. Anything else
# is ``mount_failed`` with the tool's own words.
SMB_REFUSALS = (
    ("Authentication error", "share_login_rejected"),
    ("Permission denied", "share_access_denied"),
    ("No such file or directory", "share_not_found"),
    ("Operation timed out", "share_unreachable"),
    ("Connection refused", "share_unreachable"),
    ("No route to host", "share_unreachable"),
    ("could not connect", "share_unreachable"),
)
MOUNT_TABLE_TOOL = "mount"
MOUNT_TABLE_TIMEOUT_S = 10
# How ``mount`` prints one line: ``//alice@hub/media on /Users/alice/nas
# (smbfs, nodev, nosuid, mounted by alice)``.
MOUNT_TABLE_LINE = re.compile(r"^.+? on (?P<location>.+) \([^()]*\)$")

LANGUAGE_COMMAND = ["defaults", "read", "-g", "AppleLanguages"]
LANGUAGE_TIMEOUT_S = 5
# The first quoted entry of the array ``defaults`` prints.
LANGUAGE_ENTRY = re.compile(r'"([^"]+)"')

OPEN_TOOL = "open"
OPEN_TIMEOUT_S = 10

# The administrator prompt: a shell script run as root through AppleScript.
# A person cancelling it is error -128, which osascript prints.
OSASCRIPT_TOOL = "osascript"
OSASCRIPT_TIMEOUT_S = 300
OSASCRIPT_CANCELED_MARKS = ("User canceled", "(-128)")

# The file a terminal is opened on: Terminal runs a ``.command`` file.
TERMINAL_COMMAND_FILE_NAME = "terminal.command"
TERMINAL_APP = "Terminal"


def _smb_refusal(output: str) -> str:
    """The typed refusal mount_smbfs's words name, ``mount_failed`` for none."""
    lowered = output.lower()
    for phrase, code in SMB_REFUSALS:
        if phrase.lower() in lowered:
            return code
    return "mount_failed"


def _easytier_start_script() -> str:
    """The shell that loads the EasyTier job when it is not loaded, and restarts it."""
    plist = shlex.quote(
        os.path.join(
            CLIENT_LAUNCHD_DAEMONS_DIR, CLIENT_EASYTIER_LAUNCHD_LABEL + ".plist"
        )
    )
    return (
        f"(launchctl bootstrap system {plist} 2>/dev/null; "
        f"launchctl kickstart -k system/{CLIENT_EASYTIER_LAUNCHD_LABEL})"
    )


class DarwinPlatform(ClientPlatform):
    """macOS behind the platform contract."""

    os_name = "darwin"

    def config_dir(self) -> str:
        """``~/Library/Application Support/Neutrino Client``."""
        return os.path.join(self.home(), DARWIN_CONFIG_DIR)

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
        """``~/Library/Caches/neutrino_client/neutrino_client.sock``."""
        return os.path.join(self.home(), DARWIN_SOCKET_DIR, CLIENT_CONTROL_SOCKET_NAME)

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

    def has_mount_tooling(self) -> bool:
        """Whether ``mount_smbfs`` is on this machine."""
        return shutil.which(SMB_MOUNT_TOOL) is not None

    def attach_share(
        self, *, share_url: str, location: str, credentials_path: str
    ) -> None:
        """Mount an SMB share with ``mount_smbfs``, as the person.

        The username rides the share URL; the password is typed at the
        tool's prompt on a pseudo-terminal and is on no argument vector.

        Args:
            share_url: The share, as ``//host/name``.
            location: The mount point.
            credentials_path: The credentials file.

        Raises:
            ShareAttachError: ``credentials_missing`` without the file; the
                share refusal the tool's words name, ``share_login_rejected``
                for a wrong username or password among them; ``mount_failed``
                with the tool's own words for anything else.
        """
        host, share = share_parts(share_url)
        if not host or not share:
            raise ShareAttachError("mount_failed", detail="unreadable share url")
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        username, password = read_share_credentials(credentials_path)
        login = f"{urllib.parse.quote(username, safe='')}@" if username else ""
        try:
            code, output = self.run_answering(
                [SMB_MOUNT_TOOL, f"//{login}{host}/{share}", location],
                prompt=SMB_PASSWORD_PROMPT,
                answer=password + "\n",
                timeout_s=SMB_MOUNT_TIMEOUT_S,
            )
        except OSError as error:
            raise ShareAttachError("mount_failed", detail=str(error)[:200])
        if code != 0:
            raise ShareAttachError(_smb_refusal(output), detail=output.strip()[-200:])

    def detach_share(self, *, location: str) -> None:
        """Unmount the share at a location with ``umount``.

        Args:
            location: The mount point.

        Raises:
            ShareAttachError: ``unmount_failed`` with the tool's own words.
        """
        try:
            result = run_quietly(
                [SMB_UNMOUNT_TOOL, location], timeout_s=SMB_MOUNT_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError("unmount_failed", detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError("unmount_failed", detail=detail)

    def is_share_attached(self, *, location: str) -> bool:
        """Whether anything is mounted at a location, read from ``mount``.

        Args:
            location: The mount point.

        Returns:
            True when the mount table names it.
        """
        try:
            result = run_quietly([MOUNT_TABLE_TOOL], timeout_s=MOUNT_TABLE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
        for line in (result.stdout or "").splitlines():
            found = MOUNT_TABLE_LINE.match(line.strip())
            if found is not None and found.group("location") == location:
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

    def raw_terminal(self) -> PosixRawTerminal:
        """Standard input in raw mode."""
        return PosixRawTerminal()

    def open_terminal(self, argv: list) -> None:
        """Open Terminal on a ``.command`` file that runs one command.

        Args:
            argv: The command the terminal runs.

        Raises:
            OSError: When the file cannot be written or Terminal opened.
        """
        path = os.path.join(self.config_dir(), TERMINAL_COMMAND_FILE_NAME)
        files.write_text(path, "#!/bin/sh\nexec " + shlex.join(argv) + "\n", mode=0o700)
        try:
            result = run_quietly(
                [OPEN_TOOL, "-a", TERMINAL_APP, path], timeout_s=OPEN_TIMEOUT_S
            )
        except subprocess.SubprocessError as error:
            raise OSError(str(error)) from error
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "").strip()[-200:])

    def easytier_join(
        self, *, network_name: str, secret_path: str, peer: str, hostname: str
    ) -> None:
        """Render one network's file, and have root put it in place and start the job.

        The file is rendered under the person's own configuration directory,
        0600, and removed once root has installed its copy.

        Args:
            network_name: The network, also the file's name.
            secret_path: A file of this person's holding the secret.
            peer: The hub's peer URI.
            hostname: What this machine is called on the network.

        Raises:
            OverlayControlError: The value refused, ``overlay_not_authorized``
                when the person cancelled the prompt,
                ``overlay_restart_failed`` with the script's words.
        """
        text = easytier_file_text(
            network_name=network_name,
            secret_path=secret_path,
            peer=peer,
            hostname=hostname,
        )
        staged = os.path.join(
            self.config_dir(),
            CLIENT_OVERLAY_DIR_NAME,
            network_name + CLIENT_EASYTIER_CONFIG_SUFFIX,
        )
        files.write_text(staged, text, mode=0o600)
        target = os.path.join(
            CLIENT_EASYTIER_CONFIG_DIR_DARWIN,
            network_name + CLIENT_EASYTIER_CONFIG_SUFFIX,
        )
        script = (
            f"mkdir -p {shlex.quote(CLIENT_EASYTIER_CONFIG_DIR_DARWIN)}"
            f" && chmod 700 {shlex.quote(CLIENT_EASYTIER_CONFIG_DIR_DARWIN)}"
            f" && install -m 0600 -o root -g wheel {shlex.quote(staged)}"
            f" {shlex.quote(target)}"
            f" && {_easytier_start_script()}"
        )
        try:
            self._run_as_administrator(script)
        finally:
            files.remove_file(staged)

    def easytier_leave(self, *, network_name: str) -> None:
        """Have root remove one network's file, and restart or stop the job.

        Args:
            network_name: The network.

        Raises:
            OverlayControlError: ``overlay_network_invalid`` for a name no
                file may carry, ``overlay_not_authorized`` when the person
                cancelled the prompt, ``overlay_restart_failed`` otherwise.
        """
        if not is_network_name(network_name):
            raise OverlayControlError("overlay_network_invalid")
        directory = shlex.quote(CLIENT_EASYTIER_CONFIG_DIR_DARWIN)
        target = shlex.quote(
            os.path.join(
                CLIENT_EASYTIER_CONFIG_DIR_DARWIN,
                network_name + CLIENT_EASYTIER_CONFIG_SUFFIX,
            )
        )
        script = (
            f"rm -f {target}; "
            f"if ls {directory}/*{CLIENT_EASYTIER_CONFIG_SUFFIX} >/dev/null 2>&1; "
            f"then {_easytier_start_script()}; "
            f"else launchctl bootout system/{CLIENT_EASYTIER_LAUNCHD_LABEL}"
            " 2>/dev/null; true; fi"
        )
        self._run_as_administrator(script)

    def _run_as_administrator(self, script: str) -> None:
        """Run one shell script as root behind the system's administrator prompt.

        Raises:
            OverlayControlError: ``overlay_not_authorized`` when the person
                cancelled, ``overlay_restart_failed`` with the words
                otherwise.
        """
        quoted = script.replace("\\", "\\\\").replace('"', '\\"')
        command = [
            OSASCRIPT_TOOL,
            "-e",
            f'do shell script "{quoted}" with administrator privileges',
        ]
        try:
            result = run_quietly(command, timeout_s=OSASCRIPT_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as error:
            raise OverlayControlError(
                "overlay_restart_failed", {"detail": str(error)[:200]}
            )
        if result.returncode == 0:
            return
        words = (result.stderr or result.stdout or "").strip()
        if any(mark in words for mark in OSASCRIPT_CANCELED_MARKS):
            raise OverlayControlError("overlay_not_authorized")
        raise OverlayControlError("overlay_restart_failed", {"detail": words[-200:]})

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
