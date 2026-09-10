"""The client's one Win32 binding: the libraries, their prototypes, the names.

Every Win32 constant the client uses is spelled here as Win32 spells it, every
structure is declared once, and every DLL handle comes from :func:`libraries`.
Nothing binds a library at import time, so this module imports on Linux as
readily as on Windows and the seams above it stay replaceable in tests.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes

# Process creation.
CREATE_NO_WINDOW = 0x08000000

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
ERROR_NOT_CONNECTED = 2250

# Tokens.
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1

# Security descriptors, at the one revision the SDDL converter takes.
SDDL_REVISION_1 = 1

# Shell change notifications.
SHCNE_DRIVEADD = 0x00000100
SHCNE_DRIVEREMOVED = 0x00000080
SHCNF_PATHW = 0x0005

# Drive mappings.
RESOURCETYPE_DISK = 0x00000001
CONNECT_UPDATE_PROFILE = 0x00000001
NO_ERROR = 0

# Pseudo consoles. The attribute names the console for the process about
# to start.
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

# Windows, icons and menus for the tray.
WS_POPUP = 0x80000000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_APP = 0x8000
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
MF_STRING = 0x00000000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
IDI_APPLICATION = 32512
NOTIFY_ICON_TIP_LENGTH = 128


def win_error(code: int) -> str:
    """What Windows calls one of its own error numbers.

    Args:
        code: The number a Win32 call returned.

    Returns:
        The message, or the number when there is no message for it.
    """
    maker = getattr(ctypes, "WinError", None)
    if maker is None:
        return f"error {code}"
    try:
        return maker(code).strerror or f"error {code}"
    except (OSError, ValueError):
        return f"error {code}"


def window_procedure_type():
    """The WNDPROC signature a window procedure has to be wrapped in.

    Returns:
        The ctypes function type, stdcall, taking window, message, wparam
        and lparam. WPARAM and LPARAM are pointer-sized, so a 64-bit value
        reaches the procedure whole.

    Raises:
        AttributeError: Off Windows, where ctypes has no stdcall convention.
    """
    return ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    )


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


class TokenUser:
    """The TOKEN_USER a token carries, read once.

    The SID points into the buffer this object holds, so the SID is valid
    for as long as the object is.
    """

    def __init__(self, *, advapi32, token: int):
        """
        Args:
            advapi32: The bound advapi32.
            token: The token handle to query.

        Raises:
            OSError: When the token's user cannot be read.
        """
        needed = ctypes.c_ulong(0)
        advapi32.GetTokenInformation(
            ctypes.c_void_p(token), TOKEN_USER_CLASS, None, 0, ctypes.byref(needed)
        )
        self._buffer = ctypes.create_string_buffer(max(needed.value, 64))
        ok = advapi32.GetTokenInformation(
            ctypes.c_void_p(token),
            TOKEN_USER_CLASS,
            self._buffer,
            len(self._buffer),
            ctypes.byref(needed),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        self.sid = ctypes.cast(
            self._buffer, ctypes.POINTER(ctypes.c_void_p)
        ).contents.value


class Coord(ctypes.Structure):
    """A console size."""

    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class Point(ctypes.Structure):
    """A screen position."""

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class Message(ctypes.Structure):
    """One message taken off a thread's queue."""

    _fields_ = [
        ("hWnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", Point),
    ]


class StartupInfo(ctypes.Structure):
    """What a new process is started with."""

    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_ulong),
        ("dwY", ctypes.c_ulong),
        ("dwXSize", ctypes.c_ulong),
        ("dwYSize", ctypes.c_ulong),
        ("dwXCountChars", ctypes.c_ulong),
        ("dwYCountChars", ctypes.c_ulong),
        ("dwFillAttribute", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class StartupInfoEx(ctypes.Structure):
    """A startup record with an attribute list, for the pseudo console."""

    _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class ProcessInformation(ctypes.Structure):
    """What a started process is known by."""

    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_ulong),
        ("dwThreadId", ctypes.c_ulong),
    ]


class NetResource(ctypes.Structure):
    """The connection mpr is asked to make."""

    _fields_ = [
        ("dwScope", ctypes.c_ulong),
        ("dwType", ctypes.c_ulong),
        ("dwDisplayType", ctypes.c_ulong),
        ("dwUsage", ctypes.c_ulong),
        ("lpLocalName", ctypes.c_wchar_p),
        ("lpRemoteName", ctypes.c_wchar_p),
        ("lpComment", ctypes.c_wchar_p),
        ("lpProvider", ctypes.c_wchar_p),
    ]


class NotifyIconData(ctypes.Structure):
    """What the shell is told about a notification icon."""

    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * NOTIFY_ICON_TIP_LENGTH),
        ("dwState", ctypes.c_ulong),
        ("dwStateMask", ctypes.c_ulong),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_ulong),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


class WindowClass(ctypes.Structure):
    """The class a window is registered under."""

    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


class SecurityAttributes(ctypes.Structure):
    """The SECURITY_ATTRIBUTES a pipe instance is created with."""

    _fields_ = [
        ("nLength", ctypes.c_ulong),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    ]


class Win32Libraries:
    """Every DLL the client calls, with its prototypes set once.

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
        self.mpr = ctypes.WinDLL("mpr", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._describe_kernel32()
        self._describe_advapi32()
        self._describe_mpr()
        self._describe_shell32()
        self._describe_user32()

    def _describe_kernel32(self) -> None:
        """Prototype the kernel32 calls."""
        self.kernel32.CreateNamedPipeW.restype = ctypes.c_void_p
        self.kernel32.CreateFileW.restype = ctypes.c_void_p
        self.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        self.kernel32.GetCurrentThread.restype = ctypes.c_void_p
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
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel32.WriteFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self.kernel32.CreatePipe.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        self.kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self.kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.kernel32.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.kernel32.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        self.kernel32.CreateProcessW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ProcessInformation),
        ]
        # The pseudo console calls are absent before Windows 10 1809; the
        # console runner checks for them before prototyping them.
        if hasattr(self.kernel32, "CreatePseudoConsole"):
            self.kernel32.CreatePseudoConsole.restype = ctypes.c_long
            self.kernel32.CreatePseudoConsole.argtypes = [
                Coord,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self.kernel32.ClosePseudoConsole.argtypes = [ctypes.c_void_p]

    def _describe_advapi32(self) -> None:
        """Prototype the advapi32 calls."""
        self.advapi32.ImpersonateNamedPipeClient.argtypes = [ctypes.c_void_p]
        self.advapi32.OpenProcessToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self.advapi32.OpenThreadToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self.advapi32.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self.advapi32.LookupAccountSidW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

    def _describe_mpr(self) -> None:
        """Prototype the mpr calls."""
        self.mpr.WNetAddConnection2W.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_ulong,
        ]
        self.mpr.WNetAddConnection2W.restype = ctypes.c_ulong
        self.mpr.WNetCancelConnection2W.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_int,
        ]
        self.mpr.WNetCancelConnection2W.restype = ctypes.c_ulong

    def _describe_shell32(self) -> None:
        """Prototype the shell32 calls."""
        self.shell32.SHChangeNotify.argtypes = [
            ctypes.c_long,
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        self.shell32.Shell_NotifyIconW.argtypes = [ctypes.c_ulong, ctypes.c_void_p]

    def _describe_user32(self) -> None:
        """Prototype the user32 calls."""
        self.user32.CreateWindowExW.restype = ctypes.c_void_p
        self.user32.CreatePopupMenu.restype = ctypes.c_void_p
        self.user32.LoadImageW.restype = ctypes.c_void_p
        self.user32.LoadIconW.restype = ctypes.c_void_p
        self.user32.LoadImageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        self.user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        # WPARAM and LPARAM are pointer-sized; left to ctypes' default they
        # are passed as C ints and a 64-bit value overflows on the way.
        for name in ("DefWindowProcW", "PostMessageW", "SendMessageW"):
            getattr(self.user32, name).argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
            ]
            getattr(self.user32, name).restype = ctypes.c_ssize_t
        self.user32.AppendMenuW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_wchar_p,
        ]
        self.user32.TrackPopupMenu.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.user32.DestroyMenu.argtypes = [ctypes.c_void_p]
        self.user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(Point)]
        self.user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        self.user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        self.user32.RegisterClassW.restype = ctypes.c_ushort
        self.user32.GetMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        self.user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        self.user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        self.user32.DispatchMessageW.restype = ctypes.c_ssize_t
