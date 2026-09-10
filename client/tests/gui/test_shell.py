"""The shell seam: one module per platform, refusals typed and named.

A fake toolkit stands in for each platform's web view, so the dispatch, the
embedding calls, the hide-on-close and the import-guard refusals all run
without a display. macOS has no shell and is refused typed.
"""

import sys
from pathlib import Path

import pytest

import neutrino_client.gui.tray as tray_module
import neutrino_client.gui.webkitgtk as webkitgtk
import neutrino_client.gui.webview2 as webview2
from neutrino_client.constants import CLIENT_DESKTOP_NAME
from neutrino_client.gui.bridge import GuiBridge
from neutrino_client.gui.shell import GuiShellUnavailableError, open_shell_window
from neutrino_client.gui.tray import TRAY_OPEN_LABEL, TRAY_QUIT_LABEL
from tests.gui.test_bridge import FakeGuiChannel
from tests.gui.test_tray import FakeGtk, FakeWin32TrayApi

CLIENT_ROOT = Path(__file__).resolve().parents[2]


class FakeWebviewWindow:
    """A pywebview window that records what was done to it."""

    def __init__(self, *, title, html, js_api, width, height, hidden):
        self.title = title
        self.html = html
        self.js_api = js_api
        self.width = width
        self.height = height
        self.is_hidden = hidden
        self.is_destroyed = False
        self.events = FakeWindowEvents()

    def hide(self) -> None:
        self.is_hidden = True

    def show(self) -> None:
        self.is_hidden = False

    def destroy(self) -> None:
        self.is_destroyed = True


class FakeWindowEvents:
    """pywebview's own ``+=`` subscription, recorded."""

    def __init__(self):
        self.closing = FakeEvent()


class FakeEvent:
    """One event, with the handlers subscribed to it."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        return [handler() for handler in self.handlers]


class FakeWebviewModule:
    """A pywebview stand-in that records the one window it is asked for."""

    def __init__(self):
        self.windows = []
        self.started = []

    def create_window(self, title, *, html, js_api, width, height, hidden=False):
        window = FakeWebviewWindow(
            title=title,
            html=html,
            js_api=js_api,
            width=width,
            height=height,
            hidden=hidden,
        )
        self.windows.append(window)
        return window

    def start(self, *, gui):
        self.started.append(gui)


@pytest.mark.parametrize(
    "os_name,module_name", [("linux", "webkitgtk"), ("windows", "webview2")]
)
def test_each_platform_dispatches_to_its_own_shell(monkeypatch, os_name, module_name):
    calls = []
    module = {"webkitgtk": webkitgtk, "webview2": webview2}[module_name]

    def record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(module, "open_window", record)

    def quit_it() -> None:
        return None

    def show_ready(show) -> None:
        return None

    open_shell_window(
        os_name=os_name,
        title="Neutrino client",
        html="<html>",
        bridge="the bridge",
        icon_path="/icons/x.png",
        is_hidden=True,
        on_quit=quit_it,
        on_show_ready=show_ready,
    )

    assert calls == [
        {
            "title": "Neutrino client",
            "html": "<html>",
            "bridge": "the bridge",
            "icon_path": "/icons/x.png",
            "is_hidden": True,
            "on_quit": quit_it,
            "on_show_ready": show_ready,
        }
    ]


@pytest.mark.parametrize("os_name", ["darwin", "plan9"])
def test_a_platform_without_a_shell_refuses_typed(os_name):
    with pytest.raises(GuiShellUnavailableError) as caught:
        open_shell_window(
            os_name=os_name, title="t", html="<html>", bridge=None, icon_path=""
        )

    assert caught.value.code == "unsupported_platform"


class FakeTrayIcon:
    """The Windows tray, recorded instead of drawn.

    Attributes:
        made: Every icon built, in order.
    """

    made: list = []

    def __init__(self, *, title, icon_path, on_open, on_quit):
        self.title = title
        self.icon_path = icon_path
        self.on_open = on_open
        self.on_quit = on_quit
        self.starts = 0
        self.stops = 0
        FakeTrayIcon.made.append(self)

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


def windows_toolkit(monkeypatch) -> FakeWebviewModule:
    """Put a fake pywebview and a fake tray under the Windows shell."""
    fake = FakeWebviewModule()
    monkeypatch.setitem(sys.modules, "webview", fake)
    FakeTrayIcon.made = []
    monkeypatch.setattr(webview2, "WindowsTrayIcon", FakeTrayIcon)
    return fake


def test_the_windows_shell_embeds_the_bridge_end_to_end(monkeypatch):
    fake = windows_toolkit(monkeypatch)
    channel = FakeGuiChannel(reply={"hostname": "box"})

    webview2.open_window(
        title="Neutrino client",
        html="<html>page</html>",
        bridge=GuiBridge(channel=channel),
    )

    window = fake.windows[0]
    assert window.html == "<html>page</html>"
    assert fake.started == ["edgechromium"]
    reply = window.js_api.request(
        {"id": 1, "method": "GET", "path": "/api/state", "body": None}
    )
    assert reply["body"]["hostname"] == "box"
    assert channel.asked == [("GET", "/api/state", None)]


def test_the_windows_icon_goes_up_with_the_window_and_down_with_the_loop(
    monkeypatch,
):
    windows_toolkit(monkeypatch)

    webview2.open_window(
        title="Neutrino client",
        html="<html>",
        bridge=None,
        icon_path="C:\\icons\\x.ico",
    )

    (icon,) = FakeTrayIcon.made
    assert (icon.title, icon.icon_path) == ("Neutrino client", "C:\\icons\\x.ico")
    assert (icon.starts, icon.stops) == (1, 1)


def test_closing_the_windows_window_hides_it_and_keeps_the_loop(monkeypatch):
    fake = windows_toolkit(monkeypatch)

    webview2.open_window(title="t", html="<html>", bridge=None)
    window = fake.windows[0]

    assert window.events.closing.fire() == [False]
    assert window.is_hidden is True


def test_the_windows_window_starts_hidden_when_it_is_told_to(monkeypatch):
    fake = windows_toolkit(monkeypatch)

    webview2.open_window(title="t", html="<html>", bridge=None, is_hidden=True)

    assert fake.windows[0].is_hidden is True


def test_the_windows_tray_opens_the_window_again_and_quits_the_client(monkeypatch):
    fake = windows_toolkit(monkeypatch)
    stopped = []

    def on_quit() -> None:
        stopped.append(1)

    webview2.open_window(
        title="t", html="<html>", bridge=None, is_hidden=True, on_quit=on_quit
    )
    window = fake.windows[0]
    (icon,) = FakeTrayIcon.made

    icon.on_open()
    assert window.is_hidden is False
    icon.on_quit()

    assert stopped == [1]
    assert window.is_destroyed is True


def test_a_missing_pywebview_refuses_with_the_shells_own_code(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)

    with pytest.raises(GuiShellUnavailableError) as refusal:
        webview2.open_window(title="t", html="<html>", bridge=None)

    assert refusal.value.code == "gui_webview2_missing"
    assert refusal.value.params == {"runtime": "the Microsoft Edge WebView2 Runtime"}


def test_a_missing_webkitgtk_refuses_naming_the_packages(monkeypatch):
    class FakeGi:
        @staticmethod
        def require_version(namespace, version):
            raise ValueError(f"Namespace {namespace} not available for {version}")

    monkeypatch.setitem(sys.modules, "gi", FakeGi())

    with pytest.raises(GuiShellUnavailableError) as caught:
        webkitgtk.open_window(title="t", html="<html>", bridge=None)

    assert caught.value.code == "gui_webkitgtk_missing"
    assert caught.value.params == {"packages": "gir1.2-webkit2-4.1"}


def test_the_linux_shell_pins_the_41_api(monkeypatch):
    pinned = []

    class FakeGi:
        @staticmethod
        def require_version(namespace, version):
            pinned.append((namespace, version))
            if namespace == "WebKit2":
                raise ValueError("stop here")

    monkeypatch.setitem(sys.modules, "gi", FakeGi())

    with pytest.raises(GuiShellUnavailableError):
        webkitgtk.open_window(title="t", html="<html>", bridge=None)

    assert pinned == [("Gtk", "3.0"), ("WebKit2", "4.1")]


class FakeGLib:
    """The GLib calls the Linux shell makes.

    Attributes:
        names: What the process and application were named.
        idles: Every callback handed to ``idle_add``, already run.
    """

    def __init__(self):
        self.names = {}
        self.idles = []

    def set_prgname(self, name: str) -> None:
        self.names["prgname"] = name

    def set_application_name(self, name: str) -> None:
        self.names["application"] = name

    def idle_add(self, callback, *arguments):
        self.idles.append(callback)
        callback(*arguments)
        return None


class FakeContentManager:
    """WebKit's script message manager."""

    def __init__(self):
        self.handlers = []
        self.signals = []

    def register_script_message_handler(self, name: str) -> None:
        self.handlers.append(name)

    def connect(self, signal, handler) -> None:
        self.signals.append(signal)


class FakeWebView:
    """The view the page loads into."""

    def __init__(self):
        self.loaded = ()

    def load_html(self, html, base) -> None:
        self.loaded = (html, base)


class FakeWebKit2:
    """The WebKit bindings the Linux shell reaches for."""

    UserContentManager = FakeContentManager

    @staticmethod
    def WebView(**kwargs):
        return FakeWebView()


def linux_toolkit(monkeypatch, *, indicator=None):
    """Put a fake GTK stack under the Linux shell.

    Args:
        monkeypatch: The pytest patcher.
        indicator: The indicator bindings; None takes the status icon path.

    Returns:
        ``(GLib, Gtk)``, the two the cases read back.
    """
    glib = FakeGLib()
    gtk = FakeGtk()
    monkeypatch.setattr(webkitgtk, "_toolkit", lambda: (glib, gtk, FakeWebKit2))
    if indicator is None:
        monkeypatch.setattr(tray_module, "load_indicator", lambda: None)
    return glib, gtk


def test_the_linux_window_wears_the_name_its_launcher_is_installed_under(monkeypatch):
    glib, gtk = linux_toolkit(monkeypatch)

    webkitgtk.open_window(
        title="Neutrino client", html="<html>", bridge=None, icon_path="/icons/x.png"
    )

    (window,) = gtk.windows
    assert glib.names["prgname"] == CLIENT_DESKTOP_NAME
    assert glib.names["application"] == "Neutrino client"
    assert window.title == "Neutrino client"
    assert window.icon_path == "/icons/x.png"
    assert gtk.mains == 1


def test_the_linux_window_shows_itself_unless_it_is_started_hidden(monkeypatch):
    _glib, gtk = linux_toolkit(monkeypatch)

    webkitgtk.open_window(title="t", html="<html>", bridge=None)
    shown = gtk.windows[0].shows

    webkitgtk.open_window(title="t", html="<html>", bridge=None, is_hidden=True)

    assert shown == 1
    assert gtk.windows[1].shows == 0


def test_closing_the_linux_window_hides_it_and_keeps_the_loop(monkeypatch):
    _glib, gtk = linux_toolkit(monkeypatch)
    webkitgtk.open_window(title="t", html="<html>", bridge=None)
    window = gtk.windows[0]

    kept = window.fire("delete-event", None)

    assert kept is True
    assert window.hides == 1
    assert gtk.quits == 0


def test_the_linux_tray_opens_the_window_again_and_quits_the_client(monkeypatch):
    _glib, gtk = linux_toolkit(monkeypatch)
    stopped = []

    def on_quit() -> None:
        stopped.append(1)

    webkitgtk.open_window(
        title="t", html="<html>", bridge=None, is_hidden=True, on_quit=on_quit
    )
    window = gtk.windows[0]
    opener, quitter = window_menu(gtk).items

    opener.fire("activate")
    quitter.fire("activate")

    assert [item.label for item in window_menu(gtk).items] == [
        TRAY_OPEN_LABEL,
        TRAY_QUIT_LABEL,
    ]
    assert (window.shows, window.presents) == (1, 1)
    assert stopped == [1]
    assert gtk.quits == 1


def test_the_show_the_shell_hands_back_brings_the_window_up(monkeypatch):
    _glib, gtk = linux_toolkit(monkeypatch)
    handed = []

    def on_show_ready(show) -> None:
        handed.append(show)

    webkitgtk.open_window(
        title="t",
        html="<html>",
        bridge=None,
        is_hidden=True,
        on_show_ready=on_show_ready,
    )
    (show,) = handed

    show()

    assert gtk.windows[0].presents == 1


def window_menu(gtk):
    """The tray menu the fake toolkit built for the last window."""
    return gtk.menus[-1]


def test_the_name_the_window_wears_is_the_one_the_packages_install():
    desktop_dir = CLIENT_ROOT / "neutrino_client/data/desktop"
    launcher = desktop_dir / f"{CLIENT_DESKTOP_NAME}.desktop"
    autostart = desktop_dir / f"{CLIENT_DESKTOP_NAME}_autostart.desktop"

    assert launcher.is_file() and autostart.is_file()
    assert f"Icon={CLIENT_DESKTOP_NAME}" in launcher.read_text(encoding="utf-8")
    assert "Exec=nclient gui\n" in launcher.read_text(encoding="utf-8")
    text = autostart.read_text(encoding="utf-8")
    assert "Exec=nclient gui --hidden" in text
    assert "X-GNOME-Autostart-enabled=true" in text


def test_the_polkit_policy_names_the_helper_and_the_active_seat():
    policy = (
        CLIENT_ROOT / "neutrino_client/data/polkit/com.neutrino.client.mount.policy"
    )
    text = policy.read_text(encoding="utf-8")

    assert '<action id="com.neutrino.client.mount">' in text
    assert "<allow_any>no</allow_any>" in text
    assert "<allow_inactive>no</allow_inactive>" in text
    assert "<allow_active>yes</allow_active>" in text
    assert (
        'key="org.freedesktop.policykit.exec.path">'
        "/usr/libexec/neutrino_client/mount_helper<"
    ) in text
