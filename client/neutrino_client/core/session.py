"""The resident itself: the binding, the socket to the hub, and the services.

One object owns everything the person's page and the hub both talk to. It
runs whether or not the person belongs to a hub yet: an unbound resident
still serves its page, waiting for a link.

While bound, the resident holds one socket open to the hub and reconnects
when it drops. The hub pushes its ``state``, the services it publishes and
whether the client is switched off, and the client answers each state and
every interval with a ``report``. What a service handler needs from the hub
comes down a ``service`` stream it opens. Joining and leaving stay HTTP:
both happen when there is no socket to carry them.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.parse

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_BACKOFF_MAX_S,
    CLIENT_BACKOFF_MIN_S,
    CLIENT_CHANNEL_WS_PATH,
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_DEFAULT_THEME,
    CLIENT_HELLO_TIMEOUT_S,
    CLIENT_HUB_ROLE,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
    CLIENT_ORIGINAL_DIR_NAME,
    CLIENT_PROTOCOL_REFUSAL_CODES,
    CLIENT_REFUSAL_CODE_BINDING_UNKNOWN,
    CLIENT_REPORT_INTERVAL_S,
    CLIENT_ROLE,
    CLIENT_SHUTDOWN_DEADLINE_S,
    CLIENT_SOFTWARE_PREFIX,
    CLIENT_STATE_FILE_NAME,
    CLIENT_STREAM_CODE_KIND_UNKNOWN,
    CLIENT_STREAM_KIND_SERVICE,
    CLIENT_STREAM_TIMEOUT_S,
    CLIENT_WS_CLOSE_REPLACED,
    PROTOCOL,
)
from neutrino_client.core import enrollment, protocol
from neutrino_client.core.channel import refusal_error
from neutrino_client.core.streams import ClientStreamRegistry
from neutrino_client.core.ws_client import WebSocketClient, close_error
from neutrino_client.exceptions import (
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    SocketClosed,
)
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.file import FileServiceHandler
from neutrino_client.services.port import PortServiceHandler
from neutrino_client.services.rdp import RdpViewerHandler
from neutrino_client.services.store import ClientServiceStore
from neutrino_client.services.web import WebServiceHandler

# How the four connection states are named to every surface.
CONNECTION_CONNECTED = "connected"
CONNECTION_RECONNECTING = "reconnecting"
CONNECTION_REPLACED = "replaced"
CONNECTION_UNBOUND = "unbound"

# How long a shutdown waits for the loop thread to come back.
SHUTDOWN_JOIN_TIMEOUT_S = 5
# What a shutdown lets go of, in order: the handler, the name its line
# carries, and how that line reads.
SHUTDOWN_STEPS = (
    ("ai", "ai", "restored"),
    ("file", "mounts", "{count} detached"),
    ("port", "forwards", "{count} closed"),
    ("rdp", "viewers", "{count} closed"),
)
# How long a burst of changes is left to settle before the watchers hear.
ANNOUNCE_SETTLE_S = 0.05


def end_process(status: int = 0) -> None:
    """End this process now, whatever the window's runtime left running.

    The shutdown is what restores the machine, and it has already run by the
    time this is called. What can still be standing is the window runtime's
    own: on Windows the embedded browser's helper processes and the threads
    .NET holds, none of which answer to this interpreter. A resident that
    lingers there holds this person's socket and hands the next install a
    file it cannot replace.

    Args:
        status: The exit status.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


def channel_error(error: Exception) -> dict:
    """The typed form of a channel exception.

    Args:
        error: What the channel raised.

    Returns:
        ``{"code", "params"}``.
    """
    if isinstance(error, GatewayRefusedDetail):
        return {"code": error.code, "params": dict(error.params)}
    if isinstance(error, GatewayUntrusted):
        return {"code": "hub_untrusted", "params": {}}
    if isinstance(error, GatewayRefused):
        if error.code:
            return {"code": error.code, "params": dict(error.params)}
        return {"code": "hub_refused", "params": {}}
    return {"code": "hub_unreachable", "params": {"detail": str(error)}}


def _decode(payload) -> "dict | None":
    """One text frame as an object, or None when it is not one.

    Args:
        payload: The frame's text.

    Returns:
        The decoded object, or None when the frame is not one.
    """
    try:
        message = json.loads(payload)
    except (TypeError, ValueError):
        return None
    return message if isinstance(message, dict) else None


def _hello_refusal(message: dict) -> Exception:
    """What a refused frame means: the hub turned this binding away."""
    code = str(message.get("code", "") or "")
    params = message.get("params")
    params = params if isinstance(params, dict) else {}
    if code in CLIENT_PROTOCOL_REFUSAL_CODES:
        return refusal_error(code, params)
    return GatewayRefused(
        f"hub refused this client's hello ({code})", code=code, params=params
    )


class ClientSession:
    """Everything the resident is, bound to a hub or waiting for a link."""

    def __init__(self, *, log=print, platform=None):
        """
        Args:
            log: Callable used for progress messages.
            platform: The machine's platform; None detects it.
        """
        self._log = log
        self._lock = threading.Lock()
        self.platform = platform if platform is not None else detect_platform()
        self._platform_tuple = platform_tuple()
        config_dir = self.platform.config_dir()
        self._store = ClientServiceStore(
            path=os.path.join(config_dir, CLIENT_STATE_FILE_NAME)
        )
        # Whoever draws the state, told after every change of it; the
        # announcements of one burst are folded into one.
        self._watchers: list = []
        self._announce_lock = threading.Lock()
        self._is_announcing = False
        self._services = {
            handler.service_type: handler
            for handler in (
                WebServiceHandler(platform=self.platform),
                PortServiceHandler(log=log, on_change=self.notify),
                AiServiceHandler(
                    store=self._store,
                    original_dir=os.path.join(config_dir, CLIENT_ORIGINAL_DIR_NAME),
                    open_service=self.open_service,
                    log=log,
                    on_change=self.notify,
                ),
                FileServiceHandler(
                    platform=self.platform,
                    store=self._store,
                    credentials_dir=os.path.join(
                        config_dir, CLIENT_MOUNT_CREDENTIALS_DIR_NAME
                    ),
                    log=log,
                    on_change=self.notify,
                ),
                RdpViewerHandler(
                    platform=self.platform,
                    open_service=self.open_service,
                    log=log,
                    on_change=self.notify,
                ),
            )
        }
        # Set whenever the loop should stop waiting: a binding was written, or
        # the resident is shutting down.
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._is_shut_down = False
        self._client: "WebSocketClient | None" = None
        self._streams: "ClientStreamRegistry | None" = None
        self._is_welcomed = False
        # The first binding on disk; empty while unbound.
        self._binding: dict = {}
        self._binding_stamp = 0
        self._backoff_s = CLIENT_BACKOFF_MIN_S
        # Set while another socket holds this binding; only a person clears it.
        self._is_replaced = False
        self._last_error: "dict | None" = None
        self._services_list: list = []
        self._state_hash = ""
        self._hub_software = ""
        self._is_disabled = False
        self._was_disabled = False
        self.on_show = None
        self._load_connection()

    # --- what the local page reads ---

    def platform_tuple(self) -> dict:
        """This machine's platform tuple."""
        return dict(self._platform_tuple)

    def home(self) -> str:
        """This person's home directory."""
        return self.platform.home()

    def hostname(self) -> str:
        """This machine's hostname."""
        return socket.gethostname()

    def is_connected(self) -> bool:
        """Whether this person belongs to a hub."""
        with self._lock:
            return bool(self._binding)

    def connection_state(self) -> str:
        """Where the hub socket stands, one of the four ``CONNECTION_*`` states."""
        with self._lock:
            if not self._binding:
                return CONNECTION_UNBOUND
            if self._is_replaced:
                return CONNECTION_REPLACED
            return (
                CONNECTION_CONNECTED if self._is_welcomed else CONNECTION_RECONNECTING
            )

    def gateway_url(self) -> str:
        """The hub this person belongs to, empty when none."""
        with self._lock:
            return self._binding.get("gateway_url", "")

    def hub_version(self) -> str:
        """The version the hub's welcome named, after the package name."""
        with self._lock:
            software = self._hub_software
        return software.partition("/")[2] or software

    def is_disabled(self) -> bool:
        """Whether the hub has switched this person off."""
        with self._lock:
            return self._is_disabled

    def last_error(self) -> "dict | None":
        """The most recent problem worth showing, as ``{"code", "params"}``."""
        with self._lock:
            return dict(self._last_error) if self._last_error else None

    def service_entries(self) -> list:
        """The typed service list, as the hub last sent it."""
        with self._lock:
            return [entry for entry in self._services_list if isinstance(entry, dict)]

    def suggest_mount_location(self) -> str:
        """What the platform offers as a mount location before one is typed."""
        return self.platform.suggest_mount_location()

    def mount_location_choices(self) -> list:
        """The fixed set of mount locations, when the platform has one."""
        return self.platform.mount_location_choices()

    def mount_location_shape(self) -> str:
        """What a mount location is here: ``path`` or ``drive_letter``."""
        return self.platform.mount_location_shape

    def language(self) -> str:
        """The language every surface of this client words itself in.

        The first run has none kept, and takes the machine's own; what it
        takes is written back, so the answer never changes underfoot.

        Returns:
            One of ``CLIENT_LANGUAGES``.
        """
        kept = self._store.language()
        if kept:
            return kept
        self._store.set_language(self.platform.system_language())
        return self._store.language() or CLIENT_DEFAULT_LANGUAGE

    def set_language(self, language: str) -> None:
        """Keep the language every surface words itself in, and say so.

        Args:
            language: One of ``CLIENT_LANGUAGES``.
        """
        self._store.set_language(language)
        self.notify()

    def theme(self) -> str:
        """The palette the window draws itself in.

        Returns:
            One of ``CLIENT_THEMES``; the default until one is picked.
        """
        return self._store.theme() or CLIENT_DEFAULT_THEME

    def set_theme(self, theme: str) -> None:
        """Keep the palette the window draws in, and say so.

        Args:
            theme: One of ``CLIENT_THEMES``.
        """
        self._store.set_theme(theme)
        self.notify()

    def subscribe(self, watcher) -> None:
        """Be told after every change of the state the page draws.

        Args:
            watcher: Called with no arguments, on a thread of the session's.
        """
        with self._lock:
            self._watchers.append(watcher)

    def notify(self) -> None:
        """Announce a change of state to every watcher, once per burst.

        Changes arriving while the watchers are being told are folded into
        the round that follows, so a burst of them costs one redraw.
        """
        with self._announce_lock:
            if self._is_announcing:
                self._is_pending_announcement = True
                return
            self._is_announcing = True
            self._is_pending_announcement = False
        threading.Thread(target=self._announce, daemon=True).start()

    def _announce(self) -> None:
        while True:
            time.sleep(ANNOUNCE_SETTLE_S)
            # Everything that arrived while settling is this round's.
            with self._announce_lock:
                self._is_pending_announcement = False
            with self._lock:
                watchers = list(self._watchers)
            for watcher in watchers:
                try:
                    watcher()
                except Exception as error:  # noqa: BLE001 - a watcher's own
                    self._log(f"a state watcher failed: {error}")
            with self._announce_lock:
                if not self._is_pending_announcement:
                    self._is_announcing = False
                    return

    def service_states(self) -> dict:
        """Every service type's state, merged for the page payload."""
        merged = {}
        for handler in self._services.values():
            merged.update(handler.state())
        return merged

    def list_directories(self, path: str) -> list:
        """The subdirectory names under a directory, as this person."""
        return self.platform.list_directories(path=path)

    def make_directory(self, path: str) -> None:
        """Create a directory as this person, parents included."""
        self.platform.make_directory(path=path)

    # --- what the local page does ---

    def connect(self, link: str) -> None:
        """Join the hub an enrollment link points at.

        Args:
            link: The link the person pasted.

        Raises:
            EnrollmentError: If the link is unusable or the hub refuses.
        """
        enrollment.enroll(link)
        self._reset_binding_state()
        self._load_connection()
        self._log("joined the hub")
        self.reconnect_soon()
        self.notify()

    def disconnect(self) -> None:
        """Leave the hub and let go of everything it published.

        The hub is told first; one that cannot be reached does not hold the
        person here.
        """
        with self._lock:
            binding = dict(self._binding)
        if binding:
            try:
                enrollment.leave(binding)
            except (GatewayRefused, GatewayUnreachable, GatewayUntrusted) as error:
                self._log(f"could not tell the hub we are leaving: {error}")
            enrollment.remove_binding(binding["id"])
        self._drop_socket()
        self._release()
        self._reset_binding_state()
        self._load_connection()
        self._log("left the hub")
        self.notify()

    def reconnect_soon(self) -> None:
        """Cut the wait before the next connection attempt short."""
        self._news.set()

    def reconnect(self, hub_id: str = "") -> None:
        """Take the binding back from the socket that replaced it, and connect now.

        Args:
            hub_id: The hub to connect to; empty names the one binding held.

        Raises:
            KeyError: If ``hub_id`` names no hub this person has joined.
        """
        with self._lock:
            if hub_id and hub_id != self._binding.get("hub_id"):
                raise KeyError(hub_id)
            self._is_replaced = False
        self._news.set()
        self.notify()

    def request_show(self) -> None:
        """Ask the window to come to the front, when one is listening."""
        callback = self.on_show
        if callback is not None:
            callback()

    def service_action(self, service_type: str, body: dict) -> dict:
        """Hand one page action to the handler for its service type.

        Args:
            service_type: The type the page acted on.
            body: The action's own fields.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        handler = self._services.get(service_type)
        if handler is None:
            return {"code": "unknown_request", "params": {}}
        if self.is_disabled():
            return {"code": "client_disabled", "params": {}}
        return handler.act(entries=self.service_entries(), body=body)

    def open_service(
        self, entry_id: str, timeout_s: float = CLIENT_STREAM_TIMEOUT_S
    ) -> dict:
        """Open a ``service`` stream for one entry and take the hub's close.

        Args:
            entry_id: The published entry's id.
            timeout_s: How long to wait for the close.

        Returns:
            The close's ``params``: the entry's material.

        Raises:
            GatewayRefusedDetail: When the hub closed the stream with a code.
            GatewayUnreachable: When there is no socket, the socket ends, or
                the close does not arrive in time.
        """
        with self._lock:
            streams = self._streams
            if streams is None or not self._is_welcomed:
                raise GatewayUnreachable("this person's hub is not connected")
        stream = streams.open(CLIENT_STREAM_KIND_SERVICE, {"id": entry_id})
        return stream.wait_close(timeout_s)

    # --- the loop ---

    def start(self) -> None:
        """Clear what an unclean exit left, then run the handlers and the loop.

        Nothing this person had on is turned on again: the client opens with
        every service off, and the leftovers of a run that did not shut down
        are undone before the hub's first state arrives.
        """
        self._clear_leftovers()
        for handler in self._services.values():
            handler.start()
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def run_forever(self) -> None:
        """Hold the socket, or wait to be enrolled, until the resident stops."""
        self._log(f"neutrino_client {CLIENT_VERSION} starting on {self.hostname()}")
        while not self._stop.is_set():
            # Cleared before the turn, so news that lands during it, the
            # stop included, is still standing when the wait begins.
            self._news.clear()
            delay = self.run_once()
            self._news.wait(timeout=delay)

    def run_once(self) -> int:
        """One connection's lifetime, or one idle turn while unbound.

        Returns:
            How many seconds to wait before the next one: the shortest delay
            after a clean close, a backing-off delay after a broken wire, a
            minute after a refusal the binding survives, and a short idle
            wait while the person belongs to no hub or another socket holds
            the binding.
        """
        self._adopt_external_binding()
        client = self._open_client()
        if client is None:
            return CLIENT_IDLE_POLL_INTERVAL_S
        try:
            self._connect(client)
        except (GatewayRefused, GatewayUntrusted) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            return self._on_unreachable(error)
        failure = self._serve(client)
        if failure is None:
            return CLIENT_BACKOFF_MIN_S
        if isinstance(failure, GatewayRefused):
            return self._on_rejected(failure)
        return self._on_unreachable(failure)

    def shutdown(self) -> None:
        """Let go of everything and stop the loop. Idempotent.

        The order is the one that leaves the machine as it was found: the
        tools restored, the shares unmounted, the forwards closed, the
        viewers closed. The four share ``CLIENT_SHUTDOWN_DEADLINE_S``; a
        step past its part of what is left is given up and the next runs.
        """
        with self._lock:
            if self._is_shut_down:
                return
            self._is_shut_down = True
        self._stop.set()
        self._news.set()
        self._drop_socket()
        self._release_in_time()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
        self._log("shut down")

    def _open_client(self) -> "WebSocketClient | None":
        """A socket for the current binding, or None while unbound or replaced."""
        with self._lock:
            binding = dict(self._binding)
            is_replaced = self._is_replaced
        if not binding or is_replaced:
            return None
        parts = urllib.parse.urlsplit(binding["gateway_url"])
        return WebSocketClient(
            host=parts.hostname or "",
            port=parts.port or 443,
            path=CLIENT_CHANNEL_WS_PATH,
            fingerprint=binding["fingerprint"],
            timeout_s=CLIENT_HELLO_TIMEOUT_S,
        )

    def _connect(self, client) -> None:
        """Open the socket, say hello, take the welcome, and report once.

        Args:
            client: The unconnected socket.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefused: When the hub refused the hello, by a frame or by
                its close; the protocol refusals are their own kind.
            GatewayUnreachable: On any network error, or a first frame that
                is neither a welcome nor a refusal.
        """
        client.connect()
        try:
            client.send_text(json.dumps(self._hello()))
            welcome = self._take_welcome(client)
            self._report(client)
        except SocketClosed as closed:
            raise close_error(closed.code, closed.reason) from closed
        except Exception:
            client.close()
            raise
        self._note_hub(welcome)
        with self._lock:
            self._client = client
            self._streams = ClientStreamRegistry(
                send_text=client.send_text, log=self._log
            )
            self._is_welcomed = True
            self._hub_software = str(welcome.get("software", "") or "")
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            self._last_error = None
        self.notify()

    def _serve(self, client) -> "Exception | None":
        """Read frames until the socket ends, reporting on the interval.

        Args:
            client: The connected socket.

        Returns:
            What ended it, or None when a shutdown, a close from here, or
            another socket replacing this one did.
        """
        failure = None
        ended = threading.Event()
        reporter = threading.Thread(
            target=self._report_on_interval,
            args=(client, ended),
            name="client_report",
            daemon=True,
        )
        reporter.start()
        while not self._stop.is_set():
            try:
                kind, payload = client.recv()
            except SocketClosed as closed:
                if closed.code == CLIENT_WS_CLOSE_REPLACED:
                    self._stand_aside()
                else:
                    failure = close_error(closed.code, closed.reason)
                break
            except GatewayUnreachable as error:
                if not self._stop.is_set():
                    failure = error
                break
            try:
                self._dispatch(client, kind, payload)
            except GatewayUnreachable as error:
                if not self._stop.is_set():
                    failure = error
                break
            except Exception as error:  # noqa: BLE001 - reported, never fatal
                with self._lock:
                    self._last_error = {
                        "code": "hub_reply_unreadable",
                        "params": {"detail": str(error)[:200]},
                    }
                self._log(f"could not read a frame from the hub: {error}")
        ended.set()
        self._end_socket(client)
        return failure

    def _hello(self) -> dict:
        """This client's identity card, the first frame on the socket."""
        with self._lock:
            binding = dict(self._binding)
        return {
            "type": protocol.FRAME_HELLO,
            "protocol": PROTOCOL,
            "role": CLIENT_ROLE,
            "id": binding.get("id", ""),
            "name": binding.get("name", ""),
            "software": f"{CLIENT_SOFTWARE_PREFIX}{CLIENT_VERSION}",
            "token": binding.get("token", ""),
        }

    def _take_welcome(self, client) -> dict:
        """The hub's first frame: its identity card, or the refusal.

        Args:
            client: The connected socket.

        Returns:
            The welcome.

        Raises:
            GatewayRefused: When the first frame is a refusal.
            GatewayUnreachable: When the first frame is neither, or names
                another role than the hub's.
        """
        kind, payload = client.recv()
        message = _decode(payload) if kind == "text" else None
        if message is None:
            raise GatewayUnreachable("the hub's first frame is not a welcome")
        message_type = message.get("type")
        if message_type == protocol.FRAME_REFUSED:
            raise _hello_refusal(message)
        if message_type != protocol.FRAME_WELCOME:
            raise GatewayUnreachable("the hub's first frame is not a welcome")
        if message.get("role") != CLIENT_HUB_ROLE:
            raise GatewayUnreachable("the hub's welcome names another role")
        return message

    def _note_hub(self, welcome: dict) -> None:
        """Write the hub's id and name from its welcome onto the binding."""
        hub_id = str(welcome.get("id", "") or "")
        hub_name = str(welcome.get("name", "") or "")
        with self._lock:
            binding = self._binding
            is_known = (
                binding.get("hub_id") == hub_id and binding.get("hub_name") == hub_name
            )
            binding_id = binding.get("id", "")
        if is_known or not binding_id:
            return
        try:
            enrollment.note_hub(binding_id, hub_id, hub_name)
        except OSError as error:
            self._log(f"could not record the hub's name: {error}")
            return
        with self._lock:
            self._binding["hub_id"] = hub_id
            self._binding["hub_name"] = hub_name
            self._binding_stamp = enrollment.config_stamp()

    def _report(self, client) -> None:
        """Send what is true of this machine and the hash of the state held.

        Args:
            client: The connected socket.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        with self._lock:
            state_hash = self._state_hash
        client.send_text(
            json.dumps(
                {
                    "type": protocol.FRAME_REPORT,
                    "state_hash": state_hash,
                    "machine": {
                        "hostname": self.hostname(),
                        "platform": dict(self._platform_tuple),
                    },
                }
            )
        )

    def _report_on_interval(self, client, ended: threading.Event) -> None:
        """Report every interval until the socket ends."""
        while not ended.wait(timeout=CLIENT_REPORT_INTERVAL_S):
            try:
                self._report(client)
            except GatewayUnreachable:
                return

    def _dispatch(self, client, kind: str, payload) -> None:
        """Take one frame's worth of news.

        Args:
            client: The connected socket.
            kind: ``text`` or ``binary``.
            payload: The frame's payload.

        Raises:
            TypeError: When a frame carries a field of the wrong shape.
            ValueError: When a binary frame is shorter than a stream id.
            GatewayUnreachable: When the report a state calls for cannot
                be sent.
        """
        if kind == "binary":
            stream_id, data = protocol.decode_binary(payload)
            self._log(f"dropping {len(data)} bytes the hub sent on stream {stream_id}")
            return
        message = _decode(payload)
        if message is None:
            return
        message_type = message.get("type")
        if message_type == protocol.FRAME_STATE:
            self._take_state(message)
            self._report(client)
        elif message_type == protocol.FRAME_CLOSE:
            with self._lock:
                streams = self._streams
            if streams is not None:
                streams.take_close(message)
        elif message_type == protocol.FRAME_CREDIT:
            self._log(f"dropping credit on stream {message.get('stream')}")
        elif message_type == protocol.FRAME_OPEN:
            self._refuse_open(client, message)
        else:
            self._log(f"ignoring a {message_type!r} frame from the hub")

    def _take_state(self, message: dict) -> None:
        """Replace what is held with the state the hub just sent."""
        services = message.get("services", [])
        if not isinstance(services, list):
            raise TypeError("state services is not a list")
        is_disabled = bool(message.get("is_disabled"))
        with self._lock:
            self._services_list = [
                entry for entry in services if isinstance(entry, dict)
            ]
            self._state_hash = str(message.get("hash", "") or "")
        self._take_disabled(is_disabled)
        if not is_disabled:
            self._services["ai"].refresh(entries=self.service_entries())
        self.notify()

    def _take_disabled(self, is_disabled: bool) -> None:
        """Let go of everything once when the hub switches this client off."""
        with self._lock:
            was_disabled = self._was_disabled
            self._is_disabled = is_disabled
            self._was_disabled = is_disabled
            if is_disabled:
                self._last_error = {"code": "client_disabled", "params": {}}
            elif self._last_error and self._last_error.get("code") == "client_disabled":
                self._last_error = None
        if is_disabled and not was_disabled:
            self._log("the hub switched this client off")
            self._release()

    def _refuse_open(self, client, message: dict) -> None:
        """Close a stream the hub opened: a client serves no kind."""
        stream_id = message.get("stream")
        if not isinstance(stream_id, int):
            raise TypeError("an open names its stream by an integer id")
        client.send_text(
            json.dumps(
                {
                    "type": protocol.FRAME_CLOSE,
                    "stream": stream_id,
                    "code": CLIENT_STREAM_CODE_KIND_UNKNOWN,
                    "params": {"kind": str(message.get("kind", "") or "")},
                }
            )
        )

    def _end_socket(self, client) -> None:
        """Close the socket and end every stream open on it."""
        streams = None
        with self._lock:
            if self._client is client:
                self._client = None
                streams, self._streams = self._streams, None
            self._is_welcomed = False
        client.close()
        if streams is not None:
            streams.end_all()
        self.notify()

    def _drop_socket(self) -> None:
        """End the socket from this side, when there is one."""
        with self._lock:
            client = self._client
        if client is not None:
            self._end_socket(client)

    def _stand_aside(self) -> None:
        """Another socket holds this binding: open no more until a person acts."""
        with self._lock:
            self._is_replaced = True
        self._log("another client took this binding; not reconnecting until asked")

    def _on_unreachable(self, error: Exception) -> int:
        """Back off after a broken wire."""
        with self._lock:
            self._last_error = channel_error(error)
            delay = self._backoff_s
            self._backoff_s = min(self._backoff_s * 2, CLIENT_BACKOFF_MAX_S)
        self._log(f"hub socket failed: {error}; retrying in {delay}s")
        self.notify()
        return delay

    def _on_rejected(self, error: Exception) -> int:
        """Take a refusal: the one that unbinds, or one the binding survives.

        Args:
            error: What the channel raised.

        Returns:
            Seconds until the next loop turn.
        """
        rejection = channel_error(error)
        if rejection["code"] == CLIENT_REFUSAL_CODE_BINDING_UNKNOWN:
            return self._unbind(rejection)
        with self._lock:
            self._last_error = rejection
        self._log(f"{error}; asking again in {CLIENT_BACKOFF_MAX_S}s")
        self.notify()
        return CLIENT_BACKOFF_MAX_S

    def _unbind(self, rejection: dict) -> int:
        """Let the binding go: the hub holds no such binding any more."""
        with self._lock:
            binding_id = self._binding.get("id", "")
        enrollment.remove_binding(binding_id)
        self._release()
        self._reset_binding_state()
        self._load_connection()
        with self._lock:
            self._last_error = rejection
        self._log("unbound: the hub no longer knows this client")
        self.notify()
        return CLIENT_IDLE_POLL_INTERVAL_S

    def _clear_leftovers(self) -> None:
        """Undo what a run that did not end cleanly left on this machine."""
        for service_type in ("ai", "file"):
            try:
                self._services[service_type].clear_leftovers()
            except Exception as error:  # noqa: BLE001 - reported, never fatal
                self._log(f"{service_type}: could not clear what was left: {error}")

    def _release(self) -> None:
        """Undo everything the handlers hold, in the shutdown order."""
        for service_type, _name, _word in SHUTDOWN_STEPS:
            try:
                self._services[service_type].release()
            except Exception as error:  # noqa: BLE001 - the rest must still run
                self._log(f"{service_type}: could not release: {error}")

    def _release_in_time(self) -> None:
        """Release every handler in order, none of them holding up the rest."""
        deadline = time.monotonic() + CLIENT_SHUTDOWN_DEADLINE_S
        for index, (service_type, name, word) in enumerate(SHUTDOWN_STEPS):
            left = max(deadline - time.monotonic(), 0)
            share = left / (len(SHUTDOWN_STEPS) - index)
            outcome: dict = {}
            step = threading.Thread(
                target=self._release_one,
                args=(service_type, outcome),
                name=f"client_release_{service_type}",
                daemon=True,
            )
            step.start()
            step.join(timeout=share)
            if step.is_alive():
                self._log(f"{name}: gave up after {share:.1f}s")
            elif "error" in outcome:
                self._log(f"{name}: could not release: {outcome['error']}")
            else:
                count = outcome.get("count") or 0
                self._log(f"{name}: " + word.format(count=count))

    def _release_one(self, service_type: str, outcome: dict) -> None:
        """Run one handler's release, its count or its failure in ``outcome``.

        Args:
            service_type: The handler to release.
            outcome: Filled with ``count`` or with ``error``.
        """
        try:
            outcome["count"] = self._services[service_type].release()
        except Exception as error:  # noqa: BLE001 - the rest must still run
            outcome["error"] = error

    def _reset_binding_state(self) -> None:
        with self._lock:
            self._last_error = None
            self._is_replaced = False
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            self._services_list = []
            self._state_hash = ""
            self._hub_software = ""
            self._is_disabled = False
            self._was_disabled = False

    def _load_connection(self) -> None:
        """Take the first binding on disk, or none."""
        bindings = enrollment.bindings()
        with self._lock:
            self._binding = dict(bindings[0]) if bindings else {}
            self._binding_stamp = enrollment.config_stamp()

    def _adopt_external_binding(self) -> None:
        """Pick up a binding another process wrote.

        ``nclient connect`` and ``nclient disconnect`` edit the configuration
        from their own process; the resident notices the file changing and
        converges without a restart.
        """
        with self._lock:
            if enrollment.config_stamp() == self._binding_stamp:
                return
            binding = self._binding
        self._load_connection()
        with self._lock:
            if self._binding == binding:
                return
        self._drop_socket()
        self._release()
        self._reset_binding_state()
        self._log("adopted the binding written on disk")
