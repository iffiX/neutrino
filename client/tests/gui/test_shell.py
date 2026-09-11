"""The shell seam: one module per platform, refusals typed and named.

A fake toolkit stands in for each platform's web view, so the dispatch, the
embedding calls, the hide-on-close and the import-guard refusals all run
without a display.
"""

import inspect
import os
import sys
import time
from pathlib import Path

import pytest

import neutrino_client.gui.tray_linux as tray_module
import neutrino_client.gui.webkitgtk as webkitgtk
import neutrino_client.gui.webview2 as webview2
import neutrino_client.gui.wkwebview as wkwebview
from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_DESKTOP_NAME,
    CLIENT_TRAY_OPEN_LABEL_KEY,
    CLIENT_TRAY_QUIT_LABEL_KEY,
)
from neutrino_client.exceptions import GuiShellUnavailableError
from neutrino_client.gui.bridge import GuiBridge
from neutrino_client.gui.shell import open_shell_window
from neutrino_client.words import word
from tests.gui.test_bridge import FakeGuiChannel
from tests.gui.test_tray_linux import FakeGtk
from tests.gui.test_tray_macos import FakeAppKit, FakeNSObject, FakeStatusBar

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
        self.evaluated = []

    def hide(self) -> None:
        self.is_hidden = True

    def show(self) -> None:
        self.is_hidden = False

    def destroy(self) -> None:
        self.is_destroyed = True

    def evaluate_js(self, script: str) -> None:
        self.evaluated.append(script)


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
    "os_name,module_name",
    [("linux", "webkitgtk"), ("windows", "webview2"), ("darwin", "wkwebview")],
)
def test_each_platform_dispatches_to_its_own_shell(monkeypatch, os_name, module_name):
    calls = []
    module = {
        "webkitgtk": webkitgtk,
        "webview2": webview2,
        "wkwebview": wkwebview,
    }[module_name]

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
            "language": CLIENT_DEFAULT_LANGUAGE,
            "icon_path": "/icons/x.png",
            "is_hidden": True,
            "on_quit": quit_it,
            "on_show_ready": show_ready,
            "on_push_ready": None,
        }
    ]


@pytest.mark.parametrize("os_name", ["freebsd", "plan9"])
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

    def __init__(self, *, title, open_label, quit_label, icon_path, on_open, on_quit):
        self.title = title
        self.open_label = open_label
        self.quit_label = quit_label
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
    # Before Quit, closing only hides; the loop must keep running.
    assert window.events.closing.fire() == [False]
    icon.on_quit()

    assert stopped == [1]
    assert window.is_destroyed is True
    # Quit is the one close that goes through, or the loop never ends.
    assert window.events.closing.fire() == [True]


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
    """The view the page loads into, and the scripts run in it."""

    def __init__(self):
        self.loaded = ()
        self.scripts = []

    def load_html(self, html, base) -> None:
        self.loaded = (html, base)

    def run_javascript(self, script, *_rest) -> None:
        self.scripts.append(script)


class FakeWebKit2:
    """The WebKit bindings the Linux shell reaches for."""

    UserContentManager = FakeContentManager
    views: list = []

    @classmethod
    def WebView(cls, **kwargs):
        view = FakeWebView()
        cls.views.append(view)
        return view


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


def test_the_linux_window_turns_the_dmabuf_renderer_off_unless_told_otherwise(
    monkeypatch,
):
    linux_toolkit(monkeypatch)
    monkeypatch.delenv("WEBKIT_DISABLE_DMABUF_RENDERER", raising=False)

    webkitgtk.open_window(title="t", html="<html>", bridge=None)
    assert os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"] == "1"

    monkeypatch.setenv("WEBKIT_DISABLE_DMABUF_RENDERER", "0")
    webkitgtk.open_window(title="t", html="<html>", bridge=None)
    assert os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"] == "0"


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
        word(CLIENT_DEFAULT_LANGUAGE, CLIENT_TRAY_OPEN_LABEL_KEY),
        word(CLIENT_DEFAULT_LANGUAGE, CLIENT_TRAY_QUIT_LABEL_KEY),
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

    assert launcher.is_file() and not autostart.exists()
    assert f"Icon={CLIENT_DESKTOP_NAME}" in launcher.read_text(encoding="utf-8")
    assert "Exec=nclient gui\n" in launcher.read_text(encoding="utf-8")


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


def test_the_windows_window_pushes_state_into_the_page(monkeypatch):
    fake = windows_toolkit(monkeypatch)
    pushers = []

    webview2.open_window(
        title="t",
        html="<html>",
        bridge=None,
        is_hidden=True,
        on_push_ready=pushers.append,
    )

    (push,) = pushers
    push({"is_connected": True})
    assert fake.windows[0].evaluated == ['window.neutrinoState({"is_connected": true})']


def test_the_linux_window_pushes_state_through_the_main_loop(monkeypatch):
    FakeWebKit2.views = []
    glib, _gtk = linux_toolkit(monkeypatch)
    pushers = []

    webkitgtk.open_window(
        title="t",
        html="<html>",
        bridge=None,
        is_hidden=True,
        on_push_ready=pushers.append,
    )

    (push,) = pushers
    push({"is_connected": False})
    # The main loop ran the delivery, and the page got the state.
    assert glib.idles
    assert FakeWebKit2.views[0].scripts[-1] == (
        'window.neutrinoState({"is_connected": false})'
    )


class FakeApplication(FakeNSObject):
    """The one ``NSApplication``: its policy, delegate, icon and loop.

    Attributes:
        runs: How many times the loop was entered.
        stops: How many times it was asked to end.
    """

    shared = None

    @classmethod
    def sharedApplication(cls):
        if cls.shared is None:
            cls.shared = cls.alloc().init()
        return cls.shared

    def init(self):
        self.policy = None
        self.delegate = None
        self.icon = None
        self.activations = 0
        self.runs = 0
        self.stops = 0
        return self

    def setActivationPolicy_(self, policy) -> None:
        self.policy = policy

    def setDelegate_(self, delegate) -> None:
        self.delegate = delegate

    def setApplicationIconImage_(self, image) -> None:
        self.icon = image

    def activateIgnoringOtherApps_(self, _flag) -> None:
        self.activations += 1

    def run(self) -> None:
        self.runs += 1

    def stop_(self, _sender) -> None:
        self.stops += 1


class FakeCocoaWindow(FakeNSObject):
    """The ``NSWindow`` the macOS shell opens.

    Attributes:
        shows: How many times it was brought to the front.
        hides: How many times it was ordered out.
    """

    made: list = []

    def initWithContentRect_styleMask_backing_defer_(self, rect, mask, backing, defer):
        self.rect = rect
        self.mask = mask
        self.title = ""
        self.is_released_when_closed = True
        self.content = None
        self.delegate = None
        self.shows = 0
        self.hides = 0
        self.is_centered = False
        FakeCocoaWindow.made.append(self)
        return self

    def setTitle_(self, title: str) -> None:
        self.title = title

    def setReleasedWhenClosed_(self, flag: bool) -> None:
        self.is_released_when_closed = flag

    def setContentView_(self, view) -> None:
        self.content = view

    def setDelegate_(self, delegate) -> None:
        self.delegate = delegate

    def center(self) -> None:
        self.is_centered = True

    def makeKeyAndOrderFront_(self, _sender) -> None:
        self.shows += 1

    def orderOut_(self, _sender) -> None:
        self.hides += 1


class FakeContentController:
    """WebKit's script message controller, with the handlers added."""

    def __init__(self):
        self.handlers = {}

    def addScriptMessageHandler_name_(self, handler, name: str) -> None:
        self.handlers[name] = handler


class FakeWebViewConfiguration(FakeNSObject):
    def init(self):
        self.controller = FakeContentController()
        return self

    def userContentController(self):
        return self.controller


class FakeWKWebView(FakeNSObject):
    """The view the page loads into, and the scripts run in it."""

    made: list = []

    def initWithFrame_configuration_(self, frame, configuration):
        self.frame = frame
        self.configuration = configuration
        self.mask = 0
        self.loaded = ()
        self.scripts = []
        FakeWKWebView.made.append(self)
        return self

    def setAutoresizingMask_(self, mask: int) -> None:
        self.mask = mask

    def loadHTMLString_baseURL_(self, html, base) -> None:
        self.loaded = (html, base)

    def evaluateJavaScript_completionHandler_(self, script, handler) -> None:
        self.scripts.append(script)


class FakeScriptMessage:
    """What the page posted, as WebKit hands it over."""

    def __init__(self, body: str):
        self._body = body

    def body(self):
        return self._body


class FakeOperationQueue:
    """The main queue: every block run at once, and remembered.

    Attributes:
        blocks: Every block handed over, already run.
    """

    blocks: list = []

    @classmethod
    def mainQueue(cls):
        return cls

    @classmethod
    def addOperationWithBlock_(cls, block) -> None:
        cls.blocks.append(block)
        block()


class FakeCocoaAppKit(FakeAppKit):
    """The AppKit the macOS shell reaches for, over the tray's own."""

    NSApplication = FakeApplication
    NSWindow = FakeCocoaWindow
    NSApplicationActivationPolicyRegular = 0
    NSWindowStyleMaskTitled = 1
    NSWindowStyleMaskClosable = 2
    NSWindowStyleMaskMiniaturizable = 4
    NSWindowStyleMaskResizable = 8
    NSBackingStoreBuffered = 2
    NSViewWidthSizable = 2
    NSViewHeightSizable = 16
    NSTerminateNow = 1


class FakeFoundation:
    NSOperationQueue = FakeOperationQueue

    @staticmethod
    def NSMakeRect(x, y, width, height):
        return (x, y, width, height)


class FakeWebKit:
    WKWebViewConfiguration = FakeWebViewConfiguration
    WKWebView = FakeWKWebView


def macos_toolkit(monkeypatch) -> FakeApplication:
    """Put a fake Cocoa stack under the macOS shell.

    Returns:
        The one application, which the cases read back.
    """
    FakeApplication.shared = None
    FakeCocoaWindow.made = []
    FakeWKWebView.made = []
    FakeOperationQueue.blocks = []
    FakeStatusBar.items = []
    monkeypatch.setattr(
        wkwebview, "_toolkit", lambda: (FakeCocoaAppKit, FakeFoundation, FakeWebKit)
    )
    return FakeApplication.sharedApplication()


def test_a_missing_pyobjc_refuses_naming_the_packages(monkeypatch):
    monkeypatch.setitem(sys.modules, "AppKit", None)

    with pytest.raises(GuiShellUnavailableError) as caught:
        wkwebview.open_window(title="t", html="<html>", bridge=None)

    assert caught.value.code == "gui_wkwebview_missing"
    assert caught.value.params == {
        "packages": "pyobjc-framework-Cocoa pyobjc-framework-WebKit"
    }


def test_the_macos_window_is_a_regular_app_with_the_page_in_a_web_view(monkeypatch):
    app = macos_toolkit(monkeypatch)

    wkwebview.open_window(
        title="Neutrino client",
        html="<html>page</html>",
        bridge=None,
        icon_path="/icons/x.png",
    )

    (window,) = FakeCocoaWindow.made
    (view,) = FakeWKWebView.made
    assert app.policy == FakeCocoaAppKit.NSApplicationActivationPolicyRegular
    assert app.icon.path == "/icons/x.png"
    assert app.runs == 1
    assert window.title == "Neutrino client"
    assert window.rect == (0, 0, 760, 900)
    assert window.mask == 15
    assert window.is_released_when_closed is False
    assert window.content is view
    assert window.is_centered is True
    assert view.loaded == ("<html>page</html>", None)
    assert view.mask == 18


def test_the_macos_shell_registers_the_handler_the_page_posts_to(monkeypatch):
    macos_toolkit(monkeypatch)
    channel = FakeGuiChannel(reply={"hostname": "box"})

    wkwebview.open_window(
        title="t", html="<html>", bridge=GuiBridge(channel=channel), is_hidden=True
    )

    (view,) = FakeWKWebView.made
    handlers = view.configuration.controller.handlers
    assert list(handlers) == ["neutrino"]
    handlers["neutrino"].userContentController_didReceiveScriptMessage_(
        None,
        FakeScriptMessage(
            '{"id": 1, "method": "GET", "path": "/api/state", "body": null}'
        ),
    )
    deadline = time.monotonic() + 5
    while not view.scripts and time.monotonic() < deadline:
        time.sleep(0.01)

    assert channel.asked == [("GET", "/api/state", None)]
    assert view.scripts == [
        'window.neutrinoReply({"id": 1, "status": 200, "body": {"hostname": "box"}})'
    ]
    # The reply reached the page through the main queue, never off it, as a
    # block made from a function pyobjc can read the signature of: a
    # functools.partial is refused with "Cannot create native callable".
    assert len(FakeOperationQueue.blocks) == 1
    block = FakeOperationQueue.blocks[0]
    assert inspect.isfunction(block)
    assert inspect.signature(block).parameters == {}


def test_the_macos_window_shows_itself_unless_it_is_started_hidden(monkeypatch):
    macos_toolkit(monkeypatch)

    wkwebview.open_window(title="t", html="<html>", bridge=None)
    shown = FakeCocoaWindow.made[0].shows

    wkwebview.open_window(title="t", html="<html>", bridge=None, is_hidden=True)

    assert shown == 1
    assert FakeCocoaWindow.made[1].shows == 0


def test_closing_the_macos_window_hides_it_and_keeps_the_loop(monkeypatch):
    app = macos_toolkit(monkeypatch)
    wkwebview.open_window(title="t", html="<html>", bridge=None)
    window = FakeCocoaWindow.made[0]

    kept = window.delegate.windowShouldClose_(window)

    assert kept is False
    assert window.hides == 1
    assert app.stops == 0


def test_the_menu_bar_item_opens_the_window_again_and_quits_the_client(monkeypatch):
    app = macos_toolkit(monkeypatch)
    stopped = []

    def on_quit() -> None:
        stopped.append(1)

    wkwebview.open_window(
        title="t", html="<html>", bridge=None, is_hidden=True, on_quit=on_quit
    )
    window = FakeCocoaWindow.made[0]
    (item,) = FakeStatusBar.items
    opener, quitter = item.menu.items

    opener.fire()
    quitter.fire()

    assert [entry.title for entry in item.menu.items] == [
        word(CLIENT_DEFAULT_LANGUAGE, CLIENT_TRAY_OPEN_LABEL_KEY),
        word(CLIENT_DEFAULT_LANGUAGE, CLIENT_TRAY_QUIT_LABEL_KEY),
    ]
    assert (window.shows, app.activations) == (1, 1)
    assert stopped == [1]
    assert app.stops == 1


def test_the_dock_brings_the_macos_window_back_and_a_quit_from_it_shuts_down(
    monkeypatch,
):
    app = macos_toolkit(monkeypatch)
    stopped = []

    def on_quit() -> None:
        stopped.append(1)

    wkwebview.open_window(
        title="t", html="<html>", bridge=None, is_hidden=True, on_quit=on_quit
    )
    window = FakeCocoaWindow.made[0]

    assert (
        app.delegate.applicationShouldHandleReopen_hasVisibleWindows_(app, False)
        is False
    )
    assert window.shows == 1
    assert app.delegate.applicationShouldTerminate_(app) == 1
    assert stopped == [1]


def test_the_show_the_macos_shell_hands_back_brings_the_window_up(monkeypatch):
    macos_toolkit(monkeypatch)
    handed = []

    wkwebview.open_window(
        title="t",
        html="<html>",
        bridge=None,
        is_hidden=True,
        on_show_ready=handed.append,
    )
    (show,) = handed

    show()

    assert FakeCocoaWindow.made[0].shows == 1
    assert len(FakeOperationQueue.blocks) == 1


def test_the_macos_window_pushes_state_through_the_main_queue(monkeypatch):
    macos_toolkit(monkeypatch)
    pushers = []

    wkwebview.open_window(
        title="t",
        html="<html>",
        bridge=None,
        is_hidden=True,
        on_push_ready=pushers.append,
    )

    (push,) = pushers
    push({"is_connected": False})
    assert FakeOperationQueue.blocks
    assert FakeWKWebView.made[0].scripts[-1] == (
        'window.neutrinoState({"is_connected": false})'
    )
