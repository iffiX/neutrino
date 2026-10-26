"""One hub's session: a binding, its session through the transport, and the waits between.

A session belongs to one binding and speaks to one hub, through the
client's transport, which holds the connection: the session gives it the
binding's keys and every candidate address with its path in ``dial``, and
the transport runs the rounds, the redials and the moves to a better path.
The candidates are the hub's address on its virtual network that is on, the
hub's name, and the addresses the binding holds. A network change, a
virtual network turning on, this machine's address toward the hub changing,
or a state naming other addresses, sends ``round``; new candidates are sent
in a ``dial`` again first.

Every frame of the hub's control stream passes through the transport as a
line. The session writes ``hello`` when a round's winner opens its session,
and again when the transport moves the live channel; it takes the
``welcome``, the ``state`` it answers with a ``report``, the ``pong`` that
sets the round trip, and the ``reply`` to each ``service``, ``persist`` and
``stop_session`` it asked. Streams open as connections of their own to the
transport.

A pending join is the transport's ``join``: it dials as a round does and
spends the ticket at the first address whose handshake completes under the
link's key; the binding then takes the hub's id and token, and is dialled.
The transport answers a join once, and the session tries it again by the
code. A binding a 0.5 client kept is moved first, over the hub's legacy
listener, when that is on.

The connection is one of five states: ``connected``, ``connecting`` while a
round dials, ``waiting`` once a round ended and the session waits for what
its reason names, ``replaced`` while another client holds the binding, and
``disabled`` while the hub has this client switched off. A waiting session
carries its reason and, while a countdown runs, the moment of the next
round.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import ipaddress
import secrets
import threading
import time
import urllib.parse

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_ADDRESS_SCHEME,
    CLIENT_BACKOFF_MAX_S,
    CLIENT_BACKOFF_MIN_S,
    CLIENT_HUB_ROLE,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_JOIN_RETRY_MIN_S,
    CLIENT_JOIN_TIMEOUT_S,
    CLIENT_LEAVE_TELL_TIMEOUT_S,
    CLIENT_LEGACY_KEY_PATH,
    CLIENT_PING_INTERVAL_S,
    CLIENT_PROTOCOL_REFUSAL_CODES,
    CLIENT_REFRESH_TIMEOUT_S,
    CLIENT_REFUSAL_CODE_ADMISSION_PAUSED,
    CLIENT_REFUSAL_CODE_BINDING_UNKNOWN,
    CLIENT_REPORT_INTERVAL_S,
    CLIENT_REQUEST_TIMEOUT_S,
    CLIENT_ROLE,
    CLIENT_SERVER_PATHS,
    CLIENT_SOFTWARE_PREFIX,
    CLIENT_STREAM_KIND_CONNECT,
    CLIENT_STREAM_KIND_EXEC,
    CLIENT_STREAM_KIND_SHELL,
    CLIENT_STREAM_TIMEOUT_S,
    PROTOCOL,
)
from neutrino_client.core import enrollment, protocol
from neutrino_client.core.channel import GatewayHttpChannel
from neutrino_client.core.static_key import public_key_of
from neutrino_client.core.streams import ClientStream
from neutrino_client.exceptions import (
    EnrollmentError,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
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

# The codes a round or a join ends in that are the session's own words.
CODE_HUB_UNREACHABLE = "hub_unreachable"
CODE_HUB_UNTRUSTED = "hub_untrusted"
CODE_HUB_KEY_MISSING = "hub_key_missing"
CODE_REPLACED = "replaced"
# The refusals of a join the hub answers that keep the ticket: tried again
# a minute later.
JOIN_RETRIED_CODES = ("control_unavailable", "channel_full")
# How long one turn of the session's thread waits when nothing is due.
SESSION_TICK_S = 1
# How long telling the transport to stop dialling may take.
UNDIAL_TIMEOUT_S = 2


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
        return {"code": CODE_HUB_UNTRUSTED, "params": {}}
    if isinstance(error, GatewayRefused):
        if error.code:
            return {"code": error.code, "params": dict(error.params)}
        return {"code": "hub_refused", "params": {}}
    return {"code": CODE_HUB_UNREACHABLE, "params": {"detail": str(error)}}


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


def clean_terminals(value) -> dict:
    """The state's ``terminals`` as the session holds it: machines and sessions.

    The hub sends a list of machines, each with its enabled accounts and its
    own ``sessions``; ``{machines, sessions}`` reads the same.

    Args:
        value: What the state carried.

    Returns:
        ``{"machines": [{device_id, name, is_online, accounts}], "sessions":
        [...]}``, each session as :func:`_clean_session` keeps it and
        stamped with its machine; a machine or a session without an id is
        dropped.
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
                "accounts": _clean_accounts(entry.get("accounts")),
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


def _clean_accounts(value) -> list:
    """A machine's enabled accounts, the first the default, each a name once."""
    accounts: list = []
    for item in value if isinstance(value, list) else []:
        name = item.get("account") if isinstance(item, dict) else item
        name = str(name or "").strip()
        if name and name not in accounts:
            accounts.append(name)
    return accounts


def _clean_session(entry, device_id: str) -> "dict | None":
    """One shell session as the session holds it.

    Args:
        entry: What the hub sent for it.
        device_id: The machine it was listed under, empty when the entry
            names its own.

    Returns:
        ``{session_id, device_id, account, owner, owner_name, is_owned,
        is_persistent, is_shared, attached_count, title, started_at}``; None
        for an entry without a session id or a machine.
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
        "account": str(entry.get("account", "") or ""),
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


def _clean_apps(value) -> list:
    """The state's ``apps`` as the session holds them, each with an id."""
    apps = []
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        apps.append(
            {
                "id": str(entry["id"]),
                "title": str(entry.get("title", "") or ""),
                "source": str(entry.get("source", "") or ""),
                "device_id": str(entry.get("device_id", "") or ""),
                "device_name": str(entry.get("device_name", "") or ""),
                "local_name": str(entry.get("local_name", "") or ""),
            }
        )
    return apps


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


class ClientHubSession:
    """One binding's session to its hub, through the transport, until stopped."""

    def __init__(
        self,
        *,
        binding: dict,
        transport,
        hostname: str,
        platform_tuple: dict,
        os_machine_id: str = "",
        log=print,
        on_change=None,
        on_services=None,
        on_disabled=None,
        on_unbound=None,
        on_joined=None,
        on_welcomed=None,
        local_networks=None,
        refresh_timeout_s: float = CLIENT_REFRESH_TIMEOUT_S,
        clock=time.monotonic,
        wall_clock=time.time,
        legacy_channel=None,
    ):
        """
        Args:
            binding: The binding this session speaks for.
            transport: The
                :class:`~neutrino_client.core.transport.ClientTransportChannel`
                the session goes through.
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
            on_welcomed: ``on_welcomed(session, hub_id)`` is called after
                every welcome, with the hub id it names, before the binding
                takes that id and before the session's first state is read;
                None for nobody listening.
            local_networks: Returns this machine's networks, as
                ``a.b.c.d/n`` or IPv6 prefixes, by which a candidate address
                reads as ``lan``; None knows none.
            refresh_timeout_s: How long a refresh waits for its answer.
            clock: The monotonic clock a refresh's limit and the waits are
                measured on.
            wall_clock: The wall clock, read beside it, so a jump of either
                clock, as a machine waking from sleep makes, ends the
                refresh instead of holding it.
            legacy_channel: ``legacy_channel(url, fingerprint)`` makes the
                pinned channel a 0.5 binding is moved over, with ``post``;
                None makes a :class:`GatewayHttpChannel`.
        """
        self._log = log
        self._lock = threading.Lock()
        self._binding = dict(binding)
        self._transport = transport
        self._hostname = hostname
        self._platform_tuple = dict(platform_tuple)
        self._os_machine_id = os_machine_id
        self._on_change = on_change if on_change is not None else _nobody
        self._on_services = on_services if on_services is not None else _nobody
        self._on_disabled = on_disabled if on_disabled is not None else _nobody
        self._on_unbound = on_unbound if on_unbound is not None else _nobody
        self._on_joined = on_joined if on_joined is not None else _adopt_join
        self._on_welcomed = on_welcomed if on_welcomed is not None else _nobody
        self._local_networks = (
            local_networks if local_networks is not None else _no_networks
        )
        self._legacy_channel = (
            legacy_channel if legacy_channel is not None else _pinned_channel
        )
        self._clock = clock
        self._wall_clock = wall_clock
        # The binding's id when the session began, the same for its life,
        # whatever id a completed join brings; and the label the transport
        # knows the binding by now.
        self._local_key = str(binding.get("id", ""))
        self._label = self._local_key
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        # What the session thread has to do: the transport given the
        # binding, a dial to send again with new candidates, a round to ask
        # for, and when the next join or move of a pending or 0.5 binding
        # is due on the monotonic clock.
        self._is_dialed = False
        self._is_dial_due = False
        self._is_round_due = False
        self._next_attempt_at = 0.0
        self._backoff_s = CLIENT_BACKOFF_MIN_S
        # The live session: whether a welcome came, the session a hello
        # went out on, the address and path the transport named.
        self._is_welcomed = False
        # Whether the session the hub refused by a frame is the one that
        # ends next, whose end then says nothing new.
        self._is_session_refused = False
        self._channel_open = threading.Event()
        self._address = ""
        self._path = ""
        self._hub_software = ""
        # The round trip the last pong measured, and the last ping sent.
        self._rtt_ms: "int | None" = None
        self._ping_sent: "tuple[str, float] | None" = None
        self._next_report_at = 0.0
        self._next_ping_at = 0.0
        # The questions waiting for a reply, by request.
        self._replies: dict = {}
        # This machine's own address toward the hub, as last seen.
        self._source_address: "str | None" = None
        self._next_look_at = 0.0
        self._is_replaced = False
        self._wait_reason = ""
        self._wait_code: "dict | None" = None
        self._next_round_at: "float | None" = None
        self._services_list: list = []
        self._apps_list: list = []
        self._reached_through = ""
        self._is_panel_allowed = False
        self._terminals: dict = {"machines": [], "sessions": []}
        self._state_hash = ""
        self._is_disabled = False
        self._was_disabled = False
        self._is_refreshing = False
        self._refresh_count = 0
        self._refresh_timeout_s = refresh_timeout_s
        self._refresh_since = (0.0, 0.0)
        # The hub's address on its virtual network that is on, and that
        # network's engine; empty while none is on.
        self._overlay_host = ""
        self._overlay_provider = ""
        self._is_overlay_on = False
        # The members of the state's ``urls`` that are a server's address,
        # by the path each reaches the hub by.
        self._server_urls: dict = {path: "" for path in CLIENT_SERVER_PATHS}

    # --- what the resident reads ---

    @property
    def local_key(self) -> str:
        """The binding's id when the session began, unchanged by a completed join."""
        return self._local_key

    @property
    def label(self) -> str:
        """The binding's label the transport knows it by now."""
        with self._lock:
            return self._label

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
        """The binding's id as it stands now."""
        with self._lock:
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
        """The hub's address that last answered."""
        with self._lock:
            return self._binding.get("gateway_url", "")

    def hub_software(self) -> str:
        """What the hub's welcome named as its software, empty before one."""
        with self._lock:
            return self._hub_software

    def connection(self) -> str:
        """Where the session stands, one of ``CONNECTION_STATES``."""
        with self._lock:
            return self._connection()

    def wait_channel(self, timeout_s: float) -> bool:
        """Wait until a welcomed session carries the channel.

        Args:
            timeout_s: How long to wait.

        Returns:
            Whether one does.
        """
        return self._channel_open.wait(timeout_s)

    def is_refreshing(self) -> bool:
        """Whether a refresh waits for its answer, within its limit."""
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
        """The typed service list the hub last sent, while its session is up.

        Returns:
            The entries; empty while the session is down, so a hub that is
            unreachable publishes nothing.
        """
        with self._lock:
            if not self._is_welcomed:
                return []
            return [dict(entry) for entry in self._services_list]

    def app_entries(self) -> list:
        """The apps the hub last sent, while its session is up.

        Returns:
            ``[{id, title, source, device_id, device_name, local_name}]``;
            empty while the session is down.
        """
        with self._lock:
            if not self._is_welcomed:
                return []
            return [dict(app) for app in self._apps_list]

    def reached_through(self) -> str:
        """The way the channel reached the hub, as the hub's last state named it."""
        with self._lock:
            return self._reached_through

    def rtt_ms(self) -> "int | None":
        """The round trip from this client's last ping to its pong.

        Returns:
            Whole milliseconds; None before the first pong on the live
            session and while the hub is not ``connected``.
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
        """How this machine joins each of the hub's virtual networks, as last named."""
        with self._lock:
            return [dict(item) for item in self._binding.get("overlays") or []]

    def overlay_choice(self) -> "tuple[bool, str]":
        """Where the hub's virtual network last stood, and the engine chosen."""
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
        """The machines the hub offers a terminal on, while its session is up.

        Returns:
            ``[{device_id, name, is_online, accounts}]``; empty while the
            session is down.
        """
        with self._lock:
            if not self._is_welcomed:
                return []
            return [
                dict(entry, accounts=list(entry["accounts"]))
                for entry in self._terminals["machines"]
            ]

    def note_session_flags(
        self,
        session_id: str,
        is_persistent: "bool | None" = None,
        is_shared: "bool | None" = None,
    ) -> None:
        """Show a shell session's flags as set, until the hub's next state.

        Args:
            session_id: The shell session's id.
            is_persistent: Whether the machine keeps it; None leaves it.
            is_shared: Whether every client with terminal rights lists it;
                None leaves it.
        """
        with self._lock:
            for entry in self._terminals["sessions"]:
                if entry["session_id"] != session_id:
                    continue
                if is_persistent is not None:
                    entry["is_persistent"] = bool(is_persistent)
                if is_shared is not None:
                    entry["is_shared"] = bool(is_shared)

    def terminal_sessions(self) -> list:
        """The shell sessions the hub lists for this client, while its session is up."""
        with self._lock:
            if not self._is_welcomed:
                return []
            return [dict(entry) for entry in self._terminals["sessions"]]

    # --- what the resident does ---

    def set_overlay_route(self, host: str, provider: str) -> None:
        """Name the hub's address on its virtual network that is on, and its engine.

        The candidates change, so the transport is given them again; a
        network that just turned on, or whose peers changed, is a network
        change, so a round starts at once. An empty host drops the address.

        Args:
            host: The hub's address on the network; empty while the hub
                names none on it, or once it is off.
            provider: The network's engine, ``netbird`` or ``easytier``;
                empty once it is off.
        """
        with self._lock:
            is_changed = (host, provider if host else "") != (
                self._overlay_host,
                self._overlay_provider,
            )
            self._overlay_host = host
            self._overlay_provider = provider if host else ""
            self._is_overlay_on = bool(provider)
            if is_changed:
                self._is_dial_due = self._is_dialed
        if provider:
            self.change_network()
        elif is_changed:
            self._news.set()

    def change_network(self) -> None:
        """Start one round at once, as a network change does.

        A hub ``replaced`` or ``disabled``, or waiting on a reason only a
        person ends, is left as it is. A pending join is tried again now;
        any other hub gets a round from the transport, which on a connected
        hub runs beside the live channel and moves it only to a better path.
        """
        with self._lock:
            connection = self._connection()
            if connection in (CONNECTION_REPLACED, CONNECTION_DISABLED):
                return
            if self._wait_reason in WAIT_REASONS_HELD:
                return
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            if self._is_dialed:
                self._is_round_due = True
            else:
                self._next_attempt_at = 0.0
        self._news.set()

    def reconnect(self) -> None:
        """Take the binding back from the client that replaced it, and connect now."""
        with self._lock:
            self._is_replaced = False
            self._is_dial_due = self._is_dialed
        self._news.set()
        self._on_change()

    def refresh(self) -> bool:
        """Ask the hub again now, and wait for its answer as refreshing.

        A connected hub is sent a report with ``is_refresh``, which the hub
        answers with its whole state; a hub that is connecting or waiting
        has its wait ended and a round started. Refreshing ends with the
        next state, a round ending in a code, or ``refresh_timeout_s``.

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
            is_live = connection == CONNECTION_CONNECTED
            if not is_live:
                self._wait_reason = ""
                self._wait_code = None
                self._next_round_at = None
                self._backoff_s = CLIENT_BACKOFF_MIN_S
                if self._is_dialed:
                    self._is_round_due = True
                else:
                    self._next_attempt_at = 0.0
        timer = threading.Timer(
            self._refresh_timeout_s, self._refresh_timed_out, args=(count,)
        )
        timer.daemon = True
        timer.start()
        if is_live:
            try:
                self._report(is_refresh=True)
            except GatewayUnreachable:
                pass
        self._news.set()
        self._on_change()
        return True

    def ask_service(
        self, entry_id: str, timeout_s: float = CLIENT_STREAM_TIMEOUT_S
    ) -> dict:
        """Send a ``service`` frame for one entry and take the hub's reply.

        Args:
            entry_id: The published entry's id.
            timeout_s: How long to wait for the reply.

        Returns:
            The reply's ``params``: the entry's material.

        Raises:
            GatewayRefusedDetail: When the hub replied with a code.
            GatewayUnreachable: When the hub is not connected, its session
                ends, or no reply arrives in time.
        """
        return self._ask(protocol.FRAME_SERVICE, {"id": entry_id}, timeout_s)

    def ask_panel_service(self, timeout_s: float = CLIENT_STREAM_TIMEOUT_S) -> dict:
        """Send a ``service`` frame for the hub's own panel and take the reply.

        Args:
            timeout_s: How long to wait for the reply.

        Returns:
            The reply's ``params``: ``{token}``, a sign-in usable once.

        Raises:
            GatewayRefusedDetail: When the hub replied with a code,
                ``permission_denied {kind: panel}`` among them.
            GatewayUnreachable: When the hub is not connected, its session
                ends, or no reply arrives in time.
        """
        return self._ask(protocol.FRAME_SERVICE, {"is_panel": True}, timeout_s)

    def open_connect(self, args: dict) -> ClientStream:
        """Open a ``connect`` stream: one TCP connection the hub carries.

        The hub's refusal arrives as the stream's close before its accept:
        a read comes back empty and ``wait_close`` raises it.

        Args:
            args: ``{"id"}`` naming a published entry, or
                ``{"is_panel": True}`` for the hub's own panel.

        Returns:
            The stream, its raw bytes after the accept.

        Raises:
            GatewayUnreachable: When the hub is not connected.
        """
        return self._open(
            dict(args, kind=CLIENT_STREAM_KIND_CONNECT), is_raw_after_accept=True
        )

    def open_shell(
        self,
        device_id: str,
        cols: int,
        rows: int,
        session_id: str,
        is_resumed: bool = False,
        is_shared: bool = False,
        account: str = "",
    ) -> ClientStream:
        """Open a ``shell`` stream to one managed machine.

        The hub's refusal, or the shell's ``exit_code``, arrives as the
        stream's close.

        Args:
            device_id: The machine, as the state's ``terminals`` names it.
            cols: The terminal's width in columns.
            rows: The terminal's height in rows.
            session_id: The shell session's id, a fresh uuid for a new one.
            is_resumed: Whether ``session_id`` names a session the machine
                keeps, attached to again with its kept output.
            is_shared: Whether a new session is shared from its start.
            account: The enabled account it runs as; empty for the first.

        Returns:
            The stream, to read, send on, resize and close.

        Raises:
            GatewayUnreachable: When the hub is not connected.
        """
        open_record = {
            "kind": CLIENT_STREAM_KIND_SHELL,
            "device_id": device_id,
            "cols": int(cols),
            "rows": int(rows),
            "account": str(account or ""),
            "session_id": session_id,
        }
        if is_resumed:
            open_record["is_resumed"] = True
        if is_shared:
            open_record["is_shared"] = True
        return self._open(open_record)

    def open_exec(
        self,
        device_id: str,
        argv: list,
        is_tty: bool,
        cols: int,
        rows: int,
        account: str = "",
    ) -> ClientStream:
        """Open an ``exec`` stream: one command on one managed machine.

        Without ``is_tty`` each piece read starts with its output's byte,
        1 for stdout and 2 for stderr. The hub's refusal, or the command's
        ``exit_code``, arrives as the stream's close.

        Args:
            device_id: The machine, as the state's ``terminals`` names it.
            argv: The command and its arguments, run with no shell between.
            is_tty: Whether it runs on a pseudo-terminal.
            cols: The pseudo-terminal's width in columns.
            rows: The pseudo-terminal's height in rows.
            account: The enabled account it runs as; empty for the first.

        Returns:
            The stream, to read, send on, end the input of and close.

        Raises:
            GatewayUnreachable: When the hub is not connected.
        """
        return self._open(
            {
                "kind": CLIENT_STREAM_KIND_EXEC,
                "device_id": device_id,
                "argv": [str(part) for part in argv],
                "is_tty": bool(is_tty),
                "cols": int(cols),
                "rows": int(rows),
                "account": str(account or ""),
            },
            is_fd_tagged=not is_tty,
        )

    def persist_shell(
        self,
        session_id: str,
        is_persistent: "bool | None" = None,
        is_shared: "bool | None" = None,
        timeout_s: float = CLIENT_STREAM_TIMEOUT_S,
    ) -> dict:
        """Tell the hub whether a shell session outlives its stream, and who sees it.

        The ``persist`` names only the flags given.

        Args:
            session_id: The shell session's id.
            is_persistent: Whether the machine keeps it once nobody is
                attached; None leaves it.
            is_shared: Whether every client with terminal rights on the
                machine lists it; None leaves it.
            timeout_s: How long to wait for the reply.

        Returns:
            The reply's ``params``.

        Raises:
            GatewayRefusedDetail: When the hub refused, ``session_unknown``
                and ``session_not_owned`` among the codes.
            GatewayUnreachable: When the hub is not connected, its session
                ends, or no reply arrives in time.
        """
        fields = {"session_id": session_id}
        if is_persistent is not None:
            fields["is_persistent"] = bool(is_persistent)
        if is_shared is not None:
            fields["is_shared"] = bool(is_shared)
        return self._ask(protocol.FRAME_PERSIST, fields, timeout_s)

    def stop_shell_session(
        self, session_id: str, timeout_s: float = CLIENT_STREAM_TIMEOUT_S
    ) -> dict:
        """Have the hub end a shell session on its machine.

        Args:
            session_id: The shell session's id.
            timeout_s: How long to wait for the reply.

        Returns:
            The reply's ``params``.

        Raises:
            GatewayRefusedDetail: When the hub refused, ``session_unknown``
                among the codes.
            GatewayUnreachable: When the hub is not connected, its session
                ends, or no reply arrives in time.
        """
        return self._ask(
            protocol.FRAME_STOP_SESSION, {"session_id": session_id}, timeout_s
        )

    def tell_left(self, timeout_s: float = CLIENT_LEAVE_TELL_TIMEOUT_S) -> dict:
        """Tell the hub this client leaves it, once, through the transport.

        The binding is already forgotten here; the answer changes nothing.

        Args:
            timeout_s: How long the transport is given.

        Returns:
            Empty when the hub took it; ``{code, params}`` otherwise.
        """
        with self._lock:
            binding = dict(self._binding)
        if binding.get("is_pending") or not binding.get("token"):
            return {}
        try:
            return self._transport.command(
                "leave",
                {
                    "binding": binding.get("id", ""),
                    "hub_key": binding.get("hub_key", ""),
                    "private_key": binding.get("private_key", ""),
                    "psk": enrollment.psk_of(binding),
                    "role": CLIENT_ROLE,
                    "protocol": PROTOCOL,
                    "addresses": [item["address"] for item in self._candidates()],
                },
                timeout_s,
            )
        except GatewayUnreachable as error:
            return channel_error(error)

    # --- the transport's news ---

    def transport_ready(self) -> None:
        """The transport started: the binding is given to it again."""
        with self._lock:
            self._is_dialed = False
            self._next_attempt_at = 0.0
        self._news.set()

    def transport_lost(self) -> None:
        """The transport ended: no session stands, and no reply comes."""
        with self._lock:
            self._is_dialed = False
            was_live = self._is_welcomed
            self._drop_session()
        self._fail_replies()
        if was_live:
            self._log("the client's transport ended; the hub's session with it")
        self._on_change()

    def take_line(self, line: dict) -> None:
        """Take one event or frame the transport passed for this binding.

        Args:
            line: An event line, or a ``{frame, binding}`` line.
        """
        frame = line.get("frame")
        if isinstance(frame, dict):
            self._take_frame(frame)
            return
        event = line.get("event")
        if event == "session_open":
            self._take_session_open(line)
        elif event == "round_end":
            self._take_round_end(line)
        elif event == "session_end":
            self._take_session_end(line)

    # --- the loop ---

    def start(self) -> None:
        """Hand the binding to the transport and run the session's own thread."""
        self._transport.listen_binding(self.label, self.take_line)
        thread = threading.Thread(
            target=self.run_forever, name=f"hub_session_{self._local_key}", daemon=True
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        """Stop dialling the hub and end the session's thread. Idempotent."""
        self._stop.set()
        self._news.set()
        label = self.label
        with self._lock:
            is_dialed = self._is_dialed
            self._is_dialed = False
            self._drop_session()
        self._fail_replies()
        self._transport.forget_binding(label, self.take_line)
        if is_dialed:
            try:
                self._transport.command("undial", {"binding": label}, UNDIAL_TIMEOUT_S)
            except GatewayUnreachable:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=UNDIAL_TIMEOUT_S)

    def run_forever(self) -> None:
        """Do what is due, turn after turn, until the session is stopped."""
        while not self._stop.is_set():
            self._news.clear()
            try:
                self.run_once()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(
                    f"the hub session's turn failed: {type(error).__name__}: {error}"
                )
            self._news.wait(timeout=SESSION_TICK_S)

    def run_once(self) -> None:
        """One turn: a join, a move or a dial when due, then the interval's reports and pings."""
        if not self._transport.is_ready():
            return
        with self._lock:
            is_held = self._is_replaced or self._wait_reason in WAIT_REASONS_HELD
            is_pending = self._binding.get("is_pending") is True
            is_legacy = enrollment.is_legacy(self._binding)
            is_due = self._clock() >= self._next_attempt_at
            is_dialed = self._is_dialed
            is_dial_due = self._is_dial_due
            is_round_due = self._is_round_due
        if is_pending:
            if is_due and not is_held:
                self._join()
            return
        if is_legacy:
            if is_due and not is_held:
                self._move_legacy()
            return
        if not is_dialed or is_dial_due:
            if not is_held or is_dialed:
                self._dial()
            return
        if is_round_due:
            with self._lock:
                self._is_round_due = False
            self._command("round", {"binding": self.label})
        self._keep_up()

    # --- what happens on the thread ---

    def _dial(self) -> None:
        """Give the transport the binding and every candidate."""
        with self._lock:
            binding = dict(self._binding)
            label = self._label
            self._is_dial_due = False
        candidates = self._candidates()
        answer = self._command(
            "dial",
            {
                "binding": label,
                "hub_key": binding.get("hub_key", ""),
                "private_key": binding.get("private_key", ""),
                "psk": enrollment.psk_of(binding),
                "role": CLIENT_ROLE,
                "protocol": PROTOCOL,
                "candidates": candidates,
            },
        )
        if answer is None:
            return
        with self._lock:
            was_dialed = self._is_dialed
            self._is_dialed = True
            is_round_due = self._is_round_due and was_dialed
            self._is_round_due = False
        if is_round_due:
            self._command("round", {"binding": label})
        self._log(
            "dialling the hub at "
            + ", ".join(f"{item['address']} ({item['path']})" for item in candidates)
        )

    def _join(self) -> None:
        """Spend the pending join's ticket through the transport, once."""
        with self._lock:
            binding = dict(self._binding)
            label = self._label
        fields = {
            "binding": label,
            "hub_key": binding.get("hub_key", ""),
            "private_key": binding.get("private_key", ""),
            "addresses": [item["address"] for item in self._candidates()],
        }
        fields.update(enrollment.join_payload(binding.get("ticket", "")))
        try:
            answer = self._transport.command("join", fields, CLIENT_JOIN_TIMEOUT_S)
        except GatewayUnreachable as error:
            self._join_failed(
                {"code": CODE_HUB_UNREACHABLE, "params": {"detail": str(error)}}
            )
            return
        if answer.get("code"):
            self._join_failed(
                {"code": str(answer["code"]), "params": _params_of(answer)}
            )
            return
        try:
            completed = enrollment.joined_binding(
                binding,
                str(answer.get("binding_id", "") or ""),
                str(answer.get("token", "") or ""),
            )
        except EnrollmentError as error:
            self._join_failed({"code": error.code, "params": dict(error.params)})
            return
        try:
            self._on_joined(self, completed)
        except OSError as error:
            self._log(f"the join could not be kept: {error}")
            self._join_failed(
                {"code": CODE_HUB_UNREACHABLE, "params": {"detail": str(error)}}
            )
            return
        self._relabel(completed["id"])
        self._log("joined the hub")
        self._news.set()

    def _join_failed(self, code: dict) -> None:
        """Wait after a join that did not complete, by its code.

        ``hub_unreachable`` waits the backoff, ``hub_untrusted``,
        ``control_unavailable`` and ``channel_full`` a minute, and
        ``admission_paused`` the seconds the hub names; any other code is
        the hub refusing the ticket, which waits for good.
        """
        name = code["code"]
        if name == CODE_HUB_UNREACHABLE:
            self._unreachable(code, None)
        elif name == CODE_HUB_UNTRUSTED:
            self._wait(WAIT_UNTRUSTED, code, CLIENT_BACKOFF_MAX_S, is_retried=True)
        elif name == CLIENT_REFUSAL_CODE_ADMISSION_PAUSED:
            try:
                delay = float(code["params"].get("retry_after_s") or 0)
            except (TypeError, ValueError):
                delay = 0
            delay = max(delay, CLIENT_JOIN_RETRY_MIN_S)
            self._wait(WAIT_ADMISSION_PAUSED, code, delay, is_retried=True)
            self._log(f"the hub paused admissions; joining again in {delay:g}s")
        elif name in JOIN_RETRIED_CODES:
            self._wait(
                self._silent_reason(), code, CLIENT_BACKOFF_MAX_S, is_retried=True
            )
        else:
            self._wait(WAIT_JOIN_REFUSED, code, None)
            self._log(f"the hub refused the join: {name}")

    def _move_legacy(self) -> None:
        """Move a 0.5 binding to the transport over the hub's legacy listener.

        The hub's static key comes back for this client's own; a hub whose
        legacy listener is off answers nothing, and the binding waits on
        ``hub_key_missing``.
        """
        with self._lock:
            binding = dict(self._binding)
        private_key = enrollment.make_private_key()
        body = {
            "id": binding.get("id", ""),
            "token": binding.get("token", ""),
            "public_key": public_key_of(private_key),
        }
        for url in enrollment.stored_urls(binding):
            try:
                answer = self._legacy_channel(url, binding.get("fingerprint", "")).post(
                    CLIENT_LEGACY_KEY_PATH, body
                )
            except GatewayRefused as error:
                if error.code == CLIENT_REFUSAL_CODE_BINDING_UNKNOWN:
                    self._unbind({"code": error.code, "params": dict(error.params)})
                    return
                continue
            except (GatewayUnreachable, GatewayUntrusted, ValueError):
                continue
            hub_key = str(answer.get("key", "") or "").strip().lower()
            if not enrollment.is_key(hub_key):
                continue
            moved = enrollment.moved_binding(binding, hub_key, private_key)
            try:
                enrollment.add_binding(moved)
            except (OSError, ValueError) as error:
                self._log(f"the moved binding could not be kept: {error}")
                return
            with self._lock:
                self._binding = moved
            self._log(f"the binding moved to the transport at {url}")
            self._news.set()
            return
        self._unreachable({"code": CODE_HUB_KEY_MISSING, "params": {}}, None)

    def _keep_up(self) -> None:
        """Report and ping on their intervals, and look at the route to the hub."""
        now = self._clock()
        with self._lock:
            is_live = self._is_welcomed
            is_report_due = is_live and now >= self._next_report_at
            is_ping_due = is_live and now >= self._next_ping_at
            is_look_due = now >= self._next_look_at
            is_offline_wait = self._wait_reason == WAIT_NO_NETWORK
        if is_report_due:
            try:
                self._report()
            except GatewayUnreachable:
                pass
        if is_ping_due:
            try:
                self._ping()
            except GatewayUnreachable:
                pass
        if not is_look_due:
            return
        with self._lock:
            self._next_look_at = now + CLIENT_IDLE_POLL_INTERVAL_S
        if self._watch_network():
            self.change_network()
        elif is_offline_wait and not self._is_offline():
            self._log("this machine has a network again")
            self.change_network()

    # --- the transport's events ---

    def _take_session_open(self, line: dict) -> None:
        """A round's winner opened its session: say hello on it."""
        address = str(line.get("address", "") or "")
        if address and "://" not in address:
            address = f"{CLIENT_ADDRESS_SCHEME}://{address}"
        path = str(line.get("path", "") or "")
        with self._lock:
            is_move = self._is_welcomed
            self._is_session_refused = False
            self._address = address
            self._path = path
            if not is_move:
                self._wait_reason = ""
                self._wait_code = None
                self._next_round_at = None
        if is_move:
            self._log(f"the channel moves to {address} ({path})")
        try:
            self._send(self._hello())
        except GatewayUnreachable:
            return
        self._on_change()

    def _take_round_end(self, line: dict) -> None:
        """A round ended with no session: wait by its code."""
        code = {"code": str(line.get("code", "") or ""), "params": _params_of(line)}
        try:
            next_round_s = float(line.get("next_round_s") or 0)
        except (TypeError, ValueError):
            next_round_s = 0.0
        with self._lock:
            if self._is_welcomed:
                return
        self._take_refusal(code, next_round_s if next_round_s > 0 else None)

    def _take_session_end(self, line: dict) -> None:
        """The live session ended: by a refusal, or a round starts at once."""
        code = str(line.get("code", "") or "")
        with self._lock:
            was_live = self._is_welcomed
            is_told = self._is_session_refused
            self._is_session_refused = False
            self._drop_session()
        self._fail_replies()
        if code and not is_told:
            self._take_refusal({"code": code, "params": _params_of(line)}, None)
        elif was_live:
            self._log("the hub's session ended; the transport dials again")
        self._on_change()

    def _take_frame(self, frame: dict) -> None:
        """Take one frame of the hub's control stream."""
        kind = frame.get("type")
        if kind == protocol.FRAME_WELCOME:
            self._take_welcome(frame)
        elif kind == protocol.FRAME_STATE:
            self._take_state(frame)
            try:
                self._report()
            except GatewayUnreachable:
                pass
        elif kind == protocol.FRAME_PONG:
            self._take_pong(frame)
        elif kind == protocol.FRAME_REPLY:
            self._take_reply(frame)
        elif kind == protocol.FRAME_REFUSED:
            with self._lock:
                self._drop_session()
                self._is_session_refused = True
            self._fail_replies()
            self._take_refusal(
                {"code": str(frame.get("code", "") or ""), "params": _params_of(frame)},
                None,
            )
        else:
            self._log(f"ignoring a {kind!r} frame from the hub")

    def _take_welcome(self, welcome: dict) -> None:
        """The hub's identity card: the channel is open."""
        if welcome.get("role") != CLIENT_HUB_ROLE:
            self._log("the hub's welcome names another role; ignored")
            return
        hub_id = str(welcome.get("id", "") or "")
        self._on_welcomed(self, hub_id)
        self._note_hub(welcome)
        with self._lock:
            self._is_welcomed = True
            self._hub_software = str(welcome.get("software", "") or "")
            self._backoff_s = CLIENT_BACKOFF_MIN_S
            self._rtt_ms = None
            self._ping_sent = None
            self._next_ping_at = 0.0
            self._next_report_at = self._clock() + CLIENT_REPORT_INTERVAL_S
            is_refreshing = self._is_refreshing
            address = self._address
            has_services = bool(self._services_list) and not self._is_disabled
        self._channel_open.set()
        if address:
            self._note_url(address)
        try:
            self._report(is_refresh=is_refreshing)
        except GatewayUnreachable:
            pass
        self._news.set()
        if has_services:
            self._on_services(self)
        self._on_change()

    def _take_state(self, message: dict) -> None:
        """Replace what is held with the state the hub just sent."""
        services = message.get("services", [])
        if not isinstance(services, list):
            services = []
        urls = message.get("urls")
        is_moved = isinstance(urls, list) and self._note_urls(urls)
        if "overlays" in message:
            self._note_overlays(message.get("overlays"))
        is_disabled = bool(message.get("is_disabled"))
        server_urls = {
            path: str(message.get(f"{path}_url", "") or "")
            for path in CLIENT_SERVER_PATHS
        }
        with self._lock:
            self._services_list = [
                dict(entry) for entry in services if isinstance(entry, dict)
            ]
            self._apps_list = _clean_apps(message.get("apps"))
            self._reached_through = str(message.get("reached_through", "") or "")
            is_moved = is_moved or server_urls != self._server_urls
            self._server_urls = server_urls
            self._is_panel_allowed = message.get("is_panel_allowed") is True
            self._terminals = clean_terminals(message.get("terminals", []))
            self._state_hash = str(message.get("hash", "") or "")
            self._is_refreshing = False
            if is_moved:
                self._is_dial_due = self._is_dialed
                self._is_round_due = True
        self._take_disabled(is_disabled)
        if not is_disabled:
            self._on_services(self)
        if is_moved:
            self._news.set()
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

    def _take_pong(self, message: dict) -> None:
        """Set the round trip from the pong to the last ping; any other is dropped."""
        with self._lock:
            sent = self._ping_sent
            if sent is None:
                return
            nonce, sent_at = sent
            if message.get("nonce") != nonce:
                return
            self._ping_sent = None
            self._rtt_ms = round((self._clock() - sent_at) * 1000)
        self._on_change()

    def _take_reply(self, message: dict) -> None:
        """Hand a reply to the question that waits for it."""
        request = str(message.get("request", "") or "")
        with self._lock:
            waiter = self._replies.get(request)
        if waiter is None:
            self._log("dropping a reply to a question nobody waits for")
            return
        waiter[1] = message
        waiter[0].set()

    def _take_refusal(self, code: dict, next_round_s: "float | None") -> None:
        """Wait by the code a round, a session or a refused frame ended in.

        ``binding_unknown`` unbinds, ``replaced`` is another client taking
        the binding, a protocol refusal waits for a new client, and every
        other code waits for the transport's next round.
        """
        name = code["code"]
        if name == CLIENT_REFUSAL_CODE_BINDING_UNKNOWN:
            self._unbind(code)
        elif name == CODE_REPLACED:
            self._stand_aside()
        elif name in CLIENT_PROTOCOL_REFUSAL_CODES:
            self._wait(WAIT_TOO_OLD, code, None)
            self._log(f"the hub refused this client's protocol: {name}")
        elif name == CODE_HUB_UNTRUSTED:
            self._wait(WAIT_UNTRUSTED, code, next_round_s or CLIENT_BACKOFF_MAX_S)
        elif name == CODE_HUB_UNREACHABLE or not name:
            self._unreachable(code, next_round_s)
        else:
            self._wait(
                self._silent_reason(), code, next_round_s or CLIENT_BACKOFF_MAX_S
            )
            self._log(f"the hub refused the session: {name}")

    # --- the pieces ---

    def _candidates(self) -> list:
        """Every address a round dials, each with its path, each once.

        Returns:
            ``[{address, path}]``: the hub's address on its virtual network
            that is on, the hub's name, and the addresses the binding holds.
        """
        with self._lock:
            binding = dict(self._binding)
            overlay_host = self._overlay_host
            overlay_provider = self._overlay_provider
        stored = enrollment.dialable_urls(enrollment.stored_urls(binding))
        gateway_url = stored[0] if stored else ""
        try:
            port = urllib.parse.urlsplit(gateway_url).port or 0
        except ValueError:
            port = 0
        candidates: list = []
        if overlay_host and port:
            bracketed = f"[{overlay_host}]" if ":" in overlay_host else overlay_host
            candidates.append(
                {"address": f"tcp://{bracketed}:{port}", "path": overlay_provider}
            )
        name_address = enrollment.hub_name_address(gateway_url)
        if name_address:
            candidates.append({"address": name_address, "path": "lan"})
        for url in stored:
            candidates.append({"address": url, "path": self._path_of(url)})
        kept: list = []
        for candidate in candidates:
            if all(other["address"] != candidate["address"] for other in kept):
                kept.append(candidate)
        return kept

    def _path_of(self, url: str) -> str:
        """The path one stored address reaches the hub by.

        Returns:
            ``ssh_relay``, ``sakurafrp`` or ``openfrp`` for the state's
            ``<path>_url``, ``lan`` for an address inside a network this
            machine holds an address in, and ``direct`` for any other.
        """
        with self._lock:
            server_urls = dict(self._server_urls)
        for path, server_url in server_urls.items():
            if server_url and server_url.rstrip("/") == url:
                return path
        host = urllib.parse.urlsplit(url).hostname or ""
        if is_on_local_network(host, self._local_networks()):
            return "lan"
        return "direct"

    def _command(self, command: str, fields: dict) -> "dict | None":
        """Send one command; a refusal or no answer is logged.

        Returns:
            The answer; None when the transport refused or did not answer.
        """
        try:
            answer = self._transport.command(command, fields)
        except GatewayUnreachable as error:
            self._log(f"the transport did not take {command}: {error}")
            return None
        if answer.get("code"):
            self._log(f"the transport refused {command}: {answer.get('code')}")
            return None
        return answer

    def _open(
        self,
        open_record: dict,
        *,
        is_raw_after_accept: bool = False,
        is_fd_tagged: bool = False,
    ) -> ClientStream:
        """Open one stream on the live session.

        Raises:
            GatewayUnreachable: When the hub is not connected.
        """
        with self._lock:
            if not self._is_welcomed:
                raise GatewayUnreachable("this hub is not connected")
            label = self._label
        return self._transport.open_stream(
            label,
            open_record,
            is_raw_after_accept=is_raw_after_accept,
            is_fd_tagged=is_fd_tagged,
        )

    def _ask(self, frame_type: str, fields: dict, timeout_s: float) -> dict:
        """Send a question frame and take its reply.

        Raises:
            GatewayRefusedDetail: When the reply carries a code.
            GatewayUnreachable: When the hub is not connected, its session
                ends, or no reply arrives in time.
        """
        request = secrets.token_hex(8)
        waiter = [threading.Event(), None]
        with self._lock:
            if not self._is_welcomed:
                raise GatewayUnreachable("this hub is not connected")
            self._replies[request] = waiter
        try:
            self._send({"type": frame_type, "request": request, **dict(fields)})
            if not waiter[0].wait(timeout=timeout_s):
                raise GatewayUnreachable(f"the hub did not reply to {frame_type}")
        finally:
            with self._lock:
                self._replies.pop(request, None)
        reply = waiter[1]
        if reply is None:
            raise GatewayUnreachable("the hub's session ended before its reply")
        code = str(reply.get("code", "") or "")
        if code:
            raise GatewayRefusedDetail(code=code, params=_params_of(reply))
        return _params_of(reply)

    def _fail_replies(self) -> None:
        """Wake every question waiting for a reply: none comes."""
        with self._lock:
            waiting = list(self._replies.values())
        for waiter in waiting:
            waiter[0].set()

    def _send(self, frame: dict) -> None:
        """Send one frame on the binding's control stream.

        Raises:
            GatewayUnreachable: When the transport is not running.
        """
        self._transport.send_frame(self.label, frame)

    def _hello(self) -> dict:
        """This client's identity card, the first frame on every session."""
        with self._lock:
            binding = dict(self._binding)
        return {
            "type": protocol.FRAME_HELLO,
            "protocol": PROTOCOL,
            "role": CLIENT_ROLE,
            "id": binding.get("id", ""),
            "name": binding.get("name", ""),
            "software": f"{CLIENT_SOFTWARE_PREFIX}{CLIENT_VERSION}",
        }

    def _report(self, is_refresh: bool = False) -> None:
        """Send what is true of this machine and the hash of the state held.

        Raises:
            GatewayUnreachable: When the transport is not running.
        """
        with self._lock:
            state_hash = self._state_hash
            self._next_report_at = self._clock() + CLIENT_REPORT_INTERVAL_S
        machine = {
            "hostname": self._hostname,
            "platform": dict(self._platform_tuple),
        }
        if self._os_machine_id:
            machine["os_machine_id"] = self._os_machine_id
        report = {
            "type": protocol.FRAME_REPORT,
            "state_hash": state_hash,
            "machine": machine,
        }
        if is_refresh:
            report["is_refresh"] = True
        self._send(report)

    def _ping(self) -> None:
        """Send a ``ping`` frame, its nonce and send time remembered.

        Raises:
            GatewayUnreachable: When the transport is not running.
        """
        nonce = secrets.token_urlsafe(8)
        with self._lock:
            self._ping_sent = (nonce, self._clock())
            self._next_ping_at = self._clock() + CLIENT_PING_INTERVAL_S
        self._send({"type": protocol.FRAME_PING, "nonce": nonce})

    def _relabel(self, binding_id: str) -> None:
        """Hand the transport's lines of the binding's new id to this session."""
        with self._lock:
            old = self._label
            self._label = binding_id
        self._transport.forget_binding(old, self.take_line)
        self._transport.listen_binding(binding_id, self.take_line)

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

    def _drop_session(self) -> None:
        """Forget the live session; the lock is held."""
        self._is_welcomed = False
        self._channel_open.clear()
        self._rtt_ms = None
        self._ping_sent = None

    def _stand_aside(self) -> None:
        """Another client holds this binding: dial no more until a person acts."""
        with self._lock:
            if self._is_replaced:
                return
            self._is_replaced = True
            self._is_refreshing = False
        self._log("another client took this binding; not reconnecting until asked")
        self._on_change()

    def _connection(self) -> str:
        """Where the session stands; the lock is held."""
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

    def _silent_reason(self) -> str:
        """The reason a hub that did not answer waits on: off its network or silent."""
        with self._lock:
            is_overlay_on = self._is_overlay_on
        return WAIT_HUB_OFF_OVERLAY if is_overlay_on else WAIT_HUB_SILENT

    def _unreachable(self, code: dict, next_round_s: "float | None") -> None:
        """Wait after a round, a join or a move that reached no address.

        A device with no network at all waits for one with no countdown.
        Otherwise the countdown is the transport's next round, or the
        backoff, which doubles, for what the session tries again itself.
        """
        if self._is_offline():
            self._wait(WAIT_NO_NETWORK, code, None, is_retried=True)
            return
        with self._lock:
            is_own = next_round_s is None
            delay = self._backoff_s if is_own else next_round_s
            if is_own:
                self._backoff_s = min(self._backoff_s * 2, CLIENT_BACKOFF_MAX_S)
        self._wait(self._silent_reason(), code, delay, is_retried=is_own)

    def _unbind(self, code: dict) -> None:
        """The hub holds no such binding any more: wait for a person's Leave."""
        with self._lock:
            if self._wait_reason == WAIT_UNKNOWN_DEVICE:
                return
        self._wait(WAIT_UNKNOWN_DEVICE, code, None)
        self._log("unbound: the hub no longer knows this client")
        self._on_unbound(self)

    def _wait(
        self,
        reason: str,
        code: "dict | None",
        delay: "float | None",
        is_retried: bool = False,
    ) -> None:
        """Enter waiting on one reason, the refresh ended, and announce it.

        Args:
            reason: One of ``WAIT_REASONS``.
            code: The ``{"code", "params"}`` the last round ended in.
            delay: Seconds until the next round; None while no countdown
                runs.
            is_retried: Whether the session itself tries again after the
                delay, a join or a move, rather than the transport.
        """
        with self._lock:
            self._wait_reason = reason
            self._wait_code = dict(code) if code else None
            self._next_round_at = None if delay is None else self._wall_clock() + delay
            self._is_refreshing = False
            if is_retried:
                self._next_attempt_at = self._clock() + (
                    delay if delay is not None else CLIENT_IDLE_POLL_INTERVAL_S
                )
        self._on_change()

    def _is_offline(self) -> bool:
        """Whether this machine has no network at all, as its networks say."""
        return is_offline(self._local_networks())


def _params_of(line: dict) -> dict:
    """A line's ``params``, empty when it carries none."""
    params = line.get("params")
    return dict(params) if isinstance(params, dict) else {}


def _pinned_channel(url: str, fingerprint: str) -> GatewayHttpChannel:
    """The pinned channel a 0.5 binding is moved over."""
    return GatewayHttpChannel(
        gateway_url=url, fingerprint=fingerprint, timeout=CLIENT_REQUEST_TIMEOUT_S
    )
