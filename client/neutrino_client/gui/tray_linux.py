"""The Linux status-area icon, with Open and Quit.

Closing the window hides it; the client goes on running and the tray icon is
how the person gets it back. The desktop's own indicator carries the menu,
falling back to GTK's status icon where the indicator typelib is absent.
"""

from neutrino_client.constants import CLIENT_DESKTOP_NAME

# The indicator bindings, and the GTK status icon the fallback uses.
INDICATOR_NAMESPACE = "AyatanaAppIndicator3"
INDICATOR_VERSION = "0.1"


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
        self,
        *,
        title: str,
        open_label: str,
        quit_label: str,
        icon_path: str,
        on_open,
        on_quit,
        gtk,
        indicator=None,
    ):
        """
        Args:
            title: What the icon calls itself.
            open_label: What the menu's first item says.
            quit_label: What the menu's second item says.
            icon_path: The icon file, empty to use the installed theme icon.
            on_open: Called when the person asks for the window.
            on_quit: Called when the person asks the client to stop.
            gtk: The ``Gtk`` bindings the window already loaded.
            indicator: The ``AyatanaAppIndicator3`` bindings; None loads them
                and falls back to a status icon when they are absent.
        """
        self._title = title
        self._open_label = open_label
        self._quit_label = quit_label
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
            (self._open_label, self._on_open_selected),
            (self._quit_label, self._on_quit_selected),
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
