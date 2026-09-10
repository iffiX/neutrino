"""The resident itself: the binding, the socket to the hub, and the services.

One object owns everything the person's page and the hub both talk to. It
runs whether or not the person belongs to a hub yet: an unbound resident
still serves its page, waiting for a link.

While bound, the resident holds one socket open to the hub and reconnects
when it drops. The hub pushes what it publishes — the catalog, this person's
AI credential, whether the client is switched off — and answers the asks a
service handler sends up. Joining and leaving stay HTTP: both happen when
there is no socket to carry them.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import urllib.parse

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_ASK_TIMEOUT_S,
    CLIENT_BACKOFF_MAX_S,
    CLIENT_BACKOFF_MIN_S,
    CLIENT_HELLO_TIMEOUT_S,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_LEAVE_PATH,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
    CLIENT_REFUSALS_BEFORE_UNBIND,
    CLIENT_STATE_FILE_NAME,
    CLIENT_WS_CLOSE_REPLACED,
    CLIENT_WS_PATH,
)
from neutrino_client.core import enrollment
from neutrino_client.core.channel import (
    GatewayHttpChannel,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
)
from neutrino_client.core.ws_client import SocketClosed, WebSocketClient, close_error
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.file import FileServiceHandler
from neutrino_client.services.port import PortServiceHandler
from neutrino_client.services.rdp import RdpViewerHandler
from neutrino_client.services.store import ClientServiceStore
from neutrino_client.services.web import WebServiceHandler

# How the three connection states are named to every surface.
CONNECTION_CONNECTED = "connected"
CONNECTION_RECONNECTING = "reconnecting"
CONNECTION_UNBOUND = "unbound"

# How long a shutdown waits for the loop thread to come back.
SHUTDOWN_JOIN_TIMEOUT_S = 5
ASK_ID_LENGTH = 8


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
    if isinstance(error, GatewayVersionRefused):
        return {
            "code": "client_newer_than_hub",
            "params": {
                "hub_version": error.hub_version,
                "client_version": error.client_version,
            },
        }
    if isinstance(error, GatewayRefused):
        return {"code": "hub_refused", "params": {}}
    return {"code": "hub_unreachable", "params": {"detail": str(error)}}


def _decode(kind: str, payload) -> "dict | None":
    """One text frame as an object, or None for anything else.

    Args:
        kind: ``text`` or ``binary``.
        payload: The frame's payload.

    Returns:
        The decoded object, or None when the frame is not one.
    """
    if kind != "text":
        return None
    try:
        message = json.loads(payload)
    except (TypeError, ValueError):
        return None
    return message if isinstance(message, dict) else None


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
        self._services = {
            handler.service_type: handler
            for handler in (
                WebServiceHandler(platform=self.platform),
                PortServiceHandler(log=log),
                AiServiceHandler(store=self._store, log=log),
                FileServiceHandler(
                    platform=self.platform,
                    store=self._store,
                    credentials_dir=os.path.join(
                        config_dir, CLIENT_MOUNT_CREDENTIALS_DIR_NAME
                    ),
                    log=log,
                ),
                RdpViewerHandler(platform=self.platform, ask=self.ask, log=log),
            )
        }
        # Set whenever the loop should stop waiting: a binding was written, or
        # the resident is shutting down.
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._is_shut_down = False
        self._channel = None
        self._client: "WebSocketClient | None" = None
        self._is_welcomed = False
        self._binding: tuple = ("", "", "")
        self._binding_stamp = 0
        self._backoff_s = CLIENT_BACKOFF_MIN_S
        self._refusals = 0
        self._last_error: "dict | None" = None
        self._services_list: list = []
        self._catalog_hash = ""
        self._hub_version = ""
        self._client_id = ""
        self._is_disabled = False
        self._was_disabled = False
        self._credential: dict = {}
        # One entry per ask still waiting for its answer.
        self._pending: dict = {}
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
            return bool(self._binding[0] and self._binding[1])

    def connection_state(self) -> str:
        """Where the hub socket stands: connected, reconnecting or unbound."""
        with self._lock:
            if not (self._binding[0] and self._binding[1]):
                return CONNECTION_UNBOUND
            return (
                CONNECTION_CONNECTED if self._is_welcomed else CONNECTION_RECONNECTING
            )

    def gateway_url(self) -> str:
        """The hub this person belongs to, empty when none."""
        with self._lock:
            return self._binding[0]

    def hub_version(self) -> str:
        """What the hub last reported itself as."""
        with self._lock:
            return self._hub_version

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

    def ai_credential(self) -> dict:
        """This person's gateway credential, as the hub last granted it."""
        with self._lock:
            return dict(self._credential)

    def suggest_mount_location(self) -> str:
        """What the platform offers as a mount location before one is typed."""
        return self.platform.suggest_mount_location()

    def mount_location_shape(self) -> str:
        """What a mount location is here: ``path`` or ``drive_letter``."""
        return self.platform.mount_location_shape

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

    def disconnect(self) -> None:
        """Leave the hub and let go of everything it published.

        The hub is told first; one that cannot be reached does not hold the
        person here.
        """
        with self._lock:
            channel = self._channel
        if channel is not None:
            try:
                channel.post(CLIENT_LEAVE_PATH, {})
            except (GatewayUnreachable, GatewayUntrusted) as error:
                self._log(f"could not tell the hub we are leaving: {error}")
        enrollment.disconnect()
        self._drop_socket()
        self._release()
        self._reset_binding_state()
        self._load_connection()
        self._log("left the hub")

    def reconnect_soon(self) -> None:
        """Cut the wait before the next connection attempt short."""
        self._news.set()

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

    def ask(self, kind: str, args: dict, timeout_s: float = CLIENT_ASK_TIMEOUT_S):
        """Ask the hub one question over the socket and wait for its answer.

        Args:
            kind: What is being asked, e.g. ``rdp_connect``.
            args: The ask's own fields.
            timeout_s: How long to wait for the answer.

        Returns:
            The answer's ``result``.

        Raises:
            GatewayRefusedDetail: When the hub answered with a code.
            GatewayUnreachable: When there is no socket, the socket dies, or
                no answer arrives in time.
        """
        ask_id = secrets.token_hex(ASK_ID_LENGTH)
        arrived = threading.Event()
        with self._lock:
            client = self._client
            if client is None or not self._is_welcomed:
                raise GatewayUnreachable("this person's hub is not connected")
            self._pending[ask_id] = {"event": arrived, "answer": None}
        try:
            client.send_text(
                json.dumps(
                    {"type": "ask", "id": ask_id, "kind": kind, "args": dict(args)}
                )
            )
            if not arrived.wait(timeout=timeout_s):
                raise GatewayUnreachable(f"the hub did not answer {kind} in time")
            with self._lock:
                answer = self._pending[ask_id]["answer"]
        finally:
            with self._lock:
                self._pending.pop(ask_id, None)
        if answer is None:
            raise GatewayUnreachable("the hub socket closed before it answered")
        code = str(answer.get("code", "") or "")
        if code:
            params = answer.get("params")
            raise GatewayRefusedDetail(
                code=code, params=params if isinstance(params, dict) else {}
            )
        result = answer.get("result")
        return dict(result) if isinstance(result, dict) else {}

    # --- the loop ---

    def start(self) -> None:
        """Start the handlers' reconciles and the connection loop on a thread."""
        for handler in self._services.values():
            handler.start()
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def run_forever(self) -> None:
        """Hold the socket, or wait to be enrolled, until the resident stops."""
        self._log(f"neutrino_client {CLIENT_VERSION} starting on {self.hostname()}")
        while not self._stop.is_set():
            delay = self.run_once()
            self._news.clear()
            self._news.wait(timeout=delay)

    def run_once(self) -> int:
        """One connection's lifetime, or one idle turn while unbound.

        Returns:
            How many seconds to wait before the next one: the shortest delay
            after a clean close, a backing-off delay after a broken wire, and
            a short idle wait while the person belongs to no hub.
        """
        self._adopt_external_binding()
        client = self._open_client()
        if client is None:
            return CLIENT_IDLE_POLL_INTERVAL_S
        try:
            self._connect(client)
        except (GatewayRefused, GatewayUntrusted, GatewayVersionRefused) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            return self._on_unreachable(error)
        failure = self._serve(client)
        if failure is None:
            return CLIENT_BACKOFF_MIN_S
        if isinstance(failure, (GatewayRefused, GatewayVersionRefused)):
            return self._on_rejected(failure)
        return self._on_unreachable(failure)

    def shutdown(self) -> None:
        """Let go of everything and stop the loop. Idempotent.

        The order is the one that leaves the machine as it was found: the
        tools restored, the shares unmounted, the forwards closed, the
        viewers closed.
        """
        with self._lock:
            if self._is_shut_down:
                return
            self._is_shut_down = True
        self._stop.set()
        self._news.set()
        self._drop_socket()
        self._release()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
        self._log("shut down")

    def _open_client(self) -> "WebSocketClient | None":
        """A socket for the current binding, or None while unbound."""
        with self._lock:
            gateway_url, token, fingerprint = self._binding
        if not gateway_url or not token:
            return None
        parts = urllib.parse.urlsplit(gateway_url)
        return WebSocketClient(
            host=parts.hostname or "",
            port=parts.port or 443,
            path=CLIENT_WS_PATH,
            fingerprint=fingerprint,
            timeout_s=CLIENT_HELLO_TIMEOUT_S,
        )

    def _connect(self, client) -> None:
        """Open the socket, say hello, and take the welcome.

        Args:
            client: The unconnected socket.

        Raises:
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefused: When the hub does not know this token.
            GatewayVersionRefused: When the hub refused this client as newer.
            GatewayUnreachable: On any network error, or a first frame that
                is not a welcome.
        """
        client.connect()
        try:
            client.send_text(json.dumps(self._hello()))
            welcome = self._take_welcome(client)
        except SocketClosed as closed:
            raise close_error(closed.code, closed.reason) from closed
        except Exception:
            client.close()
            raise
        with self._lock:
            self._client = client
            self._is_welcomed = True
            self._hub_version = str(welcome.get("hub_version", "") or "")
            self._client_id = str(welcome.get("client_id", "") or "")
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            self._last_error = None
            self._refusals = 0
        self._take_disabled(bool(welcome.get("is_disabled")))

    def _serve(self, client) -> "Exception | None":
        """Read frames until the socket ends.

        Args:
            client: The connected socket.

        Returns:
            What ended it, or None when a shutdown, a close from here, or
            the hub replacing this socket did.
        """
        failure = None
        while not self._stop.is_set():
            try:
                kind, payload = client.recv()
            except SocketClosed as closed:
                if closed.code != CLIENT_WS_CLOSE_REPLACED:
                    failure = close_error(closed.code, closed.reason)
                break
            except GatewayUnreachable as error:
                failure = error
                break
            try:
                self._dispatch(kind, payload)
            except Exception as error:  # noqa: BLE001 - reported, never fatal
                with self._lock:
                    self._last_error = {
                        "code": "hub_reply_unreadable",
                        "params": {"detail": str(error)[:200]},
                    }
                self._log(f"could not read a frame from the hub: {error}")
        self._end_socket(client)
        return failure

    def _hello(self) -> dict:
        """The first frame this client sends, within the hub's own grace."""
        with self._lock:
            token = self._binding[1]
            catalog_hash = self._catalog_hash
        return {
            "type": "hello",
            "kind": "client",
            "token": token,
            "client_version": CLIENT_VERSION,
            "hostname": self.hostname(),
            "platform": dict(self._platform_tuple),
            "catalog_hash": catalog_hash,
        }

    def _take_welcome(self, client) -> dict:
        """The hub's first frame, which is a welcome or the socket is wrong."""
        kind, payload = client.recv()
        message = _decode(kind, payload)
        if message is None or message.get("type") != "welcome":
            raise GatewayUnreachable("the hub's first frame is not a welcome")
        return message

    def _dispatch(self, kind: str, payload) -> None:
        """Take one frame's worth of news.

        Args:
            kind: ``text`` or ``binary``.
            payload: The frame's payload.

        Raises:
            TypeError: When a frame carries a field of the wrong shape.
        """
        message = _decode(kind, payload)
        if message is None:
            return
        message_type = message.get("type")
        if message_type == "catalog":
            self._take_catalog(message)
        elif message_type == "ai":
            self._take_credential(message.get("credential"))
        elif message_type == "disabled":
            self._take_disabled(bool(message.get("is_disabled")))
        elif message_type == "answer":
            self._take_answer(message)
        else:
            self._log(f"ignoring a {message_type!r} frame from the hub")

    def _take_catalog(self, message: dict) -> None:
        """Replace the held catalog with the one the hub just sent."""
        services = message.get("services")
        if not isinstance(services, list):
            raise TypeError("catalog services is not a list")
        with self._lock:
            self._services_list = [
                entry for entry in services if isinstance(entry, dict)
            ]
            self._catalog_hash = str(message.get("hash", "") or "")

    def _take_credential(self, credential) -> None:
        """Take the hub's AI grant, or put the tools back when it withdraws it.

        Args:
            credential: ``{"base_url", "api_key", "model"}``, or None when
                the hub granted nothing.
        """
        is_granted = isinstance(credential, dict) and bool(credential)
        with self._lock:
            self._credential = dict(credential) if is_granted else {}
            held = dict(self._credential)
            is_disabled = self._is_disabled
        if is_disabled:
            return
        if is_granted:
            self._services["ai"].update_credential(held)
        else:
            self._services["ai"].restore()

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
            credential = dict(self._credential)
        if is_disabled:
            if not was_disabled:
                self._log("the hub switched this client off")
                self._release()
            return
        if was_disabled and credential:
            self._services["ai"].update_credential(credential)

    def _take_answer(self, message: dict) -> None:
        """Hand one answer to the ask that is waiting for it."""
        ask_id = str(message.get("id", ""))
        with self._lock:
            pending = self._pending.get(ask_id)
            if pending is None:
                return
            pending["answer"] = message
        pending["event"].set()

    def _end_socket(self, client) -> None:
        """Close the socket and wake everything waiting on it."""
        with self._lock:
            if self._client is client:
                self._client = None
            self._is_welcomed = False
            waiting = list(self._pending.values())
        client.close()
        for pending in waiting:
            pending["event"].set()

    def _drop_socket(self) -> None:
        """End the socket from this side, when there is one."""
        with self._lock:
            client = self._client
        if client is not None:
            self._end_socket(client)

    def _on_unreachable(self, error: Exception) -> int:
        """Back off after a broken wire; the rejection count stands."""
        with self._lock:
            self._last_error = channel_error(error)
            delay = self._backoff_s
            self._backoff_s = min(self._backoff_s * 2, CLIENT_BACKOFF_MAX_S)
        self._log(f"hub socket failed: {error}; retrying in {delay}s")
        return delay

    def _on_rejected(self, error: Exception) -> int:
        """Take a definitive rejection for what it is, after a short grace.

        Args:
            error: What the channel raised.

        Returns:
            Seconds until the next loop turn.
        """
        rejection = channel_error(error)
        if isinstance(error, GatewayVersionRefused):
            # A hub behind this client is not a hub that has forgotten it:
            # the binding stays, the word stays on the window, and the
            # client asks again once the hub has caught up.
            with self._lock:
                self._last_error = rejection
                self._refusals = 0
            self._log(f"{error}; asking again later")
            return CLIENT_BACKOFF_MAX_S
        with self._lock:
            self._refusals += 1
            rejections = self._refusals
            self._last_error = rejection
        if rejections < CLIENT_REFUSALS_BEFORE_UNBIND:
            self._log(f"{error}; asking again")
            return CLIENT_BACKOFF_MIN_S
        enrollment.disconnect()
        self._release()
        self._reset_binding_state()
        self._load_connection()
        with self._lock:
            self._last_error = {
                "code": "self_unbound",
                "params": {"cause": rejection["code"]},
            }
        self._log(f"unbound: {rejection['code']}")
        return CLIENT_IDLE_POLL_INTERVAL_S

    def _release(self) -> None:
        """Undo everything the handlers hold, in the shutdown order."""
        for service_type in ("ai", "file", "port", "rdp"):
            try:
                self._services[service_type].release()
            except Exception as error:  # noqa: BLE001 - the rest must still run
                self._log(f"{service_type}: could not release: {error}")

    def _reset_binding_state(self) -> None:
        with self._lock:
            self._last_error = None
            self._refusals = 0
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            self._services_list = []
            self._catalog_hash = ""
            self._hub_version = ""
            self._client_id = ""
            self._is_disabled = False
            self._was_disabled = False
            self._credential = {}

    def _load_connection(self) -> None:
        config = enrollment.load_config()
        gateway_url = config.get("gateway_url", "")
        token = config.get("token", "")
        fingerprint = config.get("fingerprint", "")
        with self._lock:
            self._binding = (gateway_url, token, fingerprint)
            self._binding_stamp = enrollment.config_stamp()
            if gateway_url and token:
                self._channel = GatewayHttpChannel(
                    gateway_url=gateway_url, token=token, fingerprint=fingerprint
                )
            else:
                self._channel = None

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
