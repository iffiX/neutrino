"""The Linux shell: WebKitGTK, pinned to the 4.1 API.

The page loads into a ``WebKit2.WebView``; its bridge adapter posts each
request to the ``neutrino`` script message handler, and the reply is
delivered back by evaluating ``window.neutrinoReply``. The channel round
trip runs off the GTK main thread, so a slow agent never freezes the
window.
"""

import json
import threading

from neutrino_agent.constants import AGENT_GUI_WINDOW_HEIGHT, AGENT_GUI_WINDOW_WIDTH

# The distro packages the import guard names when the toolkit is absent.
WEBKITGTK_PACKAGES = "gir1.2-webkit2-4.1 python3-gi"


def open_window(*, title: str, html: str, bridge, icon_path: str = "") -> None:
    """Open the window and run the GTK main loop until it closes.

    Args:
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        icon_path: The window icon's file path, empty for none.

    Raises:
        GuiShellUnavailableError: When WebKitGTK 4.1 is not on the machine.
    """
    GLib, Gtk, WebKit2 = _toolkit()
    window = Gtk.Window(title=title)
    window.set_default_size(AGENT_GUI_WINDOW_WIDTH, AGENT_GUI_WINDOW_HEIGHT)
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

    def on_message(_manager, message) -> None:
        request = json.loads(message.get_js_value().to_string())
        threading.Thread(target=answer, args=(request,), daemon=True).start()

    manager.register_script_message_handler("neutrino")
    manager.connect("script-message-received::neutrino", on_message)
    window.add(view)
    view.load_html(html, "about:blank")
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()


def _toolkit():
    """The GTK and WebKit bindings, or the typed refusal.

    Returns:
        ``(GLib, Gtk, WebKit2)``.

    Raises:
        GuiShellUnavailableError: When the bindings or the 4.1 API are
            absent.
    """
    from neutrino_agent.gui.shell import GuiShellUnavailableError

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
