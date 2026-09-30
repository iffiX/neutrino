"""This machine's membership of each hub's virtual network.

A virtual network is not a service a hub publishes: it is a way to reach the
hub, so it lives beside the sessions rather than among the handlers. Each
hub's state names how to join each of its networks, preferred first:
NetBird's setup key, or for EasyTier either a manual network's name, secret
and peer or an EasyTier console's address. The person's wish to be on a
hub's virtual network is kept per hub, and this machine is on one of that
hub's networks at a time. One :class:`OverlayMemberships` holds one
membership per network, keyed by NetBird's management URL, EasyTier's
network name or the console's address, so two hubs on the same network read
one state. The
daemons the packages register as services hold the membership itself; this
side joins, leaves and asks, one step at a time per provider, and leaves
nothing behind on exit because nothing here is what keeps a network up.
EasyTier is asked of the client's own EasyTier daemon over its local socket,
the secret and the console's address in the request's body.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import functools
import json
import subprocess
import threading
import time
import urllib.parse

from neutrino_client.constants import (
    CLIENT_EASYTIER_RPC_PORTAL,
    CLIENT_OVERLAY_FAILOVER_S,
    CLIENT_OVERLAY_JOIN_TIMEOUT_S,
    CLIENT_OVERLAY_POLL_INTERVAL_S,
    CLIENT_OVERLAY_STATUS_TIMEOUT_S,
)
from neutrino_client.control.easytier_socket import ask_easytier_daemon
from neutrino_client.core.easytier_daemon import console_digest
from neutrino_client.core.easytier_config import safe_hostname
from neutrino_client.exceptions import OverlayControlError, PlatformUnsupportedError
from neutrino_client.services.worker import IF_BUSY_KEEP_ONE, ServiceWorker

# The words a membership's state takes, in the order a join walks them.
OVERLAY_STATE_OFF = "off"
OVERLAY_STATE_JOINING = "joining"
# An EasyTier console holds this machine, and has attached it to no network.
OVERLAY_STATE_WAITING = "waiting"
OVERLAY_STATE_ON = "on"
OVERLAY_STATE_LEAVING = "leaving"
OVERLAY_STATE_FAILED = "failed"
OVERLAY_STATES = (
    OVERLAY_STATE_OFF,
    OVERLAY_STATE_JOINING,
    OVERLAY_STATE_WAITING,
    OVERLAY_STATE_ON,
    OVERLAY_STATE_LEAVING,
    OVERLAY_STATE_FAILED,
)
# The states in which this machine holds the network, and a press leaves it.
OVERLAY_HELD_STATES = (OVERLAY_STATE_WAITING, OVERLAY_STATE_ON)
# The management server a NetBird setup key names when the hub names none.
NETBIRD_DEFAULT_MANAGEMENT_URL = "https://api.netbird.io:443"
# What ``netbird status`` answers when no daemon is listening.
NETBIRD_DAEMON_DOWN_MARKS = (
    "failed to connect to daemon",
    "connection refused",
    "no such file or directory",
)
# What ``easytier-cli`` prints for an instance the daemon does not run, with
# exit status 0, and for a portal nothing listens on.
EASYTIER_NO_INSTANCE_MARK = "No instance matches the selector"
EASYTIER_PEER_LOCAL_COST = "Local"
# The two ways an EasyTier network is joined; an object that names neither
# is a manual one.
EASYTIER_MODE_MANUAL = "manual"
EASYTIER_MODE_CONSOLE = "console"
# The least wait between two looks at a failover that is due, while a lane
# of its switch is still working.
OVERLAY_FAILOVER_RECHECK_S = 5


def is_console_material(material: dict) -> bool:
    """Whether an overlay object names an EasyTier console.

    Args:
        material: The hub's overlay object.

    Returns:
        True for ``{"provider": "easytier", "mode": "console"}``.
    """
    return (
        material.get("provider") == "easytier"
        and material.get("mode") == EASYTIER_MODE_CONSOLE
    )


def netbird_management_key(url: str) -> str:
    """A NetBird management URL as one membership key.

    Args:
        url: The URL the hub named, empty for NetBird's own.

    Returns:
        ``<scheme>://<host>:<port>``, lower-cased, the default port filled.
    """
    parts = urllib.parse.urlsplit((url or NETBIRD_DEFAULT_MANAGEMENT_URL).strip())
    scheme = parts.scheme or "https"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        port = 443 if scheme == "https" else 80
    return f"{scheme}://{(parts.hostname or '').lower()}:{port}"


def overlay_key(material: dict) -> str:
    """The membership one hub's overlay object belongs to.

    Args:
        material: The hub's overlay object.

    Returns:
        ``netbird:<management>``, ``easytier:<network name>`` or
        ``easytier_console:<address>``.
    """
    if material["provider"] == "netbird":
        return "netbird:" + netbird_management_key(material.get("management_url", ""))
    if is_console_material(material):
        return "easytier_console:" + material.get("config_server", "")
    return "easytier:" + material.get("network_name", "")


def overlay_network(material: dict) -> str:
    """The network one overlay object names, in the words a row shows.

    Args:
        material: The hub's overlay object.

    Returns:
        The management server's host for NetBird, the network's name for
        a manual EasyTier network, the console's host for an EasyTier
        console.
    """
    if material["provider"] == "netbird":
        key = netbird_management_key(material.get("management_url", ""))
        return urllib.parse.urlsplit(key).hostname or ""
    if is_console_material(material):
        try:
            return (
                urllib.parse.urlsplit(material.get("config_server", "")).hostname or ""
            )
        except ValueError:
            return ""
    return material.get("network_name", "")


def overlay_hub_hosts(material: dict) -> list:
    """The hub's own host names or addresses on the network one object names.

    Args:
        material: The hub's overlay object.

    Returns:
        NetBird's name for the hub, or the hub's EasyTier address; empty
        when the hub named neither.
    """
    if material["provider"] == "netbird":
        host = material.get("fqdn", "")
    else:
        host = _address(material.get("hub_address", ""))
    return [host] if host else []


def _nobody(*_args) -> None:
    """Nobody listening."""


def _off_record(
    *,
    state: str = OVERLAY_STATE_OFF,
    code: str = "",
    params: "dict | None" = None,
    address: str = "",
    is_hub_seen: bool = False,
    is_sticky: bool = False,
) -> dict:
    """One network's record, off unless told otherwise.

    ``is_sticky`` marks a step's failure, which a probe replaces only with a
    held network, ``on`` or ``waiting``.
    """
    return {
        "state": state,
        "code": code,
        "params": dict(params or {}),
        "address": address,
        "is_hub_seen": is_hub_seen,
        "is_sticky": is_sticky,
    }


def _detail(result) -> str:
    """A finished CLI's last words."""
    return (result.stderr or result.stdout or "").strip()[-200:]


def _address(value) -> str:
    """An address without its prefix length."""
    return str(value or "").split("/", 1)[0]


class OverlayNetbirdDriver:
    """NetBird's CLI, run as this person against the packaged daemon."""

    provider = "netbird"

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform, which runs the carried CLI.
        """
        self._platform = platform

    def status(self, material: dict) -> dict:
        """Where this machine stands on the network the object names.

        Args:
            material: The hub's overlay object.

        Returns:
            ``{"is_on", "is_other_network", "address", "is_hub_seen"}``.

        Raises:
            OverlayControlError: ``bundle_missing``, or
                ``overlay_daemon_down`` when no daemon answers.
        """
        result = self._netbird(["status", "--json"], CLIENT_OVERLAY_STATUS_TIMEOUT_S)
        words = (result.stdout or "") + (result.stderr or "")
        if any(mark in words.lower() for mark in NETBIRD_DAEMON_DOWN_MARKS):
            raise OverlayControlError("overlay_daemon_down")
        try:
            status = json.loads(result.stdout or "")
        except ValueError:
            status = None
        if not isinstance(status, dict):
            return {
                "is_on": False,
                "is_other_network": False,
                "address": "",
                "is_hub_seen": False,
            }
        management = status.get("management")
        management = management if isinstance(management, dict) else {}
        is_connected = bool(management.get("connected"))
        daemon_status = status.get("daemonStatus")
        if daemon_status is not None:
            is_connected = is_connected and daemon_status == "Connected"
        is_same = netbird_management_key(
            str(management.get("url", "") or "")
        ) == netbird_management_key(material.get("management_url", ""))
        is_on = is_connected and is_same
        return {
            "is_on": is_on,
            "is_other_network": is_connected and not is_same,
            "address": _address(status.get("netbirdIp")) if is_on else "",
            "is_hub_seen": is_on and self._sees(status, material.get("fqdn", "")),
        }

    def join(self, material: dict, hostname: str) -> None:
        """Bring the daemon up on the network the setup key names.

        Args:
            material: The hub's overlay object.
            hostname: Unused; NetBird names the peer itself.

        Raises:
            OverlayControlError: ``overlay_other_network`` while the daemon
                is connected to another management server, which is left
                alone; ``overlay_join_failed`` with NetBird's words.
        """
        if self.status(material)["is_other_network"]:
            raise OverlayControlError(
                "overlay_other_network", {"network": overlay_network(material)}
            )
        result = self._netbird(
            [
                "up",
                "--setup-key",
                material["setup_key"],
                "--management-url",
                netbird_management_key(material.get("management_url", "")),
                "--disable-dns",
            ],
            CLIENT_OVERLAY_JOIN_TIMEOUT_S,
        )
        if result.returncode != 0:
            raise OverlayControlError(
                "overlay_join_failed", {"detail": _detail(result)}
            )

    def leave(self, material: dict) -> None:
        """Bring the daemon down.

        Args:
            material: The hub's overlay object.

        Raises:
            OverlayControlError: ``overlay_leave_failed`` with NetBird's
                words.
        """
        result = self._netbird(["down"], CLIENT_OVERLAY_JOIN_TIMEOUT_S)
        if result.returncode != 0:
            raise OverlayControlError(
                "overlay_leave_failed", {"detail": _detail(result)}
            )

    def _netbird(self, args: list, timeout_s: float):
        """Run the carried ``netbird`` as this person.

        Raises:
            OverlayControlError: ``bundle_missing``, or
                ``overlay_daemon_down`` when it cannot run or times out.
        """
        try:
            return self._platform.run_overlay("netbird", args, timeout_s)
        except (OSError, subprocess.SubprocessError) as error:
            if isinstance(error, OverlayControlError):
                raise
            raise OverlayControlError(
                "overlay_daemon_down", {"detail": str(error)[:200]}
            )

    def _sees(self, status: dict, fqdn: str) -> bool:
        """Whether the hub is among the connected peers, by its name."""
        if not fqdn:
            return False
        peers = status.get("peers")
        details = peers.get("details") if isinstance(peers, dict) else None
        for peer in details if isinstance(details, list) else []:
            if (
                isinstance(peer, dict)
                and str(peer.get("fqdn", "")).rstrip(".") == fqdn.rstrip(".")
                and peer.get("status") == "Connected"
            ):
                return True
        return False


class OverlayEasytierDriver:
    """The client's EasyTier daemon, asked over its socket, and EasyTier's CLI."""

    provider = "easytier"

    def __init__(self, *, platform, ask=None):
        """
        Args:
            platform: The machine's platform, which names the daemon's
                socket and runs the carried CLI.
            ask: ``ask(address, request)`` returns the daemon's answer;
                None asks over the real socket.
        """
        self._platform = platform
        self._ask = ask if ask is not None else ask_easytier_daemon

    def status(self, material: dict) -> dict:
        """Where this machine stands on the network the object names.

        Args:
            material: The hub's overlay object.

        Returns:
            ``{"is_on", "is_waiting", "is_other_network", "address",
            "is_hub_seen"}``; a core that is not running runs no network,
            which reads as off, and a console's core that runs no instance
            is waiting.

        Raises:
            OverlayControlError: ``bundle_missing``, or
                ``overlay_daemon_down`` when the daemon does not answer.
        """
        status = self._request({"verb": "status"})
        _raise_refusal(status)
        if is_console_material(material):
            return self._console_status(material, status)
        if material["network_name"] not in (status.get("networks") or []):
            return _easytier_off()
        peers = self._peers(material["network_name"])
        if peers is None:
            return _easytier_off()
        return _easytier_on(peers, material.get("hub_address", ""))

    def join(self, material: dict, hostname: str) -> None:
        """Have the daemon join the network the object names.

        Args:
            material: The hub's overlay object.
            hostname: What this machine is called on a manual network.

        Raises:
            OverlayControlError: The daemon's refusal, ``overlay_other_network``
                while it holds another console, or ``overlay_daemon_down``.
            PlatformUnsupportedError: Where the client carries no EasyTier.
        """
        if is_console_material(material):
            request = {
                "verb": "join_console",
                "config_server": material["config_server"],
                "is_secure_mode": bool(material.get("is_secure_mode")),
            }
        else:
            request = {
                "verb": "join",
                "network_name": material["network_name"],
                "network_secret": material["network_secret"],
                "peer": material["peer"],
                "hostname": safe_hostname(hostname),
            }
        answer = self._request(request)
        if answer.get("code") == "overlay_other_network":
            raise OverlayControlError(
                "overlay_other_network", {"network": overlay_network(material)}
            )
        _raise_refusal(answer)

    def leave(self, material: dict) -> None:
        """Have the daemon leave the network the object names.

        A console is left only while it is the one the daemon holds.

        Args:
            material: The hub's overlay object.

        Raises:
            OverlayControlError: The daemon's refusal, or
                ``overlay_daemon_down``.
            PlatformUnsupportedError: Where the client carries no EasyTier.
        """
        if is_console_material(material):
            console = self._request({"verb": "status"}).get("console")
            digest = console.get("digest") if isinstance(console, dict) else None
            if digest != console_digest(material["config_server"]):
                return
            request = {"verb": "leave_console"}
        else:
            request = {"verb": "leave", "network_name": material["network_name"]}
        _raise_refusal(self._request(request))

    def _console_status(self, material: dict, status: dict) -> dict:
        """Where this machine stands on the console the object names."""
        console = status.get("console")
        digest = console.get("digest") if isinstance(console, dict) else None
        if digest is None:
            return _easytier_off()
        if digest != console_digest(material["config_server"]):
            off = _easytier_off()
            off["is_other_network"] = True
            return off
        if not status.get("is_running"):
            return _easytier_off()
        manual = set(status.get("networks") or [])
        names = [name for name in self._instances() if name not in manual]
        if not names:
            waiting = _easytier_off()
            waiting["is_waiting"] = True
            return waiting
        peers = self._peers(names[0])
        if peers is None:
            return _easytier_off()
        return _easytier_on(peers, material.get("hub_address", ""))

    def _instances(self) -> list:
        """The names of the instances the core runs; empty when it answers none."""
        result = self._cli(["node"])
        if result is None:
            return []
        try:
            nodes = json.loads(result.stdout or "")
        except ValueError:
            return []
        if isinstance(nodes, dict):
            nodes = [{"instance_name": _instance_name(nodes.get("config"))}]
        if not isinstance(nodes, list):
            return []
        return [
            str(node.get("instance_name") or "")
            for node in nodes
            if isinstance(node, dict) and node.get("instance_name")
        ]

    def _peers(self, instance: str) -> "list | None":
        """One instance's peers, None when the core runs no such instance."""
        result = self._cli(["-n", instance, "peer"])
        if result is None or EASYTIER_NO_INSTANCE_MARK in _detail(result):
            return None
        try:
            peers = json.loads(result.stdout or "")
        except ValueError:
            return None
        if not isinstance(peers, list):
            return None
        return [peer for peer in peers if isinstance(peer, dict)]

    def _cli(self, args: list):
        """Run the carried CLI against the daemon's core; None when it failed.

        Raises:
            OverlayControlError: ``bundle_missing``.
        """
        try:
            result = self._platform.run_overlay(
                "easytier-cli",
                ["-p", CLIENT_EASYTIER_RPC_PORTAL, "-o", "json"] + list(args),
                CLIENT_OVERLAY_STATUS_TIMEOUT_S,
            )
        except OverlayControlError:
            raise
        except (OSError, subprocess.SubprocessError):
            return None
        return result if result.returncode == 0 else None

    def _request(self, request: dict) -> dict:
        """One request to the daemon.

        Raises:
            OverlayControlError: ``overlay_daemon_down`` when it does not
                answer.
            PlatformUnsupportedError: Where the client carries no EasyTier.
        """
        address = self._platform.easytier_daemon_address()
        try:
            return self._ask(address, request)
        except (OSError, ValueError) as error:
            raise OverlayControlError(
                "overlay_daemon_down", {"detail": str(error)[:200]}
            )


def _easytier_off() -> dict:
    return {
        "is_on": False,
        "is_waiting": False,
        "is_other_network": False,
        "address": "",
        "is_hub_seen": False,
    }


def _easytier_on(peers: list, hub_address: str) -> dict:
    """An instance that runs, read from its peers.

    The hub is seen when a peer holds the hub's address; a hub that names
    none is seen when any other peer is.
    """
    local = [row for row in peers if row.get("cost") == EASYTIER_PEER_LOCAL_COST]
    others = [row for row in peers if row.get("cost") != EASYTIER_PEER_LOCAL_COST]
    if hub_address:
        is_hub_seen = any(
            _address(row.get("ipv4")) == _address(hub_address) for row in others
        )
    else:
        is_hub_seen = bool(others)
    return {
        "is_on": True,
        "is_waiting": False,
        "is_other_network": False,
        "address": _address(local[0].get("ipv4")) if local else "",
        "is_hub_seen": is_hub_seen,
    }


def _instance_name(config) -> str:
    """The ``instance_name`` a lone instance's configuration text names."""
    for line in str(config or "").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "instance_name":
            return value.strip().strip('"')
    return ""


def _raise_refusal(answer: dict) -> None:
    """Raise the daemon's refusal, when its answer is one.

    Raises:
        OverlayControlError: The refusal's code and params.
    """
    code = answer.get("code")
    if isinstance(code, str) and code:
        params = answer.get("params")
        raise OverlayControlError(code, params if isinstance(params, dict) else {})


class OverlayMemberships:
    """One membership per network the joined hubs name, and one lane per provider.

    Each hub names its networks in its order of preference; this machine is
    on at most one of them per hub, the current one. While a hub's wish is
    on, the current network is joined once, and a switch leaves the current
    network before it joins the next: when the hub's channel has been lost
    for ``CLIENT_OVERLAY_FAILOVER_S`` and the hub names another network, or
    when the hub stops naming the current one.
    """

    def __init__(
        self,
        *,
        platform,
        bindings_of,
        hostname: str,
        log=print,
        on_change=None,
        on_joined=None,
        start_thread=None,
        drivers=None,
        clock=None,
    ):
        """
        Args:
            platform: The machine's platform.
            bindings_of: Returns one ``{hub_id, overlays, is_wanted, pick,
                lost_since}`` per hub joined, in order: the hub's overlay
                objects, the person's wish, the provider chosen or empty,
                and the monotonic time its channel was lost or None.
            hostname: What this machine is called on an EasyTier network.
            log: Callable used for progress messages.
            on_change: Called with no arguments after every change a page
                draws; None for nobody listening.
            on_joined: Called with an overlay object after a join of its
                network succeeded; None for nobody listening.
            start_thread: ``start_thread(target)`` runs a lane's job; None
                uses a daemon thread. Tests pass one that runs inline.
            drivers: ``{provider: driver}``; None builds the NetBird and
                EasyTier drivers over the platform.
            clock: Returns the monotonic time; None uses ``time.monotonic``.
        """
        self._platform = platform
        self._bindings_of = bindings_of
        self._hostname = hostname
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
        self._on_joined = on_joined if on_joined is not None else _nobody
        self._clock = clock if clock is not None else time.monotonic
        self._drivers = (
            drivers
            if drivers is not None
            else {
                "netbird": OverlayNetbirdDriver(platform=platform),
                "easytier": OverlayEasytierDriver(platform=platform),
            }
        )
        self._lanes = {
            provider: ServiceWorker(
                name=f"overlay_{provider}",
                on_change=self._on_change,
                log=log,
                start_thread=start_thread,
            )
            for provider in self._drivers
        }
        self._lock = threading.Lock()
        # Each joined hub's objects as last read, by hub id, preferred first.
        self._materials: dict = {}
        # Each joined hub's wish: {is_wanted, pick, lost_since}.
        self._wishes: dict = {}
        # Every hub's objects this run has read, kept after the hub goes so
        # its network can still be left.
        self._known: dict = {}
        # The network each hub is on or aimed at, as its object.
        self._current: dict = {}
        # The provider each hub's current network was last joined on by
        # itself, so a join that failed is not tried again on every poll.
        self._attempted: dict = {}
        # When each hub last switched networks, on the clock.
        self._switched_at: dict = {}
        # One record per network: {state, code, params, address, is_hub_seen}.
        self._records: dict = {}
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    def hub_row(self, hub_id: str) -> "dict | None":
        """The overlay part of one hub's row.

        Args:
            hub_id: The hub, by its id.

        Returns:
            ``{provider, network, state, code, params, address,
            is_hub_seen, work, is_wanted, networks}`` for the current
            network, ``networks`` being ``[{provider, network}]`` for every
            network the hub names; None when the hub names none.
        """
        with self._lock:
            material = self._choose(hub_id)
            if material is None:
                return None
            record = dict(self._records.get(overlay_key(material)) or _off_record())
            networks = [
                {"provider": item["provider"], "network": overlay_network(item)}
                for item in self._materials.get(hub_id) or []
            ]
            is_wanted = bool((self._wishes.get(hub_id) or {}).get("is_wanted"))
        return {
            "provider": material["provider"],
            "network": overlay_network(material),
            "state": record["state"],
            "code": record["code"],
            "params": dict(record["params"]),
            "address": record["address"],
            "is_hub_seen": record["is_hub_seen"],
            "work": self._lanes[material["provider"]].status(),
            "is_wanted": is_wanted,
            "networks": networks,
        }

    def join(self, hub_id: str) -> dict:
        """Join one hub's current network, on its provider's lane.

        Args:
            hub_id: The hub, by its id.

        Returns:
            Empty when the step was taken; ``overlay_missing`` when the hub
            names no network, ``busy`` while the lane works.
        """
        return self._submit(hub_id, OVERLAY_STATE_JOINING)

    def leave(self, hub_id: str) -> dict:
        """Leave one hub's current network, on its provider's lane.

        Args:
            hub_id: The hub, by its id.

        Returns:
            Empty when the step was taken; ``overlay_missing`` when the hub
            names no network, ``busy`` while the lane works.
        """
        return self._submit(hub_id, OVERLAY_STATE_LEAVING)

    def pick(self, hub_id: str, provider: str) -> dict:
        """Make one of a hub's networks its current one.

        While the hub's wish is on and its current network is held or being
        joined, the current network is left and the picked one joined.

        Args:
            hub_id: The hub, by its id.
            provider: The provider of the network picked.

        Returns:
            Empty when the pick was taken; ``overlay_missing`` when the hub
            names no such network, ``busy`` while a lane of the switch works.
        """
        self.refresh_bindings()
        with self._lock:
            chosen = next(
                (
                    item
                    for item in self._materials.get(hub_id) or []
                    if item["provider"] == provider
                ),
                None,
            )
            current = self._choose(hub_id)
            is_wanted = bool((self._wishes.get(hub_id) or {}).get("is_wanted"))
        if chosen is None or current is None:
            return {"code": "overlay_missing", "params": {"hub_id": hub_id}}
        if chosen["provider"] == current["provider"]:
            return {}
        record = self._record(current)
        if is_wanted and record["state"] in OVERLAY_HELD_STATES + (
            OVERLAY_STATE_JOINING,
        ):
            return self._switch(hub_id, current, chosen)
        with self._lock:
            self._current[hub_id] = chosen
        self._on_change()
        return {}

    def reconcile(self) -> None:
        """Hold every hub whose wish is on to one network, switching when it must.

        A hub whose current network is gone from its list moves to its
        first; one whose channel has been lost for
        ``CLIENT_OVERLAY_FAILOVER_S`` moves to the network after the current
        one; one whose current network is off is joined, once.
        """
        self.refresh_bindings()
        now = self._clock()
        with self._lock:
            hubs = [
                (hub_id, list(materials), dict(self._wishes.get(hub_id) or {}))
                for hub_id, materials in self._materials.items()
            ]
        for hub_id, materials, wish in hubs:
            if not materials or not wish.get("is_wanted"):
                continue
            with self._lock:
                previous = self._current.get(hub_id)
                providers = [item["provider"] for item in materials]
                is_gone = previous is not None and previous["provider"] not in providers
                if is_gone:
                    self._current.pop(hub_id, None)
                current = self._choose(hub_id)
                deadline = self._failover_deadline(hub_id, wish, len(materials))
            if is_gone:
                self._log(
                    f"overlay: the hub no longer names {overlay_network(previous)}; "
                    f"moving to {overlay_network(current)}"
                )
                if self._switch(hub_id, previous, current):
                    with self._lock:
                        self._current[hub_id] = previous
                continue
            if deadline is not None and now >= deadline:
                index = providers.index(current["provider"])
                following = materials[(index + 1) % len(materials)]
                self._log(
                    f"overlay: the hub's channel is lost; moving from "
                    f"{overlay_network(current)} to {overlay_network(following)}"
                )
                self._switch(hub_id, current, following)
                continue
            self._join_once(hub_id, current)

    def next_deadline(self) -> "float | None":
        """How long until the next hub's channel has been lost long enough.

        Returns:
            Seconds from now, zero or more; None while no hub is waiting on
            one.
        """
        now = self._clock()
        with self._lock:
            deadlines = [
                self._failover_deadline(hub_id, wish, len(self._materials[hub_id]))
                for hub_id, wish in self._wishes.items()
                if hub_id in self._materials
            ]
        pending = [deadline for deadline in deadlines if deadline is not None]
        return max(min(pending) - now, 0) if pending else None

    def release_hub(self, hub_id: str) -> int:
        """Leave a hub's networks when no other hub joined names them.

        Args:
            hub_id: The hub being let go of.

        Returns:
            How many leaves were started.
        """
        self.refresh_bindings()
        with self._lock:
            materials = self._known.pop(hub_id, None) or []
            for table in (self._current, self._attempted, self._switched_at):
                table.pop(hub_id, None)
            others = [
                overlay_key(other)
                for other_id, items in self._materials.items()
                if other_id != hub_id
                for other in items
            ]
        count = 0
        for material in materials:
            record = self._record(material)
            is_on = record["state"] in OVERLAY_HELD_STATES + (OVERLAY_STATE_JOINING,)
            if overlay_key(material) in others or not is_on:
                continue
            self._log(f"leaving {overlay_network(material)}, which no hub joined names")
            self._lanes[material["provider"]].submit(
                OVERLAY_STATE_LEAVING,
                functools.partial(self._run_step, material, OVERLAY_STATE_LEAVING),
                if_busy=IF_BUSY_KEEP_ONE,
            )
            count += 1
        return count

    def release(self) -> int:
        """Let go of nothing: the daemons hold the networks.

        Returns:
            How many networks stay joined.
        """
        with self._lock:
            return sum(
                1
                for record in self._records.values()
                if record["state"] in OVERLAY_HELD_STATES
            )

    def refresh(self) -> None:
        """Read the bindings again and have the poll look at every network now."""
        self.refresh_bindings()
        self._news.set()

    def refresh_bindings(self) -> None:
        """Take each hub's overlay objects and wish as the sessions hold them now."""
        materials = {}
        wishes = {}
        for row in self._bindings_of():
            hub_id = row.get("hub_id")
            if not hub_id:
                continue
            materials[hub_id] = [
                dict(item)
                for item in row.get("overlays") or []
                if isinstance(item, dict)
            ]
            wishes[hub_id] = {
                "is_wanted": row.get("is_wanted") is True,
                "pick": str(row.get("pick", "") or ""),
                "lost_since": row.get("lost_since"),
            }
        with self._lock:
            is_changed = materials != self._materials or any(
                (wishes[hub_id]["is_wanted"], wishes[hub_id]["pick"])
                != (
                    (self._wishes.get(hub_id) or {}).get("is_wanted"),
                    (self._wishes.get(hub_id) or {}).get("pick"),
                )
                for hub_id in wishes
            )
            self._materials = materials
            self._wishes = wishes
            self._known.update(
                {hub_id: items for hub_id, items in materials.items() if items}
            )
        if is_changed:
            self._on_change()

    def probe(self) -> None:
        """Ask each network's daemon where this machine stands, one network at a time.

        The bindings are read first; a network whose provider's lane is
        working is left to the step.
        """
        self.refresh_bindings()
        with self._lock:
            networks = {}
            for materials in self._materials.values():
                for material in materials:
                    networks.setdefault(overlay_key(material), material)
        is_changed = False
        for key, material in networks.items():
            if self._lanes[material["provider"]].is_working:
                continue
            record = self._observe(material)
            with self._lock:
                previous = self._records.get(key)
                if (
                    previous is not None
                    and previous["is_sticky"]
                    and record["state"] not in OVERLAY_HELD_STATES
                ):
                    continue
                if previous != record:
                    self._records[key] = record
                    is_changed = True
        if is_changed:
            self._on_change()

    def start(self) -> None:
        """Probe and reconcile on a thread of its own, every ``CLIENT_OVERLAY_POLL_INTERVAL_S``."""
        thread = threading.Thread(
            target=self._poll_forever, name="client_overlay", daemon=True
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        """End the poll; every network stays as it is. Idempotent."""
        self._stop.set()
        self._news.set()

    def _poll_forever(self) -> None:
        while not self._stop.is_set():
            self._news.clear()
            try:
                self.refresh_bindings()
                self.probe()
                self.reconcile()
            except Exception as error:  # noqa: BLE001 - the poll must survive
                self._log(f"overlay: could not look at the networks: {error}")
            wait_s = CLIENT_OVERLAY_POLL_INTERVAL_S
            try:
                deadline = self.next_deadline()
            except Exception:  # noqa: BLE001 - the poll must survive
                deadline = None
            if deadline is not None:
                wait_s = min(wait_s, max(deadline, OVERLAY_FAILOVER_RECHECK_S))
            self._news.wait(timeout=wait_s)

    def _choose(self, hub_id: str) -> "dict | None":
        """The hub's current network, chosen when it has none; the lock is held.

        A hub with no current network takes one this machine already holds,
        else the one the person picked, else the hub's first. A current
        network the hub no longer names is kept for the reconcile to leave.
        """
        materials = self._materials.get(hub_id) or []
        if not materials:
            return None
        by_provider = {item["provider"]: item for item in materials}
        current = self._current.get(hub_id)
        if current is not None and current["provider"] in by_provider:
            chosen = by_provider[current["provider"]]
            self._current[hub_id] = chosen
            return chosen
        held = [
            item
            for item in materials
            if (self._records.get(overlay_key(item)) or {}).get("state")
            in OVERLAY_HELD_STATES
        ]
        pick = (self._wishes.get(hub_id) or {}).get("pick", "")
        chosen = held[0] if held else by_provider.get(pick, materials[0])
        if current is None:
            self._current[hub_id] = chosen
        return chosen

    def _failover_deadline(self, hub_id: str, wish: dict, count: int) -> "float | None":
        """When a hub moves to its next network; the lock is held."""
        lost_since = wish.get("lost_since")
        if not wish.get("is_wanted") or count < 2 or lost_since is None:
            return None
        since = max(lost_since, self._switched_at.get(hub_id, lost_since))
        return since + CLIENT_OVERLAY_FAILOVER_S

    def _record(self, material: dict) -> dict:
        """One network's record as it stands, off when it has none."""
        with self._lock:
            return dict(self._records.get(overlay_key(material)) or _off_record())

    def _join_once(self, hub_id: str, material: dict) -> None:
        """Join a wanted hub's current network when it is off and not yet tried."""
        record = self._record(material)
        if record["state"] in OVERLAY_HELD_STATES + (
            OVERLAY_STATE_JOINING,
            OVERLAY_STATE_LEAVING,
        ):
            return
        with self._lock:
            if self._attempted.get(hub_id) == material["provider"]:
                return
        lane = self._lanes[material["provider"]]
        if lane.is_working:
            return
        with self._lock:
            self._attempted[hub_id] = material["provider"]
        self._log(f"overlay: joining {overlay_network(material)}")
        self._set_record(
            overlay_key(material), _off_record(state=OVERLAY_STATE_JOINING)
        )
        lane.submit(
            OVERLAY_STATE_JOINING,
            functools.partial(self._run_step, material, OVERLAY_STATE_JOINING),
        )

    def _switch(self, hub_id: str, old: dict, new: dict) -> dict:
        """Leave one network and join another, on the new network's lane.

        Returns:
            Empty when the switch was started; ``busy`` while a lane works.
        """
        for provider in {old["provider"], new["provider"]}:
            lane = self._lanes[provider]
            if lane.is_working:
                return {"code": "busy", "params": {"step": lane.status()["step"]}}
        with self._lock:
            self._current[hub_id] = new
            self._attempted[hub_id] = new["provider"]
            self._switched_at[hub_id] = self._clock()
        self._set_record(overlay_key(new), _off_record(state=OVERLAY_STATE_JOINING))
        return self._lanes[new["provider"]].submit(
            OVERLAY_STATE_JOINING,
            functools.partial(self._run_switch, hub_id, old, new),
        )

    def _run_switch(self, hub_id: str, old: dict, new: dict) -> dict:
        """Leave the old network unless another hub is on it, then join the new."""
        with self._lock:
            is_shared = any(
                other_id != hub_id
                and (self._wishes.get(other_id) or {}).get("is_wanted")
                and overlay_key(current) == overlay_key(old)
                for other_id, current in self._current.items()
            )
        if not is_shared and self._record(old)["state"] != OVERLAY_STATE_OFF:
            self._run_step(old, OVERLAY_STATE_LEAVING)
        return self._run_step(new, OVERLAY_STATE_JOINING)

    def _submit(self, hub_id: str, step: str) -> dict:
        self.refresh_bindings()
        with self._lock:
            material = self._choose(hub_id)
        if material is None:
            return {"code": "overlay_missing", "params": {"hub_id": hub_id}}
        lane = self._lanes[material["provider"]]
        if lane.is_working:
            return {"code": "busy", "params": {"step": lane.status()["step"]}}
        with self._lock:
            self._attempted[hub_id] = material["provider"]
        self._set_record(overlay_key(material), _off_record(state=step))
        return lane.submit(step, functools.partial(self._run_step, material, step))

    def _run_step(self, material: dict, step: str) -> dict:
        """Join or leave one network, then read where it stands.

        Returns:
            Empty, or the step's refusal, which the record shows as failed.
        """
        key = overlay_key(material)
        driver = self._drivers[material["provider"]]
        try:
            if step == OVERLAY_STATE_JOINING:
                driver.join(material, self._hostname)
            else:
                driver.leave(material)
        except (OverlayControlError, PlatformUnsupportedError) as error:
            refusal = {"code": error.code, "params": dict(getattr(error, "params", {}))}
            self._set_record(
                key,
                _off_record(state=OVERLAY_STATE_FAILED, is_sticky=True, **refusal),
            )
            self._log(f"overlay: {step} {overlay_network(material)}: {error.code}")
            return refusal
        self._set_record(key, self._observe(material))
        if step == OVERLAY_STATE_JOINING:
            self._on_joined(dict(material))
        return {}

    def _observe(self, material: dict) -> dict:
        """One network's record, read from its daemon."""
        try:
            status = self._drivers[material["provider"]].status(material)
        except OverlayControlError as error:
            return _off_record(
                state=OVERLAY_STATE_FAILED, code=error.code, params=error.params
            )
        if status["is_on"]:
            return _off_record(
                state=OVERLAY_STATE_ON,
                address=status["address"],
                is_hub_seen=status["is_hub_seen"],
            )
        if status.get("is_waiting"):
            return _off_record(state=OVERLAY_STATE_WAITING)
        if status["is_other_network"]:
            return _off_record(
                code="overlay_other_network",
                params={"network": overlay_network(material)},
            )
        return _off_record()

    def _set_record(self, key: str, record: dict) -> None:
        with self._lock:
            self._records[key] = record
        self._on_change()
