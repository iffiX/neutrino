"""One hub's session: a binding, its socket, and the reconnect that holds it.

A session belongs to one binding and speaks to one hub. It holds the socket
open and reconnects when it drops; the hub pushes its ``state``, the
services it publishes and whether this client is switched off, and the
session answers each state and every interval with a ``report``. What a
service handler needs from the hub comes down a ``service`` stream the
session opens on request. The resident owns the handlers and the store; the
session tells it what changed through its callbacks and never touches them.

A ``refused`` frame ends the socket whenever it arrives, and says the same
as one that arrives instead of the welcome: its code decides what becomes
of the binding.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import threading
import urllib.parse

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_BACKOFF_MAX_S,
    CLIENT_BACKOFF_MIN_S,
    CLIENT_CHANNEL_WS_PATH,
    CLIENT_CONNECT_TIMEOUT_S,
    CLIENT_HUB_ROLE,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_PROTOCOL_REFUSAL_CODES,
    CLIENT_REFUSAL_CODE_BINDING_UNKNOWN,
    CLIENT_REPORT_INTERVAL_S,
    CLIENT_ROLE,
    CLIENT_SOFTWARE_PREFIX,
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

# How the three connection states of a session are named to every surface.
CONNECTION_CONNECTED = "connected"
CONNECTION_RECONNECTING = "reconnecting"
CONNECTION_REPLACED = "replaced"

# How long a stop waits for the loop thread to come back.
STOP_JOIN_TIMEOUT_S = 5


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


def _refusal(message: dict) -> Exception:
    """What a refused frame means: the hub turned this binding away.

    Args:
        message: The frame, wherever on the socket it arrived.

    Returns:
        The channel error its code maps to.
    """
    code = str(message.get("code", "") or "")
    params = message.get("params")
    params = params if isinstance(params, dict) else {}
    if code in CLIENT_PROTOCOL_REFUSAL_CODES:
        return refusal_error(code, params)
    return GatewayRefused(f"hub refused this client ({code})", code=code, params=params)


def _nobody(*_args) -> None:
    """Nobody listening."""


class ClientHubSession:
    """One binding's socket to its hub, reconnecting until stopped."""

    def __init__(
        self,
        *,
        binding: dict,
        hostname: str,
        platform_tuple: dict,
        log=print,
        on_change=None,
        on_services=None,
        on_disabled=None,
        on_unbound=None,
    ):
        """
        Args:
            binding: The binding this session speaks for.
            hostname: This machine's hostname, sent in every report.
            platform_tuple: This machine's platform tuple, sent in every
                report.
            log: Callable used for progress messages.
            on_change: Called with no arguments after every change of what
                a page draws; None for nobody listening.
            on_services: Called with this session after a state replaced
                the services held, while the hub has not switched this
                client off; None for nobody listening.
            on_disabled: Called with this session once when the hub
                switches this client off; None for nobody listening.
            on_unbound: Called with this session when the hub says it holds
                no such binding; None for nobody listening.
        """
        self._log = log
        self._lock = threading.Lock()
        self._binding = dict(binding)
        self._hostname = hostname
        self._platform_tuple = dict(platform_tuple)
        self._on_change = on_change if on_change is not None else _nobody
        self._on_services = on_services if on_services is not None else _nobody
        self._on_disabled = on_disabled if on_disabled is not None else _nobody
        self._on_unbound = on_unbound if on_unbound is not None else _nobody
        # Set whenever the loop should stop waiting: a person asked for a
        # connection now, or the session is stopping.
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._client: "WebSocketClient | None" = None
        self._streams: "ClientStreamRegistry | None" = None
        self._is_welcomed = False
        self._backoff_s = CLIENT_BACKOFF_MIN_S
        # Set while another socket holds this binding; only a person clears it.
        self._is_replaced = False
        self._is_unbound = False
        self._last_error: "dict | None" = None
        self._services_list: list = []
        self._state_hash = ""
        self._hub_software = ""
        self._is_disabled = False
        self._was_disabled = False

    # --- what the resident reads ---

    @property
    def binding_id(self) -> str:
        """The binding's id, the same for the life of the session."""
        return self._binding.get("id", "")

    def binding(self) -> dict:
        """The binding this session speaks for, as it stands now."""
        with self._lock:
            return dict(self._binding)

    def hub_id(self) -> str:
        """The hub's id, as its welcome named it; empty before the first."""
        with self._lock:
            return self._binding.get("hub_id", "")

    def hub_name(self) -> str:
        """The hub's name, as its welcome named it; empty before the first."""
        with self._lock:
            return self._binding.get("hub_name", "")

    def gateway_url(self) -> str:
        """The hub's address on its agent port."""
        with self._lock:
            return self._binding.get("gateway_url", "")

    def hub_software(self) -> str:
        """What the hub's welcome named as its software, empty before one."""
        with self._lock:
            return self._hub_software

    def connection_state(self) -> str:
        """Where the socket stands, one of the three ``CONNECTION_*`` states."""
        with self._lock:
            if self._is_replaced:
                return CONNECTION_REPLACED
            return (
                CONNECTION_CONNECTED if self._is_welcomed else CONNECTION_RECONNECTING
            )

    def is_disabled(self) -> bool:
        """Whether the hub has switched this client off."""
        with self._lock:
            return self._is_disabled

    def last_error(self) -> "dict | None":
        """The most recent problem worth showing, as ``{"code", "params"}``."""
        with self._lock:
            return dict(self._last_error) if self._last_error else None

    def service_entries(self) -> list:
        """The typed service list the hub last sent, while its socket is up.

        Returns:
            The entries; empty while the socket is down, so a hub that is
            unreachable publishes nothing.
        """
        with self._lock:
            if not self._is_welcomed:
                return []
            return [entry for entry in self._services_list if isinstance(entry, dict)]

    # --- what the resident does ---

    def reconnect_soon(self) -> None:
        """Cut the wait before the next connection attempt short."""
        self._news.set()

    def reconnect(self) -> None:
        """Take the binding back from the socket that replaced it, and connect now."""
        with self._lock:
            self._is_replaced = False
        self._news.set()
        self._on_change()

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
                raise GatewayUnreachable("this hub is not connected")
        stream = streams.open(CLIENT_STREAM_KIND_SERVICE, {"id": entry_id})
        return stream.wait_close(timeout_s)

    # --- the loop ---

    def start(self) -> None:
        """Run the loop on a thread of its own."""
        self._thread = threading.Thread(
            target=self.run_forever, name=f"hub_session_{self.binding_id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Close the socket and end the loop. Idempotent."""
        self._stop.set()
        self._news.set()
        self._drop_socket()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=STOP_JOIN_TIMEOUT_S)

    def run_forever(self) -> None:
        """Hold the socket until the session is stopped."""
        while not self._stop.is_set():
            # Cleared before the turn, so news that lands during it, the
            # stop included, is still standing when the wait begins.
            self._news.clear()
            delay = self.run_once()
            self._news.wait(timeout=delay)

    def run_once(self) -> int:
        """One connection's lifetime, or one idle turn.

        Returns:
            How many seconds to wait before the next one: the shortest delay
            after a clean close, a backing-off delay after a broken wire, a
            minute after a refusal the binding survives, and a short idle
            wait while another socket holds the binding or the hub has
            forgotten it.
        """
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

    def _open_client(self) -> "WebSocketClient | None":
        """A socket for the binding, or None while replaced or unbound."""
        with self._lock:
            binding = dict(self._binding)
            is_idle = self._is_replaced or self._is_unbound
        if is_idle:
            return None
        parts = urllib.parse.urlsplit(binding["gateway_url"])
        return WebSocketClient(
            host=parts.hostname or "",
            port=parts.port or 443,
            path=CLIENT_CHANNEL_WS_PATH,
            fingerprint=binding["fingerprint"],
            timeout_s=CLIENT_CONNECT_TIMEOUT_S,
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
            # A hub whose state hash the report matches pushes no state; what
            # it published last is published again once the socket is up.
            has_services = bool(self._services_list) and not self._is_disabled
        if has_services:
            self._on_services(self)
        self._on_change()

    def _serve(self, client) -> "Exception | None":
        """Read frames until the socket ends, reporting on the interval.

        Args:
            client: The connected socket.

        Returns:
            What ended it: the refusal a ``refused`` frame carried, the
            error a close or a broken wire maps to, or None when a stop, a
            close from here, or another socket replacing this one did.
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
            except GatewayRefused as refused:
                failure = refused
                break
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
            raise _refusal(message)
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
                        "hostname": self._hostname,
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
            GatewayRefused: When the frame is a refusal; the protocol
                refusals are their own kind.
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
        elif message_type == protocol.FRAME_REFUSED:
            # The close 4000 behind it is never read: the socket ends here.
            raise _refusal(message)
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
            self._on_services(self)
        self._on_change()

    def _take_disabled(self, is_disabled: bool) -> None:
        """Tell the resident once when the hub switches this client off."""
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
            self._on_disabled(self)

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
        self._on_change()

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
        self._on_change()
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
        self._on_change()
        return CLIENT_BACKOFF_MAX_S

    def _unbind(self, rejection: dict) -> int:
        """Hand the binding back: the hub holds no such binding any more."""
        with self._lock:
            self._is_unbound = True
            self._last_error = rejection
        self._log("unbound: the hub no longer knows this client")
        self._on_unbound(self)
        return CLIENT_IDLE_POLL_INTERVAL_S
