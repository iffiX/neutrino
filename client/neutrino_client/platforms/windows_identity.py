"""Who is on the other end of the control pipe, read by impersonation.

The server thread takes the client's token for the length of one query,
resolves the token's user to an account name, and reverts. Every Win32 call
rides one seam class, so nothing here needs Windows to import or to test.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes

from neutrino_client.platforms import win32


class WindowsIdentityApi:
    """The Win32 pipe identity calls, one seam tests replace whole."""

    def __init__(self):
        """
        Raises:
            OSError: When the libraries cannot be loaded.
        """
        libraries = win32.libraries()
        self._kernel32 = libraries.kernel32
        self._advapi32 = libraries.advapi32

    def impersonate_named_pipe_client(self, handle: int) -> None:
        """Impersonate the pipe's client on this thread.

        Args:
            handle: The connected pipe instance.

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

        Returns:
            The token handle.

        Raises:
            OSError: When the thread carries no token.
        """
        token = ctypes.c_void_p()
        ok = self._advapi32.OpenThreadToken(
            self._kernel32.GetCurrentThread(),
            win32.TOKEN_QUERY,
            True,
            ctypes.byref(token),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return token.value

    def token_account(self, token: int) -> str:
        """The account name a token belongs to.

        Args:
            token: The token handle to query.

        Returns:
            The account name, without its domain.

        Raises:
            OSError: When the token's user cannot be read.
        """
        user = win32.TokenUser(advapi32=self._advapi32, token=token)
        name = ctypes.create_unicode_buffer(256)
        domain = ctypes.create_unicode_buffer(256)
        name_size = ctypes.c_ulong(len(name))
        domain_size = ctypes.c_ulong(len(domain))
        use = ctypes.c_ulong(0)
        ok = self._advapi32.LookupAccountSidW(
            None,
            ctypes.c_void_p(user.sid),
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
