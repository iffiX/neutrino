"""One hub's session: a binding, its socket, and the reconnect that holds it.

A session belongs to one binding and speaks to one hub. It holds the socket
open and reconnects when it drops, through the first of the hub's addresses
that answers, the hub's name on the network this machine stands on first; a
network change under the machine starts a round at once. The hub pushes its
``state``, the addresses it answers on, the services it publishes and
whether this client is switched off, and the session answers each state and
every interval with a ``report``. What a
service handler needs from the hub comes down a ``service`` stream the
session opens on request, and a terminal on a managed machine comes down a
``shell`` stream carrying bytes both ways. The resident owns the handlers and the store; the
session tells it what changed through its callbacks and never touches them.

A ``refused`` frame ends the socket whenever it arrives, and says the same
as one that arrives instead of the welcome: its code decides what becomes
of the binding.

The connection is one of six states: ``connected``, ``connecting`` while a
round runs or a lost socket is about to be opened again, ``down`` once a
round ended in a code and the backoff runs, ``replaced`` while another
socket holds the binding, ``disabled`` while the hub has this client
switched off, and ``pending`` while a join's ticket is not spent: the
first address that answers with the pinned certificate spends it before
the hello, and a hub that refuses it leaves the session down for good. A
refresh is the same loop moved to now.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import threading
import time
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
    CLIENT_REFRESH_TIMEOUT_S,
    CLIENT_REFUSAL_CODE_BINDING_UNKNOWN,
    CLIENT_REPORT_INTERVAL_S,
    CLIENT_ROLE,
    CLIENT_ROTATE_DELAY_S,
    CLIENT_SHELL_PERSIST_VERB,
    CLIENT_SHELL_RESIZE_MODULE,
    CLIENT_SHELL_RESIZE_VERB,
    CLIENT_SHELL_STOP_VERB,
    CLIENT_SOFTWARE_PREFIX,
    CLIENT_STREAM_CODE_KIND_UNKNOWN,
    CLIENT_STREAM_KIND_COMMAND,
    CLIENT_STREAM_KIND_SERVICE,
    CLIENT_STREAM_KIND_SHELL,
    CLIENT_STREAM_TIMEOUT_S,
    CLIENT_WS_CLOSE_REPLACED,
    PROTOCOL,
)
from neutrino_client.core import enrollment, protocol
from neutrino_client.core.channel import refusal_error
from neutrino_client.core.streams import ClientStream, ClientStreamRegistry
from neutrino_client.core.ws_client import WebSocketClient, close_error
from neutrino_client.exceptions import (
    EnrollmentError,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    SocketClosed,
)

# How the five connection states of a session are named to every surface.
CONNECTION_CONNECTED = "connected"
CONNECTION_CONNECTING = "connecting"
CONNECTION_DOWN = "down"
CONNECTION_REPLACED = "replaced"
CONNECTION_DISABLED = "disabled"
CONNECTION_PENDING = "pending"
CONNECTION_STATES = (
    CONNECTION_CONNECTED,
    CONNECTION_CONNECTING,
    CONNECTION_DOWN,
    CONNECTION_REPLACED,
    CONNECTION_DISABLED,
    CONNECTION_PENDING,
)
# The states a refresh acts on; the other two change only by a person's
# Reconnect or by the hub.
CONNECTION_REFRESHABLE = (
    CONNECTION_CONNECTED,
    CONNECTION_CONNECTING,
    CONNECTION_DOWN,
    CONNECTION_PENDING,
)

# How long a stop waits for the loop thread to come back, its connect in
# progress aborted.
STOP_JOIN_TIMEOUT_S = 1


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


def _adopt_join(session, binding: dict) -> None:
    """Keep a completed join on the session that made it.

    Raises:
        OSError: When the binding file cannot be written.
    """
    session.adopt_join(binding)


def clean_terminals(value) -> dict:
    """The state's ``terminals`` as the session holds it: machines and sessions.

    The hub sends either ``{machines, sessions}`` or a list of machines,
    each with its own ``sessions``; both read as the same two lists.

    Args:
        value: What the state carried.

    Returns:
        ``{"machines": [{device_id, name, is_online}], "sessions": [...]}``,
        each session as :func:`_clean_session` keeps it and stamped with
        its machine; a machine or a session without an id is dropped.
    """
    if isinstance(value, dict):
        machines = value.get("machines")
        listed = value.get("sessions")
    else:
        machines, listed = value, []
    kept_machines = []
    sessions = []
    for entry in machines if isinstance(machines, list) else []:
        if not isinstance(entry, dict):
            continue
        device_id = str(entry.get("device_id", "") or "")
        if not device_id:
            continue
        kept_machines.append(
            {
                "device_id": device_id,
                "name": str(entry.get("name", "") or "") or device_id,
                "is_online": bool(entry.get("is_online")),
            }
        )
        nested = entry.get("sessions")
        for session in nested if isinstance(nested, list) else []:
            cleaned = _clean_session(session, device_id)
            if cleaned is not None:
                sessions.append(cleaned)
    for session in listed if isinstance(listed, list) else []:
        cleaned = _clean_session(session, "")
        if cleaned is not None:
            sessions.append(cleaned)
    return {"machines": kept_machines, "sessions": sessions}


def _clean_session(entry, device_id: str) -> "dict | None":
    """One shell session as the session holds it.

    Args:
        entry: What the hub sent for it.
        device_id: The machine it was listed under, empty when the entry
            names its own.

    Returns:
        ``{session_id, device_id, owner, owner_name, is_owned, is_persistent,
        is_shared, attached_count, title, started_at}``; None for an entry
        without a session id or a machine.
    """
    if not isinstance(entry, dict) or not entry.get("session_id"):
        return None
    device_id = str(entry.get("device_id", "") or "") or device_id
    if not device_id:
        return None
    started_at = entry.get("started_at")
    attached_count = entry.get("attached_count")
    if not isinstance(attached_count, int) or isinstance(attached_count, bool):
        attached_count = 1 if entry.get("is_attached") is True else 0
    return {
        "session_id": str(entry["session_id"]),
        "device_id": device_id,
        "owner": str(entry.get("owner", "") or ""),
        "owner_name": str(entry.get("owner_name", "") or "")
        or str(entry.get("owner", "") or ""),
        "is_owned": entry.get("is_owned") is True,
        "is_persistent": entry.get("is_persistent") is True,
        "is_shared": entry.get("is_shared") is True,
        "attached_count": max(attached_count, 0),
        "title": str(entry.get("title", "") or ""),
        "started_at": (
            started_at
            if isinstance(started_at, (int, float, str))
            and not isinstance(started_at, bool)
            else ""
        ),
    }


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
        on_joined=None,
        refresh_timeout_s: float = CLIENT_REFRESH_TIMEOUT_S,
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
            on_joined: ``on_joined(session, binding)`` keeps the binding a
                pending join completed, by :meth:`adopt_join`, raising
                OSError when it cannot; None adopts it directly.
            refresh_timeout_s: How long a refresh waits for its answer.
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
        self._on_joined = on_joined if on_joined is not None else _adopt_join
        # The binding's id when the session began, the same for its life,
        # whatever id a completed join brings.
        self._local_key = str(binding.get("id", ""))
        # Set once the hub refused a pending join; only Leave acts then.
        self._is_join_refused = False
        # Set whenever the loop should stop waiting: a person asked for a
        # connection now, or the session is stopping.
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._client: "WebSocketClient | None" = None
        # The socket a connect in progress is opening, for a stop to abort.
        self._connecting: "WebSocketClient | None" = None
        # Set when the hosts a round tries change under it: the round in
        # progress ends at once and the next one starts now.
        self._redirected = threading.Event()
        # The address the live socket was opened through.
        self._connected_url = ""
        # This machine's own address on the route to the hub as last seen;
        # None before the first look.
        self._source_address: "str | None" = None
        self._streams: "ClientStreamRegistry | None" = None
        self._is_welcomed = False
        self._backoff_s = CLIENT_BACKOFF_MIN_S
        # Set while another socket holds this binding; only a person clears it.
        self._is_replaced = False
        self._is_unbound = False
        # Set once a round ended in a code, until the next round begins.
        self._is_down = False
        self._last_error: "dict | None" = None
        self._services_list: list = []
        self._terminals: dict = {"machines": [], "sessions": []}
        self._state_hash = ""
        self._hub_software = ""
        self._is_disabled = False
        self._was_disabled = False
        # The refresh in flight, if any, and the count that tells a timer
        # of an older one apart.
        self._is_refreshing = False
        self._refresh_count = 0
        self._refresh_timeout_s = refresh_timeout_s
        # The hosts of the virtual network this machine is on, tried first,
        # or alone while the network's ``hub`` stage holds the channel there.
        self._preferred_hosts: list = []
        self._is_only_preferred = False

    # --- what the resident reads ---

    @property
    def local_key(self) -> str:
        """The binding's id when the session began, unchanged by a completed join."""
        return self._local_key

    def is_pending(self) -> bool:
        """Whether the binding is a join whose ticket is not spent yet."""
        with self._lock:
            return self._binding.get("is_pending") is True

    def adopt_join(self, binding: dict) -> None:
        """Keep the binding a pending join completed, on disk and here.

        Args:
            binding: The completed binding.

        Raises:
            OSError: When the binding file cannot be written.
        """
        with self._lock:
            pending_id = self._binding.get("id", "")
        enrollment.replace_binding(pending_id, binding)
        with self._lock:
            self._binding = dict(binding)

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

    def connection(self) -> str:
        """Where the socket stands, one of ``CONNECTION_STATES``."""
        with self._lock:
            return self._connection()

    def is_refreshing(self) -> bool:
        """Whether a refresh waits for its answer."""
        with self._lock:
            return self._is_refreshing

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

    def overlays(self) -> list:
        """How this machine joins each of the hub's virtual networks, as last named.

        Returns:
            The binding's overlay objects, the hub's preferred first; they
            are kept while the socket is down, since a virtual network is
            what can bring the hub back.
        """
        with self._lock:
            return [dict(item) for item in self._binding.get("overlays") or []]

    def overlay_choice(self) -> "tuple[bool, str]":
        """Where the hub's virtual network last stood, and the engine chosen.

        Returns:
            Whether the network was last ``on``, and the provider chosen,
            empty for the hub's first.
        """
        with self._lock:
            return (
                self._binding.get("is_overlay_on") is True,
                str(self._binding.get("overlay_pick", "") or ""),
            )

    def set_overlay_choice(self, is_on: bool, pick: str) -> None:
        """Keep where the hub's virtual network stands, and the engine chosen.

        Args:
            is_on: Whether the network is ``on``.
            pick: The provider chosen, empty for the hub's first.

        Raises:
            OSError: When the binding file cannot be written.
        """
        with self._lock:
            binding_id = self._binding.get("id", "")
        enrollment.note_overlay_choice(binding_id, is_on, pick)
        with self._lock:
            self._binding["is_overlay_on"] = bool(is_on)
            self._binding["overlay_pick"] = str(pick)

    def reaches_through(self, hosts: list) -> bool:
        """Whether the hub's channel is up through one of these hosts.

        A live socket opened elsewhere does not count. Each host's port is
        then opened and its certificate checked, and closed again before any
        hello; when one answers as this hub, the live socket is closed and
        the next round, started now, connects through the hosts.

        Args:
            hosts: The hub's names or addresses on a virtual network.

        Returns:
            True when the live socket was opened through one of them.
        """
        with self._lock:
            in_use = self._connected_url if self._is_welcomed else ""
        if in_use and urllib.parse.urlsplit(in_use).hostname in hosts:
            return True
        for url in self._host_urls(hosts):
            client = self._open_client(url)
            try:
                client.connect()
            except (GatewayRefused, GatewayUnreachable, GatewayUntrusted):
                continue
            client.close()
            self._log(f"the hub answers at {url}; moving the channel there")
            self._drop_socket()
            self._redirect_round()
            break
        return False

    def terminal_entries(self) -> list:
        """The machines the hub offers a terminal on, while its socket is up.

        Returns:
            ``[{device_id, name, is_online}]``; empty while the socket is
            down.
        """
        with self._lock:
            if not self._is_welcomed:
                return []
            return [dict(entry) for entry in self._terminals["machines"]]

    def note_session_flags(
        self, session_id: str, is_persistent: bool, is_shared: bool
    ) -> None:
        """Show a shell session's two flags as set, until the hub's next state.

        Args:
            session_id: The shell session's id.
            is_persistent: Whether the machine keeps it.
            is_shared: Whether every client with terminal rights lists it.
        """
        with self._lock:
            for entry in self._terminals["sessions"]:
                if entry["session_id"] == session_id:
                    entry["is_persistent"] = bool(is_persistent)
                    entry["is_shared"] = bool(is_shared)

    def terminal_sessions(self) -> list:
        """The shell sessions the hub lists for this client, while its socket is up.

        Returns:
            One row per session, as :func:`clean_terminals` keeps it; empty
            while the socket is down.
        """
        with self._lock:
            if not self._is_welcomed:
                return []
            return [dict(entry) for entry in self._terminals["sessions"]]

    # --- what the resident does ---

    def reconnect_through(self, hosts: list, is_only: bool = False) -> None:
        """Connect through the addresses on these hosts first, from the next round.

        A socket that is down starts that round now, its backoff at the
        floor; a live one is kept. With ``is_only``, a round in progress
        through other addresses ends at once. An empty list drops the
        preference.

        Args:
            hosts: The hub's host names or addresses on the network this
                machine is on; empty entries are ignored.
            is_only: Whether a round tries these hosts and no other
                address.
        """
        with self._lock:
            self._preferred_hosts = [host for host in hosts if host]
            self._is_only_preferred = bool(is_only) and bool(self._preferred_hosts)
            is_only = self._is_only_preferred
            is_down = not self._is_welcomed
            if is_down:
                self._backoff_s = CLIENT_BACKOFF_MIN_S
        if is_only:
            self._redirect_round()
        elif is_down:
            self._news.set()

    def reconnect(self) -> None:
        """Take the binding back from the socket that replaced it, and connect now."""
        with self._lock:
            self._is_replaced = False
        self._news.set()
        self._on_change()

    def refresh(self) -> bool:
        """Ask the hub again now, and wait for its answer as refreshing.

        The error line goes first. A connected hub is sent a report with
        ``is_refresh``, which the hub answers with its whole state; a hub
        that is connecting or down has its backoff put back to the floor,
        its wait ended, and a round started, which resolves its name again.
        Refreshing ends with the next state, a round ending in a code, or
        ``refresh_timeout_s``.

        Returns:
            Whether the hub entered refreshing: False while it is replaced,
            disabled, or already refreshing.
        """
        with self._lock:
            connection = self._connection()
            if connection not in CONNECTION_REFRESHABLE or self._is_refreshing:
                return False
            self._is_refreshing = True
            self._refresh_count += 1
            count = self._refresh_count
            self._last_error = None
            client = self._client if connection == CONNECTION_CONNECTED else None
            if client is None:
                self._backoff_s = CLIENT_BACKOFF_MIN_S
        timer = threading.Timer(
            self._refresh_timeout_s, self._refresh_timed_out, args=(count,)
        )
        timer.daemon = True
        timer.start()
        if client is None:
            self._news.set()
        else:
            try:
                self._report(client, is_refresh=True)
            except GatewayUnreachable:
                # The reader sees the socket's end.
                pass
        self._on_change()
        return True

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
        stream = self._live_streams().open(CLIENT_STREAM_KIND_SERVICE, {"id": entry_id})
        return stream.wait_close(timeout_s)

    def open_shell(
        self,
        device_id: str,
        cols: int,
        rows: int,
        session_id: str,
        is_resumed: bool = False,
    ) -> ClientStream:
        """Open a ``shell`` stream to one managed machine, credit granted.

        The hub's refusal arrives as the stream's close: a read comes back
        empty and ``wait_close`` raises it.

        Args:
            device_id: The machine, as the state's ``terminals`` names it.
            cols: The terminal's width in columns.
            rows: The terminal's height in rows.
            session_id: The shell session's id, a fresh uuid for a new one.
            is_resumed: Whether ``session_id`` names a session the machine
                keeps, attached to again with its kept output.

        Returns:
            The open stream, to read, send on and close.

        Raises:
            GatewayUnreachable: When there is no socket, or it is gone.
        """
        args = {
            "device_id": device_id,
            "cols": int(cols),
            "rows": int(rows),
            "session_id": session_id,
        }
        if is_resumed:
            args["is_resumed"] = True
        return self._live_streams().open(CLIENT_STREAM_KIND_SHELL, args, has_bytes=True)

    def persist_shell(
        self,
        session_id: str,
        is_persistent: bool,
        is_shared: bool,
        timeout_s: float = CLIENT_STREAM_TIMEOUT_S,
    ) -> dict:
        """Tell the hub whether a shell session outlives its stream, and who sees it.

        Args:
            session_id: The shell session's id.
            is_persistent: Whether the machine keeps it once nobody is
                attached.
            is_shared: Whether every client with terminal rights on the
                machine lists it.
            timeout_s: How long to wait for the close.

        Returns:
            The close's ``params``.

        Raises:
            GatewayRefusedDetail: When the hub refused, ``session_unknown``
                and ``session_not_owned`` among the codes.
            GatewayUnreachable: When there is no socket, it ends, or the
                close does not arrive in time.
        """
        return self._agent_command(
            {
                "verb": CLIENT_SHELL_PERSIST_VERB,
                "session_id": session_id,
                "is_persistent": bool(is_persistent),
                "is_shared": bool(is_shared),
            },
            timeout_s,
        )

    def stop_shell_session(
        self, session_id: str, timeout_s: float = CLIENT_STREAM_TIMEOUT_S
    ) -> dict:
        """Have the hub end a shell session on its machine.

        Args:
            session_id: The shell session's id.
            timeout_s: How long to wait for the close.

        Returns:
            The close's ``params``.

        Raises:
            GatewayRefusedDetail: When the hub refused, ``session_unknown``
                among the codes.
            GatewayUnreachable: When there is no socket, it ends, or the
                close does not arrive in time.
        """
        return self._agent_command(
            {"verb": CLIENT_SHELL_STOP_VERB, "session_id": session_id}, timeout_s
        )

    def resize_shell(
        self,
        stream_id: int,
        cols: int,
        rows: int,
        timeout_s: float = CLIENT_STREAM_TIMEOUT_S,
    ) -> dict:
        """Tell the hub a shell's terminal changed size, and take the close.

        Args:
            stream_id: The shell stream's id.
            cols: The new width in columns.
            rows: The new height in rows.
            timeout_s: How long to wait for the close.

        Returns:
            The close's ``params``.

        Raises:
            GatewayRefusedDetail: When the hub refused, ``shell_unknown``
                among the codes.
            GatewayUnreachable: When there is no socket, it ends, or the
                close does not arrive in time.
        """
        stream = self._live_streams().open(
            CLIENT_STREAM_KIND_COMMAND,
            {
                "module": CLIENT_SHELL_RESIZE_MODULE,
                "verb": CLIENT_SHELL_RESIZE_VERB,
                "shell": int(stream_id),
                "cols": int(cols),
                "rows": int(rows),
            },
        )
        return stream.wait_close(timeout_s)

    # --- the loop ---

    def start(self) -> None:
        """Run the loop on a thread of its own.

        The thread is published only once it runs, so a ``stop()`` from
        another thread meanwhile joins nothing: the loop sees the stop on
        its first turn and ends by itself.
        """
        thread = threading.Thread(
            target=self.run_forever, name=f"hub_session_{self.binding_id}", daemon=True
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        """Close the socket and end the loop, a connect in progress aborted. Idempotent."""
        self._stop.set()
        self._news.set()
        self._redirected.set()
        with self._lock:
            connecting = self._connecting
        if connecting is not None:
            connecting.abort()
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
            self._wait_out(delay)

    def run_once(self) -> int:
        """One connection's lifetime, or one idle turn.

        Returns:
            How many seconds to wait before the next one: the shortest delay
            after a clean close, a backing-off delay after a broken wire, a
            minute after a refusal the binding survives, and a short idle
            wait while another socket holds the binding or the hub has
            forgotten it.
        """
        with self._lock:
            is_idle = self._is_replaced or self._is_unbound or self._is_join_refused
            was_down = self._is_down
            self._is_down = False
        if is_idle:
            return CLIENT_IDLE_POLL_INTERVAL_S
        if was_down:
            self._on_change()
        try:
            client = self._connect_round()
        except EnrollmentError as error:
            return self._on_join_refused(error)
        except (GatewayRefused, GatewayUntrusted) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            return self._on_unreachable(error)
        if client is None:
            self._log("the round was redirected; connecting again now")
            return 0
        failure = self._serve(client)
        if failure is None:
            return CLIENT_BACKOFF_MIN_S
        if isinstance(failure, GatewayRefused):
            return self._on_rejected(failure)
        self._log(f"hub socket lost: {failure}; connecting again")
        return CLIENT_BACKOFF_MIN_S

    def _connect_round(self):
        """Connect through the first of the hub's addresses that answers.

        The name's address is first, then the one that last answered, then
        the rest the binding holds. An address the name resolves to that is
        not a stored one and fails the fingerprint check is not this hub and
        is skipped; a stored address failing it is logged and the round goes
        on. The address that answers is written onto the binding.

        Returns:
            The connected socket, its welcome taken and its first report
            sent; None when the hosts to try changed under the round, which
            then ends at once.

        Raises:
            GatewayUntrusted: When a stored address presented another
                certificate and no address answered.
            GatewayRefused: When the hub refused the hello, by a frame or by
                its close; the protocol refusals are their own kind.
            GatewayUnreachable: When no address answered, or a stop ended
                the round.
        """
        self._redirected.clear()
        if self._stop.is_set():
            self._redirected.set()
        with self._lock:
            binding = dict(self._binding)
            preferred_hosts = list(self._preferred_hosts)
            is_only = self._is_only_preferred
        stored = enrollment.stored_urls(binding)
        preferred = self._host_urls(preferred_hosts)
        if is_only:
            name_url = ""
            candidates = preferred
        else:
            name_url = enrollment.hub_name_url(binding["gateway_url"])
            candidates = enrollment.candidate_urls(binding, name_url)
            candidates = preferred + [url for url in candidates if url not in preferred]
        untrusted: "Exception | None" = None
        failure: "Exception | None" = None
        for index, url in enumerate(candidates):
            if index:
                self._redirected.wait(timeout=CLIENT_ROTATE_DELAY_S)
            if index and self._stop.is_set():
                break
            client = self._open_client(url)
            with self._lock:
                self._connecting = client
            try:
                if self._is_redirected():
                    return None
                self._connect(client, url)
            except GatewayRefused:
                if self._is_redirected():
                    return None
                raise
            except GatewayUntrusted as error:
                if url == name_url and url not in stored:
                    self._log(f"{url} answers to the hub's name and is not this hub")
                else:
                    self._log(f"{url} presented a certificate that is not the hub's")
                    untrusted = error
            except GatewayUnreachable as error:
                failure = error
            else:
                with self._lock:
                    self._connected_url = url
                self._note_url(url)
                return client
            finally:
                with self._lock:
                    self._connecting = None
            if self._is_redirected():
                return None
        if untrusted is not None:
            raise untrusted
        raise failure if failure is not None else GatewayUnreachable("no address")

    def _join_at(self, url: str) -> None:
        """Spend the pending join's ticket at the address that answered.

        Raises:
            EnrollmentError: When the hub refused the join.
            GatewayUntrusted: When what answers is not the pinned hub.
            GatewayUnreachable: When the address stops answering, or the
                completed binding cannot be kept.
        """
        completed = enrollment.complete_join(self.binding(), url)
        try:
            self._on_joined(self, completed)
        except OSError as error:
            raise GatewayUnreachable(f"the join could not be kept: {error}")
        self._log(f"joined the hub at {url}")

    def _on_join_refused(self, error: EnrollmentError) -> int:
        """Take the hub's refusal of a pending join: down, and no more rounds."""
        with self._lock:
            self._is_join_refused = True
            self._is_down = True
            self._is_refreshing = False
            self._last_error = {"code": error.code, "params": dict(error.params)}
        self._log(f"the hub refused the join: {error.code}")
        self._on_change()
        return CLIENT_IDLE_POLL_INTERVAL_S

    def _redirect_round(self) -> None:
        """End a round in progress, its connect aborted, and start the next one now."""
        with self._lock:
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            connecting = self._connecting
        self._redirected.set()
        if connecting is not None:
            connecting.abort()
        self._news.set()

    def _is_redirected(self) -> bool:
        """Whether the round in progress was redirected, a stop aside."""
        return self._redirected.is_set() and not self._stop.is_set()

    def _host_urls(self, hosts: list) -> list:
        """The hub's address on each host: a stored one, else at the gateway port."""
        with self._lock:
            binding = dict(self._binding)
        stored = enrollment.stored_urls(binding)
        port = urllib.parse.urlsplit(binding.get("gateway_url", "")).port or 443
        urls = []
        for host in hosts:
            known = [
                url for url in stored if urllib.parse.urlsplit(url).hostname == host
            ]
            url = known[0] if known else f"https://{host}:{port}"
            if url not in urls:
                urls.append(url)
        return urls

    def _open_client(self, gateway_url: str) -> WebSocketClient:
        """A socket for the binding at one of the hub's addresses.

        Args:
            gateway_url: The address to open the socket at.

        Returns:
            The unconnected socket.
        """
        with self._lock:
            fingerprint = self._binding.get("fingerprint", "")
        parts = urllib.parse.urlsplit(gateway_url)
        return WebSocketClient(
            host=parts.hostname or "",
            port=parts.port or 443,
            path=CLIENT_CHANNEL_WS_PATH,
            fingerprint=fingerprint,
            timeout_s=CLIENT_CONNECT_TIMEOUT_S,
        )

    def _connect(self, client, url: str = "") -> None:
        """Open the socket, spend a pending join's ticket, say hello, and report once.

        Args:
            client: The unconnected socket.
            url: The address the socket is opened at; empty for the
                binding's own.

        Raises:
            EnrollmentError: When the hub refused a pending join.
            GatewayUntrusted: When the peer failed the fingerprint check.
            GatewayRefused: When the hub refused the hello, by a frame or by
                its close; the protocol refusals are their own kind.
            GatewayUnreachable: On any network error, or a first frame that
                is neither a welcome nor a refusal.
        """
        client.connect()
        try:
            if self.is_pending():
                self._join_at(url or self.gateway_url())
            client.send_text(json.dumps(self._hello()))
            welcome = self._take_welcome(client)
            with self._lock:
                is_refreshing = self._is_refreshing
            self._report(client, is_refresh=is_refreshing)
        except SocketClosed as closed:
            raise close_error(closed.code, closed.reason) from closed
        except Exception:
            client.close()
            raise
        self._note_hub(welcome)
        with self._lock:
            self._client = client
            self._streams = ClientStreamRegistry(
                send_text=client.send_text,
                send_bytes=client.send_bytes,
                log=self._log,
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
                if self._is_held(client):
                    failure = error
                break
            try:
                self._dispatch(client, kind, payload)
            except GatewayRefused as refused:
                failure = refused
                break
            except GatewayUnreachable as error:
                if self._is_held(client):
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

    def _agent_command(self, args: dict, timeout_s: float) -> dict:
        """Open a ``command`` stream to the agent module and take its close."""
        stream = self._live_streams().open(
            CLIENT_STREAM_KIND_COMMAND,
            dict(args, module=CLIENT_SHELL_RESIZE_MODULE),
        )
        return stream.wait_close(timeout_s)

    def _live_streams(self) -> ClientStreamRegistry:
        """The stream registry of the live socket.

        Raises:
            GatewayUnreachable: When the hub is not connected.
        """
        with self._lock:
            streams = self._streams
            if streams is None or not self._is_welcomed:
                raise GatewayUnreachable("this hub is not connected")
        return streams

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

    def _is_held(self, client) -> bool:
        """Whether a socket is still this session's: one closed from here is not."""
        with self._lock:
            return self._client is client

    def _note_url(self, gateway_url: str) -> None:
        """Write the address that answered onto the binding, when it changed."""
        with self._lock:
            previous = self._binding.get("gateway_url", "")
            if previous == gateway_url:
                return
            self._binding["gateway_url"] = gateway_url
            binding_id = self._binding.get("id", "")
        self._log(f"the hub answered at {gateway_url}")
        try:
            enrollment.note_url(binding_id, gateway_url)
        except OSError as error:
            self._log(f"could not record the hub's address: {error}")
            with self._lock:
                self._binding["gateway_url"] = previous

    def _note_urls(self, urls: list) -> None:
        """Write the hub's address list onto the binding, when it changed."""
        cleaned = enrollment.clean_urls(urls)
        with self._lock:
            previous = list(self._binding.get("gateway_urls") or [])
            if previous == cleaned:
                return
            self._binding["gateway_urls"] = cleaned
            binding_id = self._binding.get("id", "")
        self._log(f"the hub answers at {', '.join(cleaned)}")
        try:
            enrollment.note_urls(binding_id, cleaned)
        except OSError as error:
            self._log(f"could not record the hub's addresses: {error}")
            with self._lock:
                self._binding["gateway_urls"] = previous

    def _note_overlays(self, overlays) -> None:
        """Write the hub's overlay objects onto the binding, when they changed."""
        cleaned = enrollment.clean_overlays(overlays)
        with self._lock:
            previous = list(self._binding.get("overlays") or [])
            if previous == cleaned:
                return
            self._binding["overlays"] = cleaned
            binding_id = self._binding.get("id", "")
        providers = ", ".join(item["provider"] for item in cleaned)
        self._log(f"the hub's virtual networks changed: {providers or 'none'}")
        try:
            enrollment.note_overlays(binding_id, cleaned)
        except OSError as error:
            self._log(f"could not record the hub's virtual networks: {error}")
            with self._lock:
                self._binding["overlays"] = previous

    def _watch_network(self) -> bool:
        """Look at the route to the hub.

        Returns:
            True when this machine's address on it changed since the last
            look; the first look is no change.
        """
        with self._lock:
            binding = dict(self._binding)
            held = self._source_address
        current = enrollment.default_source_address(enrollment.stored_urls(binding))
        with self._lock:
            self._source_address = current
        if held is None or current == held:
            return False
        self._log(f"this machine's address toward the hub is now {current or 'none'}")
        return True

    def _follow_name(self, client) -> None:
        """Move the live socket to the address the hub's name resolves to.

        Only when that is a stored address other than the one in use: the
        socket is closed here and the next round opens it there at once.

        Args:
            client: The connected socket.
        """
        with self._lock:
            binding = dict(self._binding)
            in_use = self._connected_url
        name_url = enrollment.hub_name_url(binding["gateway_url"])
        if not name_url or name_url == in_use:
            return
        if name_url not in enrollment.stored_urls(binding):
            return
        self._log(f"moving to {name_url}")
        self._end_socket(client)
        self._news.set()

    def _wait_out(self, delay: float) -> None:
        """Wait for the next turn: the delay, news, or a network change.

        The route to the hub is looked at every idle poll; a changed
        address ends the wait and puts the backoff back to its floor.

        Args:
            delay: How long the turn asked to wait.
        """
        deadline = time.monotonic() + delay
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._news.wait(timeout=min(remaining, CLIENT_IDLE_POLL_INTERVAL_S)):
                return
            if self._watch_network():
                with self._lock:
                    self._backoff_s = CLIENT_BACKOFF_MIN_S
                return

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

    def _report(self, client, is_refresh: bool = False) -> None:
        """Send what is true of this machine and the hash of the state held.

        Args:
            client: The connected socket.
            is_refresh: Whether the hub is asked for its whole state
                whatever the hash.

        Raises:
            GatewayUnreachable: When the socket is gone.
        """
        with self._lock:
            state_hash = self._state_hash
        report = {
            "type": protocol.FRAME_REPORT,
            "state_hash": state_hash,
            "machine": {
                "hostname": self._hostname,
                "platform": dict(self._platform_tuple),
            },
        }
        if is_refresh:
            report["is_refresh"] = True
        client.send_text(json.dumps(report))

    def _report_on_interval(self, client, ended: threading.Event) -> None:
        """Report every interval until the socket ends, and look at the network."""
        while not ended.wait(timeout=CLIENT_REPORT_INTERVAL_S):
            try:
                self._report(client)
            except GatewayUnreachable:
                return
            if self._watch_network():
                self._follow_name(client)

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
            with self._lock:
                streams = self._streams
            if streams is None:
                self._log(f"dropping {len(data)} bytes the hub sent on {stream_id}")
            else:
                streams.take_bytes(stream_id, data)
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
            with self._lock:
                streams = self._streams
            if streams is not None:
                streams.take_credit(message)
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
        urls = message.get("urls")
        if isinstance(urls, list):
            self._note_urls(urls)
        if "overlays" in message:
            self._note_overlays(message.get("overlays"))
        terminals = message.get("terminals", [])
        is_disabled = bool(message.get("is_disabled"))
        with self._lock:
            self._services_list = [
                entry for entry in services if isinstance(entry, dict)
            ]
            self._terminals = clean_terminals(terminals)
            self._state_hash = str(message.get("hash", "") or "")
            self._is_refreshing = False
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

    def _connection(self) -> str:
        """Where the socket stands; the lock is held."""
        if self._is_replaced:
            return CONNECTION_REPLACED
        if self._is_join_refused:
            return CONNECTION_DOWN
        if self._binding.get("is_pending") is True:
            return CONNECTION_PENDING
        if self._is_welcomed:
            return CONNECTION_DISABLED if self._is_disabled else CONNECTION_CONNECTED
        return CONNECTION_DOWN if self._is_down else CONNECTION_CONNECTING

    def _refresh_timed_out(self, count: int) -> None:
        """End the refresh numbered ``count`` when nothing answered it."""
        with self._lock:
            if not self._is_refreshing or self._refresh_count != count:
                return
            self._is_refreshing = False
        self._on_change()

    def _on_unreachable(self, error: Exception) -> int:
        """Back off after a round that reached no address."""
        with self._lock:
            self._last_error = channel_error(error)
            self._is_down = True
            self._is_refreshing = False
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
            self._is_down = True
            self._is_refreshing = False
        self._log(f"{error}; asking again in {CLIENT_BACKOFF_MAX_S}s")
        self._on_change()
        return CLIENT_BACKOFF_MAX_S

    def _unbind(self, rejection: dict) -> int:
        """Hand the binding back: the hub holds no such binding any more."""
        with self._lock:
            self._is_unbound = True
            self._is_down = True
            self._is_refreshing = False
            self._last_error = rejection
        self._log("unbound: the hub no longer knows this client")
        self._on_unbound(self)
        return CLIENT_IDLE_POLL_INTERVAL_S
