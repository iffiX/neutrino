"""The Windows status-area icon, driven with no shell under it.

The Win32 seam is faked, so the message pump runs here on Linux. What is
pinned is the icon's own lifetime: put up on start, taken down on stop, and
every mouse event answered.
"""

import pytest

from neutrino_client.constants import CLIENT_TRAY_OPEN_LABEL, CLIENT_TRAY_QUIT_LABEL

from neutrino_client.gui.tray_windows import (
    TRAY_CALLBACK_MESSAGE,
    TRAY_COMMAND_OPEN,
    TRAY_COMMAND_QUIT,
    WindowsTrayIcon,
)
from neutrino_client.platforms.win32 import (
    WM_COMMAND,
    WM_LBUTTONDBLCLK,
    WM_LBUTTONUP,
    WM_RBUTTONUP,
)


class FakeWin32TrayApi:
    """The Win32 seam, recorded rather than called.

    Attributes:
        added: Every icon put up.
        removed: Every window an icon was taken down for.
        menus: Every menu dropped.
        chosen: What the next ``popup_menu`` returns.
    """

    def __init__(self, chosen: int = 0):
        self.on_event = None
        self.added = []
        self.removed = []
        self.menus = []
        self.closed = []
        self.chosen = chosen
        self.is_pumping = False

    def create_window(self, *, title: str, on_event) -> int:
        self.title = title
        self.on_event = on_event
        return 4242

    def add_icon(self, *, window: int, icon_path: str, tip: str) -> None:
        self.added.append({"window": window, "icon_path": icon_path, "tip": tip})

    def remove_icon(self, *, window: int) -> None:
        self.removed.append(window)

    def popup_menu(self, *, window: int, items: tuple) -> int:
        self.menus.append({"window": window, "items": tuple(items)})
        return self.chosen

    def pump_messages(self, *, window: int) -> None:
        self.is_pumping = True

    def close_window(self, *, window: int) -> None:
        self.closed.append(window)


@pytest.fixture
def clicks():
    """What the tray's two entries reach."""
    return {"open": 0, "quit": 0}


def windows_tray(clicks, *, win32):
    """A Windows tray over a fake Win32 seam."""

    def on_open() -> None:
        clicks["open"] += 1

    def on_quit() -> None:
        clicks["quit"] += 1

    return WindowsTrayIcon(
        title="Neutrino client",
        icon_path="C:\\icons\\x.ico",
        on_open=on_open,
        on_quit=on_quit,
        win32=win32,
    )


def test_the_icon_goes_up_on_start_and_comes_down_on_stop(clicks):
    win32 = FakeWin32TrayApi()
    icon = windows_tray(clicks, win32=win32)

    icon.start()
    icon.stop()

    assert win32.added == [
        {"window": 4242, "icon_path": "C:\\icons\\x.ico", "tip": "Neutrino client"}
    ]
    assert win32.is_pumping is True
    assert win32.removed == [4242]
    assert win32.closed == [4242]


def test_stopping_an_icon_that_never_went_up_does_nothing(clicks):
    win32 = FakeWin32TrayApi()

    windows_tray(clicks, win32=win32).stop()

    assert win32.removed == []


@pytest.mark.parametrize("message", [WM_LBUTTONUP, WM_LBUTTONDBLCLK])
def test_a_click_on_the_icon_opens_the_window(clicks, message):
    win32 = FakeWin32TrayApi()
    icon = windows_tray(clicks, win32=win32)
    icon.start()

    win32.on_event(TRAY_CALLBACK_MESSAGE, 0, message)

    assert clicks == {"open": 1, "quit": 0}
    assert win32.menus == []


def test_a_right_click_drops_the_menu_and_runs_what_was_chosen(clicks):
    win32 = FakeWin32TrayApi(chosen=TRAY_COMMAND_QUIT)
    icon = windows_tray(clicks, win32=win32)
    icon.start()

    win32.on_event(TRAY_CALLBACK_MESSAGE, 0, WM_RBUTTONUP)

    assert win32.menus == [
        {
            "window": 4242,
            "items": (
                (TRAY_COMMAND_OPEN, CLIENT_TRAY_OPEN_LABEL),
                (TRAY_COMMAND_QUIT, CLIENT_TRAY_QUIT_LABEL),
            ),
        }
    ]
    assert clicks == {"open": 0, "quit": 1}


def test_a_dismissed_menu_runs_nothing(clicks):
    win32 = FakeWin32TrayApi(chosen=0)
    icon = windows_tray(clicks, win32=win32)
    icon.start()

    win32.on_event(TRAY_CALLBACK_MESSAGE, 0, WM_RBUTTONUP)

    assert clicks == {"open": 0, "quit": 0}


def test_a_menu_command_the_window_receives_runs_the_same_entries(clicks):
    win32 = FakeWin32TrayApi()
    icon = windows_tray(clicks, win32=win32)
    icon.start()

    win32.on_event(WM_COMMAND, TRAY_COMMAND_OPEN, 0)
    win32.on_event(WM_COMMAND, TRAY_COMMAND_QUIT, 0)

    assert clicks == {"open": 1, "quit": 1}


def test_a_message_the_icon_does_not_know_is_ignored(clicks):
    win32 = FakeWin32TrayApi()
    icon = windows_tray(clicks, win32=win32)
    icon.start()

    win32.on_event(0x0001, 0, 0)

    assert clicks == {"open": 0, "quit": 0}
