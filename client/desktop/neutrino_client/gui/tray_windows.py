"""The Windows status-area icon, with Open and Quit.

Closing the window hides it; the client goes on running and the tray icon is
how the person gets it back. Windows has no toolkit binding for the shell
notification area, so it is driven through :class:`_Win32TrayApi` on a thread
of its own with its own message pump. Every DLL call, structure and constant
comes from :mod:`neutrino_client.platforms.win32`.

The icon's own window is where the shell asks this process to end: an
installer, Task Manager's End task and a sign-out each send one of
``QUIT_MESSAGES``, and every one of them is the tray's Quit.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ctypes
import threading

from neutrino_client.platforms import win32

# What the tray's own window is registered as, and the message the shell
# posts to it for every mouse event on the icon.
WINDOW_CLASS_NAME = "NeutrinoClientTray"
TRAY_CALLBACK_MESSAGE = win32.WM_APP + 1
TRAY_COMMAND_OPEN = 1
TRAY_COMMAND_QUIT = 2
TRAY_ICON_ID = 1
# The tooltip field is a fixed buffer, and one character of it is the
# terminator.
TIP_LENGTH_LIMIT = win32.NOTIFY_ICON_TIP_LENGTH - 1
# How long starting the icon waits for its own thread to have one up.
TRAY_READY_TIMEOUT_S = 5

# A left click or double click opens; a right click drops the menu.
OPEN_MESSAGES = (win32.WM_LBUTTONUP, win32.WM_LBUTTONDBLCLK)
# What the shell sends the owner window when this process is to end.
QUIT_MESSAGES = (win32.WM_CLOSE, win32.WM_QUERYENDSESSION, win32.WM_ENDSESSION)


class WindowsTrayIcon:
    """The shell notification area, on a thread with its own message pump."""

    def __init__(
        self,
        *,
        title: str,
        open_label: str,
        quit_label: str,
        icon_path: str,
        on_open,
        on_quit,
        win32=None,
    ):
        """
        Args:
            title: The icon's tooltip.
            open_label: What the menu's first item says.
            quit_label: What the menu's second item says.
            icon_path: The ``.ico`` file, empty to use the stock icon.
            on_open: Called when the person asks for the window.
            on_quit: Called when the person asks the client to stop.
            win32: The Win32 seam; None builds the ctypes one.
        """
        self._title = title
        self._open_label = open_label
        self._quit_label = quit_label
        self._icon_path = icon_path
        self._on_open = on_open
        self._on_quit = on_quit
        self._win32 = win32 if win32 is not None else _Win32TrayApi()
        self._window = 0
        self._thread: "threading.Thread | None" = None
        self._is_ready = threading.Event()
        self._is_stopping = False

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
        self._is_stopping = True
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
        elif message == win32.WM_COMMAND:
            self._on_command(wparam)
        elif message in QUIT_MESSAGES:
            self._on_shell_close()

    def _on_mouse(self, event: int) -> None:
        if event in OPEN_MESSAGES:
            self._on_open()
            return
        if event != win32.WM_RBUTTONUP:
            return
        chosen = self._win32.popup_menu(
            window=self._window,
            items=(
                (TRAY_COMMAND_OPEN, self._open_label),
                (TRAY_COMMAND_QUIT, self._quit_label),
            ),
        )
        self._on_command(chosen)

    def _on_command(self, command: int) -> None:
        if command == TRAY_COMMAND_OPEN:
            self._on_open()
        elif command == TRAY_COMMAND_QUIT:
            self._on_quit()

    def _on_shell_close(self) -> None:
        """The shell asking this process to end, which is Quit.

        The close this icon posts to end its own pump arrives here too, and
        is not one.
        """
        if self._is_stopping:
            return
        self._is_stopping = True
        self._on_quit()


class _Win32TrayApi:
    """The Win32 calls the tray needs, and nothing else."""

    def __init__(self):
        """
        Raises:
            OSError: When the libraries cannot be loaded, which is every
                call off Windows.
        """
        libraries = win32.libraries()
        self._user32 = libraries.user32
        self._shell32 = libraries.shell32
        self._kernel32 = libraries.kernel32
        self._procedure_type = win32.window_procedure_type()
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
            if message == win32.WM_DESTROY:
                self._user32.PostQuitMessage(0)
                return 0
            return self._user32.DefWindowProcW(window, message, wparam, lparam)

        self._procedure = self._procedure_type(procedure)
        window_class = win32.WindowClass()
        window_class.style = 0
        window_class.lpfnWndProc = ctypes.cast(self._procedure, ctypes.c_void_p)
        window_class.hInstance = self._kernel32.GetModuleHandleW(None)
        window_class.lpszClassName = WINDOW_CLASS_NAME
        self._user32.RegisterClassW(ctypes.byref(window_class))
        window = self._user32.CreateWindowExW(
            0,
            WINDOW_CLASS_NAME,
            title,
            win32.WS_POPUP,
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
        data = win32.NotifyIconData()
        data.cbSize = ctypes.sizeof(win32.NotifyIconData)
        data.hWnd = window
        data.uID = TRAY_ICON_ID
        data.uFlags = win32.NIF_MESSAGE | win32.NIF_ICON | win32.NIF_TIP
        data.uCallbackMessage = TRAY_CALLBACK_MESSAGE
        data.hIcon = self._icon_handle(icon_path)
        data.szTip = tip[:TIP_LENGTH_LIMIT]
        self._notify_data = data
        self._shell32.Shell_NotifyIconW(win32.NIM_ADD, ctypes.byref(data))

    def remove_icon(self, *, window: int) -> None:
        """Take the icon out of the notification area.

        Args:
            window: The window it was added for.
        """
        data = self._notify_data
        if data is None:
            return
        self._notify_data = None
        self._shell32.Shell_NotifyIconW(win32.NIM_DELETE, ctypes.byref(data))

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
            self._user32.AppendMenuW(
                ctypes.c_void_p(menu), win32.MF_STRING, command, label
            )
        point = win32.Point()
        self._user32.GetCursorPos(ctypes.byref(point))
        # The shell wants the owner in the foreground, or the menu never
        # closes again.
        self._user32.SetForegroundWindow(ctypes.c_void_p(window))
        chosen = self._user32.TrackPopupMenu(
            ctypes.c_void_p(menu),
            win32.TPM_RIGHTBUTTON | win32.TPM_RETURNCMD,
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
        message = win32.Message()
        while self._user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))

    def close_window(self, *, window: int) -> None:
        """End the window, and with it the pump.

        Args:
            window: The window to close.
        """
        # Posted rather than sent, so the pump's own thread destroys it.
        self._user32.PostMessageW(ctypes.c_void_p(window), win32.WM_CLOSE, 0, 0)

    def _icon_handle(self, icon_path: str) -> int:
        """The icon file's handle, or the stock application icon."""
        if icon_path:
            handle = self._user32.LoadImageW(
                None,
                icon_path,
                win32.IMAGE_ICON,
                0,
                0,
                win32.LR_LOADFROMFILE | win32.LR_DEFAULTSIZE,
            )
            if handle:
                return handle
        return self._user32.LoadIconW(None, ctypes.c_void_p(win32.IDI_APPLICATION))
