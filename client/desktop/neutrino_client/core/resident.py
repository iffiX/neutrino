"""The resident: every binding, one session per binding, and the services.

One object is what the window, the control socket and the command line
face. It runs whether or not the person belongs to a hub yet: an unbound
resident still serves its page, waiting for a link. For every binding on
disk it holds one :class:`~neutrino_client.core.session.ClientHubSession`,
and it owns the five service handlers, the store and the choice of exit
hub, so a service is addressed by hub and id together and a hub that goes
away takes only its own entries with it. Beside the sessions it holds this
machine's place on each hub's virtual network, which a hub row connects,
cancels, disconnects and picks the engine of, and the terminals and the
commands open on the machines a hub offers.

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
import shutil
import socket
import sys
import threading
import time
import uuid

from neutrino_client import CLIENT_VERSION
from neutrino_client.bundled import bundled_path
from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_DEFAULT_THEME,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_LANGUAGES,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
    CLIENT_NOTICE_S,
    CLIENT_ORIGINAL_DIR_NAME,
    CLIENT_SHUTDOWN_DEADLINE_S,
    CLIENT_STATE_FILE_NAME,
    CLIENT_STREAM_TIMEOUT_S,
    CLIENT_TERMINAL_FONT_SIZE,
    CLIENT_THEMES,
    CLIENT_TRANSPORT_BIN_ENV,
    CLIENT_TRANSPORT_LOG_NAME,
    CLIENT_TRANSPORT_PROGRAM,
    CLIENT_TRANSPORT_START_TIMEOUT_S,
)
from neutrino_client.core import enrollment
from neutrino_client.core.overlay import OverlayMemberships
from neutrino_client.core.session import (
    CONNECTION_CONNECTED,
    CONNECTION_DISABLED,
    ClientHubSession,
)
from neutrino_client.core.streams import ClientStream
from neutrino_client.core.terminal import ExecBridge, TerminalBridge
from neutrino_client.core.transport import (
    ClientTransportChannel,
    ClientTransportProcess,
)
from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    PlatformUnsupportedError,
)
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.app import (
    AppServiceHandler,
    app_entries,
    entry_protocol,
    panel_url,
)
from neutrino_client.services.base import channel_refusal, service_key
from neutrino_client.services.file import MOUNT_SHAPE_ADAPTER, FileServiceHandler
from neutrino_client.services.files_adapter import (
    FilesAdapter,
    FilesAddressPlan,
    FilesSocksEndpoint,
)
from neutrino_client.services.forward import (
    FORWARD_KIND_PANEL,
    FORWARD_PANEL_ID,
    ConnectStreamSocket,
    ForwardListenerRegistry,
    PortLocalTable,
    forward_refusal,
    is_fixed_port_kind,
)
from neutrino_client.services.rdp import RdpViewerHandler
from neutrino_client.services.ssh import SshConfigWriter, keep_forwards
from neutrino_client.services.store import ClientServiceStore

# How long a shutdown waits for the watch thread to come back.
SHUTDOWN_JOIN_TIMEOUT_S = 5
# What a shutdown lets go of, in order: the handler, the name its line
# carries, and how that line reads. The virtual networks are kept: their
# daemons hold them. The forwards end last, after the mounts and the
# viewers that use them.
SHUTDOWN_STEPS = (
    ("overlay", "networks", "{count} kept"),
    ("ai", "ai", "restored"),
    ("file", "mounts", "{count} detached"),
    ("rdp", "viewers", "{count} closed"),
    ("forwards", "forwards", "{count} closed"),
)
# How long a burst of changes is left to settle before the watchers hear.
ANNOUNCE_SETTLE_S = 0.05
# How long one watcher is waited for before the announcements go on without
# it, and how many of its calls may be held at once before it is skipped.
ANNOUNCE_WATCHER_WAIT_S = 5
ANNOUNCE_WATCHER_HELD_MAX = 4
# The fields of a binding that make it another hub, or another join. A
# session outlives a change to any other field, the addresses it writes
# itself included.
BINDING_IDENTITY_KEYS = ("id", "token", "ticket")
# The step a press on a service entry starts, by its type and action, as
# the page words it under ``ui.job.``.
JOB_OPENING = "opening"
# The app job that opens the browser at its first page, under JOB_OPENING.
APP_ACTION_OPEN = "open"
JOB_DISCONNECTING = "disconnecting"
JOB_MOUNTING = "mounting"
JOB_UNMOUNTING = "unmounting"
JOB_SWITCHING = "switching"
JOB_CONNECTING = "connecting"
# The mount record states that read as a mount at work.
MOUNT_WORKING_STATES = ("pending", "queued", "mounting")
# How long a service job waits for the lane it started.
SERVICE_SETTLE_TIMEOUT_S = 300
# The page's settings a Save writes, by the name ``nclient settings`` and the
# state document give them.
SETTING_LANGUAGE = "language"
SETTING_THEME = "theme"
SETTING_SSH_INCLUDE = "is_ssh_include_enabled"


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


def is_forwardable(entry: dict, mount_shape: str = "") -> bool:
    """Whether the client forwards an entry from a loopback port.

    Args:
        entry: A published entry.
        mount_shape: The platform's mount location shape; a share is
            forwarded except where the system mounts it through the files
            adapter.

    Returns:
        True for a ``web``, ``port``, ``ssh``, ``ai`` and ``rdp`` entry, and
        for a ``file`` entry off Windows.
    """
    kind = entry.get("type")
    if kind == "file":
        return mount_shape != MOUNT_SHAPE_ADAPTER
    return kind in ("web", "port", "ssh", "ai", "rdp")


def _port_number(value) -> int:
    """A port as the hub sent it, 0 for anything else."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _setting_number(value):
    """A number the person typed, None for an empty field."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


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
        self,
        *,
        log=print,
        platform=None,
        overlay_drivers=None,
        start_thread=None,
        transport=None,
    ):
        """
        Args:
            log: Callable used for progress messages.
            platform: The machine's platform; None detects it.
            overlay_drivers: ``{provider: driver}`` for the virtual
                networks; None drives the carried engines.
            start_thread: ``start_thread(target)`` runs a job a press
                started; None uses a daemon thread. Tests pass one that
                runs inline.
            transport: The
                :class:`~neutrino_client.core.transport.ClientTransportChannel`
                every hub is reached through; None runs the carried
                transport as this resident's child.
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
        self._os_machine_id = self.platform.os_machine_id()
        config_dir = self.platform.config_dir()
        # The transport program this resident runs; the one a test gives
        # stands for a program that was found.
        self._transport_program = "given"
        self._transport = (
            transport if transport is not None else self._carried_transport()
        )
        self._store = ClientServiceStore(
            path=os.path.join(config_dir, CLIENT_STATE_FILE_NAME)
        )
        self._ports = PortLocalTable(store=self._store)
        self._forwards = ForwardListenerRegistry(
            command=self._transport.command,
            binding_of=self._binding_of,
            ports=self._ports,
            log=log,
            on_change=self.notify,
            on_refused=self._forward_refused,
        )
        # The files adapter a Windows mount goes through.
        self._files_plan = FilesAddressPlan(
            store=self._store, held_of=self._held_files_addresses
        )
        self._files_adapter = FilesAdapter(
            platform=self.platform,
            plan=self._files_plan,
            endpoint=FilesSocksEndpoint(
                plan=self._files_plan,
                connector=self._files_connector,
                entries_of=self.service_entries,
                log=log,
            ),
            log=log,
        )
        # Whoever draws the state, told after every change of it; the
        # announcements of one burst are folded into one.
        self._watchers: list = []
        # How many calls of each watcher, by its id, have not returned yet.
        self._held_watchers: dict = {}
        self._announce_lock = threading.Lock()
        self._is_announcing = False
        self._is_pending_announcement = False
        self._apps = AppServiceHandler(
            platform=self.platform,
            forwards=self._forwards,
            open_service=self.open_service,
            log=log,
        )
        self._ssh = SshConfigWriter(
            home=self.platform.home(),
            open_service=self.open_service,
            restrict_file=self.platform.restrict_to_person,
            is_windows=self.platform.os_name == "windows",
            log=log,
            on_change=self.notify,
        )
        self._services = {
            handler.service_type: handler
            for handler in (
                AiServiceHandler(
                    store=self._store,
                    original_dir=os.path.join(config_dir, CLIENT_ORIGINAL_DIR_NAME),
                    open_service=self.open_service,
                    exit_hub_id=self.exit_hub_id,
                    forwards=self._forwards,
                    log=log,
                    on_change=self.notify,
                    is_managed=self.platform.is_agent_installed,
                ),
                FileServiceHandler(
                    platform=self.platform,
                    store=self._store,
                    credentials_dir=os.path.join(
                        config_dir, CLIENT_MOUNT_CREDENTIALS_DIR_NAME
                    ),
                    forwards=self._forwards,
                    log=log,
                    on_change=self.notify,
                    entries_of=self.service_entries,
                    open_service=self.open_service,
                    adapter_host=self._files_adapter.host,
                    on_adapter_idle=self._files_adapter.down,
                ),
                RdpViewerHandler(
                    platform=self.platform,
                    open_service=self.open_service,
                    forwards=self._forwards,
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
            keep_choice=self._overlay_keep,
            drivers=overlay_drivers,
        )
        # One session per binding, by binding id, in the order joined.
        self._sessions: dict = {}
        # The bindings being left, by id.
        self._leaving: set = set()
        # The hubs whose panel is being opened, by session key, and the
        # failure the last press of Panel ended in.
        self._opening_panels: set = set()
        self._panel_errors: dict = {}
        # The step a press started on a service entry, and the failure the
        # last one ended in, by service key; the same for an app, by its hub
        # and its id.
        self._entry_jobs: dict = {}
        self._entry_errors: dict = {}
        self._app_jobs: dict = {}
        self._app_errors: dict = {}
        # The apps whose job is a Use, which is not in use until it ends.
        self._app_uses: dict = {}
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
        self._drop_repeated_hubs()
        self._reconcile_bindings(enrollment.config_stamp())

    def _carried_transport(self) -> ClientTransportChannel:
        """The transport this resident runs as its child, at the platform's listener."""
        program = (
            os.environ.get(CLIENT_TRANSPORT_BIN_ENV, "")
            or bundled_path(CLIENT_TRANSPORT_PROGRAM)
            or shutil.which(CLIENT_TRANSPORT_PROGRAM)
            or ""
        )
        self._transport_program = program
        listen = self.platform.transport_listen_path()
        return ClientTransportChannel(
            connect=self.platform.connect_transport,
            process=ClientTransportProcess(
                program=program or CLIENT_TRANSPORT_PROGRAM,
                listen=listen,
                log_path=os.path.join(
                    self.platform.log_dir(), CLIENT_TRANSPORT_LOG_NAME
                ),
                bind_child=self.platform.bind_child_process,
            ),
            log=self._log,
        )

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
            The hub the person chose, while it is a hub joined; empty when
            nobody chose one or the chosen hub was left.
        """
        with self._lock:
            chosen = self._chosen_exit_hub_id
            sessions = list(self._sessions.values())
        hub_ids = [session.hub_id() for session in sessions]
        return chosen if chosen and chosen in hub_ids else ""

    def hubs(self) -> list:
        """One row per hub joined, in the order joined.

        Returns:
            ``[{hub_id, hub_name, binding_id, gateway_url, software,
            connection, wait_reason, wait_code, next_round_at,
            reached_through, rtt_ms, is_panel_allowed, panel_forward,
            is_pending, last_error, is_exit, overlay, jobs}]``:
            ``connection`` is one of the session's five states,
            ``wait_reason`` why a ``waiting`` hub waits and empty
            otherwise, ``wait_code`` the ``{code, params}`` its last round
            ended in or None, ``next_round_at`` the moment of its next
            round in seconds since the epoch while a countdown runs and
            None otherwise, ``reached_through`` the hub's word for the way the channel
            reached it, ``rtt_ms`` the round trip of the last ping in whole
            milliseconds or None, ``is_panel_allowed`` whether this client may open
            the hub's panel, ``panel_forward`` the loopback port the panel's
            forward listens on or None, ``is_pending`` whether the join's
            ticket is not spent yet, ``last_error`` the failure of the last
            press of Panel, ``overlay`` the virtual
            network's ``{network, networks, state, stage, is_waiting,
            address, error}``, and ``jobs`` ``{is_refreshing,
            overlay_job, is_leaving, is_opening_panel}``. No token, ticket
            or secret is in it.
        """
        exit_hub_id = self.exit_hub_id()
        with self._lock:
            sessions = list(self._sessions.values())
            leaving = set(self._leaving)
            opening = set(self._opening_panels)
            panel_errors = dict(self._panel_errors)
        rows = []
        for session in sessions:
            binding = session.binding()
            hub_id = binding.get("hub_id", "")
            key = session.local_key
            panel_port = self._forwards.port_of(hub_id, FORWARD_PANEL_ID)
            panel_error = panel_errors.get(key)
            waiting = session.waiting() or {}
            rows.append(
                {
                    "hub_id": hub_id,
                    "hub_name": binding.get("hub_name", ""),
                    "binding_id": binding.get("id", ""),
                    "gateway_url": binding.get("gateway_url", ""),
                    "software": session.hub_software(),
                    "connection": session.connection(),
                    "wait_reason": waiting.get("reason", ""),
                    "wait_code": waiting.get("code"),
                    "next_round_at": waiting.get("next_round_at"),
                    "reached_through": session.reached_through(),
                    "rtt_ms": session.rtt_ms(),
                    "is_panel_allowed": session.is_panel_allowed(),
                    "panel_forward": panel_port or None,
                    "is_pending": binding.get("is_pending") is True,
                    "last_error": dict(panel_error) if panel_error else None,
                    "is_exit": bool(hub_id) and hub_id == exit_hub_id,
                    "overlay": self._overlay.hub_row(key),
                    "jobs": {
                        "is_refreshing": session.is_refreshing(),
                        "overlay_job": self._overlay.job(key),
                        "is_leaving": key in leaving,
                        "is_opening_panel": key in opening,
                    },
                }
            )
        return rows

    def notices(self) -> list:
        """What the page shows above the hubs for a while.

        Returns:
            ``[{id, code, params}]``, the newest last.
        """
        with self._lock:
            return [
                {
                    "id": notice["id"],
                    "code": notice["code"],
                    "params": dict(notice["params"]),
                }
                for notice in self._notices
            ]

    def close_notice(self, notice_id: str) -> None:
        """Take one notice down before its minute is over; an id no notice
        holds changes nothing.

        Args:
            notice_id: The notice's ``id``.
        """
        self._drop_notice(notice_id)

    def entry_rows(self) -> list:
        """The service entries of every connected hub, each with its job.

        Returns:
            The entries of :meth:`service_entries`, each with ``job``, the
            step at work on it or empty, and ``last_error``, the failure the
            last one ended in or None; every entry the client forwards also
            with ``local_port`` and ``forward``, the loopback port its
            forward listens on or None. An app's entry's and an ``ssh``
            entry's ``local_port`` is the number it forwards on, the
            person's or the hub's, with ``is_local_port_own`` saying whose,
            or None while neither names one; any other's is ``"auto"``. A
            ``file`` entry also carries ``mount_default`` and
            ``is_declared``.
        """
        entries = self.service_entries()
        file_handler = self._services["file"]
        mounts = file_handler.state().get("mounts") or []
        forwards = self._forwards.forwards()
        mount_shape = self.platform.mount_location_shape
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
            if is_forwardable(entry, mount_shape):
                if is_fixed_port_kind(str(entry.get("type", ""))):
                    own = self._ports.setting(key)
                    row["local_port"] = (
                        self._ports.app_port(key, _port_number(entry.get("local_port")))
                        or None
                    )
                    row["is_local_port_own"] = isinstance(own, int)
                else:
                    row["local_port"] = "auto"
                row["forward"] = forwards.get(key)
            if entry.get("type") == "file":
                row.update(file_handler.entry_fields(entry))
            rows.append(row)
        return rows

    def app_rows(self) -> list:
        """The apps of every connected hub, each with its job and whether it is in use.

        Every app the hub publishes is here, the machine's SSH server
        among them, whose local name names the machine of its ``ssh``
        entries; the page draws an app that has a ``web`` or ``port`` entry.

        Returns:
            ``[{hub_id, id, title, source, device_id, device_name,
            local_name, job, last_error, is_in_use}]``, hub order; an app
            is not in use while its Use runs.
        """
        entries = self.service_entries()
        with self._lock:
            sessions = list(self._sessions.values())
            jobs = dict(self._app_jobs)
            errors = dict(self._app_errors)
            uses = set(self._app_uses)
        rows = []
        for session in sessions:
            hub_id = session.hub_id()
            for app in session.app_entries():
                app = dict(app, hub_id=hub_id)
                key = service_key(hub_id, app["id"])
                error = errors.get(key)
                rows.append(
                    dict(
                        app,
                        job=jobs.get(key, ""),
                        last_error=dict(error) if error else None,
                        is_in_use=key not in uses
                        and self._apps.is_in_use(app=app, entries=entries),
                    )
                )
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
            ``[{hub_id, session_id, device_id, account, owner, owner_name,
            is_owned, is_persistent, is_shared, attached_count, title,
            started_at}]``
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
        """What a mount location is here: ``path``, ``drive_letter`` or ``volume``."""
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

    def is_ssh_include_enabled(self) -> bool:
        """Whether ``~/.ssh/config`` holds the line that includes Neutrino's own."""
        return self._ssh.is_include_installed()

    def ssh_config(self) -> dict:
        """``~/.ssh/neutrino_config`` as it stands.

        Returns:
            ``{"path", "text"}``.
        """
        return self._ssh.config_text()

    def apply_settings(self, body: dict) -> dict:
        """Keep the Settings page's values, each one given, and say so.

        Args:
            body: ``{language, theme, is_ssh_include_enabled}``, any of them.

        Returns:
            Empty when kept; ``setting_value_unknown {name, value}`` for a
            value the setting does not take, nothing kept then;
            ``fs_refused`` when ``~/.ssh/config`` cannot be written.
        """
        language = body.get(SETTING_LANGUAGE)
        theme = body.get(SETTING_THEME)
        include = body.get(SETTING_SSH_INCLUDE)
        for name, value, is_taken in (
            (SETTING_LANGUAGE, language, language in CLIENT_LANGUAGES),
            (SETTING_THEME, theme, theme in CLIENT_THEMES),
            (SETTING_SSH_INCLUDE, include, isinstance(include, bool)),
        ):
            if value is not None and not is_taken:
                return {
                    "code": "setting_value_unknown",
                    "params": {"name": name, "value": str(value)},
                }
        if language is not None:
            self._store.set_language(language)
        if theme is not None:
            self._store.set_theme(theme)
        if include is not None:
            try:
                self._ssh.set_include(include)
            except OSError as error:
                return {"code": "fs_refused", "params": {"detail": str(error)[:200]}}
        self.notify()
        return {}

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

        The binding, the session, its forwards, mounts, viewers and network
        go here and now; the hub is told once after, from a thread of its
        own, and its answer, or none, changes nothing.

        Args:
            hub_id: The hub to leave, by its id or by its binding's id;
                empty names the one hub joined.

        Raises:
            KeyError: If ``hub_id`` names no hub this person has joined, or
                is empty while several are.
            OSError: When the binding file cannot be written; nothing is
                let go of then.
        """
        session = self._session_for(hub_id)
        binding = session.binding()
        enrollment.remove_binding(binding["id"])
        self._forget_session(session)
        self._follow_exit()
        if binding.get("is_pending") is not True:
            threading.Thread(
                target=self._tell_hub_left,
                args=(session,),
                name="client_leave",
                daemon=True,
            ).start()
        self._log("left the hub")

    def leave(self, hub_id: str = "") -> None:
        """Start leaving one hub: the row shows it at once, and goes once the
        binding is forgotten, which never waits on the hub.

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

        Each connected, connecting or waiting hub loses its error line and
        its virtual network's error, its entries and its apps lose theirs,
        and it waits as refreshing until its answer; a hub the session does
        not refresh is left as it is. Every notice goes. A press while any
        hub still refreshes asks no hub again and is logged.
        """
        with self._lock:
            sessions = list(self._sessions.values())
            self._notices = []
        if any(session.is_refreshing() for session in sessions):
            self._log("a refresh while one runs was dropped")
            self.notify()
            return
        for session in sessions:
            if not session.refresh():
                continue
            hub_id = session.hub_id()
            self._overlay.clear_error(session.local_key)
            with self._lock:
                self._panel_errors.pop(session.local_key, None)
                for table in (self._entry_errors, self._app_errors):
                    for key in [key for key in table if key.startswith(hub_id + "/")]:
                        table.pop(key, None)
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

    def open_panel(self, hub_id: str) -> dict:
        """Start opening one hub's panel, as that hub's job.

        The job is written and announced before this returns; on a thread
        of its own the panel's forward is made when the hub has none, and
        the browser opens at the forward. A press while the panel is being
        opened is dropped and logged.

        Args:
            hub_id: The hub, by its id or by its binding's id.

        Returns:
            Empty, the press taken or dropped; ``unknown_hub`` for a hub
            this person has not joined, ``permission_denied`` while the
            hub's state does not allow the panel, ``client_disabled`` while
            the hub has this client switched off, ``hub_unreachable`` while
            it is not connected.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        if not session.is_panel_allowed():
            return {"code": "permission_denied", "params": {"kind": "panel"}}
        connection = session.connection()
        if connection == CONNECTION_DISABLED:
            return {"code": "client_disabled", "params": {}}
        if connection != CONNECTION_CONNECTED:
            return {"code": "hub_unreachable", "params": {}}
        key = session.local_key
        with self._lock:
            is_dropped = key in self._opening_panels
            if not is_dropped:
                self._opening_panels.add(key)
                self._panel_errors.pop(key, None)
        if is_dropped:
            self._log(f"a press on the panel of {session.binding_id} was dropped")
            return {}
        self.notify()
        self._start_thread(functools.partial(self._open_panel_now, session))
        return {}

    def open_connect(self, hub_id: str, entry_id: str) -> ClientStream:
        """Open one ``connect`` stream to a published entry, for any part of the resident.

        Any thread may call it. The stream is a connection of its own to the
        transport; the hub judges it and refuses it with a code before its
        accept, which ``read`` sees as the end and ``wait_close`` raises.
        After the accept it carries the connection's raw bytes: ``send``
        writes them, ``read(timeout_s)`` gives the next, empty at the end
        and None when nothing came in time, and ``close()`` ends the stream
        from this side.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            entry_id: The published entry's id.

        Returns:
            The open stream.

        Raises:
            GatewayUnreachable: When this person has not joined that hub or
                it is not connected.
        """
        return self._open_connect_args(hub_id, {"id": entry_id})

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
        is_shared: bool = False,
        account: str = "",
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
            is_shared: Whether a new session is shared from its start.
            account: The enabled account a new shell runs as; empty for the
                machine's first.

        Returns:
            ``{"terminal_id", "session_id"}``; ``unknown_hub``,
            ``unknown_terminal`` for a machine the hub offers no terminal on,
            or ``hub_unreachable`` otherwise.
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
                device_id,
                cols,
                rows,
                session_id,
                is_resumed=is_resumed,
                is_shared=is_shared and not is_resumed,
                account=account,
            )
        except GatewayUnreachable as error:
            return {"code": "hub_unreachable", "params": {"detail": str(error)}}
        terminal_id = uuid.uuid4().hex
        bridge = TerminalBridge(stream=stream, session_id=session_id)
        with self._lock:
            self._terminals[terminal_id] = (session, bridge)
        self._log(f"a terminal on {device_id} is open")
        return {"terminal_id": terminal_id, "session_id": session_id}

    def open_exec(
        self,
        hub_id: str,
        device_id: str,
        argv: list,
        is_tty: bool,
        cols: int,
        rows: int,
        account: str = "",
    ) -> dict:
        """Run one command on one machine a hub offers, for a terminal to attach to.

        The terminal's two connections carry pieces, as
        :class:`~neutrino_client.core.terminal.ExecBridge` reads and writes
        them.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            device_id: The machine, as the hub's ``terminals`` names it.
            argv: The command and its arguments.
            is_tty: Whether it runs on a pseudo-terminal.
            cols: The pseudo-terminal's width in columns.
            rows: The pseudo-terminal's height in rows.
            account: The enabled account it runs as; empty for the
                machine's first.

        Returns:
            ``{"terminal_id"}``; ``unknown_hub``, ``unknown_terminal`` for a
            machine the hub offers no terminal on, or ``hub_unreachable``
            otherwise.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        known = {entry["device_id"] for entry in session.terminal_entries()}
        if device_id not in known:
            return {"code": "unknown_terminal", "params": {"device_id": device_id}}
        try:
            stream = session.open_exec(device_id, argv, is_tty, cols, rows, account)
        except GatewayUnreachable as error:
            return {"code": "hub_unreachable", "params": {"detail": str(error)}}
        terminal_id = uuid.uuid4().hex
        bridge = ExecBridge(stream=stream, is_tty=is_tty)
        with self._lock:
            self._terminals[terminal_id] = (session, bridge)
        self._log(f"a command on {device_id} is open")
        return {"terminal_id": terminal_id}

    def open_ssh_proxy(self, hub_id: str, entry_id: str) -> dict:
        """Open a ``connect`` stream to one ``ssh`` entry, for ``nclient ssh proxy``.

        The proxy's two connections carry its standard input up the stream
        and the stream's bytes back, raw, as a terminal's do.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            entry_id: The ``ssh`` entry.

        Returns:
            ``{"terminal_id"}``; ``unknown_hub``, ``service_unknown`` for an
            entry the hub does not list as ``ssh``, or ``hub_unreachable``.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        if not any(
            entry.get("id") == entry_id and entry.get("type") == "ssh"
            for entry in session.service_entries()
        ):
            return {"code": "service_unknown", "params": {"service_id": entry_id}}
        try:
            stream = session.open_connect({"id": entry_id})
        except GatewayUnreachable as error:
            return {"code": "hub_unreachable", "params": {"detail": str(error)}}
        terminal_id = uuid.uuid4().hex
        with self._lock:
            self._terminals[terminal_id] = (session, TerminalBridge(stream=stream))
        self._log(f"an ssh proxy to {entry_id} is open")
        return {"terminal_id": terminal_id}

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
            Empty on success; ``unknown_terminal``, or ``shell_unknown`` for
            a terminal whose stream has ended.
        """
        opened = self._terminal(terminal_id)
        if opened is None:
            return {"code": "unknown_terminal", "params": {}}
        if not opened[1].resize(cols, rows):
            return {"code": "shell_unknown", "params": {"shell": terminal_id}}
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
        account: str = "",
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
            account: The enabled account a new shell runs as; empty for the
                machine's first.

        Returns:
            ``{"terminal_id", "session_id"}``; ``unknown_hub``,
            ``unknown_terminal`` or ``hub_unreachable`` otherwise.
        """
        outcome = self.open_terminal(
            hub_id, device_id, cols, rows, session_id, account=account
        )
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

    def clear_terminal(self, terminal_id: str) -> dict:
        """Clear the window's terminal: Ctrl+C to the shell, and its output
        dropped until the stream is quiet.

        ``{"id", "clearing": True}`` is pushed at once, and ``{"id",
        "clearing": False}`` once the output is drawn again.

        Args:
            terminal_id: The terminal.

        Returns:
            Empty when Ctrl+C went; ``unknown_terminal`` for a terminal that
            is not open, ``shell_unknown`` for one whose shell has ended.
        """
        opened = self._terminal(terminal_id)
        if opened is None:
            return {"code": "unknown_terminal", "params": {}}
        self._hand_terminal({"id": terminal_id, "clearing": True})
        if not opened[1].clear():
            return {"code": "shell_unknown", "params": {"shell": terminal_id}}
        return {}

    def persist_terminal(
        self,
        terminal_id: str,
        is_persistent: "bool | None" = None,
        is_shared: "bool | None" = None,
    ) -> dict:
        """Set whether one terminal's shell session outlives its windows, and who sees it.

        The session's row in the state document takes the values given at
        once on success; the next state from the hub confirms them.

        Args:
            terminal_id: The terminal.
            is_persistent: Whether the machine keeps the session; None
                leaves it.
            is_shared: Whether every client with terminal rights on the
                machine lists it; None leaves it.

        Returns:
            Empty on success; ``unknown_terminal``, the hub's refusal,
            ``session_not_owned`` among them, or ``hub_unreachable``.
        """
        opened = self._terminal(terminal_id)
        if opened is None:
            return {"code": "unknown_terminal", "params": {}}
        session, bridge = opened
        return self._persist(session, bridge.session_id, is_persistent, is_shared)

    def persist_terminal_session(
        self,
        hub_id: str,
        session_id: str,
        is_persistent: "bool | None" = None,
        is_shared: "bool | None" = None,
    ) -> dict:
        """Set whether one shell session a hub's machine keeps outlives its
        windows, and who sees it, attached or not.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            session_id: The shell session's id.
            is_persistent: Whether the machine keeps the session; None
                leaves it.
            is_shared: Whether every client with terminal rights on the
                machine lists it; None leaves it.

        Returns:
            Empty on success; ``unknown_hub``, the hub's refusal,
            ``session_not_owned`` and ``session_unknown`` among them, or
            ``hub_unreachable``.
        """
        session = self._find_session(hub_id)
        if session is None:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        return self._persist(session, session_id, is_persistent, is_shared)

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

    def open_app(self, hub_id: str, app_id: str) -> dict:
        """Start using one app, as that app's job: every entry forwarded, nothing opened.

        A press while the app is at work is dropped and logged.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            app_id: The app's id.

        Returns:
            Empty, the press taken or dropped; ``unknown_app`` for an app the
            hub does not list, ``client_disabled`` while the hub has this
            client switched off.
        """
        return self._app_press(hub_id, app_id, JOB_OPENING)

    def open_app_page(self, hub_id: str, app_id: str) -> dict:
        """Open the browser at one app's first page, as that app's job.

        A press while the app is at work is dropped and logged.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            app_id: The app's id.

        Returns:
            Empty, the press taken or dropped; ``unknown_app`` for an app the
            hub does not list, ``client_disabled`` while the hub has this
            client switched off, ``app_no_page`` for an app with no ``http``
            or ``https`` entry, ``app_not_in_use`` while that entry has no
            forward.
        """
        found = self._find_app(hub_id, app_id)
        if found is not None:
            app, entries = found
            page = self._apps.page_entry(app=app, entries=entries)
            if page is None:
                return {"code": "app_no_page", "params": {}}
            if not self._forwards.port_of(app["hub_id"], str(page.get("id", ""))):
                return {"code": "app_not_in_use", "params": {}}
        return self._app_press(hub_id, app_id, JOB_OPENING, action=APP_ACTION_OPEN)

    def stop_app(self, hub_id: str, app_id: str) -> dict:
        """End every forward of one app, as that app's job.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            app_id: The app's id.

        Returns:
            Empty, the press taken or dropped; ``unknown_app`` for an app the
            hub does not list.
        """
        return self._app_press(hub_id, app_id, JOB_DISCONNECTING)

    def configure_app(self, hub_id: str, app_id: str, ports: dict) -> dict:
        """Set the local ports of one app's entries on this client.

        Args:
            hub_id: The hub, by its id or by its binding's id.
            app_id: The app's id.
            ports: ``{entry name: number or None}``; None goes back to the
                hub's number. An entry the map does not name is left as it is.

        Returns:
            Empty when kept, nothing kept on a refusal: ``unknown_app``,
            ``app_in_use`` while the app is in use, ``unknown_request`` for
            an entry name the app has not, ``local_port_invalid {port}`` or
            ``port_taken {port}`` for a number one entry cannot take.
        """
        found = self._find_app(hub_id, app_id)
        if found is None:
            return {"code": "unknown_app", "params": {"app_id": app_id}}
        app, entries = found
        if self._apps.is_in_use(app=app, entries=entries):
            return {"code": "app_in_use", "params": {}}
        named = {
            str(entry.get("name", "")): entry for entry in app_entries(app, entries)
        }
        if any(name not in named for name in ports):
            return {"code": "unknown_request", "params": {}}
        changes = {}
        for name, port in ports.items():
            entry = named[name]
            key = service_key(app["hub_id"], str(entry.get("id", "")))
            changes[key] = (_setting_number(port), entry_protocol(entry))
        hub_numbers = {
            service_key(entry.get("hub_id", ""), entry.get("id", "")): (
                _port_number(entry.get("local_port")),
                entry_protocol(entry),
            )
            for entry in entries
            if is_fixed_port_kind(str(entry.get("type", "")))
            and service_key(entry.get("hub_id", ""), entry.get("id", "")) not in changes
        }
        taken: dict = {}
        for key, (number, protocol) in changes.items():
            if number is None:
                continue
            outcome = self._ports.check_own(
                key, number, protocol, hub_numbers, tuple(changes)
            )
            if not outcome and (number, protocol) in taken:
                outcome = {"code": "port_taken", "params": {"port": number}}
            if outcome:
                return outcome
            taken[(number, protocol)] = key
        for key, (number, protocol) in changes.items():
            self._ports.set_own(key, number, protocol)
        self.notify()
        return {}

    def open_service(
        self, hub_id: str, entry_id: str, timeout_s: float = CLIENT_STREAM_TIMEOUT_S
    ) -> dict:
        """Ask one entry's material of its hub with the ``service`` frame.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The published entry's id.
            timeout_s: How long to wait for the reply.

        Returns:
            The reply's ``params``: the entry's material.

        Raises:
            GatewayRefusedDetail: When the hub replied with a code.
            GatewayUnreachable: When this person has not joined that hub,
                its session is down or ends, or no reply arrives in time.
        """
        session = self._find_session(hub_id)
        if session is None:
            raise GatewayUnreachable("this person has not joined that hub")
        return session.ask_service(entry_id, timeout_s)

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
        self._check_ai_gate()
        self._transport.on_ready(self._transport_ready)
        self._transport.on_lost(self._transport_lost)
        self._transport.on_forward_end(self._forwards.take_end)
        if not self._transport_program:
            self._add_notice("transport_missing", {})
        self._transport.start()
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

    def arrange_relaunch(self) -> None:
        """Have this client started again once the installer that asked it to quit is done.

        A refusal is logged; the quit goes on either way.
        """
        try:
            is_arranged = self.platform.register_relaunch()
        except OSError as error:
            self._log(f"the restart after the upgrade could not be arranged: {error}")
            return
        if is_arranged:
            self._log("the client starts again once the upgrade is installed")

    def shutdown(self) -> None:
        """Let go of everything and stop every loop. Idempotent.

        The order is the one that leaves the machine as it was found: the
        hubs undialled, the virtual networks counted and kept, the tools
        restored, the shares unmounted, the viewers closed, the forwards
        closed, the files adapter taken down and its endpoint stopped, then
        the transport ended.
        The steps share
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
        self._files_adapter.stop()
        self._transport.stop()
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
                self._tell_watcher(watcher)
            with self._announce_lock:
                if not self._is_pending_announcement:
                    self._is_announcing = False
                    return

    def _tell_watcher(self, watcher) -> None:
        """Tell one watcher, waiting for it no longer than ``ANNOUNCE_WATCHER_WAIT_S``.

        A watcher that does not come back, as a window whose script call
        never answers, holds its own thread and never the announcements:
        the next change is told on a thread of its own, up to
        ``ANNOUNCE_WATCHER_HELD_MAX`` held at once.
        """
        with self._lock:
            held = self._held_watchers.get(id(watcher), 0)
            if held >= ANNOUNCE_WATCHER_HELD_MAX:
                return
            self._held_watchers[id(watcher)] = held + 1

        def tell() -> None:
            try:
                watcher()
            except Exception as error:  # noqa: BLE001 - a watcher's own
                self._log(f"a state watcher failed: {error}")
            finally:
                with self._lock:
                    self._held_watchers[id(watcher)] -= 1

        teller = threading.Thread(target=tell, name="client_announce", daemon=True)
        teller.start()
        teller.join(timeout=ANNOUNCE_WATCHER_WAIT_S)
        if teller.is_alive():
            self._log(
                f"a state watcher did not return in {ANNOUNCE_WATCHER_WAIT_S}s; "
                "the next change is told without it"
            )

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
        if service_type == "file":
            return key, JOB_UNMOUNTING if action == "unmount" else JOB_MOUNTING
        if service_type == "ai":
            return key, JOB_SWITCHING
        if service_type == "rdp":
            return key, JOB_CONNECTING
        return key, ""

    def _app_press(self, hub_id: str, app_id: str, job: str, action: str = "") -> dict:
        """Start one app's Use, Open or Stop as its job, written before this returns."""
        found = self._find_app(hub_id, app_id)
        if found is None:
            return {"code": "unknown_app", "params": {"app_id": app_id}}
        app, _entries = found
        session = self._find_session(app["hub_id"])
        if job == JOB_OPENING and session is not None:
            if session.connection() == CONNECTION_DISABLED:
                return {"code": "client_disabled", "params": {}}
        key = service_key(app["hub_id"], app["id"])
        with self._lock:
            is_dropped = key in self._app_jobs
            if not is_dropped:
                self._app_jobs[key] = job
                if job == JOB_OPENING and action != APP_ACTION_OPEN:
                    self._app_uses[key] = True
                self._app_errors.pop(key, None)
        if is_dropped:
            self._log(f"a press on the app {key} while it works was dropped")
            return {}
        self.notify()
        self._start_thread(functools.partial(self._run_app_job, app, key, job, action))
        return {}

    def _run_app_job(self, app: dict, key: str, job: str, action: str = "") -> None:
        """Run one app's Use, Open or Stop, then write how it ended and announce it."""
        try:
            entries = self.service_entries()
            if action == APP_ACTION_OPEN:
                outcome = self._apps.open_page(app=app, entries=entries)
            elif job == JOB_OPENING:
                outcome = self._apps.use(app=app, entries=entries)
            else:
                self._apps.stop(app=app, entries=entries)
                outcome = {}
        except Exception as error:  # noqa: BLE001 - reported on the row
            self._log(f"{key}: the job crashed: {type(error).__name__}: {error}")
            outcome = {"code": "crashed", "params": {"detail": str(error)[:200]}}
        with self._lock:
            self._app_jobs.pop(key, None)
            self._app_uses.pop(key, None)
            if outcome:
                self._app_errors[key] = dict(outcome)
        self.notify()

    def _find_app(self, hub_id: str, app_id: str) -> "tuple[dict, list] | None":
        """One app a connected hub lists, stamped with its hub, and the merged entries."""
        session = self._find_session(hub_id)
        if session is None:
            return None
        for app in session.app_entries():
            if app.get("id") == app_id:
                return dict(app, hub_id=session.hub_id()), self.service_entries()
        return None

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
            self._log(f"{key}: the job crashed: {type(error).__name__}: {error}")
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

    def _persist(self, session, session_id: str, is_persistent, is_shared) -> dict:
        """Send one ``persist`` and show its flags at once on success."""
        outcome = _hub_answer(
            session.persist_shell, session_id, is_persistent, is_shared
        )
        if not outcome:
            session.note_session_flags(session_id, is_persistent, is_shared)
            self.notify()
        return outcome

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

        def cleared() -> None:
            self._hand_terminal({"id": terminal_id, "clearing": False})

        bridge.pump_out(write, cleared)
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
            transport=self._transport,
            hostname=self.hostname(),
            platform_tuple=self._platform_tuple,
            os_machine_id=self._os_machine_id,
            log=self._log,
            on_change=self.notify,
            on_services=self._hub_services,
            on_disabled=self._hub_disabled,
            on_unbound=self._hub_unbound,
            on_joined=self._hub_joined,
            on_welcomed=self._hub_welcomed,
            local_networks=self.platform.local_networks,
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
            self._opening_panels.discard(session.local_key)
            self._panel_errors.pop(session.local_key, None)
            tables = (
                self._entry_jobs,
                self._entry_errors,
                self._app_jobs,
                self._app_errors,
                self._app_uses,
            )
            for table in tables:
                for key in [key for key in table if key.startswith(hub_id + "/")]:
                    table.pop(key, None)
            is_last = not self._sessions
        session.stop()
        self._release_hub(hub_id or session.binding_id, session.local_key)
        self._services["file"].drop_withdrawn(hub_id=hub_id, entries=[])
        if hub_id:
            self._files_plan.forget_hub(hub_id)
        self._services["ai"].refresh(entries=self.service_entries())
        if is_last:
            self._ssh.clear()
        else:
            self._refresh_ssh()
        self.notify()

    def _refresh_ssh(self) -> None:
        """Give the SSH configuration the machines every connected hub lists now."""
        with self._lock:
            sessions = list(self._sessions.values())
        apps = []
        hub_names = {}
        for session in sessions:
            hub_id = session.hub_id()
            hub_names[hub_id] = session.hub_name()
            apps.extend(dict(app, hub_id=hub_id) for app in session.app_entries())
        self._ssh.refresh(
            entries=self.service_entries(), apps=apps, hub_names=hub_names
        )

    def _transport_ready(self) -> None:
        """The transport started: every hub is dialled and every forward started again."""
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session.transport_ready()
        self._forwards.restart()

    def _transport_lost(self) -> None:
        """The transport ended: no hub has a session until it is back."""
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session.transport_lost()
        self.notify()

    def _binding_of(self, hub_id: str) -> str:
        """The label the transport knows a hub's binding by; empty for a hub not joined."""
        session = self._find_session(hub_id)
        return session.label if session is not None else ""

    def _hub_services(self, session: ClientHubSession) -> None:
        """A hub's state arrived: its forwards, its shares, its exit grant, its
        SSH machines and its network may change."""
        self._forwards.drop_withdrawn(
            hub_id=session.hub_id(), entries=session.service_entries()
        )
        self._keep_ssh_forwards(session)
        self._services["file"].drop_withdrawn(
            hub_id=session.hub_id(), entries=session.service_entries()
        )
        self._check_ai_gate()
        self._services["ai"].refresh(entries=self.service_entries())
        self._refresh_ssh()
        self._overlay.refresh()

    def _keep_ssh_forwards(self, session: ClientHubSession) -> None:
        """Forward every ``ssh`` entry of one hub; a failure is its entry's error."""
        hub_id = session.hub_id()
        outcomes = keep_forwards(
            self._forwards, hub_id=hub_id, entries=session.service_entries()
        )
        with self._lock:
            for entry_id, refusal in outcomes.items():
                key = service_key(hub_id, entry_id)
                if refusal:
                    self._entry_errors[key] = dict(refusal)
                else:
                    self._entry_errors.pop(key, None)
        for entry_id, refusal in outcomes.items():
            if refusal:
                self._log(f"the ssh forward of {entry_id} failed: {refusal['code']}")

    def _hub_joined(self, session: ClientHubSession, binding: dict) -> None:
        """A pending join was completed: keep it where the binding file is read.

        A session holding the id the hub gave, as a join again from this
        machine lands on, ends before the hello as at a leave, and the hub
        is not told; the completed binding keeps its hub's id and name.

        Raises:
            OSError: When the binding file cannot be written.
        """
        with self._binding_lock:
            with self._lock:
                replaced = [
                    held
                    for held in self._sessions.values()
                    if held is not session and held.binding_id == binding.get("id")
                ]
            for held in replaced:
                if held.hub_id():
                    binding = dict(
                        binding, hub_id=held.hub_id(), hub_name=held.hub_name()
                    )
            session.adopt_join(binding)
            with self._lock:
                for held in replaced:
                    self._sessions.pop(held.local_key, None)
        self._end_replaced(replaced, is_told=False)

    def _hub_welcomed(self, session: ClientHubSession, hub_id: str) -> None:
        """A welcome named its hub: every other binding to that hub ends as
        at a leave, and the hub is told of each one that holds a token.

        A binding the file cannot forget keeps its session, and is logged.
        """
        replaced = []
        with self._binding_lock:
            with self._lock:
                if not hub_id or self._sessions.get(session.local_key) is not session:
                    return
                held = [
                    other
                    for other in self._sessions.values()
                    if other is not session and other.hub_id() == hub_id
                ]
            for other in held:
                try:
                    enrollment.remove_binding(other.binding_id)
                except OSError as error:
                    self._log(f"could not forget the binding here: {error}")
                    continue
                with self._lock:
                    self._sessions.pop(other.local_key, None)
                replaced.append(other)
        self._end_replaced(replaced, is_told=True)

    def _end_replaced(self, replaced: list, is_told: bool) -> None:
        """End the sessions a join replaced, with what they held.

        Args:
            replaced: The sessions, already out of the binding file and of
                the sessions held.
            is_told: Whether the hub is told of each one that holds a token.
        """
        for session in replaced:
            self._log(f"the join replaced the binding {session.binding_id} held here")
            self._forget_session(session)
            binding = session.binding()
            if is_told and binding.get("token") and not binding.get("is_pending"):
                self._start_thread(functools.partial(self._tell_hub_left, session))
        if replaced:
            self._overlay.refresh()

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

    def _overlay_route(self, hub_id: str, host: str, provider: str) -> None:
        """A hub's virtual network turned on at this address, or went off."""
        session = self._find_session(hub_id)
        if session is not None:
            session.set_overlay_route(host, provider)

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
        """A hub holds no such binding: let go of what it published.

        The binding and its row stay, waiting on ``unknown_device`` until
        the person leaves the hub.
        """
        self._release_hub(session.hub_id(), session.local_key)

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
        """Leave one hub; only a binding file that cannot be written keeps
        the row, and a hub already gone is logged."""
        try:
            self.disconnect(session.binding_id)
        except (KeyError, OSError) as error:
            self._log(f"could not forget the binding here: {error}")
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

    def _drop_repeated_hubs(self) -> None:
        """Keep one binding per hub id, the one joined last, and tell the hub
        of each other one that holds a token."""
        try:
            dropped = enrollment.drop_repeated_hubs()
        except OSError as error:
            self._log(f"could not forget the repeated bindings here: {error}")
            return
        for binding in dropped:
            self._log(f"dropped the binding {binding['id']}: a later one holds its hub")
            if binding.get("token"):
                self._start_thread(functools.partial(self._tell_hub_left, binding))

    def _tell_hub_left(self, left) -> None:
        """Tell the hub this client left it, through the transport, once it runs.

        Args:
            left: The session of the binding left, or the binding itself.
        """
        session = left
        if isinstance(left, dict):
            session = ClientHubSession(
                binding=left,
                transport=self._transport,
                hostname=self.hostname(),
                platform_tuple=self._platform_tuple,
                log=self._log,
            )
        if not self._transport.wait_ready(CLIENT_TRANSPORT_START_TIMEOUT_S):
            self._log("could not tell the hub we are leaving: no transport")
            return
        outcome = session.tell_left()
        if outcome:
            self._log(f"could not tell the hub we are leaving: {outcome['code']}")

    def _follow_exit(self) -> None:
        """Clear the stored choice once the hub it names is gone."""
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

    def _check_ai_gate(self) -> None:
        """Look whether the agent is installed, which holds the AI page."""
        try:
            self._services["ai"].check_gate()
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            self._log(f"ai: could not look for the agent: {error}")

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
        """What one shutdown step releases: the networks, the forwards, or a handler."""
        if service_type == "overlay":
            return self._overlay
        if service_type == "forwards":
            return self._forwards
        return self._services[service_type]

    def _open_connect_args(self, hub_id: str, args: dict) -> ClientStream:
        """Open one ``connect`` stream on a hub with the open's own arguments.

        Raises:
            GatewayUnreachable: When this person has not joined that hub or
                its socket is not up.
        """
        session = self._find_session(hub_id)
        if session is None:
            raise GatewayUnreachable("this person has not joined that hub")
        return session.open_connect(args)

    def _forward_refused(self, hub_id: str, entry_id: str, refusal: dict) -> None:
        """A forward ended with a code: its entry's error line, and its app's."""
        app_id = next(
            (
                str(entry.get("app_id", "") or "")
                for entry in self.service_entries()
                if entry.get("hub_id") == hub_id and entry.get("id") == entry_id
            ),
            "",
        )
        with self._lock:
            self._entry_errors[service_key(hub_id, entry_id)] = dict(refusal)
            if app_id:
                self._app_errors[service_key(hub_id, app_id)] = dict(refusal)
        self.notify()

    def _files_connector(self, hub_id: str, entry_id: str) -> ConnectStreamSocket:
        """One ``connect`` stream to a file entry, as the files endpoint takes it.

        Raises:
            GatewayUnreachable: When this person has not joined that hub or
                its socket is not up.
        """
        return ConnectStreamSocket(self.open_connect(hub_id, entry_id))

    def _held_files_addresses(self) -> set:
        """The files adapter addresses a kept mount record names."""
        pairs = self._services["file"].adapter_pairs()
        return {
            address
            for address, record in self._store.files_addresses().items()
            if (record["hub_id"], record["machine"], record["user"]) in pairs
        }

    def _open_panel_now(self, session: ClientHubSession) -> None:
        """Take a sign-in token, make the panel's forward when the hub has none,
        and open the browser at it, signed in.

        The token goes into the address the browser is told to open and
        nowhere else: no log line, no state, nothing kept after.
        """
        key = session.local_key
        hub_id = session.hub_id()
        outcome: dict = {}
        try:
            material = session.ask_panel_service()
            token = str((material or {}).get("token", "") or "")
            if not token:
                outcome = {"code": "web_token_missing", "params": {}}
            else:
                port = self._forwards.ensure(
                    hub_id=hub_id, entry_id=FORWARD_PANEL_ID, kind=FORWARD_KIND_PANEL
                )
                self.platform.open_url(
                    panel_url(hub_id, port, token, self.platform.os_name)
                )
            token = ""
        except (GatewayRefusedDetail, GatewayUnreachable, GatewayUntrusted) as error:
            outcome = channel_refusal(error)
        except OSError as error:
            outcome = forward_refusal(error)
        except Exception as error:  # noqa: BLE001 - reported on the row
            outcome = {"code": "crashed", "params": {"detail": type(error).__name__}}
        with self._lock:
            self._opening_panels.discard(key)
            if outcome:
                self._panel_errors[key] = outcome
        self.notify()

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
