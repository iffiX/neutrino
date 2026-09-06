"""The shell seam: one module per platform, refusals typed and named.

A fake toolkit stands in for each platform's web view, so the dispatch, the
embedding calls and the import-guard refusals all run without a display.
"""

import sys

import pytest

import neutrino_agent.gui.webkitgtk as webkitgtk
import neutrino_agent.gui.webview2 as webview2
import neutrino_agent.gui.wkwebview as wkwebview
from neutrino_agent.gui.bridge import GuiBridge
from neutrino_agent.gui.shell import GuiShellUnavailableError, open_shell_window
from tests.gui.test_bridge import FakeGuiChannel


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
    assert caught.value.params == {"packages": "gir1.2-webkit2-4.1 python3-gi"}


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
