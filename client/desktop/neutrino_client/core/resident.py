"""The resident: every binding, one session per binding, and the services.

One object is what the window, the control socket and the command line
face. It runs whether or not the person belongs to a hub yet: an unbound
resident still serves its page, waiting for a link. For every binding on
disk it holds one :class:`~neutrino_client.core.session.ClientHubSession`,
and it owns the five service handlers, the store and the choice of exit
hub, so a service is addressed by hub and id together and a hub that goes
away takes only its own entries with it. Beside the sessions it holds this
machine's place on each hub's virtual network, which a hub row connects,
cancels, disconnects and picks the engine of, and the terminals open on the
machines a hub offers.

It holds the one state document the page draws, and the jobs in it: per hub
whether a refresh waits for its answer, the step on its virtual network and
whether it is being left, and per service entry the step a press started
and the failure it ended in. A press that starts a job writes the job and
announces it before it returns; a press on something already at work is
dropped and logged.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import functools
import os
import socket
import sys
import threading
import time
import uuid

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_DEFAULT_THEME,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
    CLIENT_NOTICE_S,
    CLIENT_ORIGINAL_DIR_NAME,
    CLIENT_SHUTDOWN_DEADLINE_S,
    CLIENT_STATE_FILE_NAME,
    CLIENT_STREAM_TIMEOUT_S,
    CLIENT_TERMINAL_FONT_SIZE,
)
from neutrino_client.core import enrollment
from neutrino_client.core.overlay import OverlayMemberships
from neutrino_client.core.session import (
    CONNECTION_CONNECTED,
    CONNECTION_DISABLED,
    ClientHubSession,
)
from neutrino_client.core.terminal import TerminalBridge
from neutrino_client.exceptions import (
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    PlatformUnsupportedError,
)
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.base import service_key
from neutrino_client.services.file import FileServiceHandler
from neutrino_client.services.port import PortLocalTable, PortServiceHandler
from neutrino_client.services.rdp import RdpViewerHandler
from neutrino_client.services.store import ClientServiceStore
from neutrino_client.services.web import WebServiceHandler

# How long a shutdown waits for the watch thread to come back.
SHUTDOWN_JOIN_TIMEOUT_S = 5
# What a shutdown lets go of, in order: the handler, the name its line
# carries, and how that line reads. The virtual networks are kept: their
# daemons hold them.
SHUTDOWN_STEPS = (
    ("overlay", "networks", "{count} kept"),
    ("ai", "ai", "restored"),
    ("file", "mounts", "{count} detached"),
    ("port", "forwards", "{count} closed"),
    ("web", "web forwards", "{count} closed"),
    ("rdp", "viewers", "{count} closed"),
)
# How long a burst of changes is left to settle before the watchers hear.
ANNOUNCE_SETTLE_S = 0.05
# The fields of a binding that make it another hub, or another join: a
# session outlives a change to any other field, the addresses included,
# which the session itself writes.
BINDING_IDENTITY_KEYS = ("id", "fingerprint", "token")
# The step a press on a service entry starts, by its type and action, as
# the page words it under ``ui.job.``.
JOB_OPENING = "opening"
JOB_FORWARDING = "forwarding"
JOB_DISCONNECTING = "disconnecting"
JOB_MOUNTING = "mounting"
JOB_UNMOUNTING = "unmounting"
JOB_SWITCHING = "switching"
JOB_CONNECTING = "connecting"
# The mount record states that read as a mount at work.
MOUNT_WORKING_STATES = ("pending", "queued", "mounting")
# How long a service job waits for the lane it started.
SERVICE_SETTLE_TIMEOUT_S = 300


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


def is_forwardable(entry: dict) -> bool:
    """Whether an entry forwards to the loopback: a port, or a local-only page.

    Args:
        entry: A published entry.

    Returns:
        True for a ``port`` entry and a ``web`` entry whose payload says
        ``is_local_only``.
    """
    if entry.get("type") == "port":
        return True
    return (
        entry.get("type") == "web"
        and (entry.get("payload") or {}).get("is_local_only") is True
    )


def _hub_answer(call, *args) -> dict:
    """Empty when one ask of a hub went through, else its refusal as a code."""
    try:
        call(*args)
    except GatewayRefusedDetail as refused:
        return {"code": refused.code, "params": dict(refused.params)}
    except GatewayUnreachable as error:
        return {"code": "hub_unreachable", "params": {"detail": str(error)}}
    return {}


def _start_daemon_thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()


class ClientResident:
    """Everything the person's surfaces face, over every hub joined."""

    def __init__(
        self, *, log=print, platform=None, overlay_drivers=None, start_thread=None
    ):
        """
        Args:
            log: Callable used for progress messages.
            platform: The machine's platform; None detects it.
            overlay_drivers: ``{provider: driver}`` for the virtual
                networks; None drives the carried NetBird and EasyTier.
            start_thread: ``start_thread(target)`` runs a job a press
                started; None uses a daemon thread. Tests pass one that
                runs inline.
        """
        self._log = log
        self._start_thread = (
            start_thread if start_thread is not None else _start_daemon_thread
        )
        self._lock = threading.Lock()
        # Held while the binding file is read against the sessions, and while
        # a completed join is written, so neither sees the other half done.
        self._binding_lock = threading.RLock()
        self.platform = platform if platform is not None else detect_platform()
        self._platform_tuple = platform_tuple()
        config_dir = self.platform.config_dir()
        self._store = ClientServiceStore(
            path=os.path.join(config_dir, CLIENT_STATE_FILE_NAME)
        )
        self._ports = PortLocalTable(store=self._store)
        # Whoever draws the state, told after every change of it; the
        # announcements of one burst are folded into one.
        self._watchers: list = []
        self._announce_lock = threading.Lock()
        self._is_announcing = False
        self._is_pending_announcement = False
        self._services = {
            handler.service_type: handler
            for handler in (
                WebServiceHandler(
                    platform=self.platform,
                    open_service=self.open_service,
                    log=log,
                    ports=self._ports,
                ),
                PortServiceHandler(log=log, on_change=self.notify, ports=self._ports),
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
                    entries_of=self.service_entries,
                ),
                RdpViewerHandler(
                    platform=self.platform,
                    open_service=self.open_service,
                    log=log,
                    on_change=self.notify,
                ),
            )
        }
        self._overlay = OverlayMemberships(
            platform=self.platform,
            bindings_of=self._overlay_bindings,
            hostname=self.hostname(),
            log=log,
            on_change=self.notify,
            on_route=self._overlay_route,
            reaches_hub=self._overlay_reaches,
            keep_choice=self._overlay_keep,
            drivers=overlay_drivers,
        )
        # One session per binding, by binding id, in the order joined.
        self._sessions: dict = {}
        # The bindings being left, by id.
        self._leaving: set = set()
        # The step a press started on a service entry, and the failure the
        # last one ended in, by service key.
        self._entry_jobs: dict = {}
        self._entry_errors: dict = {}
        # What the page shows above the hubs for a while: [{code, params, id}].
        self._notices: list = []
        # Every terminal open or ended and not yet asked about, by its id:
        # ``(session, bridge)``.
        self._terminals: dict = {}
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
        # Takes each piece of a window terminal, ``{"id", "data"}`` with the
        # output's bytes or ``{"id", "end"}`` with how the shell ended; None
        # while no window shows one.
        self.on_terminal_output = None
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
            ``[{hub_id, hub_name, binding_id, gateway_url, software,
            connection, is_pending, last_error, is_exit, overlay, jobs}]``:
            ``connection`` is one of the session's six states,
            ``is_pending`` whether the join's ticket is not spent yet,
            ``overlay`` the virtual network's ``{network, networks, state,
            stage, stage_since, is_waiting, address, error}``, and ``jobs``
            ``{is_refreshing, overlay_job, is_leaving}``. No token, ticket
            or secret is in it.
        """
        exit_hub_id = self.exit_hub_id()
        with self._lock:
            sessions = list(self._sessions.values())
            leaving = set(self._leaving)
        rows = []
        for session in sessions:
            binding = session.binding()
            hub_id = binding.get("hub_id", "")
            key = session.local_key
            rows.append(
                {
                    "hub_id": hub_id,
                    "hub_name": binding.get("hub_name", ""),
                    "binding_id": binding.get("id", ""),
                    "gateway_url": binding.get("gateway_url", ""),
                    "software": session.hub_software(),
                    "connection": session.connection(),
                    "is_pending": binding.get("is_pending") is True,
                    "last_error": session.last_error(),
                    "is_exit": bool(hub_id) and hub_id == exit_hub_id,
                    "overlay": self._overlay.hub_row(key),
                    "jobs": {
                        "is_refreshing": session.is_refreshing(),
                        "overlay_job": self._overlay.job(key),
                        "is_leaving": key in leaving,
                    },
                }
            )
        return rows

    def notices(self) -> list:
        """What the page shows above the hubs for a while.

        Returns:
            ``[{code, params}]``, the newest last.
        """
        with self._lock:
            return [
                {"code": notice["code"], "params": dict(notice["params"])}
                for notice in self._notices
            ]

    def entry_rows(self) -> list:
        """The service entries of every connected hub, each with its job.

        Returns:
            The entries of :meth:`service_entries`, each with ``job``, the
            step at work on it or empty, and ``last_error``, the failure the
            last one ended in or None; a port entry and a local-only web
            entry also with ``local_port``, ``"auto"`` or the fixed number,
            and ``forward``, the loopback port its forward listens on or
            None.
        """
        entries = self.service_entries()
        mounts = self._services["file"].state().get("mounts") or []
        forwards = dict(self._services["port"].state().get("forwards") or {})
        forwards.update(self._services["web"].state().get("web_forwards") or {})
        with self._lock:
            jobs = dict(self._entry_jobs)
            errors = dict(self._entry_errors)
        rows = []
        for entry in entries:
            key = service_key(entry.get("hub_id", ""), entry.get("id", ""))
            job = jobs.get(key, "")
            if not job and entry.get("type") == "file":
                if any(
                    record.get("hub_id") == entry.get("hub_id")
                    and record.get("entry_id") == entry.get("id")
                    and record.get("state") in MOUNT_WORKING_STATES
                    for record in mounts
                ):
                    job = JOB_MOUNTING
            error = errors.get(key)
            row = dict(entry, job=job, last_error=dict(error) if error else None)
            if is_forwardable(entry):
                forward = forwards.get(key) or {}
                row["local_port"] = self._ports.setting(key)
                row["forward"] = (
                    forward.get("local_port") if forward.get("is_active") else None
                )
            rows.append(row)
        return rows

    def terminal_entries(self) -> list:
        """The machines every connected hub offers a terminal on, merged.

        Returns:
            ``[{hub_id, device_id, name, is_online}]`` in hub order.
        """
        with self._lock:
            sessions = list(self._sessions.values())
        merged = []
        for session in sessions:
            hub_id = session.hub_id()
            merged.extend(
                dict(entry, hub_id=hub_id) for entry in session.terminal_entries()
            )
        return merged

    def terminal_sessions(self) -> list:
        """The shell sessions every connected hub lists for this client, merged.

        Returns:
            ``[{hub_id, session_id, device_id, owner, is_owned,
            is_persistent, is_shared, attached_count, title, started_at}]``
            in hub order.
        """
        with self._lock:
            sessions = list(self._sessions.values())
        merged = []
        for session in sessions:
            hub_id = session.hub_id()
            merged.extend(
                dict(entry, hub_id=hub_id) for entry in session.terminal_sessions()
            )
        return merged

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

    def terminal_font_size(self) -> int:
        """The terminal's font size in pixels; the default until one is chosen."""
        return self._store.terminal_font_size() or CLIENT_TERMINAL_FONT_SIZE

    def set_terminal_font_size(self, size: int) -> None:
        """Keep the terminal's font size, and say so.

        Args:
            size: The size in pixels; one out of range is held to the range.
        """
        self._store.set_terminal_font_size(size)
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

    def read_clipboard(self) -> dict:
        """The text on this person's clipboard, for a paste into a terminal.

        Returns:
            ``{"text"}``; ``clipboard_unreadable`` with the reason when the
            platform cannot read it.
        """
        try:
            return {"text": self.platform.read_clipboard()}
        except (OSError, PlatformUnsupportedError) as error:
            return {"code": "clipboard_unreadable", "params": {"detail": str(error)}}

    def write_clipboard(self, text: str) -> dict:
        """Put text on this person's clipboard, for a copy out of a terminal.

        Args:
            text: The text.

        Returns:
            Empty when it was written; ``clipboard_unwritable`` with the
            reason when the platform cannot write it.
        """
        try:
            self.platform.write_clipboard(text)
        except (OSError, PlatformUnsupportedError) as error:
            return {"code": "clipboard_unwritable", "params": {"detail": str(error)}}
        return {}

    def list_directories(self, path: str) -> list:
        """The subdirectory names under a directory, as this person."""
        return self.platform.list_directories(path=path)

    def make_directory(self, path: str) -> None:
        """Create a directory as this person, parents included."""
        self.platform.make_directory(path=path)

    # --- what the local page does ---

    def connect(self, link: str) -> None:
        """Join the hub an enrollment link points at, without waiting for it.

        The binding is stored pending and its session started; the session
        spends the ticket at the first address that answers.

        Args:
            link: The link the person pasted.

        Raises:
            EnrollmentError: If the link is unusable.
            OSError: When the binding file cannot be written.
        """
        enrollment.enroll(link)
        self._reconcile_bindings(enrollment.config_stamp())
        self._log("joined the hub")
        self.notify()

    def disconnect(self, hub_id: str = "") -> None:
        """Leave one hub and let go of everything it published.

        The binding goes first and the hub is told after, from a thread of
        its own; one that cannot be reached does not hold the person there.

        Args:
            hub_id: The hub to leave, by its id or by its binding's id;
                empty names the one hub joined.

        Raises:
            KeyError: If ``hub_id`` names no hub this person has joined, or
                is empty while several are.
        """
        session = self._session_for(hub_id)
        binding = session.binding()
        enrollment.remove_binding(binding["id"])
        self._forget_session(session)
        self._follow_exit()
        if binding.get("is_pending") is not True:
            threading.Thread(
                target=self._tell_hub_left,
                args=(binding,),
                name="client_leave",
                daemon=True,
            ).start()
        self._log("left the hub")

    def leave(self, hub_id: str = "") -> None:
        """Start leaving one hub: the row shows it at once, and goes once done.

        A second press while the hub is being left is dropped and logged.

        Args:
            hub_id: The hub to leave, by its id or by its binding's id;
                empty names the one hub joined.

        Raises:
            KeyError: If ``hub_id`` names no hub this person has joined, or
                is empty while several are.
        """
        session = self._session_for(hub_id)
        with self._lock:
            is_dropped = session.local_key in self._leaving
            self._leaving.add(session.local_key)
        if is_dropped:
            self._log(f"a second leave of {session.binding_id} was dropped")
            return
        self.notify()
        self._start_thread(functools.partial(self._leave_now, session))

    def refresh(self) -> None:
        """Ask every hub that can answer again now, and show the work.

        Each connected, connecting or down hub loses its error line and its
        virtual network's error, its entries lose theirs, and it waits as
        refreshing until its answer; a replaced or disabled hub is left as
        it is. A press while any hub still refreshes is dropped and logged.
        """
        with self._lock:
            sessions = list(self._sessions.values())
        if any(session.is_refreshing() for session in sessions):
            self._log("a refresh while one runs was dropped")
            return
        for session in sessions:
            if not session.refresh():
                continue
            hub_id = session.hub_id()
            self._overlay.clear_error(session.local_key)
            with self._lock:
                for key in list(self._entry_errors):
                    if key.startswith(hub_id + "/"):
                        self._entry_errors.pop(key, None)
        self.notify()

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
        if session.connection() != CONNECTION_CONNECTED:
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

    def connect_overlay(self, hub_id: str) -> dict:
        """Start one connect to one hub's chosen virtual network.

        Args:
            hub_id: The hub, by its id or by its binding's id.

        Returns:
            Empty, the press taken or dropped; ``unknown_hub`` otherwise.
        """
        return self._overlay_press(hub_id, self._overlay.connect)

    def cancel_overlay(self, hub_id: str) -> dict:
        """Stop a connect to one hub's virtual network in progress.

        Args:
            hub_id: The hub, by its id or by its binding's id.

        Returns:
            Empty, the press taken or dropped; ``unknown_hub`` otherwise.
        """
        return self._overlay_press(hub_id, self._overlay.cancel)

    def disconnect_overlay(self, hub_id: str) -> dict:
        """Stop one hub's virtual network that is on.

        Args:
            hub_id: The hub, by its id or by its binding's id.

        Returns:
            Empty, the press taken or dropped; ``unknown_hub`` otherwise.
        """
        return self._overlay_press(hub_id, self._overlay.disconnect)

    def pick_overlay(self, hub_id: str, provider: str) -> dict:
        """Choose the engine of one hub's virtual network while it is off.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            provider: The provider of the network chosen.

        Returns:
            Empty, the pick taken or dropped; ``unknown_hub`` otherwise.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        self._overlay.pick(session.local_key, provider)
        return {}

    def open_terminal(
        self,
        hub_id: str,
        device_id: str,
        cols: int,
        rows: int,
        session_id: str = "",
    ) -> dict:
        """Open a shell on one machine a hub offers, for a terminal to attach to.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            device_id: The machine, as the hub's ``terminals`` names it.
            cols: The terminal's width in columns.
            rows: The terminal's height in rows.
            session_id: A shell session the machine keeps, attached to again
                with its kept output; empty opens a new one under a fresh
                uuid.

        Returns:
            ``{"terminal_id", "session_id"}``; ``unknown_hub``,
            ``unknown_terminal`` or ``hub_unreachable`` otherwise.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        known = {entry["device_id"] for entry in session.terminal_entries()}
        if device_id not in known:
            return {"code": "unknown_terminal", "params": {"device_id": device_id}}
        is_resumed = bool(session_id)
        session_id = session_id or str(uuid.uuid4())
        try:
            stream = session.open_shell(
                device_id, cols, rows, session_id, is_resumed=is_resumed
            )
        except GatewayUnreachable as error:
            return {"code": "hub_unreachable", "params": {"detail": str(error)}}
        terminal_id = uuid.uuid4().hex
        bridge = TerminalBridge(stream=stream, session_id=session_id)
        with self._lock:
            self._terminals[terminal_id] = (session, bridge)
        self._log(f"a terminal on {device_id} is open")
        return {"terminal_id": terminal_id, "session_id": session_id}

    def attach_terminal(self, terminal_id: str, read) -> None:
        """Carry what is typed on one terminal to its shell until either ends.

        Args:
            terminal_id: The terminal, as ``open_terminal`` named it.
            read: ``read(size)`` returns the next bytes typed, empty at the
                end.
        """
        opened = self._terminal(terminal_id)
        if opened is not None:
            opened[1].pump_in(read)

    def terminal_output(self, terminal_id: str, write) -> None:
        """Carry one shell's output to its terminal until the shell ends.

        Args:
            terminal_id: The terminal, as ``open_terminal`` named it.
            write: ``write(data)`` puts bytes on the terminal.
        """
        opened = self._terminal(terminal_id)
        if opened is not None:
            opened[1].pump_out(write)

    def has_terminal(self, terminal_id: str) -> bool:
        """Whether a terminal by that id is open or waiting to be asked about."""
        return self._terminal(terminal_id) is not None

    def resize_terminal(self, terminal_id: str, cols: int, rows: int) -> dict:
        """Tell one terminal's shell its new size.

        Args:
            terminal_id: The terminal.
            cols: The new width in columns.
            rows: The new height in rows.

        Returns:
            Empty on success; ``unknown_terminal``, the hub's refusal, or
            ``hub_unreachable``.
        """
        opened = self._terminal(terminal_id)
        if opened is None:
            return {"code": "unknown_terminal", "params": {}}
        session, bridge = opened
        try:
            session.resize_shell(bridge.stream_id, cols, rows)
        except GatewayRefusedDetail as refused:
            return {"code": refused.code, "params": dict(refused.params)}
        except GatewayUnreachable as error:
            return {"code": "hub_unreachable", "params": {"detail": str(error)}}
        return {}

    def terminal_result(self, terminal_id: str) -> dict:
        """How one ended terminal's shell ended, asked once.

        Args:
            terminal_id: The terminal.

        Returns:
            ``{"exit_code"}`` or the refusal ``{"code", "params"}``;
            ``unknown_terminal`` for a terminal nobody opened, or one
            already asked about.
        """
        with self._lock:
            opened = self._terminals.get(terminal_id)
            if opened is None:
                return {"code": "unknown_terminal", "params": {}}
            if opened[1].is_done:
                self._terminals.pop(terminal_id, None)
        return opened[1].outcome()

    def open_window_terminal(
        self,
        hub_id: str,
        device_id: str,
        cols: int,
        rows: int,
        session_id: str = "",
    ) -> dict:
        """Open a shell for the window's own terminal, its output pushed there.

        The output goes to ``on_terminal_output`` as it arrives, and once
        the shell ends the terminal is forgotten and its end is pushed the
        same way.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            device_id: The machine, as the hub's ``terminals`` names it.
            cols: The terminal's width in columns.
            rows: The terminal's height in rows.
            session_id: A shell session the machine keeps, attached to
                again; empty opens a new one.

        Returns:
            ``{"terminal_id", "session_id"}``; ``unknown_hub``,
            ``unknown_terminal`` or ``hub_unreachable`` otherwise.
        """
        outcome = self.open_terminal(hub_id, device_id, cols, rows, session_id)
        terminal_id = outcome.get("terminal_id")
        if terminal_id:
            threading.Thread(
                target=self._push_terminal,
                args=(terminal_id,),
                name="client_terminal_output",
                daemon=True,
            ).start()
        return outcome

    def terminal_input(self, terminal_id: str, data: bytes) -> dict:
        """Send keys typed on the window's terminal to its shell.

        Args:
            terminal_id: The terminal.
            data: The bytes typed.

        Returns:
            Empty when they went; ``unknown_terminal`` for a terminal that is
            not open, ``shell_unknown`` for one whose shell has ended.
        """
        opened = self._terminal(terminal_id)
        if opened is None:
            return {"code": "unknown_terminal", "params": {}}
        if not opened[1].send(data):
            return {"code": "shell_unknown", "params": {"shell": terminal_id}}
        return {}

    def persist_terminal(
        self, terminal_id: str, is_persistent: bool, is_shared: bool
    ) -> dict:
        """Set whether one terminal's shell session outlives its windows, and who sees it.

        The session's row in the state document takes both values at once
        on success; the next state from the hub confirms them.

        Args:
            terminal_id: The terminal.
            is_persistent: Whether the machine keeps the session.
            is_shared: Whether every client with terminal rights on the
                machine lists it.

        Returns:
            Empty on success; ``unknown_terminal``, the hub's refusal,
            ``session_not_owned`` among them, or ``hub_unreachable``.
        """
        opened = self._terminal(terminal_id)
        if opened is None:
            return {"code": "unknown_terminal", "params": {}}
        session, bridge = opened
        outcome = _hub_answer(
            session.persist_shell, bridge.session_id, is_persistent, is_shared
        )
        if not outcome:
            session.note_session_flags(bridge.session_id, is_persistent, is_shared)
            self.notify()
        return outcome

    def stop_terminal_session(self, hub_id: str, session_id: str) -> dict:
        """End one shell session a hub's machine keeps, attached or not.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            session_id: The shell session's id.

        Returns:
            Empty on success; ``unknown_hub``, the hub's refusal, or
            ``hub_unreachable``.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        outcome = _hub_answer(session.stop_shell_session, session_id)
        if not outcome:
            self._log(f"the shell session {session_id} was ended")
        return outcome

    def close_terminal(self, terminal_id: str) -> dict:
        """End the shell of one of the window's terminals and forget it.

        Args:
            terminal_id: The terminal.

        Returns:
            Empty; ``unknown_terminal`` for a terminal that is not open.
        """
        with self._lock:
            opened = self._terminals.pop(terminal_id, None)
        if opened is None:
            return {"code": "unknown_terminal", "params": {}}
        opened[1].close()
        self._log("a terminal was closed from the window")
        return {}

    def request_show(self) -> None:
        """Ask the window to come to the front, when one is listening."""
        callback = self.on_show
        if callback is not None:
            callback()

    def service_action(self, service_type: str, body: dict) -> dict:
        """Start one page action on a service entry, as that entry's job.

        The entry's job is written and announced before this returns, and
        the handler runs on a thread of its own; how it ends is the entry's
        ``last_error``. A press on an entry already at work is dropped and
        logged; an open that needs no forward runs at once and has no job.

        Args:
            service_type: The type the page acted on.
            body: The action's own fields; ``hub_id`` names the hub, and an
                action naming none is the exit hub's, where the AI apply
                lands.

        Returns:
            Empty, the press taken or dropped; ``unknown_request`` for a
            type or an action nothing handles, ``client_disabled`` while
            that hub has this client switched off.
        """
        handler = self._services.get(service_type)
        if handler is None:
            return {"code": "unknown_request", "params": {}}
        hub_id = str(body.get("hub_id", "") or "") or self.exit_hub_id()
        session = self._find_session(hub_id)
        if session is not None and session.connection() == CONNECTION_DISABLED:
            return {"code": "client_disabled", "params": {}}
        body = dict(body, hub_id=hub_id)
        key, job = self._entry_job(service_type, body)
        if not job:
            return self._answer_now(
                handler.act(entries=self.service_entries(), body=body)
            )
        with self._lock:
            is_dropped = key in self._entry_jobs or self._is_mounting(key)
            if not is_dropped:
                self._entry_jobs[key] = job
                self._entry_errors.pop(key, None)
        if is_dropped:
            self._log(f"a press on {key} while it works was dropped")
            return {}
        self.notify()
        self._start_thread(functools.partial(self._run_entry_job, handler, key, body))
        return {}

    def configure_forward(self, hub_id: str, entry_id: str, setting) -> dict:
        """Set the local port one forwardable entry takes.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id.
            setting: ``"auto"`` or a fixed number.

        Returns:
            Empty when kept; ``unknown_request`` for an entry that is not
            forwardable or a setting of another shape, ``port_taken`` for a
            number another entry holds.
        """
        entry = next(
            (
                item
                for item in self.service_entries()
                if item.get("hub_id") == hub_id and item.get("id") == entry_id
            ),
            None,
        )
        if entry is None or not is_forwardable(entry):
            return {"code": "unknown_request", "params": {}}
        outcome = self._ports.configure(service_key(hub_id, entry_id), setting)
        if not outcome:
            self.notify()
        return outcome

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
        """Run the resident's own thread, and return at once.

        That thread clears what an unclean exit left, starts the handlers
        and the sessions in that order, then watches the binding file.
        Nothing this person had on is turned on again: the client opens with
        every service off, and the leftovers of a run that did not shut down
        are undone before any hub's first state arrives.
        """
        thread = threading.Thread(target=self.run_forever, daemon=True)
        thread.start()
        self._thread = thread

    def run_forever(self) -> None:
        """Clear the leftovers, start everything, then watch the binding file."""
        self._log(f"neutrino_client {CLIENT_VERSION} starting on {self.hostname()}")
        self._clear_leftovers()
        for handler in self._services.values():
            handler.start()
        self._overlay.start()
        with self._lock:
            self._is_started = True
            sessions = list(self._sessions.values())
        for session in sessions:
            session.start()
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
        sockets closed, the virtual networks counted and kept, the tools
        restored, the shares unmounted, the forwards and the web forwards
        closed, the viewers closed. The steps share
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
        self._overlay.stop()
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

    def _entry_job(self, service_type: str, body: dict) -> "tuple[str, str]":
        """The service key a press acts on and the job it starts; no job for an instant one."""
        hub_id = str(body.get("hub_id", ""))
        entry_id = str(body.get("id", "") or "")
        action = str(body.get("action", "") or "")
        if service_type == "file" and body.get("record_id"):
            records = self._services["file"].state().get("mounts") or []
            for record in records:
                if record.get("record_id") == body.get("record_id"):
                    hub_id = str(record.get("hub_id", ""))
                    entry_id = str(record.get("entry_id", ""))
        key = service_key(hub_id, entry_id)
        if service_type == "web":
            entry = next(
                (
                    item
                    for item in self.service_entries()
                    if item.get("hub_id") == hub_id and item.get("id") == entry_id
                ),
                {},
            )
            payload = entry.get("payload") or {}
            if payload.get("is_token_required") is True:
                return key, JOB_OPENING
            if payload.get("is_local_only") is not True:
                return key, ""
            return key, (
                JOB_DISCONNECTING if body.get("is_enabled") is False else JOB_OPENING
            )
        if service_type == "port":
            return key, JOB_FORWARDING if body.get("is_enabled") else JOB_DISCONNECTING
        if service_type == "file":
            return key, JOB_UNMOUNTING if action == "unmount" else JOB_MOUNTING
        if service_type == "ai":
            return key, JOB_SWITCHING
        if service_type == "rdp":
            return key, JOB_CONNECTING
        return key, ""

    def _is_mounting(self, key: str) -> bool:
        """Whether a mount record of one entry is on its way; the lock is held."""
        hub_id, _, entry_id = key.partition("/")
        for record in self._services["file"].state().get("mounts") or []:
            if (
                record.get("hub_id") == hub_id
                and record.get("entry_id") == entry_id
                and record.get("state") in MOUNT_WORKING_STATES
            ):
                return True
        return False

    def _run_entry_job(self, handler, key: str, body: dict) -> None:
        """Run one entry's job, then write how it ended and announce it."""
        try:
            outcome = handler.act(entries=self.service_entries(), body=body)
            if not outcome:
                outcome = handler.settle(SERVICE_SETTLE_TIMEOUT_S)
        except Exception as error:  # noqa: BLE001 - reported on the row
            outcome = {"code": "crashed", "params": {"detail": str(error)[:200]}}
        outcome = self._answer_now(outcome)
        with self._lock:
            self._entry_jobs.pop(key, None)
            if outcome:
                self._entry_errors[key] = dict(outcome)
        self.notify()

    def _answer_now(self, outcome: dict) -> dict:
        """A handler's answer, with ``busy`` dropped and logged."""
        if outcome and outcome.get("code") == "busy":
            self._log("a press on a lane at work was dropped")
            return {}
        return outcome or {}

    def _terminal(self, terminal_id: str) -> "tuple | None":
        """One terminal's session and bridge, None for an id nobody opened."""
        with self._lock:
            return self._terminals.get(terminal_id)

    def _push_terminal(self, terminal_id: str) -> None:
        """Push one window terminal's output until its shell ends, then its end."""
        opened = self._terminal(terminal_id)
        if opened is None:
            return
        bridge = opened[1]

        def write(data: bytes) -> None:
            self._hand_terminal({"id": terminal_id, "data": data})

        bridge.pump_out(write)
        with self._lock:
            self._terminals.pop(terminal_id, None)
        self._hand_terminal({"id": terminal_id, "end": bridge.outcome()})

    def _hand_terminal(self, chunk: dict) -> None:
        """Give one piece of a window terminal to whoever shows it."""
        listener = self.on_terminal_output
        if listener is None:
            return
        try:
            listener(chunk)
        except Exception as error:  # noqa: BLE001 - a window's own failure
            self._log(f"the window did not take terminal output: {error}")

    def _find_session(self, needle: str) -> "ClientHubSession | None":
        """The session of one hub, by hub id or binding id; None for nobody."""
        if not needle:
            return None
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if needle in (session.hub_id(), session.binding_id, session.local_key):
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
            on_joined=self._hub_joined,
        )
        with self._lock:
            self._sessions[session.local_key] = session
            is_started = self._is_started
        if is_started:
            session.start()
        return session

    def _forget_session(self, session: ClientHubSession) -> None:
        """Stop one session and let go of everything its hub published."""
        hub_id = session.hub_id()
        with self._lock:
            self._sessions.pop(session.local_key, None)
            self._leaving.discard(session.local_key)
            for table in (self._entry_jobs, self._entry_errors):
                for key in [key for key in table if key.startswith(hub_id + "/")]:
                    table.pop(key, None)
        session.stop()
        self._release_hub(hub_id or session.binding_id, session.local_key)
        self._services["ai"].refresh(entries=self.service_entries())
        self.notify()

    def _hub_services(self, session: ClientHubSession) -> None:
        """A hub's state arrived: the exit hub's grant and its network may have changed."""
        self._services["ai"].refresh(entries=self.service_entries())
        self._overlay.refresh()

    def _hub_joined(self, session: ClientHubSession, binding: dict) -> None:
        """A pending join was completed: keep it where the binding file is read.

        Raises:
            OSError: When the binding file cannot be written.
        """
        with self._binding_lock:
            session.adopt_join(binding)

    def _overlay_bindings(self) -> list:
        """Each hub's overlay objects and choice, by its session's key, for the memberships."""
        with self._lock:
            sessions = list(self._sessions.values())
        rows = []
        for session in sessions:
            is_on, pick = session.overlay_choice()
            rows.append(
                {
                    "hub_id": session.local_key,
                    "overlays": session.overlays(),
                    "urls": enrollment.stored_urls(session.binding()),
                    "is_on": is_on,
                    "pick": pick,
                }
            )
        return rows

    def _overlay_press(self, hub_id: str, press) -> dict:
        """Hand one press on a hub's virtual network to the memberships."""
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        press(session.local_key)
        return {}

    def _overlay_route(self, hub_id: str, hosts: list, is_only: bool = False) -> None:
        """A hub's channel connects through its hosts on the network first, or alone."""
        session = self._find_session(hub_id)
        if session is not None:
            session.reconnect_through(hosts, is_only)

    def _overlay_reaches(self, hub_id: str, hosts: list) -> bool:
        """Whether a hub's channel is up through its hosts on the network."""
        session = self._find_session(hub_id)
        return session is not None and session.reaches_through(hosts)

    def _overlay_keep(self, hub_id: str, is_on: bool, pick: str) -> None:
        """Write where a hub's network stands onto its binding.

        Raises:
            OSError: When the binding file cannot be written.
        """
        session = self._find_session(hub_id)
        if session is not None:
            session.set_overlay_choice(is_on, pick)

    def _hub_disabled(self, session: ClientHubSession) -> None:
        """A hub switched this client off: let go of what it published."""
        self._release_hub(session.hub_id(), session.local_key)

    def _hub_unbound(self, session: ClientHubSession) -> None:
        """A hub holds no such binding: drop it, and say so above the hubs."""
        binding = session.binding()
        try:
            enrollment.remove_binding(session.binding_id)
        except OSError as error:
            self._log(f"could not remove the binding: {error}")
        self._forget_session(session)
        self._follow_exit()
        self._add_notice(
            "binding_unknown",
            {"hub": binding.get("hub_name") or binding.get("gateway_url", "")},
        )

    def _add_notice(self, code: str, params: dict) -> None:
        """Show one notice above the hubs for ``CLIENT_NOTICE_S``."""
        notice = {"code": code, "params": dict(params), "id": uuid.uuid4().hex}
        with self._lock:
            self._notices.append(notice)
        timer = threading.Timer(
            CLIENT_NOTICE_S, self._drop_notice, args=(notice["id"],)
        )
        timer.daemon = True
        timer.start()
        self.notify()

    def _drop_notice(self, notice_id: str) -> None:
        """Take one notice down."""
        with self._lock:
            self._notices = [
                notice for notice in self._notices if notice["id"] != notice_id
            ]
        self.notify()

    def _leave_now(self, session: ClientHubSession) -> None:
        """Leave one hub; a leave that cannot finish puts the row back."""
        try:
            self.disconnect(session.binding_id)
        except (KeyError, OSError) as error:
            self._log(f"could not leave the hub: {error}")
            with self._lock:
                self._leaving.discard(session.local_key)
            self.notify()

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
        with self._binding_lock:
            config = enrollment.load_config()
            on_disk = {binding["id"]: binding for binding in config["bindings"]}
            with self._lock:
                self._binding_stamp = stamp
                self._chosen_exit_hub_id = config["exit_hub_id"]
                held = list(self._sessions.values())
            stale = [
                session
                for session in held
                if on_disk.get(session.binding_id) is None
                or not is_same_join(on_disk[session.binding_id], session.binding())
            ]
            kept = {session.binding_id for session in held if session not in stale}
            missing = [
                binding
                for binding_id, binding in on_disk.items()
                if binding_id not in kept
            ]
        dropped = []
        for session in stale:
            self._forget_session(session)
            dropped.append(session.binding_id)
            self._log(f"dropped the binding {session.binding_id} written on disk")
        for binding in missing:
            self._make_session(binding)
            self._log(f"adopted the binding {binding['id']} written on disk")
        if dropped:
            self._follow_exit()
        if missing:
            self.notify()
        if dropped or missing:
            self._overlay.refresh()

    def _tell_hub_left(self, binding: dict) -> None:
        """Post the leave to the hub; one that cannot be told is logged."""
        try:
            enrollment.leave(binding)
        except (GatewayRefused, GatewayUnreachable, GatewayUntrusted) as error:
            self._log(f"could not tell the hub we are leaving: {error}")

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

    def _release_hub(self, hub_id: str, overlay_key: str) -> None:
        """Undo everything the handlers hold for one hub, in the shutdown order."""
        for service_type, _name, _word in SHUTDOWN_STEPS:
            key = overlay_key if service_type == "overlay" else hub_id
            try:
                self._releaser(service_type).release_hub(key)
            except Exception as error:  # noqa: BLE001 - the rest must still run
                self._log(f"{service_type}: could not release {hub_id}: {error}")

    def _releaser(self, service_type: str):
        """What one shutdown step releases: the networks, or a handler."""
        if service_type == "overlay":
            return self._overlay
        return self._services[service_type]

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
            outcome["count"] = self._releaser(service_type).release()
        except Exception as error:  # noqa: BLE001 - the rest must still run
            outcome["error"] = error
