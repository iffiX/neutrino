"""The seat on Windows: the console session's user, and netstat.

The agent runs in session 0, so the person at the screen is read from the
session attached to the console: ``WTSGetActiveConsoleSessionId`` names it
and ``WTSQuerySessionInformationW`` its user, empty at the sign-in screen.
The connected peers are the established rows ``netstat`` prints for the
direct port. Windows asks for no permission before RustDesk shows the
screen, so a seated screen has nothing for a peer to wait on.

Not pure: calls the session API and runs netstat.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import subprocess

from neutrino_agent.platforms import win32
from neutrino_agent.rdp.netstat import established_count
from neutrino_agent.rdp.constants import (
    RDP_SESSION_TIMEOUT_S,
    RDP_WINDOWS_ESTABLISHED,
    RDP_WINDOWS_NETSTAT_COMMAND,
    RDP_WINDOWS_NO_CONSOLE_SESSION,
    RDP_WINDOWS_WTS_USER_NAME,
)


class WindowsSeat:
    """The Windows seat, behind the seat seam the share host reads."""

    def __init__(self, *, kernel32=None, wtsapi32=None):
        """
        Args:
            kernel32: The bound kernel32; None binds the real one.
            wtsapi32: The bound wtsapi32; None binds the real one.
        """
        self._kernel32 = kernel32
        self._wtsapi32 = wtsapi32

    def graphical_accounts(self) -> "list | None":
        """The account signed in at the console.

        Returns:
            ``[account]``, empty at the sign-in screen or with no console
            session, None where the session API cannot be asked.
        """
        try:
            kernel32, wtsapi32 = self._bound()
        except (OSError, AttributeError):
            return None
        session = kernel32.WTSGetActiveConsoleSessionId()
        if session == RDP_WINDOWS_NO_CONSOLE_SESSION:
            return []
        buffer = ctypes.c_wchar_p()
        size = win32.DWORD(0)
        if not wtsapi32.WTSQuerySessionInformationW(
            None,
            session,
            RDP_WINDOWS_WTS_USER_NAME,
            ctypes.byref(buffer),
            ctypes.byref(size),
        ):
            return None
        try:
            name = buffer.value or ""
        finally:
            wtsapi32.WTSFreeMemory(buffer)
        return [name] if name else []

    def has_desktop_session(self) -> bool:
        """Whether there is a desktop to share: always, on Windows."""
        return True

    def connected_count(self, port: int) -> int:
        """How many peers are connected to the direct port right now.

        Args:
            port: The local port a direct connection lands on.

        Returns:
            The number of established connections to it, zero when netstat
            cannot be run.
        """
        try:
            result = subprocess.run(
                list(RDP_WINDOWS_NETSTAT_COMMAND),
                capture_output=True,
                text=True,
                timeout=RDP_SESSION_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        return established_count(
            result.stdout or "",
            port,
            established=RDP_WINDOWS_ESTABLISHED,
            separator=":",
        )

    def screen_attention(self, account_home: str) -> str:
        """What a peer would wait on at a seated screen: nothing on Windows.

        Args:
            account_home: The home of the account the share is for.

        Returns:
            Empty.
        """
        return ""

    def _bound(self) -> tuple:
        """kernel32 and wtsapi32, bound on first use."""
        if self._kernel32 is None or self._wtsapi32 is None:
            libraries = win32.libraries()
            self._kernel32 = self._kernel32 or libraries.kernel32
            self._wtsapi32 = self._wtsapi32 or libraries.wtsapi32
        return self._kernel32, self._wtsapi32
