"""The Windows platform behind the contract.

The client runs in the person's own session, so a share is a drive mapping
made by this process itself: a mapping belongs to the logon session that
made it, and one made anywhere else is reachable by name yet drawn as
disconnected in File Explorer. The login travels in a structure, on no
argument vector. The control channel is a named pipe of the person's own,
whose peer identity comes from pipe impersonation and must be the same
account.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import getpass
import os
import re
import subprocess

from neutrino_client.constants import (
    CLIENT_CONTROL_PIPE_NAME_PREFIX,
    CLIENT_CONTROL_PIPE_PREFIX,
    CLIENT_DEFAULT_LANGUAGE,
)
from neutrino_client.platforms import win32
from neutrino_client.exceptions import PlatformUnsupportedError, ShareAttachError
from neutrino_client.platforms.base import ClientPlatform, run_quietly
from neutrino_client.platforms.windows_console import WindowsConsoleApi
from neutrino_client.platforms.windows_identity import WindowsIdentityApi
from neutrino_client.words import language_for_tag

WINDOWS_CONFIG_DIR_NAME = "Neutrino Client"
WINDOWS_MOUNT_TIMEOUT_S = 60

# A share that File Explorer never hears about stands there as a disconnected
# drive while every other program reaches it; the shell is told after a
# mapping comes or goes.
SHCNE_DRIVEADD = win32.SHCNE_DRIVEADD
SHCNE_DRIVEREMOVED = win32.SHCNE_DRIVEREMOVED


def _share_parts(share_url: str) -> "tuple[str, str]":
    """The host and share a ``//host/name`` URL names.

    Args:
        share_url: The share URL.

    Returns:
        The host and the share name, either empty when unreadable.
    """
    trimmed = share_url.replace("\\", "/").strip("/")
    host, _, share = trimmed.partition("/")
    return host, share


def _read_share_credentials(path: str) -> "tuple[str, str]":
    """One credentials file's login.

    Args:
        path: The credentials file.

    Returns:
        The username and password, empty where unreadable.
    """
    values = {"username": "", "password": ""}
    try:
        with open(path, "r", encoding="utf-8") as stream:
            for line in stream:
                key, _, value = line.partition("=")
                if key.strip() in values:
                    values[key.strip()] = value.rstrip("\n")
    except OSError:
        pass
    return values["username"], values["password"]


def _pipe_safe_name(account: str) -> str:
    """An account name with the characters a pipe name refuses replaced."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", account)


class WindowsPlatform(ClientPlatform):
    """Windows behind the platform contract."""

    os_name = "windows"
    mount_location_shape = "drive_letter"

    def __init__(self, *, win32=None):
        """
        Args:
            win32: The Win32 seam for pipe identity; None builds the real one
                on first use.
        """
        self._win32_api = win32

    def config_dir(self) -> str:
        """``%APPDATA%\\Neutrino Client``."""
        root = os.environ.get("APPDATA", "") or os.path.join(
            self.home(), "AppData", "Roaming"
        )
        return os.path.join(root, WINDOWS_CONFIG_DIR_NAME)

    def system_language(self) -> str:
        """The language this account's Windows UI is in.

        Returns:
            One of ``CLIENT_LANGUAGES``; the default where Windows cannot
            be asked.
        """
        try:
            language_id = self._win32().user_ui_language_id()
        except OSError:
            return CLIENT_DEFAULT_LANGUAGE
        primary = language_id & win32.LANGUAGE_PRIMARY_MASK
        if primary == win32.LANGUAGE_PRIMARY_CHINESE:
            return language_for_tag("zh")
        return CLIENT_DEFAULT_LANGUAGE

    def control_socket_path(self) -> str:
        """This person's own named pipe."""
        return (
            CLIENT_CONTROL_PIPE_PREFIX
            + CLIENT_CONTROL_PIPE_NAME_PREFIX
            + _pipe_safe_name(self.current_account())
        )

    def current_account(self) -> str:
        """The account this process runs as."""
        return getpass.getuser()

    def read_peer_identity(self, connection) -> dict:
        """A pipe peer's identity, from pipe impersonation.

        Args:
            connection: The accepted pipe connection.

        Returns:
            ``{"account", "uid", "is_same_user"}``; ``uid`` is -1 because
            Windows reports names.

        Raises:
            PlatformUnsupportedError: When the peer is not a pipe or the
                token cannot be read.
        """
        handle = getattr(connection, "pipe_handle", None)
        if handle is None:
            raise PlatformUnsupportedError("not a pipe peer")
        win32 = self._win32()
        try:
            win32.impersonate_named_pipe_client(handle)
        except OSError as error:
            raise PlatformUnsupportedError(str(error))
        try:
            token = win32.open_thread_token()
            try:
                account = win32.token_account(token)
            finally:
                win32.close_handle(token)
        except OSError as error:
            raise PlatformUnsupportedError(str(error))
        finally:
            win32.revert_to_self()
        return {
            "account": account,
            "uid": -1,
            "is_same_user": account.lower() == self.current_account().lower(),
        }

    def validate_mount_location(self, *, location: str) -> "dict | None":
        """Judge a proposed mount location: a single drive letter plus a colon.

        Args:
            location: The proposed location, as typed.

        Returns:
            None for an unused drive letter such as ``Z:``, otherwise the
            typed refusal ``{"code", "params"}``.
        """
        if re.fullmatch(r"[A-Za-z]:", location) is None:
            return {"code": "mountpoint_not_drive_letter", "params": {}}
        if os.path.exists(location + "\\"):
            return {"code": "mountpoint_not_empty", "params": {}}
        return None

    def mount_location_choices(self) -> list:
        """Every drive letter still open, from the top down.

        Returns:
            Free letters with their colon, e.g. ``["Z:", "Y:", ...]``.
        """
        return [
            f"{letter}:"
            for letter in "ZYXWVUTSRQPONMLKJIHGFE"
            if not os.path.exists(f"{letter}:\\")
        ]

    def suggest_mount_location(self) -> str:
        """The first unused drive letter, from the top down.

        Returns:
            A letter with its colon, or empty when every letter is taken.
        """
        free = self.mount_location_choices()
        return free[0] if free else ""

    def prepare_mount_location(self, *, location: str) -> "dict | None":
        """A drive letter needs no preparation."""
        return None

    def attach_share(
        self, *, share_url: str, location: str, credentials_path: str
    ) -> None:
        """Map a share in this person's own session.

        Args:
            share_url: The share, as ``//host/name``.
            location: The drive letter.
            credentials_path: The credentials file the login is read from.

        Raises:
            ShareAttachError: ``credentials_missing`` without the file,
                ``mount_failed`` with the tool's own words otherwise.
        """
        host, share = _share_parts(share_url)
        if not host or not share:
            raise ShareAttachError("mount_failed", detail="unreadable share url")
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        username, password = _read_share_credentials(credentials_path)
        code = self._win32().add_connection(
            local=location,
            remote=f"\\\\{host}\\{share}",
            username=username,
            password=password,
        )
        if code != win32.NO_ERROR:
            raise ShareAttachError("mount_failed", detail=win32.win_error(code))
        self._announce_drive(location, SHCNE_DRIVEADD)

    def detach_share(self, *, location: str) -> None:
        """Take the mapping at a drive letter down, in this session.

        Args:
            location: The mapped drive letter.

        Raises:
            ShareAttachError: ``unmount_failed`` with the Win32 error.
        """
        code = self._win32().cancel_connection(location)
        # A letter only remembered from an earlier build is taken off the
        # profile and answered as not connected: gone either way.
        if code not in (win32.NO_ERROR, win32.ERROR_NOT_CONNECTED):
            raise ShareAttachError("unmount_failed", detail=win32.win_error(code))
        self._announce_drive(location, SHCNE_DRIVEREMOVED)

    def is_share_attached(self, *, location: str) -> bool:
        """Whether a mapping stands at a drive letter.

        Args:
            location: The mapped drive letter.

        Returns:
            True when ``net use <drive>`` names a remote path.
        """
        try:
            result = run_quietly(
                ["net", "use", location], timeout_s=WINDOWS_MOUNT_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and "\\" in (result.stdout or "")

    def run_answering(
        self, argv: list, *, prompt: str, answer: str, timeout_s: float
    ) -> tuple:
        """Run a program on a pseudo console and answer one prompt.

        Args:
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long the whole run may take.

        Returns:
            ``(returncode, output)``.

        Raises:
            PlatformUnsupportedError: When no pseudo console can be made.
        """
        return self._win32().run_on_console(
            argv, prompt=prompt, answer=answer, timeout_s=timeout_s
        )

    def _announce_drive(self, location: str, event: int) -> None:
        """Tell the shell a drive letter came or went.

        A share that File Explorer never hears about stands there as a
        disconnected drive while every other program reaches it.

        Args:
            location: The drive letter, as ``Z:``.
            event: ``SHCNE_DRIVEADD`` or ``SHCNE_DRIVEREMOVED``.
        """
        try:
            self._win32().notify_drive(location + "\\", event)
        except OSError:
            # The mapping stands either way; only the icon is at stake.
            pass

    def _win32(self):
        """The Win32 seam, built on first use."""
        if self._win32_api is None:
            self._win32_api = _WindowsApi()
        return self._win32_api


class _WindowsApi:
    """The Win32 the Windows platform reaches, one seam tests replace whole.

    Mount, the shell notification and the pseudo console run here; the pipe
    identity is :class:`WindowsIdentityApi`, held so a peer's account is
    read the one way it is read anywhere.
    """

    def __init__(self):
        self._identity = WindowsIdentityApi()
        self._console = WindowsConsoleApi()

    def add_connection(
        self, *, local: str, remote: str, username: str, password: str
    ) -> int:
        """Map a share into this process's own logon session, not persisted.

        The login travels in a structure rather than on any argument vector,
        and the session is this one, which is what leaves the drive standing
        for every program the person runs. It is not written to the profile:
        the client remounts what it holds, so Windows need not, and a
        persisted mapping is what File Explorer keeps drawing after it is
        gone.

        Args:
            local: The drive letter, as ``Z:``.
            remote: The share, as ``\\\\host\\share``.
            username: The share's own username.
            password: The share's own password.

        Returns:
            ``win32.NO_ERROR``, or the Win32 error number.
        """
        resource = win32.NetResource()
        resource.dwType = win32.RESOURCETYPE_DISK
        resource.lpLocalName = local
        resource.lpRemoteName = remote
        return int(
            win32.libraries().mpr.WNetAddConnection2W(
                ctypes.byref(resource), password, username, 0
            )
        )

    def cancel_connection(self, local: str) -> int:
        """Take a drive mapping down, and off the profile if remembered there.

        Args:
            local: The drive letter, as ``Z:``.

        Returns:
            ``win32.NO_ERROR``, or the Win32 error number.
        """
        return int(
            win32.libraries().mpr.WNetCancelConnection2W(
                local, win32.CONNECT_UPDATE_PROFILE, True
            )
        )

    def user_ui_language_id(self) -> int:
        """The LANGID of the UI language this account signed in with.

        Returns:
            The LANGID Windows answers with.

        Raises:
            OSError: When kernel32 cannot be reached, which is every call
                off Windows.
        """
        return int(win32.libraries().kernel32.GetUserDefaultUILanguage())

    def notify_drive(self, path: str, event: int) -> None:
        """Raise the shell's own drive-changed notification.

        Args:
            path: The drive's root, as ``Z:\\``.
            event: ``win32.SHCNE_DRIVEADD`` or ``win32.SHCNE_DRIVEREMOVED``.
        """
        win32.libraries().shell32.SHChangeNotify(event, win32.SHCNF_PATHW, path, None)

    def run_on_console(
        self, argv: list, *, prompt: str, answer: str, timeout_s: float
    ) -> tuple:
        """Run a program on a pseudo console and answer one prompt.

        Args:
            argv: Argument vector.
            prompt: The text the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long the whole run may take.

        Returns:
            ``(returncode, output)``.

        Raises:
            PlatformUnsupportedError: When the console API is not there.
        """
        return self._console.run(
            argv, prompt=prompt, answer=answer, timeout_s=timeout_s
        )

    def impersonate_named_pipe_client(self, handle: int) -> None:
        """Impersonate the pipe's client on this thread."""
        self._identity.impersonate_named_pipe_client(handle)

    def revert_to_self(self) -> None:
        """Drop the impersonation. Best-effort."""
        self._identity.revert_to_self()

    def open_thread_token(self) -> int:
        """This thread's impersonation token, for querying."""
        return self._identity.open_thread_token()

    def token_account(self, token: int) -> str:
        """The account name a token belongs to."""
        return self._identity.token_account(token)

    def close_handle(self, handle: int) -> None:
        """Close a handle. Best-effort."""
        self._identity.close_handle(handle)
