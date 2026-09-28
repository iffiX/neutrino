"""The Linux platform, complete.

The client runs as the person, so a CIFS mount and an EasyTier network's
file are the two privileged steps: each goes through its own root helper
under ``pkexec``, which polkit gates on the person being at the console.
The mount helper mounts under the person's home with their uid and gid; the
overlay helper writes the network's file and restarts the daemon. Nothing
else here needs root.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import shutil
import socket
import struct
import subprocess

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_client.constants import (
    CLIENT_CONTROL_SOCKET_NAME,
    CLIENT_MOUNT_HELPER_EXIT_CODES,
    CLIENT_MOUNT_HELPER_PATH,
    CLIENT_OVERLAY_HELPER_EXIT_CODES,
    CLIENT_OVERLAY_HELPER_PATH,
    CLIENT_PKEXEC_REFUSAL_EXIT_CODES,
)
from neutrino_client.exceptions import (
    ControlSocketUnavailableError,
    OverlayControlError,
    PlatformUnsupportedError,
    ShareAttachError,
)
from neutrino_client.platforms.base import ClientPlatform, run_on_pty

CIFS_HELPER = "mount.cifs"
# Where the distributions put it. A person's PATH on Debian carries no sbin
# directory, and the helper that runs it as root finds it either way.
CIFS_HELPER_PATH = "/sbin:/usr/sbin:/bin:/usr/bin"
CIFS_MOUNT_TIMEOUT_S = 120
OVERLAY_HELPER_TIMEOUT_S = 120
PROC_MOUNTS_PATH = "/proc/mounts"
# How /proc/mounts spells the characters a mount point may not carry plainly.
PROC_MOUNTS_ESCAPES = (
    ("\\", "\\134"),
    (" ", "\\040"),
    ("\t", "\\011"),
    ("\n", "\\012"),
)
CONFIG_DIR_NAME = "neutrino_client"


class LinuxPlatform(ClientPlatform):
    """Linux behind the platform contract."""

    os_name = "linux"

    def config_dir(self) -> str:
        """``~/.config/neutrino_client``, honoring ``XDG_CONFIG_HOME``."""
        root = os.environ.get("XDG_CONFIG_HOME", "") or os.path.join(
            self.home(), ".config"
        )
        return os.path.join(root, CONFIG_DIR_NAME)

    def control_socket_path(self) -> str:
        """``$XDG_RUNTIME_DIR/neutrino_client.sock``.

        Raises:
            ControlSocketUnavailableError: When the runtime directory is
                not set.
        """
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_dir:
            raise ControlSocketUnavailableError("XDG_RUNTIME_DIR is not set")
        return os.path.join(runtime_dir, CLIENT_CONTROL_SOCKET_NAME)

    def read_peer_identity(self, connection) -> dict:
        """The peer's identity, from the kernel's ``SO_PEERCRED``.

        Args:
            connection: The accepted socket.

        Returns:
            ``{"account", "uid", "is_same_user"}``.
        """
        data = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        )
        _pid, uid, _gid = struct.unpack("3i", data)
        try:
            account = pwd.getpwuid(uid).pw_name if pwd is not None else str(uid)
        except KeyError:
            account = str(uid)
        return {"account": account, "uid": uid, "is_same_user": uid == os.getuid()}

    def has_mount_tooling(self) -> bool:
        """Whether the root helper and ``mount.cifs`` are on this machine."""
        return (
            os.path.isfile(CLIENT_MOUNT_HELPER_PATH)
            and shutil.which(CIFS_HELPER, path=CIFS_HELPER_PATH) is not None
        )

    def attach_share(
        self, *, share_url: str, location: str, credentials_path: str
    ) -> None:
        """Mount a CIFS share through the root helper under ``pkexec``.

        Args:
            share_url: The share, as ``//host/name``.
            location: The mount point.
            credentials_path: The credentials file.

        Raises:
            ShareAttachError: ``mount_not_authorized`` when the person
                declined or is not allowed, the helper's own code otherwise,
                ``mount_failed`` with the tool's words for anything else.
        """
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        self._run_mount_helper(
            [
                "mount",
                "--share",
                share_url,
                "--location",
                location,
                "--credentials",
                credentials_path,
            ],
            failure_code="mount_failed",
        )

    def detach_share(self, *, location: str) -> None:
        """Unmount the share at a location through the root helper.

        Args:
            location: The mount point.

        Raises:
            ShareAttachError: ``mount_not_authorized`` when the person
                declined, ``unmount_failed`` with the tool's own words.
        """
        self._run_mount_helper(
            ["unmount", "--location", location], failure_code="unmount_failed"
        )

    def is_share_attached(self, *, location: str) -> bool:
        """Whether anything is mounted at a location, read from the kernel.

        Args:
            location: The mount point.

        Returns:
            True when ``/proc/mounts`` names it.
        """
        encoded = location
        for character, escape in PROC_MOUNTS_ESCAPES:
            encoded = encoded.replace(character, escape)
        try:
            with open(PROC_MOUNTS_PATH, "r", encoding="utf-8") as stream:
                lines = stream.readlines()
        except OSError:
            return False
        for line in lines:
            fields = line.split()
            if len(fields) >= 2 and fields[1] == encoded:
                return True
        return False

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

    def easytier_join(
        self, *, network_name: str, secret_path: str, peer: str, hostname: str
    ) -> None:
        """Hand one network to the overlay helper under ``pkexec``.

        The secret stays in its file; only the file's path is on the
        argument vector.

        Args:
            network_name: The network, also the file's name.
            secret_path: A 0600 file of this person's holding the secret.
            peer: The hub's peer URI.
            hostname: What this machine is called on the network.

        Raises:
            OverlayControlError: ``overlay_not_authorized`` when the person
                declined, the helper's own code otherwise,
                ``overlay_restart_failed`` with the tool's words for anything
                else.
        """
        self._run_overlay_helper(
            [
                "easytier",
                "up",
                "--network",
                network_name,
                "--secret-file",
                secret_path,
                "--peer",
                peer,
                "--hostname",
                hostname,
            ]
        )

    def easytier_leave(self, *, network_name: str) -> None:
        """Have the overlay helper take one network's file away.

        Args:
            network_name: The network.

        Raises:
            OverlayControlError: ``overlay_not_authorized`` when the person
                declined, the helper's own code otherwise.
        """
        self._run_overlay_helper(["easytier", "down", "--network", network_name])

    def _run_mount_helper(self, arguments: list, *, failure_code: str) -> None:
        """Run the mount helper and judge its exit status.

        Raises:
            ShareAttachError: Typed from the exit status.
        """
        outcome = run_root_helper(
            CLIENT_MOUNT_HELPER_PATH,
            arguments,
            exit_codes=CLIENT_MOUNT_HELPER_EXIT_CODES,
            refusal_code="mount_not_authorized",
            failure_code=failure_code,
            timeout_s=CIFS_MOUNT_TIMEOUT_S,
        )
        if outcome is not None:
            raise ShareAttachError(outcome[0], detail=outcome[1])

    def _run_overlay_helper(self, arguments: list) -> None:
        """Run the overlay helper and judge its exit status.

        Raises:
            OverlayControlError: Typed from the exit status.
        """
        outcome = run_root_helper(
            CLIENT_OVERLAY_HELPER_PATH,
            arguments,
            exit_codes=CLIENT_OVERLAY_HELPER_EXIT_CODES,
            refusal_code="overlay_not_authorized",
            failure_code="overlay_restart_failed",
            timeout_s=OVERLAY_HELPER_TIMEOUT_S,
        )
        if outcome is not None:
            code, detail = outcome
            raise OverlayControlError(code, {"detail": detail} if detail else {})


def run_root_helper(
    helper: str,
    arguments: list,
    *,
    exit_codes: dict,
    refusal_code: str,
    failure_code: str,
    timeout_s: float,
) -> "tuple[str, str] | None":
    """Run one root helper under ``pkexec`` and type its exit status.

    Args:
        helper: The helper's path, the one its polkit action pins.
        arguments: The helper's own arguments.
        exit_codes: What each helper exit status means.
        refusal_code: The code for pkexec's own 126 and 127, the person
            declining or not being allowed.
        failure_code: The code for a status outside the table, or a helper
            that could not be run.
        timeout_s: How long the helper may take.

    Returns:
        None on success, otherwise ``(code, detail)``, the detail being the
        tool's last words.
    """
    command = ["pkexec", helper] + list(arguments)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_s
        )
    except (OSError, subprocess.SubprocessError) as error:
        return failure_code, str(error)[:200]
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout or "").strip()[-200:]
    if result.returncode in CLIENT_PKEXEC_REFUSAL_EXIT_CODES:
        return refusal_code, ""
    return exit_codes.get(result.returncode, failure_code), detail
