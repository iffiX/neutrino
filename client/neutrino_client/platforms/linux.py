"""The Linux platform, complete.

The client runs as the person, so a CIFS mount is the one privileged step:
it goes through the root helper under ``pkexec``, which polkit gates on the
person being at the console. The helper mounts under the person's home with
their uid and gid, and nothing else here needs root.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import shutil
import socket
import struct
import subprocess
import time

try:
    import pty
    import select
except ImportError:  # Windows has no pseudo-terminal of this kind.
    pty = None
    select = None

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_client.constants import (
    CLIENT_CONTROL_SOCKET_NAME,
    CLIENT_MOUNT_HELPER_EXIT_CODES,
    CLIENT_MOUNT_HELPER_PATH,
    CLIENT_PKEXEC_REFUSAL_EXIT_CODES,
)
from neutrino_client.platforms.base import (
    ClientPlatform,
    ControlSocketUnavailableError,
    PlatformUnsupportedError,
    ShareAttachError,
    answer_on_prompt,
)

CIFS_HELPER = "mount.cifs"
CIFS_MOUNT_TIMEOUT_S = 120
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
            and shutil.which(CIFS_HELPER) is not None
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
        self._run_helper(
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
        self._run_helper(
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
        if pty is None or select is None:
            raise PlatformUnsupportedError("no pseudo-terminal on this platform")
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.execvp(argv[0], argv)
            finally:
                os._exit(127)

        def read(wait_s: float):
            ready, _, _ = select.select([fd], [], [], wait_s)
            if not ready:
                return None
            try:
                return os.read(fd, 4096)
            except OSError:
                # Linux answers EIO once the other side has gone: the end.
                return b""

        def write(data: bytes) -> None:
            os.write(fd, data)

        try:
            output = answer_on_prompt(
                read,
                write,
                prompt=prompt,
                answer=answer,
                deadline=time.monotonic() + timeout_s,
            )
        finally:
            os.close(fd)
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status), output.decode("utf-8", "replace")

    def _run_helper(self, arguments: list, *, failure_code: str) -> None:
        """Run the root helper under ``pkexec`` and judge its exit status.

        Args:
            arguments: The helper's own arguments.
            failure_code: The code for an exit status outside the table.

        Raises:
            ShareAttachError: Typed from the exit status.
        """
        command = ["pkexec", CLIENT_MOUNT_HELPER_PATH] + list(arguments)
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=CIFS_MOUNT_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError(failure_code, detail=str(error)[:200])
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout or "").strip()[-200:]
        if result.returncode in CLIENT_PKEXEC_REFUSAL_EXIT_CODES:
            raise ShareAttachError("mount_not_authorized")
        code = CLIENT_MOUNT_HELPER_EXIT_CODES.get(result.returncode, failure_code)
        raise ShareAttachError(code, detail=detail)
