"""The agent's one Win32 binding: the libraries, their prototypes, the names.

Every Win32 constant the agent uses is spelled here as Win32 spells it, every
structure is declared once, and every DLL handle comes from :func:`libraries`.
Nothing binds a library at import time, so this module imports on Linux as
readily as on Windows and the seams above it stay replaceable in tests.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes

# A DWORD is 32 bits on Windows; c_ulong is 64 on Linux, where the tests
# build these same structures.
DWORD = ctypes.c_uint32

# Files and handles.
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
# As the unsigned value a c_void_p restype hands back.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Named pipes. One instance per client, like one accepted socket per client.
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
PIPE_BUFFER_BYTES = 64 * 1024
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232

# Security descriptors, at the one revision the SDDL converter takes.
SDDL_REVISION_1 = 1

# Services: the one kind this agent is, the states it reports, the controls
# it accepts and answers.
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
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063


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


_LIBRARIES = None


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


class FileTime(ctypes.Structure):
    """A count of 100-nanosecond intervals, in two halves."""

    _fields_ = [("dwLowDateTime", DWORD), ("dwHighDateTime", DWORD)]

    @property
    def value(self) -> int:
        """The count, whole."""
        return (self.dwHighDateTime << 32) | self.dwLowDateTime


class MemoryStatusEx(ctypes.Structure):
    """What GlobalMemoryStatusEx fills in."""

    _fields_ = [
        ("dwLength", DWORD),
        ("dwMemoryLoad", DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SecurityAttributes(ctypes.Structure):
    """The SECURITY_ATTRIBUTES a pipe instance is created with."""

    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    ]


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


class Win32Libraries:
    """Every DLL the agent calls, with its prototypes set once.

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
        """Prototype the kernel32 calls."""
        self.kernel32.GetSystemTimes.argtypes = [
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
        ]
        self.kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]
        self.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self.kernel32.GetTickCount64.argtypes = []
        self.kernel32.CreateNamedPipeW.restype = ctypes.c_void_p
        self.kernel32.CreateNamedPipeW.argtypes = [
            ctypes.c_wchar_p,
            DWORD,
            DWORD,
            DWORD,
            DWORD,
            DWORD,
            DWORD,
            ctypes.c_void_p,
        ]
        self.kernel32.CreateFileW.restype = ctypes.c_void_p
        self.kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            DWORD,
            DWORD,
            ctypes.c_void_p,
            DWORD,
            DWORD,
            ctypes.c_void_p,
        ]
        for name in (
            "FlushFileBuffers",
            "DisconnectNamedPipe",
            "CloseHandle",
            "LocalFree",
        ):
            getattr(self.kernel32, name).argtypes = [ctypes.c_void_p]
        self.kernel32.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.kernel32.ReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel32.WriteFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

    def _describe_advapi32(self) -> None:
        """Prototype the advapi32 calls."""
        self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
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
