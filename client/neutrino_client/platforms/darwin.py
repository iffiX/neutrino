"""The macOS platform behind the contract.

The client runs as the person, and macOS lets a person mount an SMB share
under their own home with no root: ``mount_smbfs`` attaches it and
``umount`` takes it down. The login stays off every argument vector: the
share is named as ``//user@host/share`` and the password is typed at the
tool's own prompt on a pseudo-terminal of its own. The control channel is a
Unix socket under the person's Caches directory, whose peer identity comes
from the kernel's ``LOCAL_PEERCRED``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import urllib.parse

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_client.constants import CLIENT_CONTROL_SOCKET_NAME
from neutrino_client.exceptions import ShareAttachError
from neutrino_client.platforms.base import (
    ClientPlatform,
    read_share_credentials,
    run_on_pty,
    run_quietly,
    share_parts,
)
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
            ShareAttachError: ``credentials_missing`` without the file,
                ``mount_failed`` with the tool's own words otherwise.
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
            raise ShareAttachError("mount_failed", detail=output.strip()[-200:])

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
