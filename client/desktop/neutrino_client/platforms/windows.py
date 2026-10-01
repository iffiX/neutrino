"""The Windows platform behind the contract.

The client runs in the person's own session, so a share is a drive mapping
made by this process itself: a mapping belongs to the logon session that
made it, and one made anywhere else is reachable by name yet drawn as
disconnected in File Explorer. The login travels in a structure, on no
argument vector. The control channel is a named pipe of the person's own,
whose peer identity comes from pipe impersonation and must be the same
account. An EasyTier network is asked of the EasyTier daemon, a service
running as SYSTEM, over its named pipe; the daemon keeps its state under
ProgramData in a directory only SYSTEM and the administrators may open, and
ties the core it starts to its own life with a job object.
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
    CLIENT_EASYTIER_PIPE_WINDOWS,
    CLIENT_EASYTIER_STATE_NAME_WINDOWS,
    CLIENT_OVERLAY_DATA_DIR_WINDOWS,
)
from neutrino_client.platforms import win32
from neutrino_client.exceptions import (
    PlatformUnsupportedError,
    ShareAttachError,
)
from neutrino_client.platforms.base import (
    ClientPlatform,
    read_share_credentials,
    run_quietly,
    share_parts,
)
from neutrino_client.platforms.windows_console import (
    WindowsConsoleApi,
    WindowsRawConsole,
)
from neutrino_client.platforms.windows_identity import WindowsIdentityApi
from neutrino_client.words import language_for_tag

WINDOWS_CONFIG_DIR_NAME = "Neutrino Client"
WINDOWS_MOUNT_TIMEOUT_S = 60
WINDOWS_PROGRAM_DATA_DEFAULT = "C:\\ProgramData"

# A share that File Explorer never hears about stands there as a disconnected
# drive while every other program reaches it; the shell is told after a
# mapping comes or goes.
SHCNE_DRIVEADD = win32.SHCNE_DRIVEADD
SHCNE_DRIVEREMOVED = win32.SHCNE_DRIVEREMOVED


def _pipe_safe_name(account: str) -> str:
    """An account name with the characters a pipe name refuses replaced."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", account)


# What WNetAddConnection2 answers a share with, as the typed refusals every
# platform words alike. Anything outside the table is ``mount_failed`` with
# the Win32 message.
SHARE_REFUSALS = {
    win32.ERROR_LOGON_FAILURE: "share_login_rejected",
    win32.ERROR_INVALID_PASSWORD: "share_login_rejected",
    win32.ERROR_ACCESS_DENIED: "share_access_denied",
    win32.ERROR_BAD_NET_NAME: "share_not_found",
    win32.ERROR_BAD_NETPATH: "share_unreachable",
    win32.ERROR_NO_NET_OR_BAD_PATH: "share_unreachable",
    win32.ERROR_NO_NETWORK: "share_unreachable",
    win32.ERROR_SESSION_CREDENTIAL_CONFLICT: "share_session_conflict",
}


# The EasyTier daemon's state directory: SYSTEM and the administrators alone,
# every file in it the same, nothing taken from ProgramData above it.
EASYTIER_STATE_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"


class WindowsPlatform(ClientPlatform):
    """Windows behind the platform contract."""

    os_name = "windows"
    mount_location_shape = "drive_letter"

    def __init__(self, *, win32=None):
        """
        Args:
            win32: The Win32 seam; None builds the real one on first use.
        """
        self._win32_api = win32
        self._job: "int | None" = None

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
            ShareAttachError: ``credentials_missing`` without the file; the
                share refusal the Win32 code names, ``share_login_rejected``
                for a wrong username or password among them; ``mount_failed``
                with the Win32 message for any other code.
        """
        host, share = share_parts(share_url)
        if not host or not share:
            raise ShareAttachError("mount_failed", detail="unreadable share url")
        if not os.path.isfile(credentials_path):
            raise ShareAttachError("credentials_missing")
        username, password = read_share_credentials(credentials_path)
        code = self._win32().add_connection(
            local=location,
            remote=f"\\\\{host}\\{share}",
            username=username,
            password=password,
        )
        if code != win32.NO_ERROR:
            raise ShareAttachError(
                SHARE_REFUSALS.get(code, "mount_failed"), detail=win32.win_error(code)
            )
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
        # Enter on a Windows console is a carriage return.
        return self._win32().run_on_console(
            argv, prompt=prompt, answer=answer.replace("\n", "\r"), timeout_s=timeout_s
        )

    def raw_terminal(self) -> WindowsRawConsole:
        """This process's console in raw VT mode."""
        return WindowsRawConsole()

    def read_clipboard(self) -> str:
        """The clipboard's text, read through ``OpenClipboard``.

        Returns:
            The text; empty when the clipboard holds none.

        Raises:
            OSError: When another program holds the clipboard or Windows
                refuses.
        """
        return self._win32().clipboard_text()

    def write_clipboard(self, text: str) -> None:
        """Put text on the clipboard through ``SetClipboardData``.

        Args:
            text: The text.

        Raises:
            OSError: When another program holds the clipboard or Windows
                refuses.
        """
        self._win32().set_clipboard_text(text)

    def easytier_daemon_address(self) -> str:
        """The pipe named ``neutrino_client_easytier``."""
        return CLIENT_EASYTIER_PIPE_WINDOWS

    def easytier_state_dir(self) -> str:
        """``easytier`` under ``Neutrino Client`` in ProgramData."""
        root = os.environ.get("PROGRAMDATA", "") or WINDOWS_PROGRAM_DATA_DEFAULT
        return os.path.join(
            root, CLIENT_OVERLAY_DATA_DIR_WINDOWS, CLIENT_EASYTIER_STATE_NAME_WINDOWS
        )

    def secure_easytier_state_dir(self, path: str) -> None:
        """Make the state directory, SYSTEM's and the administrators' alone.

        Args:
            path: The directory.

        Raises:
            OSError: When it cannot be made or its access list set.
        """
        os.makedirs(path, exist_ok=True)
        self._win32().protect_directory(path, EASYTIER_STATE_SDDL)

    def bind_child_process(self, process) -> None:
        """Put a child in a job that ends it when the daemon ends.

        Args:
            process: The started ``subprocess.Popen``.

        Raises:
            OSError: When the job cannot be made or the child put in it.
        """
        api = self._win32()
        if self._job is None:
            self._job = api.create_kill_on_close_job()
        api.assign_to_job(self._job, int(process._handle))

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

    def protect_directory(self, path: str, sddl: str) -> None:
        """Set a directory's access list whole, cut off from its parent's.

        Args:
            path: The directory.
            sddl: The descriptor whose access list it takes.

        Raises:
            OSError: When the descriptor or the directory refuses.
        """
        libraries = win32.libraries()
        advapi32 = libraries.advapi32
        descriptor = ctypes.c_void_p()
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, win32.SDDL_REVISION_1, ctypes.byref(descriptor), None
        ):
            raise win32.last_error()
        try:
            is_present = ctypes.c_int()
            dacl = ctypes.c_void_p()
            is_defaulted = ctypes.c_int()
            if not advapi32.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(is_present),
                ctypes.byref(dacl),
                ctypes.byref(is_defaulted),
            ):
                raise win32.last_error()
            status = advapi32.SetNamedSecurityInfoW(
                path,
                win32.SE_FILE_OBJECT,
                win32.DACL_SECURITY_INFORMATION
                | win32.PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                dacl,
                None,
            )
            if status != win32.NO_ERROR:
                raise ctypes.WinError(status)
        finally:
            libraries.kernel32.LocalFree(descriptor)

    def create_kill_on_close_job(self) -> int:
        """A job whose processes end when its last handle closes.

        Returns:
            The job's handle, held for the life of this process.

        Raises:
            OSError: When the job cannot be made or limited.
        """
        kernel32 = win32.libraries().kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise win32.last_error()
        limits = win32.JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = (
            win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            job,
            win32.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = win32.last_error()
            kernel32.CloseHandle(job)
            raise error
        return job

    def assign_to_job(self, job: int, process_handle: int) -> None:
        """Put one process in a job.

        Args:
            job: The job's handle.
            process_handle: The process's handle.

        Raises:
            OSError: When Windows refuses.
        """
        if not win32.libraries().kernel32.AssignProcessToJobObject(job, process_handle):
            raise win32.last_error()

    def clipboard_text(self) -> str:
        """The clipboard's Unicode text, the clipboard closed again after.

        Returns:
            The text; empty when the clipboard holds no text.

        Raises:
            OSError: When the clipboard cannot be opened or its text locked.
        """
        libraries = win32.libraries()
        user32 = libraries.user32
        kernel32 = libraries.kernel32
        if not user32.OpenClipboard(None):
            raise win32.last_error()
        try:
            handle = user32.GetClipboardData(win32.CF_UNICODETEXT)
            if not handle:
                return ""
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise win32.last_error()
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def set_clipboard_text(self, text: str) -> None:
        """Replace the clipboard's content with Unicode text.

        Args:
            text: The text.

        Raises:
            OSError: When the clipboard cannot be opened, the memory cannot
                be had, or Windows refuses the data.
        """
        libraries = win32.libraries()
        user32 = libraries.user32
        kernel32 = libraries.kernel32
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        if not user32.OpenClipboard(None):
            raise win32.last_error()
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(win32.GMEM_MOVEABLE, size)
            if not handle:
                raise win32.last_error()
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                error = win32.last_error()
                kernel32.GlobalFree(handle)
                raise error
            try:
                ctypes.memmove(pointer, data, size)
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(win32.CF_UNICODETEXT, handle):
                error = win32.last_error()
                kernel32.GlobalFree(handle)
                raise error
        finally:
            user32.CloseClipboard()

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
