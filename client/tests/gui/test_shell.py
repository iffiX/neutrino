"""The shell seam: one module per platform, refusals typed and named.

A fake toolkit stands in for each platform's web view, so the dispatch, the
embedding calls and the import-guard refusals all run without a display.
macOS has no shell and is refused typed.
"""

import sys
from pathlib import Path

import pytest

import neutrino_client.gui.webkitgtk as webkitgtk
import neutrino_client.gui.webview2 as webview2
from neutrino_client.constants import CLIENT_DESKTOP_NAME
from neutrino_client.gui.bridge import GuiBridge
from neutrino_client.gui.shell import GuiShellUnavailableError, open_shell_window
from tests.gui.test_bridge import FakeGuiChannel

CLIENT_ROOT = Path(__file__).resolve().parents[2]


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
    "os_name,module_name", [("linux", "webkitgtk"), ("windows", "webview2")]
)
def test_each_platform_dispatches_to_its_own_shell(monkeypatch, os_name, module_name):
    calls = []
    module = {"webkitgtk": webkitgtk, "webview2": webview2}[module_name]

    def record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(module, "open_window", record)

    open_shell_window(
        os_name=os_name,
        title="Neutrino client",
        html="<html>",
        bridge="the bridge",
        icon_path="/icons/x.png",
    )

    assert calls == [
        {
            "title": "Neutrino client",
            "html": "<html>",
            "bridge": "the bridge",
            "icon_path": "/icons/x.png",
        }
    ]


@pytest.mark.parametrize("os_name", ["darwin", "plan9"])
def test_a_platform_without_a_shell_refuses_typed(os_name):
    with pytest.raises(GuiShellUnavailableError) as caught:
        open_shell_window(
            os_name=os_name, title="t", html="<html>", bridge=None, icon_path=""
        )

    assert caught.value.code == "unsupported_platform"


def test_the_windows_shell_embeds_the_bridge_end_to_end(monkeypatch):
    fake = FakeWebviewModule()
    monkeypatch.setitem(sys.modules, "webview", fake)
    channel = FakeGuiChannel(reply={"hostname": "box"})

    webview2.open_window(
        title="Neutrino client",
        html="<html>page</html>",
        bridge=GuiBridge(channel=channel),
    )

    window = fake.windows[0]
    assert window["html"] == "<html>page</html>"
    assert fake.started == ["edgechromium"]
    reply = window["js_api"].request(
        {"id": 1, "method": "GET", "path": "/api/state", "body": None}
    )
    assert reply["body"]["hostname"] == "box"
    assert channel.asked == [("GET", "/api/state", None)]


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


def test_the_linux_window_wears_the_name_its_launcher_is_installed_under(monkeypatch):
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

    webkitgtk.open_window(title="Neutrino client", html="<html>", bridge=None)

    assert named["prgname"] == CLIENT_DESKTOP_NAME
    assert named["application"] == "Neutrino client"
    assert named["title"] == "Neutrino client"


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
