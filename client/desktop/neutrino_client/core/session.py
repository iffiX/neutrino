"""One hub's session: a binding, its socket, and the reconnect that holds it.

A session belongs to one binding and speaks to one hub. It holds the socket
open and reconnects when it drops: a round dials every address of the hub at
once and keeps the first socket to connect with the pinned certificate. A
network change starts a round at once: a virtual network turning on, this
machine's address toward the hub changing, a state naming other
addresses, or the peers of a virtual network that is on changing. On a hub
that is not connected the change ends the wait and the round in flight,
whose dials still waiting are closed; on a connected hub the round runs
beside the live channel, and its winner takes the channel only on a better
path. The hub pushes its
``state``, the addresses it answers on, the services it publishes and
whether this client is switched off, and the session answers each state and
every interval with a ``report``. What a
service handler needs from the hub comes down a ``service`` stream the
session opens on request, a terminal on a managed machine comes down a
``shell`` stream carrying bytes both ways, and every connection a local
forward accepts rides a ``connect`` stream. The resident owns the handlers and the store; the
session tells it what changed through its callbacks and never touches them.

A ``refused`` frame ends the socket whenever it arrives, and says the same
as one that arrives instead of the welcome: its code decides what becomes
of the binding.

The connection is one of five states: ``connected``, ``connecting`` while a
round dials, ``waiting`` once a round ended and the session waits for what
its reason names, ``replaced`` while another socket holds the binding, and
``disabled`` while the hub has this client switched off. A waiting session
carries its reason and, while a countdown runs, the moment of the next
round. A join whose ticket is not spent rounds like any other: the first
address that answers with the pinned certificate spends it before the
hello, and a hub that refuses it leaves the session waiting for good. A
refresh is the same loop moved to now. The client sends a ``ping`` frame
on the open socket every interval, and the ``pong`` that echoes its nonce
sets the round trip the hub row shows.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ipaddress
import json
import queue
import secrets
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
    CLIENT_JOIN_RETRY_MIN_S,
    CLIENT_PATH_RANKS,
    CLIENT_PING_INTERVAL_S,
    CLIENT_PROTOCOL_REFUSAL_CODES,
    CLIENT_REFRESH_TIMEOUT_S,
    CLIENT_REFUSAL_CODE_ADMISSION_PAUSED,
    CLIENT_REFUSAL_CODE_BINDING_UNKNOWN,
    CLIENT_REPORT_INTERVAL_S,
    CLIENT_ROLE,
    CLIENT_SHELL_PERSIST_VERB,
    CLIENT_SHELL_RESIZE_MODULE,
    CLIENT_SHELL_RESIZE_VERB,
    CLIENT_SHELL_STOP_VERB,
    CLIENT_SOFTWARE_PREFIX,
    CLIENT_STREAM_CODE_KIND_UNKNOWN,
    CLIENT_STREAM_KIND_COMMAND,
    CLIENT_STREAM_KIND_CONNECT,
    CLIENT_STREAM_KIND_SERVICE,
    CLIENT_STREAM_KIND_SHELL,
    CLIENT_STREAM_TIMEOUT_S,
    CLIENT_WS_CLOSE_REPLACED,
    CLIENT_WS_SILENCE_TIMEOUT_S,
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
CONNECTION_WAITING = "waiting"
CONNECTION_REPLACED = "replaced"
CONNECTION_DISABLED = "disabled"
CONNECTION_STATES = (
    CONNECTION_CONNECTED,
    CONNECTION_CONNECTING,
    CONNECTION_WAITING,
    CONNECTION_REPLACED,
    CONNECTION_DISABLED,
)
# The states a refresh acts on; the other two change only by a person's
# Reconnect or by the hub.
CONNECTION_REFRESHABLE = (
    CONNECTION_CONNECTED,
    CONNECTION_CONNECTING,
    CONNECTION_WAITING,
)
# Why a waiting session waits, as every surface names it.
WAIT_HUB_SILENT = "hub_silent"
WAIT_HUB_OFF_OVERLAY = "hub_off_overlay"
WAIT_NO_NETWORK = "no_network"
WAIT_UNTRUSTED = "untrusted"
WAIT_ADMISSION_PAUSED = "admission_paused"
WAIT_UNKNOWN_DEVICE = "unknown_device"
WAIT_TOO_OLD = "too_old"
WAIT_JOIN_REFUSED = "join_refused"
WAIT_REASONS = (
    WAIT_HUB_SILENT,
    WAIT_HUB_OFF_OVERLAY,
    WAIT_NO_NETWORK,
    WAIT_UNTRUSTED,
    WAIT_ADMISSION_PAUSED,
    WAIT_UNKNOWN_DEVICE,
    WAIT_TOO_OLD,
    WAIT_JOIN_REFUSED,
)
# The reasons no round ends by itself: neither a countdown nor a network
# change starts one.
WAIT_REASONS_HELD = (WAIT_UNKNOWN_DEVICE, WAIT_TOO_OLD, WAIT_JOIN_REFUSED)
# The held reasons a refresh does not start a round for: a round there
# spends a credential the hub already refused.
WAIT_REASONS_FINAL = (WAIT_UNKNOWN_DEVICE, WAIT_JOIN_REFUSED)

# How long a stop waits for the loop thread to come back, its connect in
# progress aborted.
STOP_JOIN_TIMEOUT_S = 1
# How long a round waits for one dial's result before it looks again
# whether the session is stopping.
DIAL_WAIT_TURN_S = 0.1
# The rank of a path the table does not name: below every named one.
PATH_RANK_UNKNOWN = max(CLIENT_PATH_RANKS.values()) + 1


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


def is_better_path(
    path: str, handshake_s: float, live_path: str, live_handshake_s: float
) -> bool:
    """Whether a round's winner is a better path than the live channel.

    Args:
        path: The winner's path, a key of ``CLIENT_PATH_RANKS``.
        handshake_s: How long the winner's handshake took.
        live_path: The live channel's path.
        live_handshake_s: How long the live channel's handshake took when
            it won.

    Returns:
        True when the winner's path ranks higher, or ranks the same and its
        handshake took less time.
    """
    rank = CLIENT_PATH_RANKS.get(path, PATH_RANK_UNKNOWN)
    live_rank = CLIENT_PATH_RANKS.get(live_path, PATH_RANK_UNKNOWN)
    return rank < live_rank or (rank == live_rank and handshake_s < live_handshake_s)


def is_on_local_network(host: str, networks: list) -> bool:
    """Whether a host is an address inside one of this machine's networks.

    Args:
        host: The host of a candidate address.
        networks: This machine's networks, as ``a.b.c.d/n`` or IPv6 prefixes.

    Returns:
        True when the host is an IP address inside one of them.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    for network in networks:
        try:
            if address in ipaddress.ip_network(network, strict=False):
                return True
        except (TypeError, ValueError):
            continue
    return False


def is_offline(networks: list) -> bool:
    """Whether a machine's networks leave it no network at all.

    Args:
        networks: This machine's networks, as ``a.b.c.d/n`` or IPv6
            prefixes; empty where the system does not say.

    Returns:
        True when the system named networks and every one is loopback or
        link-local; False for an empty list, which says nothing.
    """
    if not networks:
        return False
    for network in networks:
        try:
            parsed = ipaddress.ip_network(network, strict=False)
        except (TypeError, ValueError):
            return False
        if not (parsed.is_loopback or parsed.is_link_local):
            return False
    return True


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


def _no_networks() -> list:
    """No network of this machine is known."""
    return []


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
        os_machine_id: str = "",
        log=print,
        on_change=None,
        on_services=None,
        on_disabled=None,
        on_unbound=None,
        on_joined=None,
        local_networks=None,
        refresh_timeout_s: float = CLIENT_REFRESH_TIMEOUT_S,
        clock=time.monotonic,
        wall_clock=time.time,
    ):
        """
        Args:
            binding: The binding this session speaks for.
            hostname: This machine's hostname, sent in every report.
            platform_tuple: This machine's platform tuple, sent in every
                report.
            os_machine_id: The operating system's id for this machine, sent
                in every report; empty sends none.
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
            local_networks: Returns this machine's networks, as
                ``a.b.c.d/n`` or IPv6 prefixes, by which a candidate address
                reads as ``lan``; None knows none.
            refresh_timeout_s: How long a refresh waits for its answer.
            clock: The monotonic clock a refresh's limit is measured on.
            wall_clock: The wall clock, read beside it, so a jump of either
                clock, as a machine waking from sleep makes, ends the
                refresh instead of holding it.
        """
        self._log = log
        self._lock = threading.Lock()
        self._binding = dict(binding)
        self._hostname = hostname
        self._platform_tuple = dict(platform_tuple)
        self._os_machine_id = os_machine_id
        self._on_change = on_change if on_change is not None else _nobody
        self._on_services = on_services if on_services is not None else _nobody
        self._on_disabled = on_disabled if on_disabled is not None else _nobody
        self._on_unbound = on_unbound if on_unbound is not None else _nobody
        self._on_joined = on_joined if on_joined is not None else _adopt_join
        self._local_networks = (
            local_networks if local_networks is not None else _no_networks
        )
        # The binding's id when the session began, the same for its life,
        # whatever id a completed join brings.
        self._local_key = str(binding.get("id", ""))
        # Set whenever the loop should stop waiting: a person asked for a
        # connection now, or the session is stopping.
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._client: "WebSocketClient | None" = None
        # The rounds in progress, for a stop or a network change to abort.
        self._dialings: list = []
        # Set once a network change or a refresh ended the round in flight.
        self._is_round_cut = False
        # The address the live socket was opened through, its path, and how
        # long its handshake took when it won.
        self._connected_url = ""
        self._connected_path = ""
        self._connected_handshake_s = 0.0
        # A round beside the live channel runs, and another is due after it.
        self._is_changing = False
        self._is_change_due = False
        # The socket the channel last moved off, whose 4010 is expected; the
        # event set once that move ended; the socket a move is greeting.
        self._moved_from: "WebSocketClient | None" = None
        self._moving = threading.Event()
        self._moving.set()
        self._moving_to: "WebSocketClient | None" = None
        # This machine's own address on the route to the hub as last seen;
        # None before the first look.
        self._source_address: "str | None" = None
        self._streams: "ClientStreamRegistry | None" = None
        self._is_welcomed = False
        # The round trip the last pong on the live socket measured, in
        # whole milliseconds; None before the first pong.
        self._rtt_ms: "int | None" = None
        # The nonce and the send time of the last ping on the live socket;
        # None before the first, and once its pong was read.
        self._ping_sent: "tuple[str, float] | None" = None
        self._backoff_s = CLIENT_BACKOFF_MIN_S
        # Set while another socket holds this binding; only a person clears it.
        self._is_replaced = False
        # Why the session waits, one of ``WAIT_REASONS``, empty while it
        # does not; the code behind it; and the wall clock's moment of the
        # next round, None while no countdown runs.
        self._wait_reason = ""
        self._wait_code: "dict | None" = None
        self._next_round_at: "float | None" = None
        self._services_list: list = []
        # The state's word for the way this socket reached the hub, and
        # whether this client may open the hub's panel; empty and False
        # before the first state.
        self._reached_through = ""
        self._is_panel_allowed = False
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
        self._clock = clock
        self._wall_clock = wall_clock
        # When the refresh in flight began, on both clocks.
        self._refresh_since = (0.0, 0.0)
        # The hub's address on its virtual network that is on, and that
        # network's engine; empty while none is on.
        self._overlay_host = ""
        self._overlay_provider = ""
        # Whether this client's virtual network of the hub's is on.
        self._is_overlay_on = False
        # The member of the state's ``urls`` that is the relay's address.
        self._relay_url = ""

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
        """Whether a refresh waits for its answer, within its limit.

        A refresh whose limit has passed on either clock, or whose wall
        clock moved back, is over here and now, whether or not its timer
        has fired.
        """
        with self._lock:
            if self._is_refreshing and self._is_refresh_over():
                self._is_refreshing = False
            return self._is_refreshing

    def is_disabled(self) -> bool:
        """Whether the hub has switched this client off."""
        with self._lock:
            return self._is_disabled

    def waiting(self) -> "dict | None":
        """Why the session waits, while it does.

        Returns:
            ``{"reason", "code", "next_round_at"}``: one of
            ``WAIT_REASONS``, the ``{"code", "params"}`` the last round
            ended in, and the wall clock's moment of the next round in
            seconds since the epoch, None while no countdown runs; None
            while the connection is not ``waiting``.
        """
        with self._lock:
            if self._connection() != CONNECTION_WAITING:
                return None
            return {
                "reason": self._wait_reason,
                "code": dict(self._wait_code) if self._wait_code else None,
                "next_round_at": self._next_round_at,
            }

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

    def reached_through(self) -> str:
        """The way the channel reached the hub, as the hub's last state named it.

        Returns:
            ``lan``, ``netbird``, ``easytier`` or ``relay``; empty before
            the first state.
        """
        with self._lock:
            return self._reached_through

    def rtt_ms(self) -> "int | None":
        """The round trip from this client's last ping to its pong.

        Returns:
            Whole milliseconds; None before the first pong on the live
            socket and while the hub is not ``connected``.
        """
        with self._lock:
            if self._connection() != CONNECTION_CONNECTED:
                return None
            return self._rtt_ms

    def is_panel_allowed(self) -> bool:
        """Whether the hub's last state allows this client to open its panel."""
        with self._lock:
            return self._is_panel_allowed

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

    def set_overlay_route(self, host: str, provider: str) -> None:
        """Name the hub's address on its virtual network that is on, and its engine.

        Every round dials the address with the others from then on. A
        network that just turned on, or whose peers changed, is a network
        change, so a round starts at once; an empty host drops the address.

        Args:
            host: The hub's address on the network; empty while the hub
                names none on it, or once it is off.
            provider: The network's engine, ``netbird`` or ``easytier``;
                empty once it is off.
        """
        with self._lock:
            self._overlay_host = host
            self._overlay_provider = provider if host else ""
            self._is_overlay_on = bool(provider)
        if provider:
            self.change_network()

    def change_network(self) -> None:
        """Start one round at once, as a network change does.

        A hub ``replaced`` or ``disabled``, or waiting on a reason that
        only a person ends, is left as it is. A hub that is not connected
        has its backoff put at the floor, its wait and its round in flight
        ended, and a new round started. A connected hub gets a round
        beside its live channel, whose winner takes the channel only on a
        better path; a change while that round runs starts one more after
        it.
        """
        with self._lock:
            connection = self._connection()
            if connection in (CONNECTION_REPLACED, CONNECTION_DISABLED):
                return
            if self._wait_reason in WAIT_REASONS_HELD:
                return
            is_live = connection == CONNECTION_CONNECTED
            if is_live and self._is_changing:
                self._is_change_due = True
                return
            if is_live:
                self._is_changing = True
        if not is_live:
            self._cut_round()
            return
        threading.Thread(
            target=self._change_rounds, name="client_change_round", daemon=True
        ).start()

    def reconnect(self) -> None:
        """Take the binding back from the socket that replaced it, and connect now."""
        with self._lock:
            self._is_replaced = False
        self._news.set()
        self._on_change()

    def refresh(self) -> bool:
        """Ask the hub again now, and wait for its answer as refreshing.

        A connected hub is sent a report with ``is_refresh``, which the hub
        answers with its whole state; a hub that is connecting or waiting
        has its backoff put back to the floor, its wait and its round in
        flight ended, and a round started, which resolves its name again.
        Refreshing ends with the next state, a round ending in a code, or
        ``refresh_timeout_s``.

        Returns:
            Whether the hub entered refreshing: False while it is replaced,
            disabled, waiting on a device the hub does not know or a
            refused join, or already refreshing.
        """
        with self._lock:
            connection = self._connection()
            if self._is_refreshing and self._is_refresh_over():
                self._is_refreshing = False
            if connection not in CONNECTION_REFRESHABLE or self._is_refreshing:
                return False
            if self._wait_reason in WAIT_REASONS_FINAL:
                return False
            self._is_refreshing = True
            self._refresh_since = (self._clock(), self._wall_clock())
            self._refresh_count += 1
            count = self._refresh_count
            client = self._client if connection == CONNECTION_CONNECTED else None
            if client is None:
                self._wait_reason = ""
                self._wait_code = None
                self._next_round_at = None
        timer = threading.Timer(
            self._refresh_timeout_s, self._refresh_timed_out, args=(count,)
        )
        timer.daemon = True
        timer.start()
        if client is None:
            self._cut_round()
        else:
            # Sent from a thread of its own: a socket that takes no bytes
            # holds that thread until its send timeout, never the press.
            threading.Thread(
                target=self._send_refresh,
                args=(client,),
                name="client_refresh",
                daemon=True,
            ).start()
        self._on_change()
        return True

    def _send_refresh(self, client) -> None:
        """Send the report a refresh asks for; a dead socket ends the socket."""
        try:
            self._report(client, is_refresh=True)
        except GatewayUnreachable:
            # The reader sees the socket's end.
            pass

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

    def open_panel_service(self, timeout_s: float = CLIENT_STREAM_TIMEOUT_S) -> dict:
        """Open a ``service`` stream for the hub's own panel and take the close.

        Args:
            timeout_s: How long to wait for the close.

        Returns:
            The close's ``params``: ``{token}``, a sign-in usable once.

        Raises:
            GatewayRefusedDetail: When the hub closed the stream with a code,
                ``permission_denied {kind: panel}`` among them.
            GatewayUnreachable: When there is no socket, the socket ends, or
                the close does not arrive in time.
        """
        stream = self._live_streams().open(
            CLIENT_STREAM_KIND_SERVICE, {"is_panel": True}
        )
        return stream.wait_close(timeout_s)

    def open_connect(self, args: dict) -> ClientStream:
        """Open a ``connect`` stream: one TCP connection the hub carries.

        The hub's refusal arrives as the stream's close: a read comes back
        empty and ``wait_close`` raises it.

        Args:
            args: ``{"id"}`` naming a published entry, or
                ``{"is_panel": True}`` for the hub's own panel.

        Returns:
            The open stream, credit granted, to read, send on and close.

        Raises:
            GatewayUnreachable: When there is no socket, or it is gone.
        """
        return self._live_streams().open(
            CLIENT_STREAM_KIND_CONNECT, dict(args), has_bytes=True
        )

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
        with self._lock:
            dialings = list(self._dialings)
            moving_to = self._moving_to
        for dialing in dialings:
            dialing.settle()
        if moving_to is not None:
            moving_to.abort()
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

    def run_once(self) -> float:
        """One connection's lifetime, or one idle turn.

        Returns:
            How many seconds to wait before the next one: none after the
            socket ends or a network change ended the round, a backing-off
            delay after a round no address answered, a minute after a
            refusal the binding survives, the hub's own delay after a paused
            join, no end while the device has no network, and a short idle
            wait while another socket holds the binding or the session
            waits on a reason only a person ends.
        """
        with self._lock:
            if self._is_replaced or self._wait_reason in WAIT_REASONS_HELD:
                return CLIENT_IDLE_POLL_INTERVAL_S
            was_waiting = bool(self._wait_reason)
            self._wait_reason = ""
            self._wait_code = None
            self._next_round_at = None
        if was_waiting:
            self._on_change()
        try:
            client = self._connect_round()
        except EnrollmentError as error:
            return self._on_join_refused(error)
        except (GatewayRefused, GatewayUntrusted) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            if self._take_round_cut():
                self._log("a network change ended the round; starting another")
                return 0
            return self._on_unreachable(error)
        failure = self._serve(client)
        if isinstance(failure, GatewayRefused):
            return self._on_rejected(failure)
        if failure is not None:
            self._log(f"hub socket lost: {failure}; connecting again")
        return 0

    def _connect_round(self):
        """Connect through whichever of the hub's addresses answers first.

        Every address is dialled at once: the hub's address on each virtual
        network that is up, the name's address, and the addresses the
        binding holds; none is preferred for having answered last. The
        first socket to connect with the pinned certificate is the round's,
        every other one is closed before any hello, and the hello goes on
        the round's socket alone. An address the name resolves to that is
        not a stored one and fails the fingerprint check is not this hub
        and is skipped; a stored address failing it is logged. The address
        that answers is written onto the binding.

        Returns:
            The connected socket, its welcome taken and its first report
            sent.

        Raises:
            EnrollmentError: When the hub refused a pending join.
            GatewayUntrusted: When a stored address presented another
                certificate and no address answered.
            GatewayRefused: When the hub refused the upgrade or the hello,
                by a frame or by its close; the protocol refusals are their
                own kind.
            GatewayUnreachable: When no address answered, the round's
                socket ended before the welcome, or a stop or a network
                change ended the round.
        """
        if self._stop.is_set():
            raise GatewayUnreachable("the session is stopping")
        with self._lock:
            self._is_round_cut = False
        urls, name_url, stored = self._candidates()
        url, client, errors, handshake_s = self._dial_all(urls)
        untrusted, failure = self._sort_failures(errors, name_url, stored)
        with self._lock:
            is_cut = self._is_round_cut
        if self._stop.is_set() or is_cut:
            if client is not None:
                client.close()
            raise GatewayUnreachable("the round was ended")
        if client is None:
            if isinstance(failure, GatewayRefused):
                raise failure
            if untrusted is not None:
                raise untrusted
            raise failure if failure is not None else GatewayUnreachable("no address")
        self._greet(client, url)
        path = self._path_of(url)
        with self._lock:
            self._connected_url = url
            self._connected_path = path
            self._connected_handshake_s = handshake_s
        self._note_url(url)
        return client

    def _candidates(self) -> "tuple[list, str, list]":
        """Every address a round dials, the name's address, and the stored ones.

        Returns:
            ``(urls, name_url, stored)``: the hub's address on its virtual
            network that is on, the name's address and the stored ones,
            each once; the name's address, empty when the name does not
            resolve; and the addresses the binding holds.
        """
        with self._lock:
            binding = dict(self._binding)
            overlay_host = self._overlay_host
        stored = enrollment.stored_urls(binding)
        urls = self._host_urls([overlay_host]) if overlay_host else []
        name_url = enrollment.hub_name_url(binding["gateway_url"])
        urls += [
            url
            for url in enrollment.candidate_urls(binding, name_url)
            if url not in urls
        ]
        return urls, name_url, stored

    def _sort_failures(self, errors: list, name_url: str, stored: list) -> tuple:
        """Log the addresses off the pin, and keep the round's last failures.

        Returns:
            ``(untrusted, failure)``: the last refusal of the pin by a stored
            address, and the last other failure; each None when there was
            none.
        """
        untrusted: "Exception | None" = None
        failure: "Exception | None" = None
        for failed_url, error in errors:
            if not isinstance(error, GatewayUntrusted):
                failure = error
            elif failed_url == name_url and failed_url not in stored:
                self._log(f"{failed_url} answers to the hub's name and is not this hub")
            else:
                self._log(f"{failed_url} presented a certificate that is not the hub's")
                untrusted = error
        return untrusted, failure

    def _path_of(self, url: str) -> str:
        """The path one candidate address reaches the hub by.

        Returns:
            The virtual network's engine for the hub's address on it,
            ``relay`` for the state's ``relay_url``, ``lan`` for an address
            inside a network this machine holds an address in, and
            ``direct`` for any other.
        """
        parts = urllib.parse.urlsplit(url)
        with self._lock:
            overlay_host = self._overlay_host
            overlay_provider = self._overlay_provider
            relay_url = self._relay_url
        if overlay_host and parts.hostname == overlay_host:
            return overlay_provider
        if relay_url:
            relay = urllib.parse.urlsplit(relay_url)
            if (relay.hostname, relay.port) == (parts.hostname, parts.port):
                return "relay"
        if is_on_local_network(parts.hostname or "", self._local_networks()):
            return "lan"
        return "direct"

    def _change_rounds(self) -> None:
        """Run rounds beside the live channel until no network change is due."""
        while True:
            self._change_round()
            with self._lock:
                if not self._is_change_due or self._stop.is_set():
                    self._is_changing = False
                    return
                self._is_change_due = False

    def _change_round(self) -> None:
        """One round beside the live channel; its winner moves the channel only on a better path."""
        with self._lock:
            live = self._client if self._is_welcomed else None
            live_url = self._connected_url
            live_path = self._connected_path
            live_handshake_s = self._connected_handshake_s
        if live is None:
            return
        urls, name_url, stored = self._candidates()
        url, client, errors, handshake_s = self._dial_all(urls)
        self._sort_failures(errors, name_url, stored)
        if client is None:
            return
        path = self._path_of(url)
        with self._lock:
            is_live = self._client is live and self._is_welcomed
        is_better = url != live_url and is_better_path(
            path, handshake_s, live_path, live_handshake_s
        )
        if not is_live or not is_better or self._stop.is_set():
            self._log(
                f"a network change found {url} ({path}); the channel stays "
                f"at {live_url} ({live_path})"
            )
            client.close()
            return
        self._move(live, client, url, path, handshake_s)

    def _move(self, live, client, url: str, path: str, handshake_s: float) -> None:
        """Move the channel onto a better path's socket; its hello replaces the live one."""
        moving = threading.Event()
        with self._lock:
            live_url = self._connected_url
            self._moved_from = live
            self._moving = moving
            self._moving_to = client
            streams = self._streams
        self._log(f"moving the channel from {live_url} to {url} ({path})")
        try:
            self._greet(client, url)
        except (
            EnrollmentError,
            GatewayRefused,
            GatewayUnreachable,
            GatewayUntrusted,
        ) as error:
            self._log(f"the channel could not move to {url}: {error}")
            with self._lock:
                self._moved_from = None
            return
        finally:
            with self._lock:
                self._moving_to = None
            moving.set()
        with self._lock:
            self._connected_url = url
            self._connected_path = path
            self._connected_handshake_s = handshake_s
            self._rtt_ms = None
            self._ping_sent = None
        self._note_url(url)
        if streams is not None:
            streams.end_all()
        live.close()

    def _dial_all(self, urls: list) -> "tuple[str, object, list, float]":
        """Open a socket at every address at once and keep the first to connect.

        Args:
            urls: The addresses to dial.

        Returns:
            ``(url, client, errors, handshake_s)``: the address, the open
            socket and the handshake's seconds of the first to connect, or
            an empty address, None and 0 when none did, the hub refused the
            upgrade, the session is stopping, or a network change ended the
            round; ``errors`` holds
            ``(url, error)`` for every address that failed before the round
            settled.
        """
        dialing = _ClientDialRound(
            clients=[(url, self._open_client(url)) for url in urls]
        )
        with self._lock:
            self._dialings.append(dialing)
        errors: list = []
        try:
            dialing.start()
            while len(errors) < len(urls):
                if self._stop.is_set() or self._is_cut():
                    dialing.settle()
                    break
                result = dialing.next_result(DIAL_WAIT_TURN_S)
                if result is None:
                    continue
                url, client, error, handshake_s = result
                if client is not None:
                    dialing.settle(kept=client)
                    return url, client, errors, handshake_s
                errors.append((url, error))
                if isinstance(error, GatewayRefused):
                    dialing.settle()
                    break
        finally:
            with self._lock:
                self._dialings.remove(dialing)
        return "", None, errors, 0.0

    def _join_at(self, url: str) -> None:
        """Spend the pending join's ticket at the address that answered.

        Raises:
            EnrollmentError: When the hub refused the ticket.
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

    def _on_join_refused(self, error: EnrollmentError) -> float:
        """Take the hub's refusal of a pending join: waiting, and no more rounds.

        ``admission_paused`` is the one refusal that keeps the ticket: the
        session counts down the ``retry_after_s`` it names and joins again.
        """
        if error.code == CLIENT_REFUSAL_CODE_ADMISSION_PAUSED:
            return self._on_admission_paused(error)
        self._wait(
            WAIT_JOIN_REFUSED, {"code": error.code, "params": dict(error.params)}, None
        )
        self._log(f"the hub refused the join: {error.code}")
        return CLIENT_IDLE_POLL_INTERVAL_S

    def _on_admission_paused(self, error: EnrollmentError) -> float:
        """Keep a join the hub paused: counted down, and joined again at 0.

        Returns:
            The hub's ``retry_after_s``, at least ``CLIENT_JOIN_RETRY_MIN_S``.
        """
        try:
            delay = float(error.params.get("retry_after_s") or 0)
        except (TypeError, ValueError):
            delay = 0
        delay = max(delay, CLIENT_JOIN_RETRY_MIN_S)
        self._wait(
            WAIT_ADMISSION_PAUSED,
            {"code": error.code, "params": dict(error.params)},
            delay,
        )
        self._log(f"the hub paused admissions; joining again in {delay:g}s")
        return delay

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
            bracketed = f"[{host}]" if ":" in host else host
            url = known[0] if known else f"https://{bracketed}:{port}"
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

    def _greet(self, client, url: str = "") -> None:
        """Spend a pending join's ticket, say hello on the open socket, and report once.

        Args:
            client: The open socket.
            url: The address the socket is open at; empty for the binding's
                own.

        Raises:
            EnrollmentError: When the hub refused a pending join.
            GatewayUntrusted: When the join's address is not the pinned hub.
            GatewayRefused: When the hub refused the hello, by a frame or by
                its close; the protocol refusals are their own kind.
            GatewayUnreachable: On any network error, or a first frame that
                is neither a welcome nor a refusal.
        """
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
            # A hub whose state hash the report matches pushes no state; what
            # it published last is published again once the socket is up.
            has_services = bool(self._services_list) and not self._is_disabled
        if has_services:
            self._on_services(self)
        self._on_change()

    def _serve(self, client) -> "Exception | None":
        """Read frames until the channel ends, following it when it moves.

        A socket the channel moved off ends with the move: its reading
        goes on with the socket the move greeted.

        Args:
            client: The connected socket.

        Returns:
            What ended the channel, as :meth:`_serve_socket` says it.
        """
        while True:
            failure = self._serve_socket(client)
            with self._lock:
                is_moved = client is self._moved_from
                moving = self._moving
            if not is_moved or self._stop.is_set():
                return failure
            moving.wait(timeout=CLIENT_WS_SILENCE_TIMEOUT_S)
            with self._lock:
                successor = self._client if self._is_welcomed else None
            if successor is None or successor is client:
                return failure
            client = successor

    def _serve_socket(self, client) -> "Exception | None":
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
        threading.Thread(
            target=self._ping_on_interval,
            args=(client, ended),
            name="client_ping",
            daemon=True,
        ).start()
        while not self._stop.is_set():
            try:
                kind, payload = client.recv()
            except SocketClosed as closed:
                if closed.code == CLIENT_WS_CLOSE_REPLACED:
                    if not self._is_moved_from(client):
                        self._stand_aside()
                elif self._is_held(client):
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
            except Exception as error:  # noqa: BLE001 - logged, never fatal
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

    def _is_moved_from(self, client) -> bool:
        """Whether the channel moved off this socket, so its 4010 is expected."""
        with self._lock:
            return self._moved_from is client

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

    def _note_urls(self, urls: list) -> bool:
        """Write the hub's address list onto the binding, when it changed.

        Returns:
            Whether the list differs from the binding's.
        """
        cleaned = enrollment.clean_urls(urls)
        with self._lock:
            previous = list(self._binding.get("gateway_urls") or [])
            if previous == cleaned:
                return False
            self._binding["gateway_urls"] = cleaned
            binding_id = self._binding.get("id", "")
        self._log(f"the hub answers at {', '.join(cleaned)}")
        try:
            enrollment.note_urls(binding_id, cleaned)
        except OSError as error:
            self._log(f"could not record the hub's addresses: {error}")
            with self._lock:
                self._binding["gateway_urls"] = previous
        return True

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

    def _wait_out(self, delay: float) -> None:
        """Wait for the next turn: the delay, news, or a network change.

        The route to the hub is looked at every idle poll; a changed
        address ends the wait and puts the backoff back to its floor. While
        the device has no network, the wait ends once it has one.

        Args:
            delay: How long the turn asked to wait; infinite waits for news
                or a network change alone.
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
            with self._lock:
                is_offline_wait = self._wait_reason == WAIT_NO_NETWORK
            if is_offline_wait and not self._is_offline():
                self._log("this machine has a network again")
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
        if self._os_machine_id:
            report["machine"]["os_machine_id"] = self._os_machine_id
        if is_refresh:
            report["is_refresh"] = True
        client.send_text(json.dumps(report))

    def _report_on_interval(self, client, ended: threading.Event) -> None:
        """Report every interval until the socket ends, and look at the network.

        The route to the hub is looked at every idle poll between reports;
        a changed address is a network change.
        """
        due = time.monotonic() + CLIENT_REPORT_INTERVAL_S
        while True:
            wait_s = min(CLIENT_IDLE_POLL_INTERVAL_S, max(due - time.monotonic(), 0))
            if ended.wait(timeout=wait_s):
                return
            if time.monotonic() >= due:
                try:
                    self._report(client)
                except GatewayUnreachable:
                    return
                due = time.monotonic() + CLIENT_REPORT_INTERVAL_S
            if self._watch_network():
                self.change_network()

    def _ping_on_interval(self, client, ended: threading.Event) -> None:
        """Ping the socket at once and every interval until it ends."""
        while True:
            try:
                self._ping(client)
            except GatewayUnreachable:
                return
            if ended.wait(timeout=CLIENT_PING_INTERVAL_S):
                return

    def _ping(self, client) -> None:
        """Send a ``ping`` frame, its nonce and send time remembered."""
        nonce = secrets.token_urlsafe(8)
        with self._lock:
            self._ping_sent = (nonce, self._clock())
        client.send_text(json.dumps({"type": protocol.FRAME_PING, "nonce": nonce}))

    def _take_pong(self, client, message: dict) -> None:
        """Set the round trip from the pong to the last ping; any other is dropped."""
        with self._lock:
            sent = self._ping_sent
            if sent is None or self._client is not client:
                return
            nonce, sent_at = sent
            if message.get("nonce") != nonce:
                return
            self._ping_sent = None
            self._rtt_ms = round((self._clock() - sent_at) * 1000)
        self._on_change()

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
        elif message_type == protocol.FRAME_PONG:
            self._take_pong(client, message)
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
        is_moved = isinstance(urls, list) and self._note_urls(urls)
        if "overlays" in message:
            self._note_overlays(message.get("overlays"))
        terminals = message.get("terminals", [])
        is_disabled = bool(message.get("is_disabled"))
        with self._lock:
            self._services_list = [
                entry for entry in services if isinstance(entry, dict)
            ]
            self._reached_through = str(message.get("reached_through", "") or "")
            self._relay_url = str(message.get("relay_url", "") or "")
            self._is_panel_allowed = message.get("is_panel_allowed") is True
            self._terminals = clean_terminals(terminals)
            self._state_hash = str(message.get("hash", "") or "")
            self._is_refreshing = False
        self._take_disabled(is_disabled)
        if not is_disabled:
            self._on_services(self)
        self._on_change()
        if is_moved:
            self.change_network()

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
                self._rtt_ms = None
                self._ping_sent = None
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
        if self._is_welcomed:
            return CONNECTION_DISABLED if self._is_disabled else CONNECTION_CONNECTED
        return CONNECTION_WAITING if self._wait_reason else CONNECTION_CONNECTING

    def _is_refresh_over(self) -> bool:
        """Whether the refresh in flight is past its limit; the lock is held."""
        started, started_wall = self._refresh_since
        elapsed = self._clock() - started
        elapsed_wall = self._wall_clock() - started_wall
        limit = self._refresh_timeout_s
        return elapsed >= limit or elapsed_wall >= limit or elapsed_wall < 0

    def _refresh_timed_out(self, count: int) -> None:
        """End the refresh numbered ``count`` when nothing answered it."""
        with self._lock:
            if not self._is_refreshing or self._refresh_count != count:
                return
            self._is_refreshing = False
        self._on_change()

    def _on_unreachable(self, error: Exception) -> float:
        """Wait after a round that reached no address.

        A device with no network at all waits for one with no countdown.
        Otherwise the wait is the backoff, which doubles, and its reason
        says whether this client's virtual network of the hub's is on.
        """
        if self._is_offline():
            self._wait(WAIT_NO_NETWORK, channel_error(error), None)
            self._log(f"hub socket failed: {error}; this machine has no network")
            return float("inf")
        with self._lock:
            delay = self._backoff_s
            self._backoff_s = min(self._backoff_s * 2, CLIENT_BACKOFF_MAX_S)
            is_overlay_on = self._is_overlay_on
        reason = WAIT_HUB_OFF_OVERLAY if is_overlay_on else WAIT_HUB_SILENT
        self._wait(reason, channel_error(error), delay)
        self._log(f"hub socket failed: {error}; retrying in {delay}s")
        return delay

    def _on_rejected(self, error: Exception) -> float:
        """Take a refusal: the one that unbinds, or one the binding survives.

        A protocol refusal waits for a person; a certificate off the pin,
        and any other refusal, is asked again after ``CLIENT_BACKOFF_MAX_S``.

        Args:
            error: What the channel raised.

        Returns:
            Seconds until the next loop turn.
        """
        rejection = channel_error(error)
        code = rejection["code"]
        if code == CLIENT_REFUSAL_CODE_BINDING_UNKNOWN:
            return self._unbind(rejection)
        if code in CLIENT_PROTOCOL_REFUSAL_CODES:
            self._wait(WAIT_TOO_OLD, rejection, None)
            self._log(f"{error}; waiting for a refresh")
            return CLIENT_IDLE_POLL_INTERVAL_S
        if isinstance(error, GatewayUntrusted):
            reason = WAIT_UNTRUSTED
        else:
            with self._lock:
                is_overlay_on = self._is_overlay_on
            reason = WAIT_HUB_OFF_OVERLAY if is_overlay_on else WAIT_HUB_SILENT
        self._wait(reason, rejection, CLIENT_BACKOFF_MAX_S)
        self._log(f"{error}; asking again in {CLIENT_BACKOFF_MAX_S}s")
        return CLIENT_BACKOFF_MAX_S

    def _unbind(self, rejection: dict) -> float:
        """The hub holds no such binding any more: wait for a person's Leave."""
        self._wait(WAIT_UNKNOWN_DEVICE, rejection, None)
        self._log("unbound: the hub no longer knows this client")
        self._on_unbound(self)
        return CLIENT_IDLE_POLL_INTERVAL_S

    def _wait(self, reason: str, code: "dict | None", delay: "float | None") -> None:
        """Enter waiting on one reason, the refresh ended, and announce it.

        Args:
            reason: One of ``WAIT_REASONS``.
            code: The ``{"code", "params"}`` the round ended in.
            delay: Seconds until the next round; None while no countdown
                runs.
        """
        with self._lock:
            self._wait_reason = reason
            self._wait_code = dict(code) if code else None
            self._next_round_at = None if delay is None else self._wall_clock() + delay
            self._is_refreshing = False
        self._on_change()

    def _cut_round(self) -> None:
        """End the wait and the round in flight; the next round starts at once.

        The backoff goes back to its floor, and every dial of the round
        still waiting out its connect time is aborted, not waited for.
        """
        with self._lock:
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            dialings = list(self._dialings)
            if dialings:
                self._is_round_cut = True
        for dialing in dialings:
            dialing.settle()
        self._news.set()

    def _is_cut(self) -> bool:
        """Whether a network change ended the round in flight."""
        with self._lock:
            return self._is_round_cut

    def _take_round_cut(self) -> bool:
        """Whether a network change ended the last round; the mark is cleared."""
        with self._lock:
            is_cut = self._is_round_cut
            self._is_round_cut = False
        return is_cut

    def _is_offline(self) -> bool:
        """Whether this machine has no network at all, as its networks say."""
        return is_offline(self._local_networks())


class _ClientDialRound:
    """One round's sockets, dialled at once; the first to connect is kept."""

    def __init__(self, *, clients: list):
        """
        Args:
            clients: ``(url, client)`` per address, each socket unconnected.
        """
        self._clients = list(clients)
        self._results: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._is_settled = False

    def start(self) -> None:
        """Dial every address, each on a thread of its own."""
        for url, client in self._clients:
            threading.Thread(
                target=self._dial,
                args=(url, client),
                name="client_dial",
                daemon=True,
            ).start()

    def next_result(self, timeout_s: float) -> "tuple | None":
        """The next dial to end, as ``(url, client, error, handshake_s)``.

        Args:
            timeout_s: How long to wait for one.

        Returns:
            The open socket, None and the seconds its handshake took, or
            None, what the connect raised and 0; None when no dial ended
            within the timeout.
        """
        try:
            return self._results.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def settle(self, kept=None) -> None:
        """End the round: every socket but the kept one is aborted or closed.

        Args:
            kept: The round's socket, left open; None ends every dial.
        """
        with self._lock:
            self._is_settled = True
        for _url, client in self._clients:
            if client is not kept:
                client.abort()

    def _dial(self, url: str, client) -> None:
        """Connect one socket, timed; one that connects after the round settled is closed."""
        started = time.monotonic()
        try:
            client.connect()
        except (GatewayRefused, GatewayUnreachable, GatewayUntrusted) as error:
            self._results.put((url, None, error, 0.0))
            return
        handshake_s = time.monotonic() - started
        with self._lock:
            if not self._is_settled:
                self._results.put((url, client, None, handshake_s))
                return
        client.close()
