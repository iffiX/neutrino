"""The Linux status-area icon: the same two entries, whichever way it is drawn.

The GTK toolkit is faked, so the indicator path and the status-icon fallback
both run here with no desktop. What is pinned is the menu both paths carry
and which call each entry reaches.
"""

import pytest

import neutrino_client.gui.tray_linux as tray_module
from neutrino_client.constants import (
    CLIENT_DESKTOP_NAME,
    CLIENT_TRAY_OPEN_LABEL,
    CLIENT_TRAY_QUIT_LABEL,
)
from neutrino_client.gui.tray_linux import (
    LinuxTrayIcon,
)


class FakeSignalled:
    """Anything that carries GTK signal handlers.

    Attributes:
        handlers: Signal name to the handler connected for it.
    """

    def __init__(self):
        self.handlers = {}

    def connect(self, signal, handler, *rest) -> None:
        self.handlers[signal] = handler

    def fire(self, signal, *arguments):
        """Call one connected handler the way GTK would."""
        return self.handlers[signal](self, *arguments)


class FakeMenuItem(FakeSignalled):
    """One entry of the tray menu."""

    def __init__(self, label=""):
        super().__init__()
        self.label = label


class FakeMenu:
    """The menu both Linux paths build.

    Attributes:
        items: The entries appended, in order.
        popups: Every ``popup`` call's arguments.
    """

    def __init__(self):
        self.items = []
        self.popups = []
        self.is_shown = False

    def append(self, item) -> None:
        self.items.append(item)

    def show_all(self) -> None:
        self.is_shown = True

    def popup(self, *arguments) -> None:
        self.popups.append(arguments)


class FakeStatusIcon(FakeSignalled):
    """GTK's own status icon, the fallback path."""

    def __init__(self):
        super().__init__()
        self.file_path = ""
        self.icon_name = ""
        self.tooltip = ""

    def set_from_file(self, path: str) -> None:
        self.file_path = path

    def set_from_icon_name(self, name: str) -> None:
        self.icon_name = name

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text


class FakeGtk:
    """The GTK bindings a window and a tray reach for.

    Attributes:
        windows: Every window built through it.
        menus: Every menu built through it.
        quits: How many times the main loop was asked to end.
    """

    MenuItem = FakeMenuItem
    StatusIcon = FakeStatusIcon

    def __init__(self):
        self.windows = []
        self.menus = []
        self.quits = 0
        self.mains = 0

    def Menu(self):
        made = FakeMenu()
        self.menus.append(made)
        return made

    def Window(self, **kwargs):
        window = FakeGtkWindow(**kwargs)
        self.windows.append(window)
        return window

    def main_quit(self, *arguments) -> None:
        self.quits += 1

    def main(self) -> None:
        self.mains += 1


class FakeGtkWindow(FakeSignalled):
    """The window the Linux shell opens.

    Attributes:
        shows: How many times it was shown.
        hides: How many times it was hidden.
    """

    def __init__(self, **kwargs):
        super().__init__()
        self.title = kwargs.get("title", "")
        self.size = ()
        self.icon_path = ""
        self.child = None
        self.shows = 0
        self.hides = 0
        self.presents = 0

    def set_default_size(self, width, height) -> None:
        self.size = (width, height)

    def set_icon_from_file(self, path) -> None:
        self.icon_path = path

    def add(self, child) -> None:
        self.child = child

    def show_all(self) -> None:
        self.shows += 1

    def present(self) -> None:
        self.presents += 1

    def hide(self) -> None:
        self.hides += 1


class FakeIndicator:
    """One AyatanaAppIndicator3 indicator."""

    def __init__(self, name, icon, category):
        self.name = name
        self.icon = icon
        self.category = category
        self.status = ""
        self.title = ""
        self.menu = None

    def set_status(self, status) -> None:
        self.status = status

    def set_title(self, title: str) -> None:
        self.title = title

    def set_menu(self, menu) -> None:
        self.menu = menu


class FakeIndicatorModule:
    """The AyatanaAppIndicator3 bindings, without the typelib.

    Attributes:
        made: Every indicator built through it.
    """

    def __init__(self):
        module = self

        class Indicator:
            @staticmethod
            def new(name, icon, category):
                made = FakeIndicator(name, icon, category)
                module.made.append(made)
                return made

        class IndicatorCategory:
            APPLICATION_STATUS = "application-status"

        class IndicatorStatus:
            ACTIVE = "active"

        self.made = []
        self.Indicator = Indicator
        self.IndicatorCategory = IndicatorCategory
        self.IndicatorStatus = IndicatorStatus


@pytest.fixture
def clicks():
    """What the tray's two entries reach."""
    return {"open": 0, "quit": 0}


def linux_tray(clicks, *, indicator=None, icon_path="/icons/x.png"):
    """A Linux tray over a fake toolkit."""

    def on_open() -> None:
        clicks["open"] += 1

    def on_quit() -> None:
        clicks["quit"] += 1

    return LinuxTrayIcon(
        title="Neutrino client",
        icon_path=icon_path,
        on_open=on_open,
        on_quit=on_quit,
        gtk=FakeGtk(),
        indicator=indicator,
    )


def test_the_indicator_carries_open_and_quit_and_nothing_else(clicks):
    indicator = FakeIndicatorModule()

    icon = linux_tray(clicks, indicator=indicator)

    (made,) = indicator.made
    assert made.name == CLIENT_DESKTOP_NAME
    assert made.icon == "/icons/x.png"
    assert made.status == "active"
    assert made.title == "Neutrino client"
    assert [item.label for item in made.menu.items] == [
        CLIENT_TRAY_OPEN_LABEL,
        CLIENT_TRAY_QUIT_LABEL,
    ]
    assert made.menu.is_shown is True
    assert icon.is_shown is True


def test_each_indicator_entry_reaches_its_own_callback(clicks):
    indicator = FakeIndicatorModule()
    linux_tray(clicks, indicator=indicator)

    opener, quitter = indicator.made[0].menu.items
    opener.fire("activate")
    quitter.fire("activate")

    assert clicks == {"open": 1, "quit": 1}


def test_without_the_typelib_the_status_icon_carries_the_same_menu(clicks, monkeypatch):
    monkeypatch.setattr(tray_module, "load_indicator", lambda: None)

    icon = linux_tray(clicks)

    status_icon = icon._status_icon
    assert isinstance(status_icon, FakeStatusIcon)
    assert status_icon.file_path == "/icons/x.png"
    assert status_icon.tooltip == "Neutrino client"
    assert [item.label for item in icon._menu.items] == [
        CLIENT_TRAY_OPEN_LABEL,
        CLIENT_TRAY_QUIT_LABEL,
    ]


def test_the_status_icon_opens_on_a_click_and_drops_its_menu_on_a_right_click(
    clicks, monkeypatch
):
    monkeypatch.setattr(tray_module, "load_indicator", lambda: None)
    icon = linux_tray(clicks)

    icon._status_icon.fire("activate")
    icon._status_icon.fire("popup-menu", 3, 12345)

    assert clicks["open"] == 1
    assert icon._menu.popups == [(None, None, None, None, 3, 12345)]


def test_a_status_icon_with_no_file_falls_back_to_the_installed_icon(
    clicks, monkeypatch
):
    monkeypatch.setattr(tray_module, "load_indicator", lambda: None)

    icon = linux_tray(clicks, icon_path="")

    assert icon._status_icon.icon_name == CLIENT_DESKTOP_NAME


def test_a_toolkit_with_no_status_area_shows_nothing_and_does_not_fail(
    clicks, monkeypatch
):
    monkeypatch.setattr(tray_module, "load_indicator", lambda: None)

    class BareGtk:
        Menu = FakeMenu
        MenuItem = FakeMenuItem

    icon = LinuxTrayIcon(
        title="t",
        icon_path="",
        on_open=lambda: None,
        on_quit=lambda: None,
        gtk=BareGtk(),
    )

    assert icon.is_shown is False


def test_the_indicator_bindings_are_absent_here():
    """The typelib is not in the test environment, and that is not a failure."""
    assert tray_module.load_indicator() is None
