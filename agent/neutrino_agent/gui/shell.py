"""One window seam, one shell per platform.

Each shell embeds the platform's own web view — WebKitGTK on Linux,
WebView2 on Windows, WKWebView on macOS — loads the page, and registers the
message handler the page's bridge adapter posts to. The toolkit imports are
guarded at call time, so a machine without one still imports the agent, and
opening the window there refuses with a typed code naming what to install.
"""


class GuiShellUnavailableError(Exception):
    """The platform's web view cannot be loaded."""

    def __init__(self, code: str, params=None):
        """
        Args:
            code: The typed refusal code.
            params: The code's parameters.
        """
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})


def open_shell_window(*, os_name: str, title: str, html: str, bridge, icon_path=""):
    """Open the platform's window and block until it closes.

    Args:
        os_name: The platform's ``os_name``.
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        icon_path: The window icon's file path, empty for none.

    Raises:
        GuiShellUnavailableError: When the platform has no shell, or its
            toolkit is not on the machine.
    """
    shell = _shell_for(os_name)
    if shell is None:
        raise GuiShellUnavailableError("unsupported_platform")
    shell.open_window(title=title, html=html, bridge=bridge, icon_path=icon_path)


def _shell_for(os_name: str):
    """The platform's shell module, or None.

    The shells import this module's error class, so they load at call time.

    Args:
        os_name: The platform's ``os_name``.

    Returns:
        The shell module, or None for a platform without one.
    """
    if os_name == "linux":
        from neutrino_agent.gui import webkitgtk

        return webkitgtk
    if os_name == "windows":
        from neutrino_agent.gui import webview2

        return webview2
    if os_name == "darwin":
        from neutrino_agent.gui import wkwebview

        return wkwebview
    return None
