"""The Windows platform behind the contract.

The client runs in the person's own session, so a share is a drive mapping
made right here with ``New-SmbMapping``, fed the login on standard input.
The control channel is a named pipe of the person's own, whose peer identity
comes from pipe impersonation and must be the same account.
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
)
from neutrino_client.platforms.base import (
    ClientPlatform,
    PlatformUnsupportedError,
    ShareAttachError,
)

WINDOWS_CONFIG_DIR_NAME = "Neutrino Client"
WINDOWS_MOUNT_TIMEOUT_S = 60
# The last line a fully-run mapping script prints. PowerShell fed a script on
# standard input can discard it silently and still exit zero, so a zero exit
# without this marker is a failure, never a success.
WINDOWS_MOUNT_SUCCESS_MARKER = "NEUTRINO_MOUNT_OK"
CREATE_NO_WINDOW = 0x08000000

# Win32 values, by their own names.
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1


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


def _powershell_literal(value: str) -> str:
    """A PowerShell single-quoted literal for one value."""
    return "'" + value.replace("'", "''") + "'"


def _mapping_script(
    *, host: str, share: str, location: str, username: str, password: str
) -> str:
    """The PowerShell that stores the login and maps the share.

    Fed on standard input, so the login is on no argument vector. The script
    ends with a blank line, which is what closes a block PowerShell reads
    from ``-Command -``; the success marker is the proof it ran.

    Args:
        host: The share's host.
        share: The share name.
        location: The drive letter the share appears at.
        username: The share's own username.
        password: The share's own password.

    Returns:
        The script text, closed by a trailing blank line.
    """
    remote = f"\\\\{host}\\{share}"
    return (
        f"$h = {_powershell_literal(host)}\n"
        f"$u = {_powershell_literal(username)}\n"
        f"$p = {_powershell_literal(password)}\n"
        f"$remote = {_powershell_literal(remote)}\n"
        f"$local = {_powershell_literal(location)}\n"
        "try {\n"
        "  cmdkey /add:$h /user:$u /pass:$p | Out-Null\n"
        "  Remove-SmbMapping -LocalPath $local -Force "
        "-ErrorAction SilentlyContinue | Out-Null\n"
        "  New-SmbMapping -LocalPath $local -RemotePath $remote "
        "-UserName $u -Password $p -Persistent $true -ErrorAction Stop | Out-Null\n"
        f"  Write-Output '{WINDOWS_MOUNT_SUCCESS_MARKER}'\n"
        "  exit 0\n"
        "} catch {\n"
        "  Write-Error $_\n"
        "  exit 1\n"
        "}\n"
        "\n"
    )


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

    def suggest_mount_location(self) -> str:
        """The first unused drive letter, from the top down.

        Returns:
            A letter with its colon, or empty when every letter is taken.
        """
        for letter in "ZYXWVUTSRQPONMLKJIHGFE":
            if not os.path.exists(f"{letter}:\\"):
                return f"{letter}:"
        return ""

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
        script = _mapping_script(
            host=host,
            share=share,
            location=location,
            username=username,
            password=password,
        )
        result = self._run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", "-"],
            stdin=script,
            failure_code="mount_failed",
        )
        if WINDOWS_MOUNT_SUCCESS_MARKER not in (result.stdout or ""):
            detail = ((result.stdout or "") + (result.stderr or "")).strip()[-200:]
            raise ShareAttachError("mount_failed", detail=detail)

    def detach_share(self, *, location: str) -> None:
        """Delete the mapping at a drive letter.

        Args:
            location: The mapped drive letter.

        Raises:
            ShareAttachError: ``unmount_failed`` with the tool's own words.
        """
        self._run(
            ["net", "use", location, "/delete", "/y"], failure_code="unmount_failed"
        )

    def is_share_attached(self, *, location: str) -> bool:
        """Whether a mapping stands at a drive letter.

        Args:
            location: The mapped drive letter.

        Returns:
            True when ``net use <drive>`` names a remote path.
        """
        try:
            result = subprocess.run(
                ["net", "use", location],
                capture_output=True,
                text=True,
                timeout=WINDOWS_MOUNT_TIMEOUT_S,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and "\\\\" in (result.stdout or "")

    def _run(self, command: list, *, stdin: str = "", failure_code: str):
        """Run one tool in this session, its failure typed.

        Args:
            command: Argument vector.
            stdin: Sent to standard input.
            failure_code: The code a non-zero exit carries.

        Returns:
            The completed process.

        Raises:
            ShareAttachError: With the tool's own words on failure.
        """
        try:
            result = subprocess.run(
                command,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=WINDOWS_MOUNT_TIMEOUT_S,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ShareAttachError(failure_code, detail=str(error)[:200])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-200:]
            raise ShareAttachError(failure_code, detail=detail)
        return result

    def _win32(self):
        """The Win32 seam, built on first use."""
        if self._win32_api is None:
            self._win32_api = _Win32Api()
        return self._win32_api


class _Win32Api:
    """The Win32 pipe identity calls, one seam tests replace whole."""

    def __init__(self):
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._kernel32.GetCurrentThread.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._advapi32.ImpersonateNamedPipeClient.argtypes = [ctypes.c_void_p]
        self._advapi32.OpenThreadToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self._advapi32.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self._advapi32.LookupAccountSidW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

    def impersonate_named_pipe_client(self, handle: int) -> None:
        """Impersonate the pipe's client on this thread.

        Raises:
            OSError: When impersonation is refused.
        """
        if not self._advapi32.ImpersonateNamedPipeClient(ctypes.c_void_p(handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def revert_to_self(self) -> None:
        """Drop the impersonation. Best-effort."""
        self._advapi32.RevertToSelf()

    def open_thread_token(self) -> int:
        """This thread's impersonation token, for querying.

        Raises:
            OSError: When the thread carries no token.
        """
        token = ctypes.c_void_p()
        ok = self._advapi32.OpenThreadToken(
            self._kernel32.GetCurrentThread(), TOKEN_QUERY, True, ctypes.byref(token)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return token.value

    def token_account(self, token: int) -> str:
        """The account name a token belongs to.

        Raises:
            OSError: When the token's user cannot be read.
        """
        needed = ctypes.c_ulong(0)
        self._advapi32.GetTokenInformation(
            ctypes.c_void_p(token), TOKEN_USER_CLASS, None, 0, ctypes.byref(needed)
        )
        buffer = ctypes.create_string_buffer(max(needed.value, 64))
        ok = self._advapi32.GetTokenInformation(
            ctypes.c_void_p(token),
            TOKEN_USER_CLASS,
            buffer,
            len(buffer),
            ctypes.byref(needed),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        name = ctypes.create_unicode_buffer(256)
        domain = ctypes.create_unicode_buffer(256)
        name_size = ctypes.c_ulong(len(name))
        domain_size = ctypes.c_ulong(len(domain))
        use = ctypes.c_ulong(0)
        ok = self._advapi32.LookupAccountSidW(
            None,
            ctypes.c_void_p(sid),
            name,
            ctypes.byref(name_size),
            domain,
            ctypes.byref(domain_size),
            ctypes.byref(use),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return name.value

    def close_handle(self, handle: int) -> None:
        """Close a handle. Best-effort."""
        self._kernel32.CloseHandle(ctypes.c_void_p(handle))
