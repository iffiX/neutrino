"""One window seam, one shell per platform.

Each shell embeds the platform's own web view, WebKitGTK on Linux and
WebView2 on Windows, loads the page, registers the message handler the
page's bridge adapter posts to, and puts an icon in the status area. The
toolkit imports are guarded at call time, so a machine without one still
imports the client, and opening the window there refuses with a typed code
naming what to install.
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


def open_shell_window(
    *,
    os_name: str,
    title: str,
    html: str,
    bridge,
    icon_path="",
    is_hidden: bool = False,
    on_quit=None,
    on_show_ready=None,
    on_push_ready=None,
):
    """Open the platform's window and block until its Quit ends the loop.

    Args:
        os_name: The platform's ``os_name``.
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        icon_path: The window icon's file path, empty for none.
        is_hidden: Whether to start in the tray with no window shown.
        on_quit: Called when the person picks Quit, before the loop ends.
        on_show_ready: Called with a callable that brings the window up.
        on_push_ready: Called with a callable that hands the page one state
            payload to redraw from.

    Raises:
        GuiShellUnavailableError: When the platform has no shell, or its
            toolkit is not on the machine.
    """
    shell = _shell_for(os_name)
    if shell is None:
        raise GuiShellUnavailableError("unsupported_platform")
    shell.open_window(
        title=title,
        html=html,
        bridge=bridge,
        icon_path=icon_path,
        is_hidden=is_hidden,
        on_quit=on_quit,
        on_show_ready=on_show_ready,
        on_push_ready=on_push_ready,
    )


def _shell_for(os_name: str):
    """The platform's shell module, or None.

    Args:
        os_name: The platform's ``os_name``.

    Returns:
        The shell module, or None for a platform without one.
    """
    if os_name == "linux":
        from neutrino_client.gui import webkitgtk

        return webkitgtk
    if os_name == "windows":
        from neutrino_client.gui import webview2

        return webview2
    return None
