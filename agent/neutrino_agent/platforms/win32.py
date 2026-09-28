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


# A DWORD is 32 bits on Windows; c_ulong is 64 on Linux, where the tests
# build these same structures.
class FileTime(ctypes.Structure):
    """A count of 100-nanosecond intervals, in two halves."""

    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    @property
    def value(self) -> int:
        """The count, whole."""
        return (self.dwHighDateTime << 32) | self.dwLowDateTime


class MemoryStatusEx(ctypes.Structure):
    """What GlobalMemoryStatusEx fills in."""

    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


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
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._describe_kernel32()
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

    def _describe_shell32(self) -> None:
        """Prototype the shell32 calls."""
        self.shell32.IsUserAnAdmin.restype = ctypes.c_int
        self.shell32.IsUserAnAdmin.argtypes = []
