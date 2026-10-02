"""This machine's place on each hub's virtual network.

A virtual network is not a service a hub publishes: it is a way to reach the
hub, so it lives beside the sessions rather than among the handlers. Each
hub's state names how to join each of its networks, preferred first:
NetBird's setup key, or for EasyTier either a manual network's name, secret
and peer or an EasyTier console's address. Per hub the network is ``off``,
``connecting`` or ``on``, on the one engine the person chose, and a failure
is kept as the error while it is off. The daemons the packages register as
services hold the network itself; this side starts and stops them and asks
where they stand, and leaves nothing behind on exit because nothing here is
what keeps a network up. EasyTier is asked of the client's own EasyTier
daemon over its local socket, the secret and the console's address in the
request's body.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import functools
import ipaddress
import json
import subprocess
import threading
import time
import urllib.parse

from neutrino_client.constants import (
    CLIENT_EASYTIER_RPC_PORTAL,
    CLIENT_OVERLAY_CONNECT_POLL_S,
    CLIENT_OVERLAY_HUB_PROBE_S,
    CLIENT_OVERLAY_JOIN_TIMEOUT_S,
    CLIENT_OVERLAY_LOGIN_TIMEOUT_S,
    CLIENT_OVERLAY_NETBIRD_NETWORK,
    CLIENT_OVERLAY_POLL_INTERVAL_S,
    CLIENT_OVERLAY_STATUS_TIMEOUT_S,
)
from neutrino_client.control.easytier_socket import ask_easytier_daemon
from neutrino_client.core.easytier_daemon import console_digest
from neutrino_client.core.easytier_config import safe_hostname
from neutrino_client.exceptions import OverlayControlError, PlatformUnsupportedError

# The three states of a hub's virtual network.
OVERLAY_STATE_OFF = "off"
OVERLAY_STATE_CONNECTING = "connecting"
OVERLAY_STATE_ON = "on"
OVERLAY_STATES = (OVERLAY_STATE_OFF, OVERLAY_STATE_CONNECTING, OVERLAY_STATE_ON)
# The step running on a hub's network, which its button shows.
OVERLAY_JOB_CONNECTING = "connecting"
OVERLAY_JOB_DISCONNECTING = "disconnecting"
# The two stages of a connect, which the line's reason names: the engine
# logging in until it has an address, then the hub answering through it.
OVERLAY_STAGE_LOGIN = "login"
OVERLAY_STAGE_HUB = "hub"
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


def overlay_hub_host(material: dict, urls: list, network: str = "") -> str:
    """The hub's own address on the network one object names.

    Args:
        material: The hub's overlay object.
        urls: The addresses the binding holds, in the hub's order.
        network: The prefix of the network this machine is on, as
            ``a.b.c.d/n``; empty takes NetBird's own for NetBird and none
            for EasyTier.

    Returns:
        The object's ``hub_address``; else the host of the first of
        ``urls`` that is an IP address inside the network; else NetBird's
        name for the hub; empty when there is none of them.
    """
    host = _address(material.get("hub_address", ""))
    if host:
        return host
    if not network and material["provider"] == "netbird":
        network = CLIENT_OVERLAY_NETBIRD_NETWORK
    for url in urls:
        try:
            host = urllib.parse.urlsplit(str(url)).hostname or ""
        except ValueError:
            continue
        if _is_inside(host, network):
            return host
    if material["provider"] == "netbird":
        return str(material.get("fqdn", "") or "")
    return ""


def _nobody(*_args) -> None:
    """Nobody listening."""


def _detail(result) -> str:
    """A finished CLI's last words."""
    return (result.stderr or result.stdout or "").strip()[-200:]


def _address(value) -> str:
    """An address without its prefix length."""
    return str(value or "").split("/", 1)[0]


def _network_of(value) -> str:
    """The network an address with its prefix length sits in; empty for none."""
    text = str(value or "")
    if "/" not in text:
        return ""
    try:
        return str(ipaddress.ip_interface(text).network)
    except ValueError:
        return ""


def _is_inside(host: str, network: str) -> bool:
    """Whether a host is an IP address inside a network."""
    if not network:
        return False
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network(network)
    except ValueError:
        return False


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
            ``{"is_on", "is_other_network", "address", "network",
            "is_hub_seen"}``; the hub is seen when its peer is
            ``Connected``.

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
                "network": "",
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
            "network": CLIENT_OVERLAY_NETBIRD_NETWORK if is_on else "",
            "is_hub_seen": is_on and self._sees(status, material),
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

    def _sees(self, status: dict, material: dict) -> bool:
        """Whether the hub is among the connected peers, by its address or name."""
        fqdn = str(material.get("fqdn", "") or "").rstrip(".")
        address = _address(material.get("hub_address", ""))
        peers = status.get("peers")
        details = peers.get("details") if isinstance(peers, dict) else None
        for peer in details if isinstance(details, list) else []:
            if not isinstance(peer, dict) or peer.get("status") != "Connected":
                continue
            if address and _address(peer.get("netbirdIp")) == address:
                return True
            if fqdn and str(peer.get("fqdn", "")).rstrip(".") == fqdn:
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
            "network", "is_hub_seen"}``; a core that is not running runs no
            network, which reads as off, and a console's core that runs no
            instance is waiting.

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
        "network": "",
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
        "network": _network_of(local[0].get("ipv4")) if local else "",
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
    """Each joined hub's virtual network: ``off``, ``connecting`` or ``on``.

    A hub names its networks in its order of preference, and the person
    chooses one engine among them while the network is off; the chosen one
    is the first until they do. Connect is one attempt in two stages:
    ``login``, the engine up and an address on the network within its
    limit, then ``hub``, with no limit, the hub's channel up through the
    hub's own address there. Nothing here retries, moves to another network, or
    changes the choice. While a hub's network is on, the poll asks its
    engine whether it still stands, and a network the hub stops naming is
    left with ``overlay_withdrawn``.
    """

    def __init__(
        self,
        *,
        platform,
        bindings_of,
        hostname: str,
        log=print,
        on_change=None,
        on_route=None,
        reaches_hub=None,
        keep_choice=None,
        drivers=None,
        start_thread=None,
        clock=None,
        login_timeout_s: float = CLIENT_OVERLAY_LOGIN_TIMEOUT_S,
        hub_probe_s: float = CLIENT_OVERLAY_HUB_PROBE_S,
        poll_s: float = CLIENT_OVERLAY_CONNECT_POLL_S,
    ):
        """
        Args:
            platform: The machine's platform.
            bindings_of: Returns one ``{hub_id, overlays, urls, pick,
                is_on}`` per hub joined, in order: the hub's overlay
                objects, the addresses the binding holds, the provider
                chosen or empty, and whether the network was last on.
            hostname: What this machine is called on an EasyTier network.
            log: Callable used for progress messages.
            on_change: Called with no arguments after every change a page
                draws; None for nobody listening.
            on_route: ``on_route(hub_id, hosts, is_only)`` has the hub's
                channel connect through these hosts first, or through them
                alone with ``is_only``, an empty list dropping the
                preference; None for nobody listening.
            reaches_hub: ``reaches_hub(hub_id, hosts)`` says whether the
                hub's channel is up through one of the hosts; None reads as
                never.
            keep_choice: ``keep_choice(hub_id, is_on, pick)`` writes where
                the network stands and the engine chosen onto the binding,
                raising OSError when it cannot; None keeps nothing.
            drivers: ``{provider: driver}``; None builds the NetBird and
                EasyTier drivers over the platform.
            start_thread: ``start_thread(target)`` runs a step; None uses a
                daemon thread. Tests pass one that runs inline.
            clock: Returns the monotonic time; None uses ``time.monotonic``.
            login_timeout_s: How long the ``login`` stage may take; a
                console that registered this machine and assigned no
                network yet waits with no limit.
            hub_probe_s: How often the ``hub`` stage, which has no limit,
                asks the engine and probes the hub.
            poll_s: How often a connect looks again.
        """
        self._platform = platform
        self._bindings_of = bindings_of
        self._hostname = hostname
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
        self._on_route = on_route if on_route is not None else _nobody
        self._reaches_hub = reaches_hub if reaches_hub is not None else _never
        self._keep_choice = keep_choice if keep_choice is not None else _nobody
        self._start_thread = (
            start_thread if start_thread is not None else _start_daemon_thread
        )
        self._clock = clock if clock is not None else time.monotonic
        self._login_timeout_s = login_timeout_s
        self._hub_probe_s = hub_probe_s
        self._poll_s = poll_s
        self._drivers = (
            drivers
            if drivers is not None
            else {
                "netbird": OverlayNetbirdDriver(platform=platform),
                "easytier": OverlayEasytierDriver(platform=platform),
            }
        )
        self._lock = threading.Lock()
        # Each joined hub's objects as last read, by hub id, preferred first.
        self._materials: dict = {}
        # Each joined hub's addresses as its binding holds them, by hub id.
        self._urls: dict = {}
        # Each joined hub's choice: {pick, is_on}.
        self._choices: dict = {}
        # One record per hub: {state, stage, stage_since, is_waiting, address,
        # error, job, material, count, cancel}. ``material`` is the network
        # in use while not off, and ``count`` tells a step that was overtaken
        # apart.
        self._records: dict = {}
        self._news = threading.Event()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    # --- what the page draws ---

    def hub_row(self, hub_id: str) -> dict:
        """The virtual network part of one hub's row.

        Args:
            hub_id: The hub, by its id.

        Returns:
            ``{network, networks, state, stage, stage_since, is_waiting,
            address, error}``: the provider chosen or in use, ``[{provider,
            network}]`` for every network the hub names, the state, the
            stage while connecting (``login`` or ``hub``, else empty) and
            the epoch second it began (0 for none),
            whether a console registered this machine and assigned it no
            network yet, this machine's address from the ``hub`` stage on,
            and ``{code, params}`` of the last failure while off, else
            None.
        """
        with self._lock:
            record = dict(self._records.get(hub_id) or _off_record())
            materials = list(self._materials.get(hub_id) or [])
            chosen = self._chosen(hub_id)
        material = record["material"] if record["state"] != OVERLAY_STATE_OFF else None
        material = material or chosen
        return {
            "network": material["provider"] if material else "",
            "networks": [
                {"provider": item["provider"], "network": overlay_network(item)}
                for item in materials
            ],
            "state": record["state"],
            "stage": record["stage"],
            "stage_since": record["stage_since"],
            "is_waiting": record["is_waiting"],
            "address": record["address"],
            "error": dict(record["error"]) if record["error"] else None,
        }

    def job(self, hub_id: str) -> str:
        """The step running on one hub's network: empty, connecting or disconnecting."""
        with self._lock:
            return (self._records.get(hub_id) or {}).get("job", "")

    # --- what a press does ---

    def connect(self, hub_id: str) -> None:
        """Start one connect to the chosen network of a hub that is off.

        A press while the network is not off, or on a hub that names no
        network, is dropped and logged.

        Args:
            hub_id: The hub, by its id.
        """
        self.refresh_bindings()
        with self._lock:
            record = self._records.setdefault(hub_id, _off_record())
            material = self._chosen(hub_id)
            if record["state"] != OVERLAY_STATE_OFF or record["job"] or not material:
                material = None
            else:
                record.update(
                    state=OVERLAY_STATE_CONNECTING,
                    stage=OVERLAY_STAGE_LOGIN,
                    stage_since=int(time.time()),
                    is_waiting=False,
                    job=OVERLAY_JOB_CONNECTING,
                    error=None,
                    address="",
                    material=material,
                    count=record["count"] + 1,
                    cancel=threading.Event(),
                )
                count, cancel = record["count"], record["cancel"]
        if material is None:
            self._log(f"overlay: a connect of {hub_id} was dropped")
            return
        self._log(f"overlay: connecting to {overlay_network(material)}")
        self._on_change()
        self._start_thread(
            functools.partial(self._attempt, hub_id, material, count, cancel)
        )

    def cancel(self, hub_id: str) -> None:
        """Stop a connect in progress; the network goes off once its engine stops.

        Args:
            hub_id: The hub, by its id.
        """
        with self._lock:
            record = self._records.get(hub_id)
            if (
                record is None
                or record["state"] != OVERLAY_STATE_CONNECTING
                or record["job"] != OVERLAY_JOB_CONNECTING
            ):
                record = None
            else:
                record["cancel"].set()
                record["count"] += 1
                record["job"] = OVERLAY_JOB_DISCONNECTING
                count, material = record["count"], record["material"]
        if record is None:
            self._log(f"overlay: a cancel of {hub_id} was dropped")
            return
        self._log(f"overlay: cancelling the connect to {overlay_network(material)}")
        self._on_change()
        self._start_thread(functools.partial(self._run_stop, hub_id, material, count))

    def disconnect(self, hub_id: str) -> None:
        """Stop the engine of a network that is on; it goes off once stopped.

        Args:
            hub_id: The hub, by its id.
        """
        with self._lock:
            record = self._records.get(hub_id)
            if record is None or record["state"] != OVERLAY_STATE_ON or record["job"]:
                record = None
            else:
                record["count"] += 1
                record["job"] = OVERLAY_JOB_DISCONNECTING
                count, material = record["count"], record["material"]
        if record is None:
            self._log(f"overlay: a disconnect of {hub_id} was dropped")
            return
        self._log(f"overlay: disconnecting from {overlay_network(material)}")
        self._on_change()
        self._start_thread(functools.partial(self._run_stop, hub_id, material, count))

    def pick(self, hub_id: str, provider: str) -> None:
        """Choose the engine of a hub whose network is off.

        A pick while the network is not off, or of a network the hub does
        not name, is dropped and logged.

        Args:
            hub_id: The hub, by its id.
            provider: The provider of the network chosen.
        """
        self.refresh_bindings()
        with self._lock:
            record = self._records.get(hub_id) or _off_record()
            providers = [item["provider"] for item in self._materials.get(hub_id) or []]
            is_taken = (
                record["state"] == OVERLAY_STATE_OFF
                and not record["job"]
                and provider in providers
            )
            if is_taken:
                self._choices.setdefault(hub_id, {"is_on": False})["pick"] = provider
        if not is_taken:
            self._log(f"overlay: a pick of {provider} for {hub_id} was dropped")
            return
        self._keep(hub_id, False, provider)
        self._on_change()

    def clear_error(self, hub_id: str) -> None:
        """Forget the last failure of one hub's network, as a refresh does.

        Args:
            hub_id: The hub, by its id.
        """
        with self._lock:
            record = self._records.get(hub_id)
            if record is None or not record["error"]:
                return
            record["error"] = None
        self._on_change()

    # --- the loop ---

    def start(self) -> None:
        """Connect each network that was last on once, then watch on a thread."""
        thread = threading.Thread(
            target=self._poll_forever, name="client_overlay", daemon=True
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        """End the poll; every network stays as it is. Idempotent."""
        self._stop.set()
        self._news.set()

    def resume(self) -> None:
        """Connect once each hub whose network was last on and is off now."""
        self.refresh_bindings()
        with self._lock:
            hub_ids = [
                hub_id
                for hub_id, choice in self._choices.items()
                if choice.get("is_on") and self._materials.get(hub_id)
            ]
        for hub_id in hub_ids:
            self._log(f"overlay: {hub_id} was on the network; connecting once")
            self.connect(hub_id)

    def refresh(self) -> None:
        """Read the bindings again; a network the hub stopped naming is left."""
        self.refresh_bindings()
        self._withdraw()

    def refresh_bindings(self) -> None:
        """Take each hub's overlay objects and choice as the sessions hold them now."""
        materials = {}
        urls = {}
        choices = {}
        for row in self._bindings_of():
            hub_id = row.get("hub_id")
            if not hub_id:
                continue
            materials[hub_id] = [
                dict(item)
                for item in row.get("overlays") or []
                if isinstance(item, dict)
            ]
            urls[hub_id] = [str(url) for url in row.get("urls") or []]
            choices[hub_id] = {
                "pick": str(row.get("pick", "") or ""),
                "is_on": row.get("is_on") is True,
            }
        with self._lock:
            is_changed = materials != self._materials
            self._materials = materials
            self._urls = urls
            self._choices = choices
        if is_changed:
            self._on_change()

    def watch(self) -> None:
        """Ask the engine of every network that is on whether it still stands."""
        self.refresh()
        with self._lock:
            held = [
                (hub_id, record["material"], record["count"])
                for hub_id, record in self._records.items()
                if record["state"] == OVERLAY_STATE_ON and not record["job"]
            ]
        for hub_id, material, count in held:
            try:
                status = self._drivers[material["provider"]].status(material)
            except OverlayControlError as error:
                self._lost(hub_id, material, count, _refusal(error))
                continue
            if not status["is_on"]:
                self._lost(hub_id, material, count, _engine_stopped())
                continue
            with self._lock:
                record = self._records.get(hub_id)
                is_moved = (
                    record is not None
                    and record["count"] == count
                    and record["address"] != status["address"]
                )
                if is_moved:
                    record["address"] = status["address"]
            if is_moved:
                self._on_change()

    def release_hub(self, hub_id: str) -> int:
        """Let go of one hub's network: stopped unless another hub is on it.

        Args:
            hub_id: The hub being let go of.

        Returns:
            How many engines were stopped.
        """
        with self._lock:
            record = self._records.pop(hub_id, None)
            self._materials.pop(hub_id, None)
            self._urls.pop(hub_id, None)
            self._choices.pop(hub_id, None)
        if record is None or record["state"] == OVERLAY_STATE_OFF:
            return 0
        if record["cancel"] is not None:
            record["cancel"].set()
        if self._is_shared(hub_id, record["material"]):
            return 0
        self._log(f"overlay: leaving {overlay_network(record['material'])}")
        self._stop_engine(record["material"])
        return 1

    def release(self) -> int:
        """Let go of nothing: the daemons hold the networks.

        Returns:
            How many networks stay on.
        """
        with self._lock:
            return sum(
                1
                for record in self._records.values()
                if record["state"] == OVERLAY_STATE_ON
            )

    def _poll_forever(self) -> None:
        try:
            self.resume()
        except Exception as error:  # noqa: BLE001 - the poll must survive
            self._log(f"overlay: could not connect at start: {error}")
        while not self._stop.is_set():
            self._news.wait(timeout=CLIENT_OVERLAY_POLL_INTERVAL_S)
            self._news.clear()
            if self._stop.is_set():
                return
            try:
                self.watch()
            except Exception as error:  # noqa: BLE001 - the poll must survive
                self._log(f"overlay: could not look at the networks: {error}")

    # --- the steps ---

    def _attempt(self, hub_id: str, material: dict, count: int, cancel) -> None:
        """One connect: stage ``login`` to an address, then stage ``hub``."""
        driver = self._drivers[material["provider"]]
        status = self._login(hub_id, material, count, cancel, driver)
        if status is None:
            return
        address = status["address"]
        with self._lock:
            record = self._records.get(hub_id)
            is_current = record is not None and record["count"] == count
            if is_current:
                record.update(
                    stage=OVERLAY_STAGE_HUB,
                    stage_since=int(time.time()),
                    is_waiting=False,
                    address=address,
                )
            urls = list(self._urls.get(hub_id) or [])
        if not is_current:
            return
        self._on_change()
        host = overlay_hub_host(material, urls, status.get("network", ""))
        if not self._reach(hub_id, material, count, cancel, driver, host):
            return
        with self._lock:
            record = self._records.get(hub_id)
            is_current = record is not None and record["count"] == count
            if is_current:
                record.update(
                    state=OVERLAY_STATE_ON,
                    stage="",
                    stage_since=0,
                    address=address,
                    job="",
                    cancel=None,
                )
        if not is_current:
            return
        self._on_route(hub_id, [host] if host else [], False)
        self._log(f"overlay: on {overlay_network(material)} as {address}")
        self._keep(hub_id, True, material["provider"])
        self._on_change()

    def _login(
        self, hub_id: str, material: dict, count: int, cancel, driver
    ) -> "dict | None":
        """Stage ``login``: the engine's status once it has an address; None if not."""
        network = overlay_network(material)
        started = self._clock()
        deadline = started + self._login_timeout_s
        self._log(f"overlay: {network}: stage login started")
        try:
            driver.join(material, self._hostname)
        except (OverlayControlError, PlatformUnsupportedError) as error:
            self._log_end("login", network, started, error.code)
            self._settle_off(hub_id, count, _refusal(error))
            return None
        while not cancel.is_set():
            try:
                status = driver.status(material)
            except OverlayControlError:
                status = None
            if status is not None and status["is_on"] and status["address"]:
                self._log_end("login", network, started, status["address"])
                return status
            if status is not None and status.get("is_waiting") and deadline:
                deadline = 0
                self._log(f"overlay: {network}: registered, waiting for the console")
                self._note_waiting(hub_id, count)
            if deadline and self._clock() >= deadline:
                self._log_end("login", network, started, "overlay_no_address")
                self._fail(hub_id, material, count, "overlay_no_address")
                return None
            cancel.wait(self._poll_s)
        self._log_end("login", network, started, "cancelled")
        return None

    def _reach(
        self, hub_id: str, material: dict, count: int, cancel, driver, host: str
    ) -> bool:
        """Stage ``hub``: whether the channel came up through the hub's address."""
        network = overlay_network(material)
        started = self._clock()
        self._log(f"overlay: {network}: stage hub started at {host or 'no address'}")
        if not host:
            self._log_end("hub", network, started, "the hub names no address")
            return not cancel.is_set()
        self._on_route(hub_id, [host], True)
        is_seen = False
        while not cancel.is_set():
            try:
                status = driver.status(material)
                error = None if status["is_on"] else _engine_stopped()
            except OverlayControlError as refusal:
                status, error = {}, _refusal(refusal)
            if error is not None and not cancel.is_set():
                self._log_end("hub", network, started, error["code"])
                self._lost(hub_id, material, count, error)
                return False
            if not is_seen and status.get("is_hub_seen"):
                is_seen = True
                elapsed = self._clock() - started
                self._log(
                    f"overlay: {network}: the hub's peer is connected "
                    f"after {elapsed:.1f}s"
                )
            if self._reaches_hub(hub_id, [host]):
                self._log_end("hub", network, started, f"the hub answers at {host}")
                return not cancel.is_set()
            cancel.wait(self._hub_probe_s)
        self._log_end("hub", network, started, "cancelled")
        return False

    def _note_waiting(self, hub_id: str, count: int) -> None:
        """Mark a connect as waiting for its console to assign a network."""
        with self._lock:
            record = self._records.get(hub_id)
            is_current = record is not None and record["count"] == count
            if is_current:
                record["is_waiting"] = True
        if is_current:
            self._on_change()

    def _log_end(self, stage: str, network: str, started: float, outcome: str) -> None:
        """One line for a stage's end, with its duration."""
        elapsed = self._clock() - started
        self._log(
            f"overlay: {network}: stage {stage} ended after {elapsed:.1f}s: {outcome}"
        )

    def _fail(self, hub_id: str, material: dict, count: int, code: str) -> None:
        """A connect that ran out of time: its engine stopped, the network off."""
        self._log(f"overlay: {overlay_network(material)}: {code}")
        if not self._is_shared(hub_id, material):
            self._stop_engine(material)
        self._settle_off(hub_id, count, {"code": code, "params": {}})

    def _lost(self, hub_id: str, material: dict, count: int, error: dict) -> None:
        """A network that was on and is not: off with why."""
        self._log(f"overlay: {overlay_network(material)} is gone: {error['code']}")
        self._settle_off(hub_id, count, error)

    def _withdraw(self) -> None:
        """Leave every network that is on and that its hub no longer names."""
        with self._lock:
            gone = [
                (hub_id, record["material"], record["count"])
                for hub_id, record in self._records.items()
                if record["state"] == OVERLAY_STATE_ON
                and not record["job"]
                and hub_id in self._materials
                and overlay_key(record["material"])
                not in [overlay_key(item) for item in self._materials[hub_id]]
            ]
        for hub_id, material, count in gone:
            self._log(f"overlay: the hub no longer names {overlay_network(material)}")
            if not self._is_shared(hub_id, material):
                self._stop_engine(material)
            self._settle_off(
                hub_id,
                count,
                {
                    "code": "overlay_withdrawn",
                    "params": {"network": overlay_network(material)},
                },
            )

    def _run_stop(self, hub_id: str, material: dict, count: int) -> None:
        """Stop the engine of a cancelled or disconnected network, then go off."""
        failure = None
        if not self._is_shared(hub_id, material):
            failure = self._stop_engine(material)
        self._settle_off(hub_id, count, failure)

    def _settle_off(self, hub_id: str, count: int, error: "dict | None") -> None:
        """Put one hub's network off, unless a later step overtook this one."""
        with self._lock:
            record = self._records.get(hub_id)
            if record is None or record["count"] != count:
                return
            record.update(
                state=OVERLAY_STATE_OFF,
                stage="",
                stage_since=0,
                is_waiting=False,
                address="",
                error=dict(error) if error else None,
                job="",
                material=None,
                cancel=None,
            )
            pick = (self._choices.get(hub_id) or {}).get("pick", "")
        self._on_route(hub_id, [], False)
        self._keep(hub_id, False, pick)
        self._on_change()

    def _stop_engine(self, material: dict) -> "dict | None":
        """Stop one network's engine; its refusal, None when it stopped."""
        try:
            self._drivers[material["provider"]].leave(material)
        except (OverlayControlError, PlatformUnsupportedError) as error:
            self._log(f"overlay: could not leave {overlay_network(material)}: {error}")
            return _refusal(error)
        return None

    def _is_shared(self, hub_id: str, material: "dict | None") -> bool:
        """Whether another hub's network that is not off runs on the same engine network."""
        if material is None:
            return False
        key = overlay_key(material)
        with self._lock:
            return any(
                other_id != hub_id
                and record["state"] != OVERLAY_STATE_OFF
                and record["material"] is not None
                and overlay_key(record["material"]) == key
                for other_id, record in self._records.items()
            )

    def _chosen(self, hub_id: str) -> "dict | None":
        """The network the person chose for a hub, its first until they do; the lock is held."""
        materials = self._materials.get(hub_id) or []
        if not materials:
            return None
        pick = (self._choices.get(hub_id) or {}).get("pick", "")
        by_provider = {item["provider"]: item for item in materials}
        return by_provider.get(pick, materials[0])

    def _keep(self, hub_id: str, is_on: bool, pick: str) -> None:
        """Write where one hub's network stands onto its binding."""
        with self._lock:
            choice = self._choices.setdefault(hub_id, {"pick": pick})
            choice["is_on"] = is_on
            choice["pick"] = pick
        try:
            self._keep_choice(hub_id, is_on, pick)
        except OSError as error:
            self._log(f"overlay: could not record the network's state: {error}")


def _off_record() -> dict:
    """One hub's network record before anything was pressed."""
    return {
        "state": OVERLAY_STATE_OFF,
        "stage": "",
        "stage_since": 0,
        "is_waiting": False,
        "address": "",
        "error": None,
        "job": "",
        "material": None,
        "count": 0,
        "cancel": None,
    }


def _refusal(error) -> dict:
    """An engine's refusal as ``{code, params}``."""
    return {"code": error.code, "params": dict(getattr(error, "params", {}) or {})}


def _engine_stopped() -> dict:
    """The failure of an engine that stopped by itself."""
    return {"code": "overlay_engine_stopped", "params": {}}


def _never(*_args) -> bool:
    """Nothing answers."""
    return False


def _start_daemon_thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()
