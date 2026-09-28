"""One Windows service, stopped, started and asked about as this person.

The installer grants Users the right to start, stop and query the one
service the client drives, so none of this needs an administrator. Every
Win32 call rides one seam class, so nothing here needs Windows to import or
to test.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import time

from neutrino_client.platforms import win32

# How long a stop is waited for before the start is tried anyway.
SERVICE_STOP_WAIT_S = 30
SERVICE_POLL_S = 0.25


class WindowsServiceApi:
    """The Win32 service controller calls, one seam tests replace whole."""

    def __init__(self):
        """
        Raises:
            OSError: When the libraries cannot be loaded.
        """
        self._advapi32 = win32.libraries().advapi32

    def state(self, name: str) -> int:
        """One service's current state.

        Args:
            name: The service's name.

        Returns:
            One of the ``win32.SERVICE_*`` states.

        Raises:
            OSError: When the service cannot be opened or asked.
        """
        handle = self._open(name, win32.SERVICE_QUERY_STATUS)
        try:
            return self._query(handle)
        finally:
            self._advapi32.CloseServiceHandle(handle)

    def start(self, name: str) -> None:
        """Start one service; one already running is left running.

        Args:
            name: The service's name.

        Raises:
            OSError: When the service cannot be opened or started.
        """
        handle = self._open(name, win32.SERVICE_START)
        try:
            if not self._advapi32.StartServiceW(handle, 0, None):
                code = ctypes.get_last_error()
                if code != win32.ERROR_SERVICE_ALREADY_RUNNING:
                    raise ctypes.WinError(code)
        finally:
            self._advapi32.CloseServiceHandle(handle)

    def stop(self, name: str) -> None:
        """Stop one service and wait for it to stop; one not running is left.

        Args:
            name: The service's name.

        Raises:
            OSError: When the service cannot be opened or stopped.
            TimeoutError: When it has not stopped in ``SERVICE_STOP_WAIT_S``.
        """
        handle = self._open(name, win32.SERVICE_STOP | win32.SERVICE_QUERY_STATUS)
        try:
            status = win32.ServiceStatus()
            if not self._advapi32.ControlService(
                handle, win32.SERVICE_CONTROL_STOP, ctypes.byref(status)
            ):
                code = ctypes.get_last_error()
                if code != win32.ERROR_SERVICE_NOT_ACTIVE:
                    raise ctypes.WinError(code)
            deadline = time.monotonic() + SERVICE_STOP_WAIT_S
            while self._query(handle) != win32.SERVICE_STOPPED:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{name} did not stop")
                time.sleep(SERVICE_POLL_S)
        finally:
            self._advapi32.CloseServiceHandle(handle)

    def _open(self, name: str, access: int) -> int:
        """One service's handle with the rights asked for.

        Raises:
            OSError: When the controller or the service refuses.
        """
        manager = self._advapi32.OpenSCManagerW(None, None, win32.SC_MANAGER_CONNECT)
        if not manager:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            handle = self._advapi32.OpenServiceW(manager, name, access)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            return handle
        finally:
            self._advapi32.CloseServiceHandle(manager)

    def _query(self, handle: int) -> int:
        """The state an open service is in.

        Raises:
            OSError: When the controller will not say.
        """
        status = win32.ServiceStatus()
        if not self._advapi32.QueryServiceStatus(handle, ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(status.dwCurrentState)
