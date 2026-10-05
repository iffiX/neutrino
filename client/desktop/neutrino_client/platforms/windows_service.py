"""Running as a Windows service: the dispatcher, the handler, the states.

The service control manager starts ``nclient.exe easytier-daemon --service``
and waits for the process to call ``StartServiceCtrlDispatcherW``; a process
that has not within 30 seconds is failed with error 1053. The dispatcher
calls the service's main on a thread of its own, which registers the control
handler, reports ``START_PENDING`` and then ``RUNNING``, and runs the
daemon. A stop or a shutdown reports ``STOP_PENDING`` and returns to the
manager at once; the service's main thread then runs the stop callback,
reports ``STOPPED`` and returns, and the process ends once the dispatcher
hands its thread back. A control handler that does not return is a stop
the manager reports as failed. A daemon that ends by
itself ends the process without reporting ``STOPPED``, which the manager
reads as a crash and answers with the service's recovery actions.

Not pure: talks to the service control manager and ends the process.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import os
import threading

from neutrino_client.platforms import win32

# How long the service control manager is told a start or a stop may take
# before it reports the service hung.
SERVICE_WAIT_HINT_MS = 30_000


class ServiceControlDispatcher:
    """One service in this process, as the service control manager sees it."""

    def __init__(self, name: str, on_start, on_stop, *, advapi32=None, exit=None):
        """
        Args:
            name: The service name the manager knows.
            on_start: Called with no arguments once the service is running;
                it runs the daemon and returns only if the daemon ended.
            on_stop: Called with no arguments when the manager stops the
                service or the machine shuts down.
            advapi32: The bound advapi32; None binds the real one.
            exit: Ends the process with a status; None is ``os._exit``.
        """
        self._name = name
        self._on_start = on_start
        self._on_stop = on_stop
        self._advapi32 = advapi32
        self._exit = exit if exit is not None else os._exit
        self._status_handle = None
        self._is_stop_asked = threading.Event()
        self._is_stopped = threading.Event()
        # The callbacks the manager holds pointers to, kept alive here.
        self._callbacks: list = []

    def run(self) -> None:
        """Hand this thread to the service control manager until the service ends.

        The process ends with status 0 once the service has stopped.

        Raises:
            OSError: When the process was not started by the service control
                manager (error 1063), or the dispatcher could not start.
        """
        advapi32 = self._bound_advapi32()
        main = win32.service_main_type()(self._service_main)
        self._callbacks.append(main)
        table = (win32.ServiceTableEntry * 2)()
        table[0].lpServiceName = self._name
        table[0].lpServiceProc = ctypes.cast(main, ctypes.c_void_p)
        if not advapi32.StartServiceCtrlDispatcherW(table):
            raise win32.last_error()
        self._exit(0)

    def _bound_advapi32(self):
        """advapi32, bound on first use."""
        if self._advapi32 is None:
            self._advapi32 = win32.libraries().advapi32
        return self._advapi32

    def _service_main(self, argument_count, arguments) -> None:
        """The service's main: register, report, run the daemon, stop on request."""
        handler = win32.service_handler_type()(self._handle_control)
        self._callbacks.append(handler)
        self._status_handle = self._advapi32.RegisterServiceCtrlHandlerExW(
            self._name, ctypes.cast(handler, ctypes.c_void_p), None
        )
        if not self._status_handle:
            return
        self._report(win32.SERVICE_START_PENDING, wait_hint_ms=SERVICE_WAIT_HINT_MS)
        worker = threading.Thread(
            target=self._run_daemon, name="easytier_service", daemon=True
        )
        worker.start()
        self._report(win32.SERVICE_RUNNING)
        self._is_stop_asked.wait()
        try:
            self._on_stop()
        finally:
            self._report(win32.SERVICE_STOPPED)
            self._is_stopped.set()

    def _run_daemon(self) -> None:
        """Run the daemon; one that ends by itself ends the process as a crash."""
        try:
            self._on_start()
        finally:
            if not self._is_stop_asked.is_set():
                self._exit(1)

    def _handle_control(self, control, event_type, event_data, context) -> int:
        """Answer one control from the service control manager."""
        if control in (win32.SERVICE_CONTROL_STOP, win32.SERVICE_CONTROL_SHUTDOWN):
            if self._is_stop_asked.is_set():
                return win32.NO_ERROR
            self._report(win32.SERVICE_STOP_PENDING, wait_hint_ms=SERVICE_WAIT_HINT_MS)
            self._is_stop_asked.set()
            return win32.NO_ERROR
        if control == win32.SERVICE_CONTROL_INTERROGATE:
            return win32.NO_ERROR
        return win32.ERROR_CALL_NOT_IMPLEMENTED

    def _report(self, state: int, *, wait_hint_ms: int = 0) -> None:
        """Tell the manager where the service stands."""
        status = win32.ServiceStatus()
        status.dwServiceType = win32.SERVICE_WIN32_OWN_PROCESS
        status.dwCurrentState = state
        status.dwControlsAccepted = (
            win32.SERVICE_ACCEPT_STOP | win32.SERVICE_ACCEPT_SHUTDOWN
            if state == win32.SERVICE_RUNNING
            else 0
        )
        status.dwWin32ExitCode = win32.NO_ERROR
        status.dwWaitHint = wait_hint_ms
        self._advapi32.SetServiceStatus(self._status_handle, ctypes.byref(status))
