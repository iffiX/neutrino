"""The shell seam: one module per platform, refusals typed and named.

A fake toolkit stands in for each platform's web view, so the dispatch, the
embedding calls and the import-guard refusals all run without a display.
"""

import sys
from pathlib import Path

import pytest

import neutrino_agent.gui.webkitgtk as webkitgtk
import neutrino_agent.gui.webview2 as webview2
import neutrino_agent.gui.wkwebview as wkwebview
from neutrino_agent.gui.bridge import GuiBridge
from neutrino_agent.gui.shell import GuiShellUnavailableError, open_shell_window
from neutrino_agent.constants import AGENT_DESKTOP_NAME
from tests.gui.test_bridge import FakeGuiChannel

AGENT_ROOT = Path(__file__).resolve().parents[2]


class FakeWebviewModule:
    """A pywebview stand-in that records the one window it is asked for."""

    def __init__(self):
        self.windows = []
        self.started = []

    def create_window(self, title, *, html, js_api, width, height):
        self.windows.append(
            {
                "title": title,
                "html": html,
                "js_api": js_api,
                "width": width,
                "height": height,
            }
        )

    def start(self, *, gui):
        self.started.append(gui)


@pytest.mark.parametrize(
    "os_name,module_name",
    [("linux", "webkitgtk"), ("windows", "webview2"), ("darwin", "wkwebview")],
)
def test_each_platform_dispatches_to_its_own_shell(monkeypatch, os_name, module_name):
    calls = []
    module = {"webkitgtk": webkitgtk, "webview2": webview2, "wkwebview": wkwebview}[
        module_name
    ]

    def record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(module, "open_window", record)

    open_shell_window(
        os_name=os_name,
        title="Neutrino agent",
        html="<html>",
        bridge="the bridge",
        icon_path="/icons/x.png",
    )

    assert calls == [
        {
            "title": "Neutrino agent",
            "html": "<html>",
            "bridge": "the bridge",
            "icon_path": "/icons/x.png",
        }
    ]


def test_a_platform_without_a_shell_refuses_typed():
    with pytest.raises(GuiShellUnavailableError) as caught:
        open_shell_window(
            os_name="plan9", title="t", html="<html>", bridge=None, icon_path=""
        )

    assert caught.value.code == "unsupported_platform"


def test_the_pywebview_shells_embed_the_bridge_end_to_end(monkeypatch):
    # The fake shell drives the fake channel through the real bridge: what
    # the page would call answers with the channel's reply.
    fake = FakeWebviewModule()
    monkeypatch.setitem(sys.modules, "webview", fake)
    channel = FakeGuiChannel(reply={"caller": {"account": "alice"}})

    webview2.open_window(
        title="Neutrino agent",
        html="<html>page</html>",
        bridge=GuiBridge(channel=channel),
    )

    window = fake.windows[0]
    assert window["html"] == "<html>page</html>"
    assert fake.started == ["edgechromium"]
    reply = window["js_api"].request(
        {"id": 1, "method": "GET", "path": "/api/state", "body": None}
    )
    assert reply["body"]["caller"]["account"] == "alice"
    assert channel.asked == [("GET", "/api/state", None)]


def test_the_mac_shell_starts_the_cocoa_backend(monkeypatch):
    fake = FakeWebviewModule()
    monkeypatch.setitem(sys.modules, "webview", fake)

    wkwebview.open_window(title="t", html="<html>", bridge=GuiBridge(channel=None))

    assert fake.started == ["cocoa"]


def test_a_missing_pywebview_refuses_with_each_shells_own_code(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)

    with pytest.raises(GuiShellUnavailableError) as windows_refusal:
        webview2.open_window(title="t", html="<html>", bridge=None)
    with pytest.raises(GuiShellUnavailableError) as mac_refusal:
        wkwebview.open_window(title="t", html="<html>", bridge=None)

    assert windows_refusal.value.code == "gui_webview2_missing"
    assert windows_refusal.value.params == {
        "runtime": "the Microsoft Edge WebView2 Runtime"
    }
    assert mac_refusal.value.code == "gui_wkwebview_missing"


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


def test_the_linux_window_wears_the_name_its_launcher_is_installed_under(monkeypatch):
    """GTK takes WM_CLASS from argv[0], which for a carried interpreter is the
    entry script; a desktop matching a window to its launcher by that name
    then finds neither the installed icon nor the installed title."""
    named = {}

    class FakeGLib:
        @staticmethod
        def set_prgname(name):
            named["prgname"] = name

        @staticmethod
        def set_application_name(name):
            named["application"] = name

        @staticmethod
        def idle_add(*args, **kwargs):
            return None

    class FakeWindow:
        def __init__(self, **kwargs):
            named["title"] = kwargs.get("title", "")

        def set_default_size(self, *args):
            return None

        def set_icon_from_file(self, *args):
            return None

        def add(self, *args):
            return None

        def connect(self, *args):
            return None

        def show_all(self):
            return None

    class FakeGtk:
        Window = FakeWindow
        main_quit = staticmethod(lambda *a: None)
        main = staticmethod(lambda: None)

    class FakeManager:
        def register_script_message_handler(self, *args):
            return None

        def connect(self, *args):
            return None

    class FakeWebKit2:
        UserContentManager = FakeManager

        @staticmethod
        def WebView(**kwargs):
            class _View:
                def load_html(self, *args):
                    return None

            return _View()

    monkeypatch.setattr(webkitgtk, "_toolkit", lambda: (FakeGLib, FakeGtk, FakeWebKit2))

    webkitgtk.open_window(title="Neutrino agent", html="<html>", bridge=None)

    assert named["prgname"] == AGENT_DESKTOP_NAME
    assert named["application"] == "Neutrino agent"
    assert named["title"] == "Neutrino agent"


def test_the_name_the_window_wears_is_the_one_the_packages_install():
    """One spelling: the launcher, the icon and WM_CLASS agree or the desktop
    matches none of them together."""
    desktop = (
        AGENT_ROOT / "neutrino_agent/data/desktop" / f"{AGENT_DESKTOP_NAME}.desktop"
    )

    assert desktop.is_file()
    assert f"Icon={AGENT_DESKTOP_NAME}" in desktop.read_text(encoding="utf-8")
