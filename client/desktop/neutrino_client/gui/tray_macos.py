"""The macOS menu bar icon, with Open and Quit.

Closing the window hides it; the client goes on running and the status
item is how the person gets it back. The item is an ``NSStatusItem``
carrying an ``NSMenu``; a menu entry reaches a selector on an object and
nothing else, so the two entries land on an ``NSObject`` subclass this
module defines against the AppKit the window loaded.
"""

# How many points the icon is drawn at in the menu bar.
STATUS_ICON_EDGE = 18
# The selectors the two entries send to the target.
OPEN_ACTION = "open:"
QUIT_ACTION = "quit:"


class MacosTrayIcon:
    """The menu bar's status area, carrying an Open and a Quit."""

    def __init__(
        self,
        *,
        title: str,
        open_label: str,
        quit_label: str,
        icon_path: str,
        on_open,
        on_quit,
        appkit,
    ):
        """
        Args:
            title: The icon's tooltip, and its text where no icon loads.
            open_label: What the menu's first item says.
            quit_label: What the menu's second item says.
            icon_path: The icon file, empty to show the title instead.
            on_open: Called when the person asks for the window.
            on_quit: Called when the person asks the client to stop.
            appkit: The ``AppKit`` bindings the window already loaded.
        """
        self._title = title
        self._open_label = open_label
        self._quit_label = quit_label
        self._icon_path = icon_path
        self._on_open = on_open
        self._on_quit = on_quit
        self._appkit = appkit
        self._target = self._build_target()
        self._menu = self._build_menu()
        self._status_item = None
        self._attach()

    @property
    def is_shown(self) -> bool:
        """Whether an item actually reached the menu bar."""
        return self._status_item is not None

    def _attach(self) -> None:
        """Put the item in the menu bar with the icon, or the title, on it."""
        appkit = self._appkit
        bar = appkit.NSStatusBar.systemStatusBar()
        item = bar.statusItemWithLength_(appkit.NSVariableStatusItemLength)
        button = item.button()
        image = None
        if self._icon_path:
            image = appkit.NSImage.alloc().initWithContentsOfFile_(self._icon_path)
        if image is not None:
            image.setSize_((STATUS_ICON_EDGE, STATUS_ICON_EDGE))
            button.setImage_(image)
        else:
            button.setTitle_(self._title)
        button.setToolTip_(self._title)
        item.setMenu_(self._menu)
        self._status_item = item

    def _build_menu(self):
        """The two-item menu, each entry aimed at the target."""
        appkit = self._appkit
        menu = appkit.NSMenu.alloc().init()
        for label, action in (
            (self._open_label, OPEN_ACTION),
            (self._quit_label, QUIT_ACTION),
        ):
            item = appkit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, action, ""
            )
            item.setTarget_(self._target)
            menu.addItem_(item)
        return menu

    def _build_target(self):
        """The object the two selectors land on."""
        tray = self

        class NeutrinoTrayTarget(self._appkit.NSObject):
            def open_(self, _sender) -> None:
                tray._on_open()

            def quit_(self, _sender) -> None:
                tray._on_quit()

        return NeutrinoTrayTarget.alloc().init()
