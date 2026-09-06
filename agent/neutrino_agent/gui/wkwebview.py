"""The macOS shell: WKWebView, embedded through pywebview.

The same embedding pattern as the Windows shell, on the Cocoa backend the
packaging build vendors for macOS.
"""

from neutrino_agent.constants import AGENT_GUI_WINDOW_HEIGHT, AGENT_GUI_WINDOW_WIDTH
from neutrino_agent.gui.bridge import GuiWindowApi


def open_window(*, title: str, html: str, bridge, icon_path: str = "") -> None:
    """Open the window and block until it closes.

    Args:
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        icon_path: Accepted for the seam's shape; a macOS window takes its
            icon from the application bundle.

    Raises:
        GuiShellUnavailableError: When the embedding library is not in this
            install.
    """
    from neutrino_agent.gui.shell import GuiShellUnavailableError

    try:
        import webview
    except ImportError as error:
        raise GuiShellUnavailableError("gui_wkwebview_missing", {}) from error
    webview.create_window(
        title,
        html=html,
        js_api=GuiWindowApi(bridge),
        width=AGENT_GUI_WINDOW_WIDTH,
        height=AGENT_GUI_WINDOW_HEIGHT,
    )
    webview.start(gui="cocoa")
