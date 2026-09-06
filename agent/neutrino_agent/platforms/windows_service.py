"""The agent's residency on Windows: a real service, spoken over the SCM.

Windows starts the agent the way systemd and launchd do on the other two
platforms — as a service of its own, not a task the scheduler runs. What that
costs is a handshake: a service process has to answer the service control
manager within seconds of starting, report ``running``, and answer ``stop``
when it is asked to. This module is that handshake, in ctypes, so the agent
needs no wrapper binary and no dependency to be one.

The agent loop runs on a daemon thread while ``service_main`` waits for a
control; a stop reports the state and returns, and the loop dies with the
process. Every Win32 call rides one seam class, so nothing here needs Windows
to import or to test.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import threading
from contextlib import contextmanager

SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_SHUTDOWN = 0x00000004

SERVICE_STOPPED = 1
SERVICE_START_PENDING = 2
SERVICE_STOP_PENDING = 3
SERVICE_RUNNING = 4
SERVICE_PAUSED = 7

SERVICE_CONTROL_STOP = 1
SERVICE_CONTROL_SHUTDOWN = 5

# What the manager grants for each thing this asks of it.
SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_STATUS = 0x0004
SERVICE_START = 0x0010

# How long the manager is told to wait for a state that is still settling.
SERVICE_WAIT_HINT_MS = 10000

# The state words this platform reports, keyed by what the manager returns.
SERVICE_STATE_WORDS = {
    SERVICE_STOPPED: "stopped",
    SERVICE_START_PENDING: "starting",
    SERVICE_STOP_PENDING: "stopping",
    SERVICE_RUNNING: "running",
    SERVICE_PAUSED: "paused",
}


class ServiceStatus(ctypes.Structure):
    """The SERVICE_STATUS the manager is told about and asked for."""

    _fields_ = [
        ("dwServiceType", ctypes.c_ulong),
        ("dwCurrentState", ctypes.c_ulong),
        ("dwControlsAccepted", ctypes.c_ulong),
        ("dwWin32ExitCode", ctypes.c_ulong),
        ("dwServiceSpecificExitCode", ctypes.c_ulong),
        ("dwCheckPoint", ctypes.c_ulong),
        ("dwWaitHint", ctypes.c_ulong),
    ]


def host_service(*, name: str, run, api=None) -> None:
    """Run the agent as the named service until the manager stops it.

    Args:
        name: The service name the manager knows.
        run: The agent's own loop, which never returns by itself.
        api: The Win32 seam; None uses the real one.

    Raises:
        OSError: When the manager refuses the dispatcher, which is what a
            service process started by anything but the manager gets.
    """
    service_api = api if api is not None else Win32ServiceApi()
    stopping = threading.Event()
    reported: dict = {}

    def on_control(control: int) -> None:
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            service_api.set_status(reported.get("handle"), SERVICE_STOP_PENDING)
            stopping.set()

    def service_main(*_arguments) -> None:
        reported["handle"] = service_api.register_control_handler(name, on_control)
        service_api.set_status(reported["handle"], SERVICE_START_PENDING)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        service_api.set_status(reported["handle"], SERVICE_RUNNING)
        stopping.wait()
        service_api.set_status(reported["handle"], SERVICE_STOPPED)

    service_api.start_dispatcher(name, service_main)


def read_state(name: str, *, api=None) -> str:
    """What the manager says about the named service.

    Args:
        name: The service name.
        api: The Win32 seam; None uses the real one.

    Returns:
        The state word, or ``unknown`` when the manager does not answer —
        which includes the service not being installed at all.
    """
    try:
        service_api = api if api is not None else Win32ServiceApi()
        state = service_api.query_state(name)
    except OSError:
        return "unknown"
    return SERVICE_STATE_WORDS.get(state, "unknown")


def start(name: str, *, api=None) -> None:
    """Ask the manager to start the named service. Best-effort.

    Args:
        name: The service name.
        api: The Win32 seam; None uses the real one.
    """
    try:
        service_api = api if api is not None else Win32ServiceApi()
        service_api.start_service(name)
    except OSError:
        return


class Win32ServiceApi:
    """The service control manager calls, one seam the tests replace whole."""

    def __init__(self):
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        # Handles are pointers: without these prototypes a 64-bit handle
        # comes back truncated to an int.
        for name in (
            "OpenSCManagerW",
            "OpenServiceW",
            "RegisterServiceCtrlHandlerW",
        ):
            getattr(self._advapi32, name).restype = ctypes.c_void_p
        self._advapi32.OpenServiceW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_ulong,
        ]
        self._advapi32.CloseServiceHandle.argtypes = [ctypes.c_void_p]
        self._advapi32.QueryServiceStatus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ServiceStatus),
        ]
        self._advapi32.StartServiceW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self._advapi32.SetServiceStatus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ServiceStatus),
        ]
        # The manager calls back into this process, so both callback types
        # are built here: the factory itself exists only on Windows.
        self._main_type = ctypes.WINFUNCTYPE(
            None, ctypes.c_ulong, ctypes.POINTER(ctypes.c_wchar_p)
        )
        self._handler_type = ctypes.WINFUNCTYPE(None, ctypes.c_ulong)
        # The manager keeps the pointers it is given; Python must keep the
        # objects behind them alive for as long as the service runs.
        self._callbacks: list = []

    def start_dispatcher(self, name: str, service_main) -> None:
        """Hand the manager this process's service entry and serve it.

        Blocks until the entry returns, which is what ends the service.

        Args:
            name: The service name the manager knows.
            service_main: What the manager calls to start the service.

        Raises:
            OSError: When the manager refuses the connection.
        """
        entry_type = self._main_type(service_main)
        self._callbacks.append(entry_type)

        class ServiceTableEntry(ctypes.Structure):
            _fields_ = [
                ("lpServiceName", ctypes.c_wchar_p),
                ("lpServiceProc", self._main_type),
            ]

        table = (ServiceTableEntry * 2)()
        table[0].lpServiceName = name
        table[0].lpServiceProc = entry_type
        if not self._advapi32.StartServiceCtrlDispatcherW(table):
            raise ctypes.WinError(ctypes.get_last_error())

    def register_control_handler(self, name: str, handler) -> int:
        """Register what answers the manager's controls.

        Args:
            name: The service name.
            handler: Called with each control code.

        Returns:
            The status handle every later report names.

        Raises:
            OSError: When the manager refuses the registration.
        """
        callback = self._handler_type(handler)
        self._callbacks.append(callback)
        handle = self._advapi32.RegisterServiceCtrlHandlerW(name, callback)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def set_status(self, handle: int, state: int) -> None:
        """Report one state to the manager.

        Args:
            handle: The status handle registration returned.
            state: One of the ``SERVICE_`` states.
        """
        status = ServiceStatus()
        status.dwServiceType = SERVICE_WIN32_OWN_PROCESS
        status.dwCurrentState = state
        status.dwControlsAccepted = (
            SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN
            if state == SERVICE_RUNNING
            else 0
        )
        status.dwWin32ExitCode = 0
        status.dwServiceSpecificExitCode = 0
        status.dwCheckPoint = 0
        status.dwWaitHint = (
            SERVICE_WAIT_HINT_MS
            if state in (SERVICE_START_PENDING, SERVICE_STOP_PENDING)
            else 0
        )
        self._advapi32.SetServiceStatus(handle, ctypes.byref(status))

    def query_state(self, name: str) -> int:
        """What state the manager holds for one service.

        Args:
            name: The service name.

        Returns:
            The manager's own state number.

        Raises:
            OSError: When the manager or the service cannot be opened.
        """
        status = ServiceStatus()
        with self._service(name, SERVICE_QUERY_STATUS) as service:
            if not self._advapi32.QueryServiceStatus(service, ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
        return status.dwCurrentState

    def start_service(self, name: str) -> None:
        """Ask the manager to start one service.

        Args:
            name: The service name.

        Raises:
            OSError: When the manager refuses.
        """
        with self._service(name, SERVICE_START | SERVICE_QUERY_STATUS) as service:
            if not self._advapi32.StartServiceW(service, 0, None):
                raise ctypes.WinError(ctypes.get_last_error())

    def _service(self, name: str, access: int):
        """Open one service, closing it and the manager afterwards.

        Args:
            name: The service name.
            access: What is being asked of it.

        Returns:
            A context manager over the service handle.
        """

        @contextmanager
        def opened():
            manager = self._advapi32.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
            if not manager:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                service = self._advapi32.OpenServiceW(manager, name, access)
                if not service:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    yield service
                finally:
                    self._advapi32.CloseServiceHandle(service)
            finally:
                self._advapi32.CloseServiceHandle(manager)

        return opened()
