"""The resident: every binding, one session per binding, and the services.

One object is what the window, the control socket and the command line
face. It runs whether or not the person belongs to a hub yet: an unbound
resident still serves its page, waiting for a link. For every binding on
disk it holds one :class:`~neutrino_client.core.session.ClientHubSession`,
and it owns the five service handlers, the store and the choice of exit
hub, so a service is addressed by hub and id together and a hub that goes
away takes only its own entries with it.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import socket
import sys
import threading
import time

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_DEFAULT_THEME,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
    CLIENT_ORIGINAL_DIR_NAME,
    CLIENT_SHUTDOWN_DEADLINE_S,
    CLIENT_STATE_FILE_NAME,
    CLIENT_STREAM_TIMEOUT_S,
)
from neutrino_client.core import enrollment
from neutrino_client.core.session import CONNECTION_CONNECTED, ClientHubSession
from neutrino_client.exceptions import (
    GatewayRefused,
    GatewayUnreachable,
    GatewayUntrusted,
)
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.file import FileServiceHandler
from neutrino_client.services.port import PortServiceHandler
from neutrino_client.services.rdp import RdpViewerHandler
from neutrino_client.services.store import ClientServiceStore
from neutrino_client.services.web import WebServiceHandler

# How long a shutdown waits for the watch thread to come back.
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
# The fields of a binding that make it another hub, or another join: a
# session outlives a change to any other field, the addresses included,
# which the session itself writes.
BINDING_IDENTITY_KEYS = ("id", "fingerprint", "token")


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


def is_same_join(one: dict, other: dict) -> bool:
    """Whether two binding records are the same join of the same hub.

    Args:
        one: A binding record.
        other: Another binding record.

    Returns:
        True when every field in ``BINDING_IDENTITY_KEYS`` agrees.
    """
    return all(one.get(key) == other.get(key) for key in BINDING_IDENTITY_KEYS)


class ClientResident:
    """Everything the person's surfaces face, over every hub joined."""

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
        self._is_pending_announcement = False
        self._services = {
            handler.service_type: handler
            for handler in (
                WebServiceHandler(platform=self.platform),
                PortServiceHandler(log=log, on_change=self.notify),
                AiServiceHandler(
                    store=self._store,
                    original_dir=os.path.join(config_dir, CLIENT_ORIGINAL_DIR_NAME),
                    open_service=self.open_service,
                    exit_hub_id=self.exit_hub_id,
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
        # One session per binding, by binding id, in the order joined.
        self._sessions: dict = {}
        # The binding file's stamp as last read; None before the first read.
        self._binding_stamp: "int | None" = None
        self._chosen_exit_hub_id = ""
        # Set whenever the watch loop should look at the binding file now,
        # or stop waiting because the resident is shutting down.
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._is_started = False
        self._is_shut_down = False
        self.on_show = None
        self._reconcile_bindings(enrollment.config_stamp())

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
        """Whether this person belongs to at least one hub."""
        with self._lock:
            return bool(self._sessions)

    def exit_hub_id(self) -> str:
        """The hub whose AI gateway this person's tools point at.

        Returns:
            The chosen hub's id when it names a hub joined, otherwise the
            first hub joined, empty while none has answered. The choice
            follows a removed exit to that hub and is pinned there.
        """
        with self._lock:
            chosen = self._chosen_exit_hub_id
            sessions = list(self._sessions.values())
        hub_ids = [session.hub_id() for session in sessions]
        if chosen and chosen in hub_ids:
            return chosen
        return hub_ids[0] if hub_ids else ""

    def hubs(self) -> list:
        """One row per hub joined, in the order joined.

        Returns:
            ``[{hub_id, hub_name, hub_software, binding_id, name,
            gateway_url, connection_state, is_disabled, is_exit,
            last_error}]``; no token is in it.
        """
        exit_hub_id = self.exit_hub_id()
        with self._lock:
            sessions = list(self._sessions.values())
        rows = []
        for session in sessions:
            binding = session.binding()
            hub_id = binding.get("hub_id", "")
            rows.append(
                {
                    "hub_id": hub_id,
                    "hub_name": binding.get("hub_name", ""),
                    "hub_software": session.hub_software(),
                    "binding_id": binding.get("id", ""),
                    "name": binding.get("name", ""),
                    "gateway_url": binding.get("gateway_url", ""),
                    "connection_state": session.connection_state(),
                    "is_disabled": session.is_disabled(),
                    "is_exit": bool(hub_id) and hub_id == exit_hub_id,
                    "last_error": session.last_error(),
                }
            )
        return rows

    def service_entries(self) -> list:
        """The typed service lists of every connected hub, merged.

        Returns:
            The entries in hub order, each stamped with its ``hub_id``.
        """
        with self._lock:
            sessions = list(self._sessions.values())
        merged = []
        for session in sessions:
            hub_id = session.hub_id()
            merged.extend(
                dict(entry, hub_id=hub_id) for entry in session.service_entries()
            )
        return merged

    def service_states(self) -> dict:
        """Every service type's state, merged for the page payload."""
        merged = {}
        for handler in self._services.values():
            merged.update(handler.state())
        return merged

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
            watcher: Called with no arguments, on a thread of the resident's.
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
        self._reconcile_bindings(enrollment.config_stamp())
        self._log("joined the hub")
        self.notify()

    def disconnect(self, hub_id: str = "") -> None:
        """Leave one hub and let go of everything it published.

        The hub is told first; one that cannot be reached does not hold the
        person there.

        Args:
            hub_id: The hub to leave, by its id or by its binding's id;
                empty names the one hub joined.

        Raises:
            KeyError: If ``hub_id`` names no hub this person has joined, or
                is empty while several are.
        """
        session = self._session_for(hub_id)
        binding = session.binding()
        try:
            enrollment.leave(binding)
        except (GatewayRefused, GatewayUnreachable, GatewayUntrusted) as error:
            self._log(f"could not tell the hub we are leaving: {error}")
        enrollment.remove_binding(binding["id"])
        self._forget_session(session)
        self._follow_exit()
        self._log("left the hub")

    def set_exit(self, hub_id: str) -> dict:
        """Choose the hub whose AI gateway the tools point at, and point them.

        The choice is written to the binding file; the AI handler follows it
        in one activation at the new hub's ``ai`` entry.

        Args:
            hub_id: The hub, by its id or by its binding's id.

        Returns:
            Empty on success; ``unknown_hub`` when this person has not joined
            that hub, ``no_exit_hub`` while its socket is not up.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        if session.connection_state() != CONNECTION_CONNECTED:
            return {"code": "no_exit_hub", "params": {"hub_id": hub_id}}
        self._pin_exit(session.hub_id())
        self._services["ai"].refresh(entries=self.service_entries())
        self.notify()
        return {}

    def reconnect(self, hub_id: str = "") -> None:
        """Take one binding back from the socket that replaced it, and connect now.

        Args:
            hub_id: The hub to connect to, by its id or by its binding's
                id; empty names the one hub joined.

        Raises:
            KeyError: If ``hub_id`` names no hub this person has joined, or
                is empty while several are.
        """
        self._session_for(hub_id).reconnect()

    def request_show(self) -> None:
        """Ask the window to come to the front, when one is listening."""
        callback = self.on_show
        if callback is not None:
            callback()

    def service_action(self, service_type: str, body: dict) -> dict:
        """Hand one page action to the handler for its service type.

        Args:
            service_type: The type the page acted on.
            body: The action's own fields; ``hub_id`` names the hub, and an
                action naming none is the exit hub's, where the AI apply
                lands.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal;
            ``client_disabled`` while that hub has this client switched off.
        """
        handler = self._services.get(service_type)
        if handler is None:
            return {"code": "unknown_request", "params": {}}
        hub_id = str(body.get("hub_id", "") or "") or self.exit_hub_id()
        session = self._find_session(hub_id)
        if session is not None and session.is_disabled():
            return {"code": "client_disabled", "params": {}}
        return handler.act(entries=self.service_entries(), body=body)

    def open_service(
        self, hub_id: str, entry_id: str, timeout_s: float = CLIENT_STREAM_TIMEOUT_S
    ) -> dict:
        """Open a ``service`` stream for one entry on its hub and take the close.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The published entry's id.
            timeout_s: How long to wait for the close.

        Returns:
            The close's ``params``: the entry's material.

        Raises:
            GatewayRefusedDetail: When the hub closed the stream with a code.
            GatewayUnreachable: When this person has not joined that hub,
                its socket is down or ends, or the close does not arrive in
                time.
        """
        session = self._find_session(hub_id)
        if session is None:
            raise GatewayUnreachable("this person has not joined that hub")
        return session.open_service(entry_id, timeout_s)

    # --- the loop ---

    def start(self) -> None:
        """Clear what an unclean exit left, then run the handlers and the sessions.

        Nothing this person had on is turned on again: the client opens with
        every service off, and the leftovers of a run that did not shut down
        are undone before any hub's first state arrives.
        """
        self._clear_leftovers()
        for handler in self._services.values():
            handler.start()
        with self._lock:
            self._is_started = True
            sessions = list(self._sessions.values())
        for session in sessions:
            session.start()
        thread = threading.Thread(target=self.run_forever, daemon=True)
        thread.start()
        self._thread = thread

    def run_forever(self) -> None:
        """Watch the binding file until the resident stops."""
        self._log(f"neutrino_client {CLIENT_VERSION} starting on {self.hostname()}")
        while not self._stop.is_set():
            # Cleared before the turn, so news that lands during it, the
            # stop included, is still standing when the wait begins.
            self._news.clear()
            try:
                self._adopt_external_binding()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(f"could not read the bindings: {error}")
            self._news.wait(timeout=CLIENT_IDLE_POLL_INTERVAL_S)

    def shutdown(self) -> None:
        """Let go of everything and stop every loop. Idempotent.

        The order is the one that leaves the machine as it was found: the
        sockets closed, the tools restored, the shares unmounted, the
        forwards closed, the viewers closed. The four share
        ``CLIENT_SHUTDOWN_DEADLINE_S``; a step past its part of what is left
        is given up and the next runs.
        """
        with self._lock:
            if self._is_shut_down:
                return
            self._is_shut_down = True
            sessions = list(self._sessions.values())
        self._stop.set()
        self._news.set()
        for session in sessions:
            session.stop()
        self._release_in_time()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
        self._log("shut down")

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

    def _find_session(self, needle: str) -> "ClientHubSession | None":
        """The session of one hub, by hub id or binding id; None for nobody."""
        if not needle:
            return None
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if needle in (session.hub_id(), session.binding_id):
                return session
        return None

    def _session_for(self, needle: str) -> ClientHubSession:
        """The session a page named, or the one held when it named none.

        Args:
            needle: A hub id, a binding id, or empty.

        Returns:
            The session.

        Raises:
            KeyError: When nothing matches, or the needle is empty while
                more than one hub is joined.
        """
        if not needle:
            with self._lock:
                sessions = list(self._sessions.values())
            if len(sessions) == 1:
                return sessions[0]
            raise KeyError(needle)
        session = self._find_session(needle)
        if session is None:
            raise KeyError(needle)
        return session

    def _make_session(self, binding: dict) -> ClientHubSession:
        """One session for one binding, started when the resident is."""
        session = ClientHubSession(
            binding=binding,
            hostname=self.hostname(),
            platform_tuple=self._platform_tuple,
            log=self._log,
            on_change=self.notify,
            on_services=self._hub_services,
            on_disabled=self._hub_disabled,
            on_unbound=self._hub_unbound,
        )
        with self._lock:
            self._sessions[binding["id"]] = session
            is_started = self._is_started
        if is_started:
            session.start()
        return session

    def _forget_session(self, session: ClientHubSession) -> None:
        """Stop one session and let go of everything its hub published."""
        with self._lock:
            self._sessions.pop(session.binding_id, None)
        session.stop()
        self._release_hub(session.hub_id())
        self._services["ai"].refresh(entries=self.service_entries())
        self.notify()

    def _hub_services(self, session: ClientHubSession) -> None:
        """A hub's services changed: the exit hub's grant may have."""
        self._services["ai"].refresh(entries=self.service_entries())

    def _hub_disabled(self, session: ClientHubSession) -> None:
        """A hub switched this client off: let go of what it published."""
        self._release_hub(session.hub_id())

    def _hub_unbound(self, session: ClientHubSession) -> None:
        """A hub holds no such binding: drop it, and everything it published."""
        try:
            enrollment.remove_binding(session.binding_id)
        except OSError as error:
            self._log(f"could not remove the binding: {error}")
        self._forget_session(session)
        self._follow_exit()

    def _adopt_external_binding(self) -> None:
        """Pick up a binding file another process wrote.

        ``nclient join`` and ``nclient leave`` edit the file from their own
        process when no resident runs; the resident notices the file
        changing and converges without a restart.
        """
        stamp = enrollment.config_stamp()
        with self._lock:
            if stamp == self._binding_stamp:
                return
        self._reconcile_bindings(stamp)

    def _reconcile_bindings(self, stamp: int) -> None:
        """Bring the sessions in line with the binding file.

        A welcome writes the hub's name onto its binding; a session is
        started, stopped or replaced only when a binding appears, goes, or
        names another join.

        Args:
            stamp: The file's stamp, as read before the file.
        """
        config = enrollment.load_config()
        on_disk = {binding["id"]: binding for binding in config["bindings"]}
        with self._lock:
            self._binding_stamp = stamp
            self._chosen_exit_hub_id = config["exit_hub_id"]
            held = list(self._sessions.values())
        dropped = []
        for session in held:
            fresh = on_disk.get(session.binding_id)
            if fresh is None or not is_same_join(fresh, session.binding()):
                self._forget_session(session)
                dropped.append(session.binding_id)
                self._log(f"dropped the binding {session.binding_id} written on disk")
        with self._lock:
            missing = [
                binding
                for binding_id, binding in on_disk.items()
                if binding_id not in self._sessions
            ]
        for binding in missing:
            self._make_session(binding)
            self._log(f"adopted the binding {binding['id']} written on disk")
        if dropped:
            self._follow_exit()
        if missing:
            self.notify()

    def _follow_exit(self) -> None:
        """Pin the stored choice on the hub the exit moved to, when it moved."""
        effective = self.exit_hub_id()
        with self._lock:
            is_moved = effective != self._chosen_exit_hub_id
        if is_moved:
            self._pin_exit(effective)

    def _pin_exit(self, hub_id: str) -> None:
        """Write one hub as the exit and hold it as the choice."""
        try:
            enrollment.set_exit_hub_id(hub_id)
        except OSError as error:
            self._log(f"could not write the exit hub: {error}")
        with self._lock:
            self._chosen_exit_hub_id = hub_id

    def _clear_leftovers(self) -> None:
        """Undo what a run that did not end cleanly left on this machine."""
        for service_type in ("ai", "file"):
            try:
                self._services[service_type].clear_leftovers()
            except Exception as error:  # noqa: BLE001 - reported, never fatal
                self._log(f"{service_type}: could not clear what was left: {error}")

    def _release_hub(self, hub_id: str) -> None:
        """Undo everything the handlers hold for one hub, in the shutdown order."""
        for service_type, _name, _word in SHUTDOWN_STEPS:
            try:
                self._services[service_type].release_hub(hub_id)
            except Exception as error:  # noqa: BLE001 - the rest must still run
                self._log(f"{service_type}: could not release {hub_id}: {error}")

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
        """Run one handler's release, its count or its failure in ``outcome``."""
        try:
            outcome["count"] = self._services[service_type].release()
        except Exception as error:  # noqa: BLE001 - the rest must still run
            outcome["error"] = error
