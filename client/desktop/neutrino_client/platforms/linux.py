"""The Linux platform, complete.

The client runs as the person, so a CIFS mount is the one privileged step:
it goes through the root helper under ``pkexec``, which polkit gates on the
person being at the console, and mounts under the person's home with their
uid and gid. An EasyTier network is asked of the EasyTier daemon over its
socket, which needs no root of the person. Nothing else here needs root.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import shutil
import socket
import struct
import subprocess
import threading

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_client.constants import (
    CLIENT_CLIPBOARD_TIMEOUT_S,
    CLIENT_CONTROL_SOCKET_NAME,
    CLIENT_EASYTIER_SOCKET_PATH_LINUX,
    CLIENT_EASYTIER_STATE_DIR_LINUX,
    CLIENT_MOUNT_HELPER_EXIT_CODES,
    CLIENT_MOUNT_HELPER_PATH,
    CLIENT_PKEXEC_REFUSAL_EXIT_CODES,
)
from neutrino_client.exceptions import (
    ControlSocketUnavailableError,
    PlatformUnsupportedError,
    ShareAttachError,
)
from neutrino_client.platforms.base import ClientPlatform, run_on_pty, run_quietly
from neutrino_client.platforms.posix_terminal import PosixRawTerminal

CIFS_HELPER = "mount.cifs"
# Where the distributions put it. A person's PATH on Debian carries no sbin
# directory, and the helper that runs it as root finds it either way.
CIFS_HELPER_PATH = "/sbin:/usr/sbin:/bin:/usr/bin"
CIFS_MOUNT_TIMEOUT_S = 120
PROC_MOUNTS_PATH = "/proc/mounts"
# How /proc/mounts spells the characters a mount point may not carry plainly.
PROC_MOUNTS_ESCAPES = (
    ("\\", "\\134"),
    (" ", "\\040"),
    ("\t", "\\011"),
    ("\n", "\\012"),
)
# This person's client directory under the configuration root, and the
# directory its socket sits in under the runtime root.
CONFIG_DIR_NAME = os.path.join("neutrino", "client")
SOCKET_DIR_NAME = "neutrino"
# The clipboard tools, each with the variable naming the session it serves.
CLIPBOARD_TOOLS = (
    ("WAYLAND_DISPLAY", ("wl-paste", "--no-newline", "--type", "text")),
    ("DISPLAY", ("xclip", "-selection", "clipboard", "-o")),
)
# The tools that write it, the same way round, each taking the text on its
# standard input.
CLIPBOARD_WRITE_TOOLS = (
    ("WAYLAND_DISPLAY", ("wl-copy", "--type", "text/plain")),
    ("DISPLAY", ("xclip", "-selection", "clipboard", "-i")),
)


class LinuxPlatform(ClientPlatform):
    """Linux behind the platform contract."""

    os_name = "linux"

    def config_dir(self) -> str:
        """``~/.config/neutrino/client``, honoring ``XDG_CONFIG_HOME``."""
        root = os.environ.get("XDG_CONFIG_HOME", "") or os.path.join(
            self.home(), ".config"
        )
        return os.path.join(root, CONFIG_DIR_NAME)

    def control_socket_path(self) -> str:
        """``$XDG_RUNTIME_DIR/neutrino/client.sock``.

        Raises:
            ControlSocketUnavailableError: When the runtime directory is
                not set.
        """
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_dir:
            raise ControlSocketUnavailableError("XDG_RUNTIME_DIR is not set")
        return os.path.join(runtime_dir, SOCKET_DIR_NAME, CLIENT_CONTROL_SOCKET_NAME)

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

    def raw_terminal(self) -> PosixRawTerminal:
        """Standard input in raw mode."""
        return PosixRawTerminal()

    def read_clipboard(self) -> str:
        """The text on the clipboard of this person's session.

        ``wl-paste`` on a Wayland session and ``xclip`` on an X one, when
        the tool is installed, else GTK's own clipboard.

        Returns:
            The text; empty when the clipboard holds none.

        Raises:
            OSError: When the tool cannot run or takes too long, or GTK is
                missing or does not answer in time.
        """
        for variable, tool in CLIPBOARD_TOOLS:
            if os.environ.get(variable) and shutil.which(tool[0]):
                try:
                    result = run_quietly(
                        list(tool),
                        timeout_s=CLIENT_CLIPBOARD_TIMEOUT_S,
                        encoding="utf-8",
                    )
                except subprocess.SubprocessError as error:
                    raise OSError(f"{tool[0]}: {error}") from error
                # Both tools end non-zero on a clipboard that holds no text.
                if result.returncode != 0:
                    return ""
                return result.stdout or ""
        return gtk_clipboard_text(CLIENT_CLIPBOARD_TIMEOUT_S)

    def write_clipboard(self, text: str) -> None:
        """Put text on the clipboard of this person's session.

        ``wl-copy`` on a Wayland session and ``xclip`` on an X one, when the
        tool is installed, else GTK's own clipboard.

        Args:
            text: The text.

        Raises:
            OSError: When the tool cannot run, fails or takes too long, or
                GTK is missing or does not answer in time.
        """
        for variable, tool in CLIPBOARD_WRITE_TOOLS:
            if os.environ.get(variable) and shutil.which(tool[0]):
                try:
                    result = run_quietly(
                        list(tool),
                        input=text,
                        timeout_s=CLIENT_CLIPBOARD_TIMEOUT_S,
                        encoding="utf-8",
                    )
                except subprocess.SubprocessError as error:
                    raise OSError(f"{tool[0]}: {error}") from error
                if result.returncode != 0:
                    detail = (result.stderr or "").strip()[:200]
                    raise OSError(f"{tool[0]}: {detail}")
                return
        gtk_set_clipboard_text(text, CLIENT_CLIPBOARD_TIMEOUT_S)

    def easytier_daemon_address(self) -> str:
        """``/run/neutrino/client/easytier.sock``."""
        return CLIENT_EASYTIER_SOCKET_PATH_LINUX

    def easytier_state_dir(self) -> str:
        """``/var/lib/neutrino/client/easytier``."""
        return CLIENT_EASYTIER_STATE_DIR_LINUX

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


def gtk_clipboard_text(timeout_s: float) -> str:
    """The clipboard's text as GTK reads it, asked on GTK's own main loop.

    Args:
        timeout_s: How long the main loop is given to answer.

    Returns:
        The text; empty when the clipboard holds none.

    Raises:
        OSError: When GTK cannot be loaded.
        TimeoutError: When no main loop answers in time.
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
    except (ImportError, ValueError) as error:
        raise OSError(f"no clipboard tool and no GTK here: {error}") from error
    answer = {"text": ""}
    done = threading.Event()

    def received(_clipboard, text) -> None:
        answer["text"] = text or ""
        done.set()

    def ask() -> bool:
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_text(received)
        return False

    GLib.idle_add(ask)
    if not done.wait(timeout_s):
        raise TimeoutError("the clipboard did not answer")
    return answer["text"]


def gtk_set_clipboard_text(text: str, timeout_s: float) -> None:
    """Put text on the clipboard through GTK, on GTK's own main loop.

    Args:
        text: The text.
        timeout_s: How long the main loop is given to take it.

    Raises:
        OSError: When GTK cannot be loaded.
        TimeoutError: When no main loop answers in time.
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
    except (ImportError, ValueError) as error:
        raise OSError(f"no clipboard tool and no GTK here: {error}") from error
    done = threading.Event()

    def put() -> bool:
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()
        done.set()
        return False

    GLib.idle_add(put)
    if not done.wait(timeout_s):
        raise TimeoutError("the clipboard did not answer")


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
