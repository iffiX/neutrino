"""The Windows shell: WebView2, embedded through pywebview.

The page loads into an Edge Chromium view; its bridge adapter calls
``window.pywebview.api.request``, which pywebview routes to the window's
:class:`~neutrino_client.gui.bridge.GuiWindowApi`. The pywebview wheels are
vendored by the packaging build; the WebView2 runtime itself comes with the
installer's bootstrapper.
"""

from neutrino_client.constants import (
    CLIENT_GUI_WINDOW_HEIGHT,
    CLIENT_GUI_WINDOW_WIDTH,
)
from neutrino_client.gui.bridge import GuiWindowApi

WEBVIEW2_RUNTIME = "the Microsoft Edge WebView2 Runtime"


def open_window(*, title: str, html: str, bridge, icon_path: str = "") -> None:
    """Open the window and block until it closes.

    Args:
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        icon_path: Accepted for the seam's shape; pywebview windows take
            their icon from the installed application.

    Raises:
        GuiShellUnavailableError: When the embedding library is not in this
            install.
    """
    from neutrino_client.gui.shell import GuiShellUnavailableError

    try:
        import webview
    except ImportError as error:
        raise GuiShellUnavailableError(
            "gui_webview2_missing", {"runtime": WEBVIEW2_RUNTIME}
        ) from error
    webview.create_window(
        title,
        html=html,
        js_api=GuiWindowApi(bridge),
        width=CLIENT_GUI_WINDOW_WIDTH,
        height=CLIENT_GUI_WINDOW_HEIGHT,
    )
    webview.start(gui="edgechromium")
