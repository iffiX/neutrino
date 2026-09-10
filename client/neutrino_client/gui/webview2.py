"""The Windows shell: WebView2, embedded through pywebview.

The page loads into an Edge Chromium view; its bridge adapter calls
``window.pywebview.api.request``, which pywebview routes to the window's
:class:`~neutrino_client.gui.bridge.GuiWindowApi`. The pywebview wheels are
vendored by the packaging build; the WebView2 runtime itself comes with the
installer's bootstrapper.

Closing the window hides it and leaves the client running; the tray icon
brings it back and its Quit is what ends the loop.
"""

import json

from neutrino_client.constants import (
    CLIENT_GUI_WINDOW_HEIGHT,
    CLIENT_GUI_WINDOW_WIDTH,
)
from neutrino_client.exceptions import GuiShellUnavailableError
from neutrino_client.gui.bridge import GuiWindowApi
from neutrino_client.gui.tray import WindowsTrayIcon

WEBVIEW2_RUNTIME = "the Microsoft Edge WebView2 Runtime"


def open_window(
    *,
    title: str,
    html: str,
    bridge,
    icon_path: str = "",
    is_hidden: bool = False,
    on_quit=None,
    on_show_ready=None,
    on_push_ready=None,
) -> None:
    """Open the window and block until Quit ends the loop.

    Args:
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        icon_path: The tray icon's file path, empty for the stock icon;
            pywebview windows take their own icon from the installed
            application.
        is_hidden: Whether to start in the tray with no window shown.
        on_quit: Called when the person picks Quit, before the loop ends.
        on_show_ready: Called with a callable that brings the window up.
        on_push_ready: Called with a callable that hands the page one
            state payload; the page redraws from it without asking.

    Raises:
        GuiShellUnavailableError: When the embedding library is not in this
            install.
    """
    try:
        import webview
    except ImportError as error:
        raise GuiShellUnavailableError(
            "gui_webview2_missing", {"runtime": WEBVIEW2_RUNTIME}
        ) from error
    window = webview.create_window(
        title,
        html=html,
        js_api=GuiWindowApi(bridge),
        width=CLIENT_GUI_WINDOW_WIDTH,
        height=CLIENT_GUI_WINDOW_HEIGHT,
        hidden=is_hidden,
    )

    # The close button hides the window into the tray; the tray's Quit is
    # the one close that may go through, or the loop never ends.
    state = {"is_quitting": False}

    def on_closing() -> bool:
        if state["is_quitting"]:
            return True
        window.hide()
        return False

    def show_window() -> None:
        window.show()

    def quit_window() -> None:
        state["is_quitting"] = True
        if on_quit is not None:
            on_quit()
        window.destroy()

    def push_state(state: dict) -> None:
        window.evaluate_js(f"window.neutrinoState({json.dumps(state)})")

    window.events.closing += on_closing
    tray = WindowsTrayIcon(
        title=title, icon_path=icon_path, on_open=show_window, on_quit=quit_window
    )
    tray.start()
    if on_show_ready is not None:
        on_show_ready(show_window)
    if on_push_ready is not None:
        on_push_ready(push_state)
    try:
        webview.start(gui="edgechromium")
    finally:
        tray.stop()
