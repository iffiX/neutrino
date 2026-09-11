"""The macOS menu bar icon: the same two entries, each reaching its call.

AppKit is faked, so the status item, its menu and the target its entries
send to all run here with no desktop. What is pinned is the menu the item
carries, which selector each entry sends, and what the button shows with
and without an icon file.
"""

import pytest

from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_TRAY_OPEN_LABEL_KEY,
    CLIENT_TRAY_QUIT_LABEL_KEY,
)
from neutrino_client.gui.tray_macos import MacosTrayIcon
from neutrino_client.words import word

TRAY_OPEN = word(CLIENT_DEFAULT_LANGUAGE, CLIENT_TRAY_OPEN_LABEL_KEY)
TRAY_QUIT = word(CLIENT_DEFAULT_LANGUAGE, CLIENT_TRAY_QUIT_LABEL_KEY)


class FakeNSObject:
    """pyobjc's root class: made with ``alloc().init()``, never ``()``."""

    @classmethod
    def alloc(cls):
        return cls.__new__(cls)

    def init(self):
        return self


class FakeImage(FakeNSObject):
    """An ``NSImage`` loaded from a file; a path with no file loads nothing."""

    def initWithContentsOfFile_(self, path):
        if path.endswith(".missing"):
            return None
        self.path = path
        self.size = ()
        return self

    def setSize_(self, size) -> None:
        self.size = tuple(size)


class FakeStatusButton:
    """The button on a status item: an image or a title, and a tooltip."""

    def __init__(self):
        self.image = None
        self.title = ""
        self.tooltip = ""

    def setImage_(self, image) -> None:
        self.image = image

    def setTitle_(self, title: str) -> None:
        self.title = title

    def setToolTip_(self, tip: str) -> None:
        self.tooltip = tip


class FakeStatusItem:
    """One ``NSStatusItem``."""

    def __init__(self, length):
        self.length = length
        self._button = FakeStatusButton()
        self.menu = None

    def button(self):
        return self._button

    def setMenu_(self, menu) -> None:
        self.menu = menu


class FakeStatusBar:
    """The one system status bar, remembering every item made on it.

    Attributes:
        items: Every status item, in order.
    """

    items: list = []

    @classmethod
    def systemStatusBar(cls):
        return cls

    @classmethod
    def statusItemWithLength_(cls, length):
        item = FakeStatusItem(length)
        cls.items.append(item)
        return item


class FakeMenuItem(FakeNSObject):
    """One entry: its title, the selector it sends, and the target."""

    def initWithTitle_action_keyEquivalent_(self, title, action, key):
        self.title = title
        self.action = action
        self.key = key
        self.target = None
        return self

    def setTarget_(self, target) -> None:
        self.target = target

    def fire(self):
        """Send the entry's selector to its target the way AppKit would."""
        return getattr(self.target, self.action.replace(":", "_"))(self)


class FakeMenu(FakeNSObject):
    """An ``NSMenu`` with the entries added to it."""

    def init(self):
        self.items = []
        return self

    def addItem_(self, item) -> None:
        self.items.append(item)


class FakeAppKit:
    """The AppKit names the tray reaches for."""

    NSObject = FakeNSObject
    NSImage = FakeImage
    NSStatusBar = FakeStatusBar
    NSMenu = FakeMenu
    NSMenuItem = FakeMenuItem
    NSVariableStatusItemLength = -1


@pytest.fixture
def clicks():
    """What the tray's two entries reach."""
    return {"open": 0, "quit": 0}


def macos_tray(clicks, *, icon_path="/icons/x.png"):
    """A macOS tray over a fake AppKit."""
    FakeStatusBar.items = []

    def on_open() -> None:
        clicks["open"] += 1

    def on_quit() -> None:
        clicks["quit"] += 1

    return MacosTrayIcon(
        title="Neutrino client",
        open_label=TRAY_OPEN,
        quit_label=TRAY_QUIT,
        icon_path=icon_path,
        on_open=on_open,
        on_quit=on_quit,
        appkit=FakeAppKit,
    )


def test_the_status_item_carries_open_and_quit_and_nothing_else(clicks):
    icon = macos_tray(clicks)

    (item,) = FakeStatusBar.items
    assert item.length == FakeAppKit.NSVariableStatusItemLength
    assert [entry.title for entry in item.menu.items] == [TRAY_OPEN, TRAY_QUIT]
    assert [entry.action for entry in item.menu.items] == ["open:", "quit:"]
    assert item.button().tooltip == "Neutrino client"
    assert icon.is_shown is True


def test_each_entry_reaches_its_own_callback(clicks):
    macos_tray(clicks)

    opener, quitter = FakeStatusBar.items[0].menu.items
    opener.fire()
    quitter.fire()

    assert clicks == {"open": 1, "quit": 1}


def test_the_icon_file_is_drawn_at_menu_bar_size(clicks):
    macos_tray(clicks)

    button = FakeStatusBar.items[0].button()
    assert button.image.path == "/icons/x.png"
    assert button.image.size == (18, 18)
    assert button.title == ""


@pytest.mark.parametrize("icon_path", ["", "/icons/x.missing"])
def test_without_an_icon_the_item_shows_the_title(clicks, icon_path):
    macos_tray(clicks, icon_path=icon_path)

    button = FakeStatusBar.items[0].button()
    assert button.image is None
    assert button.title == "Neutrino client"
