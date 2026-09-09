"""The resident itself: the binding, the poll loop, and the service handlers.

One object owns everything the person's page and the hub both talk to. It
runs whether or not the person belongs to a hub yet: an unbound resident
still serves its page, waiting for a link.

The hub publishes the service catalog and this person's AI credential; every
choice about what to do with them is made here, one typed handler per
service type. Errors are ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import socket
import threading

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_BACKOFF_MAX_S,
    CLIENT_BACKOFF_MIN_S,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_LEAVE_PATH,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
    CLIENT_POLL_INTERVAL_S,
    CLIENT_POLL_PATH,
    CLIENT_REFUSALS_BEFORE_UNBIND,
    CLIENT_STATE_FILE_NAME,
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
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.file import FileServiceHandler
from neutrino_client.services.port import PortServiceHandler
from neutrino_client.services.rdp import RdpViewerHandler
from neutrino_client.services.store import ClientServiceStore
from neutrino_client.services.web import WebServiceHandler


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
                RdpViewerHandler(platform=self.platform, post=self.post, log=log),
            )
        }
        # Set whenever there is something new to do, so the loop polls then
        # rather than at the end of its next interval.
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._is_shut_down = False
        self._channel = None
        self._binding: tuple = ("", "", "")
        self._binding_stamp = 0
        self._backoff_s = CLIENT_BACKOFF_MIN_S
        self._refusals = 0
        self._last_error: "dict | None" = None
        self._services_list: list = []
        self._catalog_hash = ""
        self._hub_version = ""
        self._is_disabled = False
        self._credential: dict = {}
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
            return self._channel is not None

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
        self.poll_soon()

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
        self._release()
        self._reset_binding_state()
        self._load_connection()
        self._log("left the hub")

    def poll_soon(self) -> None:
        """Cut the wait before the next poll short."""
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

    def post(self, path: str, payload: dict) -> dict:
        """Post to the hub over the pinned channel.

        Args:
            path: The hub path.
            payload: The body; the token is added.

        Returns:
            The hub's reply.

        Raises:
            GatewayUnreachable: When this person belongs to no hub, or the
                channel's own exceptions otherwise.
        """
        with self._lock:
            channel = self._channel
        if channel is None:
            raise GatewayUnreachable("this person belongs to no hub")
        return channel.post(path, payload)

    # --- the loop ---

    def start(self) -> None:
        """Start the handlers' reconciles and the poll loop on a thread."""
        for handler in self._services.values():
            handler.start()
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def run_forever(self) -> None:
        """Poll, or wait to be enrolled, until the resident is shut down."""
        self._log(f"neutrino_client {CLIENT_VERSION} starting on {self.hostname()}")
        while not self._stop.is_set():
            delay = self.run_once()
            self._news.clear()
            self._news.wait(timeout=delay)

    def run_once(self) -> int:
        """Do one poll's worth of work.

        Returns:
            How many seconds to wait before the next one: the normal
            interval after a success, a backing-off delay after a failure,
            and a short idle poll while the person belongs to no hub.
        """
        self._adopt_external_binding()
        with self._lock:
            channel = self._channel
            catalog_hash = self._catalog_hash
        if channel is None:
            return CLIENT_IDLE_POLL_INTERVAL_S
        payload = {
            "hostname": self.hostname(),
            "platform": self._platform_tuple,
            "client_version": CLIENT_VERSION,
            "catalog_hash": catalog_hash,
        }
        try:
            reply = channel.post(CLIENT_POLL_PATH, payload)
        except (GatewayRefused, GatewayUntrusted, GatewayVersionRefused) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            with self._lock:
                self._last_error = channel_error(error)
                delay = self._backoff_s
                self._backoff_s = min(self._backoff_s * 2, CLIENT_BACKOFF_MAX_S)
            self._log(f"poll failed: {error}; retrying in {delay}s")
            return delay
        with self._lock:
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            self._last_error = None
            self._refusals = 0
        try:
            self._apply_reply(reply)
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            with self._lock:
                self._last_error = {
                    "code": "hub_reply_unreadable",
                    "params": {"detail": str(error)[:200]},
                }
            self._log(f"could not apply the hub's reply: {error}")
        return CLIENT_POLL_INTERVAL_S

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
        self._release()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=CLIENT_POLL_INTERVAL_S)
        self._log("shut down")

    def _apply_reply(self, reply: dict) -> None:
        """Take one poll reply's worth of news.

        Args:
            reply: ``{hub_version, is_disabled, catalog_hash, catalog, ai}``.
        """
        is_disabled = bool(reply.get("is_disabled"))
        catalog = reply.get("catalog")
        if catalog is not None and not isinstance(catalog, dict):
            raise TypeError(f"catalog is {type(catalog).__name__}, not an object")
        credential = reply.get("ai")
        with self._lock:
            was_disabled = self._is_disabled
            self._is_disabled = is_disabled
            self._hub_version = str(reply.get("hub_version", ""))
            if catalog is not None:
                services = catalog.get("services") or []
                if not isinstance(services, list):
                    raise TypeError("catalog services is not a list")
                self._services_list = [
                    entry for entry in services if isinstance(entry, dict)
                ]
                self._catalog_hash = str(reply.get("catalog_hash", ""))
            self._credential = dict(credential) if isinstance(credential, dict) else {}
            if is_disabled:
                self._last_error = {"code": "client_disabled", "params": {}}
        if is_disabled:
            if not was_disabled:
                self._log("the hub switched this client off")
                self._release()
            return
        self._services["ai"].update_credential(self._credential)

    def _on_rejected(self, error: Exception) -> int:
        """Take a definitive rejection for what it is, after a short grace.

        Args:
            error: What the channel raised.

        Returns:
            Seconds until the next loop turn.
        """
        rejection = channel_error(error)
        with self._lock:
            self._refusals += 1
            rejections = self._refusals
            self._last_error = rejection
        if rejections < CLIENT_REFUSALS_BEFORE_UNBIND:
            self._log(f"{error}; asking again")
            return CLIENT_POLL_INTERVAL_S
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
            self._is_disabled = False
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
        self._release()
        self._reset_binding_state()
        self._log("adopted the binding written on disk")
