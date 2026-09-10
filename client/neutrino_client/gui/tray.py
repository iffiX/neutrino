"""The status-area icon, one per platform, with Open and Quit.

Closing the window hides it; the client goes on running and the tray icon is
how the person gets it back. Linux uses the desktop's own indicator, falling
back to GTK's status icon where the indicator typelib is absent. Windows has
no such binding, so the shell notification API is driven through ctypes
behind :class:`_Win32TrayApi`, on a thread of its own with its own message
pump.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import threading

from neutrino_client.constants import CLIENT_DESKTOP_NAME

TRAY_OPEN_LABEL = "Open"
TRAY_QUIT_LABEL = "Quit"

# The indicator bindings, and the GTK status icon the fallback uses.
INDICATOR_NAMESPACE = "AyatanaAppIndicator3"
INDICATOR_VERSION = "0.1"

# What the tray's own window is registered as, and the message the shell
# posts to it for every mouse event on the icon.
WINDOW_CLASS_NAME = "NeutrinoClientTray"
TRAY_CALLBACK_MESSAGE = 0x8000 + 1
TRAY_COMMAND_OPEN = 1
TRAY_COMMAND_QUIT = 2
TRAY_ICON_ID = 1
TIP_LENGTH_LIMIT = 127
# How long starting the icon waits for its own thread to have one up.
TRAY_READY_TIMEOUT_S = 5

# The window messages the icon answers: a left click or double click opens,
# a right click drops the menu.
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
OPEN_MESSAGES = (WM_LBUTTONUP, WM_LBUTTONDBLCLK)

# The Win32 values the seam passes, spelled out rather than written inline.
# A window parented here has no screen presence at all.
# A window with no size and no style is never drawn, but unlike a
# message-only child it can take the foreground, which is what a popup menu
# needs of its owner.
WS_POPUP = 0x80000000
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
MF_STRING = 0
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
IDI_APPLICATION = 32512


def load_indicator():
    """The desktop indicator bindings, or None when the typelib is absent.

    Returns:
        The ``AyatanaAppIndicator3`` module, or None.
    """
    try:
        import gi

        gi.require_version(INDICATOR_NAMESPACE, INDICATOR_VERSION)
        from gi.repository import AyatanaAppIndicator3

        return AyatanaAppIndicator3
    except (ImportError, ValueError):
        return None


class LinuxTrayIcon:
    """The desktop's status area, carrying an Open and a Quit."""

    def __init__(
        self, *, title: str, icon_path: str, on_open, on_quit, gtk, indicator=None
    ):
        """
        Args:
            title: What the icon calls itself.
            icon_path: The icon file, empty to use the installed theme icon.
            on_open: Called when the person asks for the window.
            on_quit: Called when the person asks the client to stop.
            gtk: The ``Gtk`` bindings the window already loaded.
            indicator: The ``AyatanaAppIndicator3`` bindings; None loads them
                and falls back to a status icon when they are absent.
        """
        self._title = title
        self._icon_path = icon_path
        self._on_open = on_open
        self._on_quit = on_quit
        self._gtk = gtk
        self._indicator_module = load_indicator() if indicator is None else indicator
        self._menu = self._build_menu()
        self._indicator = None
        self._status_icon = None
        if self._menu is not None:
            self._attach()

    @property
    def is_shown(self) -> bool:
        """Whether an icon actually reached the status area."""
        return self._indicator is not None or self._status_icon is not None

    def _attach(self) -> None:
        """Hand the menu to the indicator, or to a status icon instead."""
        if self._indicator_module is not None:
            module = self._indicator_module
            self._indicator = module.Indicator.new(
                CLIENT_DESKTOP_NAME,
                self._icon_path or CLIENT_DESKTOP_NAME,
                module.IndicatorCategory.APPLICATION_STATUS,
            )
            self._indicator.set_status(module.IndicatorStatus.ACTIVE)
            self._indicator.set_title(self._title)
            self._indicator.set_menu(self._menu)
            return
        status_icon = getattr(self._gtk, "StatusIcon", None)
        if status_icon is None:
            return
        icon = status_icon()
        if self._icon_path:
            icon.set_from_file(self._icon_path)
        else:
            icon.set_from_icon_name(CLIENT_DESKTOP_NAME)
        icon.set_tooltip_text(self._title)
        icon.connect("activate", self._on_activated)
        icon.connect("popup-menu", self._on_popup)
        self._status_icon = icon

    def _build_menu(self):
        """The two-item menu both paths share, or None without a toolkit."""
        menu_class = getattr(self._gtk, "Menu", None)
        item_class = getattr(self._gtk, "MenuItem", None)
        if menu_class is None or item_class is None:
            return None
        menu = menu_class()
        for label, handler in (
            (TRAY_OPEN_LABEL, self._on_open_selected),
            (TRAY_QUIT_LABEL, self._on_quit_selected),
        ):
            item = item_class(label=label)
            item.connect("activate", handler)
            menu.append(item)
        menu.show_all()
        return menu

    def _on_activated(self, _icon) -> None:
        self._on_open()

    def _on_popup(self, _icon, button, activate_time) -> None:
        self._menu.popup(None, None, None, None, button, activate_time)

    def _on_open_selected(self, _item) -> None:
        self._on_open()

    def _on_quit_selected(self, _item) -> None:
        self._on_quit()


class WindowsTrayIcon:
    """The shell notification area, on a thread with its own message pump."""

    def __init__(self, *, title: str, icon_path: str, on_open, on_quit, win32=None):
        """
        Args:
            title: The icon's tooltip.
            icon_path: The ``.ico`` file, empty to use the stock icon.
            on_open: Called when the person asks for the window.
            on_quit: Called when the person asks the client to stop.
            win32: The Win32 seam; None builds the ctypes one.
        """
        self._title = title
        self._icon_path = icon_path
        self._on_open = on_open
        self._on_quit = on_quit
        self._win32 = win32 if win32 is not None else _Win32TrayApi()
        self._window = 0
        self._thread: "threading.Thread | None" = None
        self._is_ready = threading.Event()

    def start(self) -> None:
        """Put the icon up and start pumping its messages."""
        self._thread = threading.Thread(
            target=self._serve, name="client_tray", daemon=True
        )
        self._thread.start()
        self._is_ready.wait(timeout=TRAY_READY_TIMEOUT_S)

    def stop(self) -> None:
        """Take the icon down and end its message pump."""
        window = self._window
        if not window:
            return
        self._window = 0
        self._win32.remove_icon(window=window)
        self._win32.close_window(window=window)

    def _serve(self) -> None:
        """Own the icon's window for as long as its pump runs."""
        self._window = self._win32.create_window(
            title=self._title, on_event=self._on_event
        )
        self._win32.add_icon(
            window=self._window, icon_path=self._icon_path, tip=self._title
        )
        self._is_ready.set()
        self._win32.pump_messages(window=self._window)

    def _on_event(self, message: int, wparam: int, lparam: int) -> None:
        """One window message the icon's own window received.

        Args:
            message: The message id.
            wparam: The chosen command, for a menu command.
            lparam: The mouse event, for a callback message.
        """
        if message == TRAY_CALLBACK_MESSAGE:
            self._on_mouse(lparam)
        elif message == WM_COMMAND:
            self._on_command(wparam)

    def _on_mouse(self, event: int) -> None:
        if event in OPEN_MESSAGES:
            self._on_open()
            return
        if event != WM_RBUTTONUP:
            return
        chosen = self._win32.popup_menu(
            window=self._window,
            items=(
                (TRAY_COMMAND_OPEN, TRAY_OPEN_LABEL),
                (TRAY_COMMAND_QUIT, TRAY_QUIT_LABEL),
            ),
        )
        self._on_command(chosen)

    def _on_command(self, command: int) -> None:
        if command == TRAY_COMMAND_OPEN:
            self._on_open()
        elif command == TRAY_COMMAND_QUIT:
            self._on_quit()


class _Win32TrayApi:
    """The Win32 calls the tray needs, and nothing else."""

    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Handles are pointers: without these prototypes a 64-bit handle
        # comes back truncated to an int.
        self._user32.CreateWindowExW.restype = ctypes.c_void_p
        self._user32.CreatePopupMenu.restype = ctypes.c_void_p
        self._user32.LoadImageW.restype = ctypes.c_void_p
        self._user32.LoadIconW.restype = ctypes.c_void_p
        self._kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self._procedure_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        # WPARAM and LPARAM are pointer-sized; left to ctypes' default they
        # are passed as C ints and a 64-bit value overflows on the way.
        self._user32.DefWindowProcW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self._user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self._user32.PostMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        # Held so the trampoline the window keeps is not collected under it.
        self._procedure = None
        self._notify_data = None

    def create_window(self, *, title: str, on_event) -> int:
        """Register a class and make the unseen window behind the icon.

        Args:
            title: The window's title, which nobody sees.
            on_event: Called with ``(message, wparam, lparam)`` per message.

        Returns:
            The window handle.

        Raises:
            OSError: When the window cannot be made.
        """

        def procedure(window, message, wparam, lparam):
            on_event(message, wparam, lparam)
            if message == WM_DESTROY:
                self._user32.PostQuitMessage(0)
                return 0
            return self._user32.DefWindowProcW(window, message, wparam, lparam)

        self._procedure = self._procedure_type(procedure)
        window_class = _WindowClass()
        window_class.style = 0
        window_class.lpfnWndProc = ctypes.cast(self._procedure, ctypes.c_void_p)
        window_class.hInstance = self._kernel32.GetModuleHandleW(None)
        window_class.lpszClassName = WINDOW_CLASS_NAME
        self._user32.RegisterClassW(ctypes.byref(window_class))
        window = self._user32.CreateWindowExW(
            0,
            WINDOW_CLASS_NAME,
            title,
            WS_POPUP,
            0,
            0,
            0,
            0,
            # Top level, never shown: the menu the icon drops needs an owner
            # the shell will put in the foreground, and a message-only child
            # can never be one.
            None,
            None,
            ctypes.c_void_p(window_class.hInstance),
            None,
        )
        if not window:
            raise ctypes.WinError(ctypes.get_last_error())
        return window

    def add_icon(self, *, window: int, icon_path: str, tip: str) -> None:
        """Put the icon in the notification area.

        Args:
            window: The window the shell posts the icon's events to.
            icon_path: The ``.ico`` file, empty for the stock icon.
            tip: The tooltip.
        """
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(_NotifyIconData)
        data.hWnd = window
        data.uID = TRAY_ICON_ID
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = TRAY_CALLBACK_MESSAGE
        data.hIcon = self._icon_handle(icon_path)
        data.szTip = tip[:TIP_LENGTH_LIMIT]
        self._notify_data = data
        self._shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))

    def remove_icon(self, *, window: int) -> None:
        """Take the icon out of the notification area.

        Args:
            window: The window it was added for.
        """
        data = self._notify_data
        if data is None:
            return
        self._notify_data = None
        self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))

    def popup_menu(self, *, window: int, items: tuple) -> int:
        """Drop the menu at the pointer and return what was chosen.

        Args:
            window: The window that owns the menu.
            items: ``(command_id, label)`` per entry.

        Returns:
            The chosen command, 0 when the menu was dismissed.
        """
        menu = self._user32.CreatePopupMenu()
        for command, label in items:
            self._user32.AppendMenuW(ctypes.c_void_p(menu), MF_STRING, command, label)
        point = _Point()
        self._user32.GetCursorPos(ctypes.byref(point))
        # The shell wants the owner in the foreground, or the menu never
        # closes again.
        self._user32.SetForegroundWindow(ctypes.c_void_p(window))
        chosen = self._user32.TrackPopupMenu(
            ctypes.c_void_p(menu),
            TPM_RIGHTBUTTON | TPM_RETURNCMD,
            point.x,
            point.y,
            0,
            ctypes.c_void_p(window),
            None,
        )
        self._user32.DestroyMenu(ctypes.c_void_p(menu))
        return int(chosen)

    def pump_messages(self, *, window: int) -> None:
        """Run the window's message loop until it is destroyed.

        Args:
            window: The window to pump for.
        """
        message = _Message()
        while self._user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))

    def close_window(self, *, window: int) -> None:
        """End the window, and with it the pump.

        Args:
            window: The window to close.
        """
        # Posted rather than sent, so the pump's own thread destroys it.
        self._user32.PostMessageW(ctypes.c_void_p(window), WM_CLOSE, 0, 0)

    def _icon_handle(self, icon_path: str) -> int:
        """The icon file's handle, or the stock application icon."""
        if icon_path:
            handle = self._user32.LoadImageW(
                None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
            if handle:
                return handle
        return self._user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))


class _WindowClass(ctypes.Structure):
    """The window class the tray's own window is registered under."""

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


class _Point(ctypes.Structure):
    """Where the pointer was when the menu was asked for."""

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Message(ctypes.Structure):
    """One message off the queue."""

    _fields_ = [
        ("hWnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", _Point),
    ]


class _NotifyIconData(ctypes.Structure):
    """What the shell is told about the icon."""

    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_ulong),
        ("dwStateMask", ctypes.c_ulong),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_ulong),
    ]
