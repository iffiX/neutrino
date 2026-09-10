"""The Linux shell: WebKitGTK, pinned to the 4.1 API.

The page loads into a ``WebKit2.WebView``; its bridge adapter posts each
request to the ``neutrino`` script message handler, and the reply is
delivered back by evaluating ``window.neutrinoReply``. The channel round
trip runs off the GTK main thread, so a slow step never freezes the window.

Closing the window hides it and leaves the client running; the tray icon
brings it back and its Quit is what ends the loop.

The bindings are the package's own, built for the interpreter it carries. A
machine still needs the C libraries under them, which is the one thing this
can refuse for.
"""

import json
import threading

from neutrino_client.constants import (
    CLIENT_DESKTOP_NAME,
    CLIENT_GUI_WINDOW_HEIGHT,
    CLIENT_GUI_WINDOW_WIDTH,
)
from neutrino_client.exceptions import GuiShellUnavailableError
from neutrino_client.gui.tray import LinuxTrayIcon

# The distribution packages the import guard names when the C stack is
# absent.
WEBKITGTK_PACKAGES = "gir1.2-webkit2-4.1"


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
    """Open the window and run the GTK main loop until Quit ends it.

    Args:
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        icon_path: The window icon's file path, empty for none.
        is_hidden: Whether to start in the tray with no window shown.
        on_quit: Called when the person picks Quit, before the loop ends.
        on_push_ready: Called with a callable that hands the page one
            state payload; the page redraws from it without asking.
        on_show_ready: Called with a callable that brings the window up,
            safe to call from any thread.

    Raises:
        GuiShellUnavailableError: When WebKitGTK 4.1 is not on the machine.
    """
    GLib, Gtk, WebKit2 = _toolkit()
    # WM_CLASS, which GTK otherwise takes from argv[0]. The desktop matches a
    # window to its launcher by this name.
    GLib.set_prgname(CLIENT_DESKTOP_NAME)
    GLib.set_application_name(title)
    window = Gtk.Window(title=title)
    window.set_default_size(CLIENT_GUI_WINDOW_WIDTH, CLIENT_GUI_WINDOW_HEIGHT)
    if icon_path:
        try:
            window.set_icon_from_file(icon_path)
        except Exception:  # noqa: BLE001 - a bad icon must not cost the window
            pass
    manager = WebKit2.UserContentManager()
    view = WebKit2.WebView(user_content_manager=manager)

    def deliver(reply: dict) -> bool:
        script = f"window.neutrinoReply({json.dumps(reply)})"
        evaluate = getattr(view, "evaluate_javascript", None)
        if evaluate is not None:
            evaluate(script, -1, None, None, None, None)
        else:
            view.run_javascript(script, None, None, None)
        return False

    def answer(request: dict) -> None:
        GLib.idle_add(deliver, bridge.handle(request))

    def deliver_state(state: dict) -> bool:
        script = f"window.neutrinoState({json.dumps(state)})"
        evaluate = getattr(view, "evaluate_javascript", None)
        if evaluate is not None:
            evaluate(script, -1, None, None, None, None)
        else:
            view.run_javascript(script, None, None, None)
        return False

    def push_state(state: dict) -> None:
        GLib.idle_add(deliver_state, state)

    def on_message(_manager, message) -> None:
        request = json.loads(message.get_js_value().to_string())
        threading.Thread(target=answer, args=(request,), daemon=True).start()

    def present() -> bool:
        window.show_all()
        window.present()
        return False

    def show_window() -> None:
        GLib.idle_add(present)

    def on_delete(_window, _event) -> bool:
        window.hide()
        return True

    def quit_window() -> None:
        if on_quit is not None:
            on_quit()
        Gtk.main_quit()

    manager.register_script_message_handler("neutrino")
    manager.connect("script-message-received::neutrino", on_message)
    window.add(view)
    view.load_html(html, "about:blank")
    window.connect("delete-event", on_delete)
    LinuxTrayIcon(
        title=title,
        icon_path=icon_path,
        on_open=show_window,
        on_quit=quit_window,
        gtk=Gtk,
    )
    if not is_hidden:
        window.show_all()
    if on_show_ready is not None:
        on_show_ready(show_window)
    if on_push_ready is not None:
        on_push_ready(push_state)
    Gtk.main()


def _toolkit():
    """The GTK and WebKit bindings, or the typed refusal.

    Returns:
        ``(GLib, Gtk, WebKit2)``.

    Raises:
        GuiShellUnavailableError: When the bindings or the 4.1 API are
            absent.
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import GLib, Gtk, WebKit2
    except (ImportError, ValueError) as error:
        raise GuiShellUnavailableError(
            "gui_webkitgtk_missing", {"packages": WEBKITGTK_PACKAGES}
        ) from error
    return GLib, Gtk, WebKit2
