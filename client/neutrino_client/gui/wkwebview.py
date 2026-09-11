"""The macOS shell: WKWebView, through pyobjc.

The page loads into a ``WKWebView``; its bridge adapter posts each request
to the ``neutrino`` script message handler, the same name WebKitGTK
registers, and the reply is delivered back by evaluating
``window.neutrinoReply``. The channel round trip runs off the main thread,
and every call back into AppKit is queued onto the main operation queue.

Closing the window hides it and leaves the client running; the status item
in the menu bar brings it back and its Quit is what ends the loop. A quit
from the Dock or a logout runs the same shutdown through the application
delegate and then lets the process end.

The bindings are pyobjc, compiled into the app bundle by the packaging
build; a checkout without them refuses typed.
"""

import json
import threading

from neutrino_client import words
from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_GUI_WINDOW_HEIGHT,
    CLIENT_GUI_WINDOW_WIDTH,
    CLIENT_TRAY_OPEN_LABEL_KEY,
    CLIENT_TRAY_QUIT_LABEL_KEY,
)
from neutrino_client.exceptions import GuiShellUnavailableError
from neutrino_client.gui.tray_macos import MacosTrayIcon

# The distributions the import guard names when the bindings are absent.
PYOBJC_PACKAGES = "pyobjc-framework-Cocoa pyobjc-framework-WebKit"
# The name the page posts to: ``window.webkit.messageHandlers.neutrino``.
MESSAGE_HANDLER_NAME = "neutrino"


def open_window(
    *,
    title: str,
    html: str,
    bridge,
    language: str = CLIENT_DEFAULT_LANGUAGE,
    icon_path: str = "",
    is_hidden: bool = False,
    on_quit=None,
    on_show_ready=None,
    on_push_ready=None,
) -> None:
    """Open the window and run the application loop until Quit ends it.

    Args:
        title: The window title.
        html: The page, as one document.
        bridge: The window's bridge.
        language: The language the menu bar item is worded in.
        icon_path: The icon's file path, empty for the bundle's own.
        is_hidden: Whether to start in the menu bar with no window shown.
        on_quit: Called when the person picks Quit, before the loop ends.
        on_show_ready: Called with a callable that brings the window up,
            safe to call from any thread.
        on_push_ready: Called with a callable that hands the page one
            state payload; the page redraws from it without asking.

    Raises:
        GuiShellUnavailableError: When pyobjc is not in this install.
    """
    AppKit, Foundation, WebKit = _toolkit()
    classes = _delegate_classes(AppKit.NSObject)
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    if icon_path:
        image = AppKit.NSImage.alloc().initWithContentsOfFile_(icon_path)
        if image is not None:
            app.setApplicationIconImage_(image)

    queue = Foundation.NSOperationQueue.mainQueue()
    frame = Foundation.NSMakeRect(
        0, 0, CLIENT_GUI_WINDOW_WIDTH, CLIENT_GUI_WINDOW_HEIGHT
    )
    configuration = WebKit.WKWebViewConfiguration.alloc().init()
    handler = classes["message_handler"].alloc().init()
    configuration.userContentController().addScriptMessageHandler_name_(
        handler, MESSAGE_HANDLER_NAME
    )
    view = WebKit.WKWebView.alloc().initWithFrame_configuration_(frame, configuration)
    view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, _window_style(AppKit), AppKit.NSBackingStoreBuffered, False
    )
    window.setTitle_(title)
    window.setReleasedWhenClosed_(False)
    window.setContentView_(view)
    window.center()

    def on_main(callback, *arguments) -> None:
        # A block takes a function whose signature pyobjc can read; a partial
        # is refused, so the call is closed over instead.
        def run() -> None:
            callback(*arguments)

        queue.addOperationWithBlock_(run)

    def deliver(reply: dict) -> None:
        script = f"window.neutrinoReply({json.dumps(reply)})"
        view.evaluateJavaScript_completionHandler_(script, None)

    def answer(request: dict) -> None:
        on_main(deliver, bridge.handle(request))

    def on_message(body) -> None:
        request = json.loads(str(body))
        threading.Thread(target=answer, args=(request,), daemon=True).start()

    def deliver_state(state: dict) -> None:
        script = f"window.neutrinoState({json.dumps(state)})"
        view.evaluateJavaScript_completionHandler_(script, None)

    def push_state(state: dict) -> None:
        on_main(deliver_state, state)

    def present() -> None:
        window.makeKeyAndOrderFront_(None)
        app.activateIgnoringOtherApps_(True)

    def show_window() -> None:
        on_main(present)

    def hide_window() -> None:
        window.orderOut_(None)

    def quit_window() -> None:
        if on_quit is not None:
            on_quit()
        app.stop_(None)

    def on_terminate() -> None:
        if on_quit is not None:
            on_quit()

    # AppKit keeps no strong reference to a delegate, a menu target or a
    # status item; these locals do, for as long as the loop runs.
    handler.on_message = on_message
    window_delegate = classes["window_delegate"].alloc().init()
    window_delegate.on_close = hide_window
    window.setDelegate_(window_delegate)
    app_delegate = classes["application_delegate"].alloc().init()
    app_delegate.on_reopen = present
    app_delegate.on_terminate = on_terminate
    app_delegate.terminate_reply = AppKit.NSTerminateNow
    app.setDelegate_(app_delegate)
    view.loadHTMLString_baseURL_(html, None)
    tray = MacosTrayIcon(
        title=title,
        open_label=words.word(language, CLIENT_TRAY_OPEN_LABEL_KEY),
        quit_label=words.word(language, CLIENT_TRAY_QUIT_LABEL_KEY),
        icon_path=icon_path,
        on_open=show_window,
        on_quit=quit_window,
        appkit=AppKit,
    )
    if not is_hidden:
        present()
    if on_show_ready is not None:
        on_show_ready(show_window)
    if on_push_ready is not None:
        on_push_ready(push_state)
    app.run()


def _toolkit():
    """The AppKit, Foundation and WebKit bindings, or the typed refusal.

    Returns:
        ``(AppKit, Foundation, WebKit)``.

    Raises:
        GuiShellUnavailableError: When pyobjc is absent.
    """
    try:
        import AppKit
        import Foundation
        import WebKit
    except ImportError as error:
        raise GuiShellUnavailableError(
            "gui_wkwebview_missing", {"packages": PYOBJC_PACKAGES}
        ) from error
    return AppKit, Foundation, WebKit


def _window_style(AppKit) -> int:
    """A titled window that closes, minimizes and resizes."""
    return (
        AppKit.NSWindowStyleMaskTitled
        | AppKit.NSWindowStyleMaskClosable
        | AppKit.NSWindowStyleMaskMiniaturizable
        | AppKit.NSWindowStyleMaskResizable
    )


def _delegate_classes(base) -> dict:
    """The three ``NSObject`` subclasses AppKit and WebKit call back into.

    Each is defined against the loaded bindings and carries its callbacks
    as plain attributes set after ``alloc().init()``.

    Args:
        base: The ``NSObject`` class of the loaded bindings.

    Returns:
        ``{"message_handler", "window_delegate", "application_delegate"}``.
    """

    class NeutrinoScriptMessageHandler(base):
        def userContentController_didReceiveScriptMessage_(
            self, _controller, message
        ) -> None:
            self.on_message(message.body())

    class NeutrinoWindowDelegate(base):
        def windowShouldClose_(self, _sender) -> bool:
            self.on_close()
            return False

    class NeutrinoApplicationDelegate(base):
        def applicationShouldHandleReopen_hasVisibleWindows_(
            self, _application, _has_visible_windows
        ) -> bool:
            self.on_reopen()
            return False

        def applicationShouldTerminate_(self, _sender) -> int:
            self.on_terminate()
            return self.terminate_reply

    return {
        "message_handler": NeutrinoScriptMessageHandler,
        "window_delegate": NeutrinoWindowDelegate,
        "application_delegate": NeutrinoApplicationDelegate,
    }
