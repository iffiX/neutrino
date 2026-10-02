"""The hub's one Win32 binding: the libraries, their prototypes, the names.

Copied from the agent's and cut to what the hub calls: the service
dispatcher, the job its children run in, and the elevation check. Nothing
binds a library at import time, so this module imports on Linux as readily
as on Windows and the seams above it stay replaceable in tests.
"""

import ctypes

# A DWORD is 32 bits on Windows; c_ulong is 64 on Linux, where the tests
# build these same structures.
DWORD = ctypes.c_uint32

# Services: the one kind the hub is, the states it reports, the controls it
# accepts and answers.
SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_STOPPED = 1
SERVICE_START_PENDING = 2
SERVICE_STOP_PENDING = 3
SERVICE_RUNNING = 4
SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_SHUTDOWN = 0x00000004
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_INTERROGATE = 0x00000004
SERVICE_CONTROL_SHUTDOWN = 0x00000005
NO_ERROR = 0
ERROR_CALL_NOT_IMPLEMENTED = 120

# Job objects: every child of the service dies with the job's last handle.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

_LIBRARIES = None


def last_error() -> OSError:
    """The calling thread's last Win32 error, as the OSError it is.

    Returns:
        The error; off Windows, a plain OSError naming the number.
    """
    code = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
    maker = getattr(ctypes, "WinError", None)
    if maker is None:
        return OSError(code, f"error {code}")
    return maker(code)


def service_main_type():
    """The LPSERVICE_MAIN_FUNCTIONW signature a service's main is wrapped in.

    Returns:
        The ctypes function type: stdcall, taking the argument count and
        the argument vector.

    Raises:
        AttributeError: Off Windows, where ctypes has no stdcall convention.
    """
    return ctypes.WINFUNCTYPE(None, DWORD, ctypes.c_void_p)


def service_handler_type():
    """The LPHANDLER_FUNCTION_EX signature a control handler is wrapped in.

    Returns:
        The ctypes function type: stdcall, taking the control, the event
        type, the event data and the context, answering a DWORD.

    Raises:
        AttributeError: Off Windows, where ctypes has no stdcall convention.
    """
    return ctypes.WINFUNCTYPE(DWORD, DWORD, DWORD, ctypes.c_void_p, ctypes.c_void_p)


def libraries() -> "Win32Libraries":
    """The bound libraries, built on first use.

    Returns:
        The one :class:`Win32Libraries` this process shares.

    Raises:
        OSError: When a library cannot be loaded, which is every call off
            Windows.
    """
    global _LIBRARIES
    if _LIBRARIES is None:
        _LIBRARIES = Win32Libraries()
    return _LIBRARIES


class ServiceStatus(ctypes.Structure):
    """What a service reports to the service control manager."""

    _fields_ = [
        ("dwServiceType", DWORD),
        ("dwCurrentState", DWORD),
        ("dwControlsAccepted", DWORD),
        ("dwWin32ExitCode", DWORD),
        ("dwServiceSpecificExitCode", DWORD),
        ("dwCheckPoint", DWORD),
        ("dwWaitHint", DWORD),
    ]


class ServiceTableEntry(ctypes.Structure):
    """One row of the table StartServiceCtrlDispatcherW is handed."""

    _fields_ = [("lpServiceName", ctypes.c_wchar_p), ("lpServiceProc", ctypes.c_void_p)]


class JobObjectBasicLimitInformation(ctypes.Structure):
    """JOBOBJECT_BASIC_LIMIT_INFORMATION."""

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class IoCounters(ctypes.Structure):
    """IO_COUNTERS."""

    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JobObjectExtendedLimitInformation(ctypes.Structure):
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION, which carries the kill-on-close flag."""

    _fields_ = [
        ("BasicLimitInformation", JobObjectBasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class Win32Libraries:
    """Every DLL the hub calls, with its prototypes set once.

    Handles are pointers: without these prototypes a 64-bit handle comes
    back truncated to an int.
    """

    def __init__(self):
        """
        Raises:
            OSError: When a library cannot be loaded.
        """
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._describe_kernel32()
        self._describe_advapi32()
        self._describe_shell32()

    def _describe_kernel32(self) -> None:
        """Prototype the job calls."""
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self.kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self.kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            DWORD,
        ]
        self.kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

    def _describe_advapi32(self) -> None:
        """Prototype the service calls."""
        self.advapi32.StartServiceCtrlDispatcherW.argtypes = [ctypes.c_void_p]
        self.advapi32.RegisterServiceCtrlHandlerExW.restype = ctypes.c_void_p
        self.advapi32.RegisterServiceCtrlHandlerExW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.advapi32.SetServiceStatus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ServiceStatus),
        ]

    def _describe_shell32(self) -> None:
        """Prototype the shell32 calls."""
        self.shell32.IsUserAnAdmin.restype = ctypes.c_int
        self.shell32.IsUserAnAdmin.argtypes = []
