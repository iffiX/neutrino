"""This machine's membership of each hub's virtual network.

A virtual network is not a service a hub publishes: it is a way to reach the
hub, so it lives beside the sessions rather than among the handlers. Each
hub's state names how to join its network, NetBird's setup key or EasyTier's
name, secret and peer. One :class:`OverlayMemberships` holds one membership
per network, keyed by NetBird's management URL or EasyTier's network name,
so two hubs on the same network read one state. The daemons the packages
register as services hold the membership itself; this side joins, leaves
and asks, one step at a time per provider, and leaves nothing behind on
exit because nothing here is what keeps a network up.

Errors are ``{"code", "params"}``, never an English sentence; every surface
does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import functools
import json
import os
import subprocess
import threading
import urllib.parse

from neutrino_client.constants import (
    CLIENT_EASYTIER_RPC_PORTAL,
    CLIENT_OVERLAY_DIR_NAME,
    CLIENT_OVERLAY_JOIN_TIMEOUT_S,
    CLIENT_OVERLAY_POLL_INTERVAL_S,
    CLIENT_OVERLAY_STATUS_TIMEOUT_S,
)
from neutrino_client.core import files
from neutrino_client.core.easytier_config import safe_hostname
from neutrino_client.exceptions import OverlayControlError, PlatformUnsupportedError
from neutrino_client.services.worker import IF_BUSY_KEEP_ONE, ServiceWorker

# The words a membership's state takes, in the order a join walks them.
OVERLAY_STATE_OFF = "off"
OVERLAY_STATE_JOINING = "joining"
OVERLAY_STATE_ON = "on"
OVERLAY_STATE_LEAVING = "leaving"
OVERLAY_STATE_FAILED = "failed"
OVERLAY_STATES = (
    OVERLAY_STATE_OFF,
    OVERLAY_STATE_JOINING,
    OVERLAY_STATE_ON,
    OVERLAY_STATE_LEAVING,
    OVERLAY_STATE_FAILED,
)
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
        ``netbird:<management>`` or ``easytier:<network name>``.
    """
    if material["provider"] == "netbird":
        return "netbird:" + netbird_management_key(material.get("management_url", ""))
    return "easytier:" + material.get("network_name", "")


def overlay_network(material: dict) -> str:
    """The network one overlay object names, in the words a row shows.

    Args:
        material: The hub's overlay object.

    Returns:
        The management server's host for NetBird, the network's name for
        EasyTier.
    """
    if material["provider"] == "netbird":
        key = netbird_management_key(material.get("management_url", ""))
        return urllib.parse.urlsplit(key).hostname or ""
    return material.get("network_name", "")


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

    ``is_sticky`` marks a step's failure, which a probe replaces only with
    an ``on``.
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
    """EasyTier's CLI and the platform's root step for its network files."""

    provider = "easytier"

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform, which runs the carried CLI and
                puts a network's file in place as root.
        """
        self._platform = platform

    def status(self, material: dict) -> dict:
        """Where this machine stands on the network the object names.

        Args:
            material: The hub's overlay object.

        Returns:
            ``{"is_on", "is_other_network", "address", "is_hub_seen"}``; a
            daemon that is not running runs no network, which reads as off.

        Raises:
            OverlayControlError: ``bundle_missing``.
        """
        off = {
            "is_on": False,
            "is_other_network": False,
            "address": "",
            "is_hub_seen": False,
        }
        try:
            result = self._platform.run_overlay(
                "easytier-cli",
                [
                    "-p",
                    CLIENT_EASYTIER_RPC_PORTAL,
                    "-n",
                    material["network_name"],
                    "-o",
                    "json",
                    "peer",
                ],
                CLIENT_OVERLAY_STATUS_TIMEOUT_S,
            )
        except OverlayControlError:
            raise
        except (OSError, subprocess.SubprocessError):
            return off
        if result.returncode != 0 or EASYTIER_NO_INSTANCE_MARK in _detail(result):
            return off
        try:
            peers = json.loads(result.stdout or "")
        except ValueError:
            return off
        if not isinstance(peers, list):
            return off
        rows = [peer for peer in peers if isinstance(peer, dict)]
        local = [row for row in rows if row.get("cost") == EASYTIER_PEER_LOCAL_COST]
        return {
            "is_on": True,
            "is_other_network": False,
            "address": _address(local[0].get("ipv4")) if local else "",
            "is_hub_seen": len(rows) > len(local),
        }

    def join(self, material: dict, hostname: str) -> None:
        """Hand the network to the platform's root step, its secret in a 0600 file.

        The file lives under the person's own configuration directory for
        the length of the step.

        Args:
            material: The hub's overlay object.
            hostname: What this machine is called on the network.

        Raises:
            OverlayControlError: The platform's refusal, or ``overlay_*``
                for a value the step refused.
            PlatformUnsupportedError: Where the client carries no EasyTier.
        """
        secret_path = os.path.join(
            self._platform.config_dir(),
            CLIENT_OVERLAY_DIR_NAME,
            material["network_name"] + ".secret",
        )
        files.write_text(secret_path, material["network_secret"], mode=0o600)
        try:
            self._platform.easytier_join(
                network_name=material["network_name"],
                secret_path=secret_path,
                peer=material["peer"],
                hostname=safe_hostname(hostname),
            )
        finally:
            files.remove_file(secret_path)

    def leave(self, material: dict) -> None:
        """Have the platform's root step take the network away.

        Args:
            material: The hub's overlay object.

        Raises:
            OverlayControlError: The platform's refusal.
            PlatformUnsupportedError: Where the client carries no EasyTier.
        """
        self._platform.easytier_leave(network_name=material["network_name"])


class OverlayMemberships:
    """One membership per network the joined hubs name, and one lane per provider."""

    def __init__(
        self,
        *,
        platform,
        bindings_of,
        hostname: str,
        log=print,
        on_change=None,
        start_thread=None,
        drivers=None,
    ):
        """
        Args:
            platform: The machine's platform.
            bindings_of: Returns ``[(hub_id, overlay object or None)]`` for
                every hub joined, in order.
            hostname: What this machine is called on an EasyTier network.
            log: Callable used for progress messages.
            on_change: Called with no arguments after every change a page
                draws; None for nobody listening.
            start_thread: ``start_thread(target)`` runs a lane's job; None
                uses a daemon thread. Tests pass one that runs inline.
            drivers: ``{provider: driver}``; None builds the NetBird and
                EasyTier drivers over the platform.
        """
        self._platform = platform
        self._bindings_of = bindings_of
        self._hostname = hostname
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
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
        # Each joined hub's object as last read, by hub id.
        self._materials: dict = {}
        # Every hub's object this run has read, kept after the hub goes so
        # its network can still be left.
        self._known: dict = {}
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
            is_hub_seen, work}``; None when the hub names no network.
        """
        with self._lock:
            material = self._materials.get(hub_id)
            if material is None:
                return None
            record = dict(self._records.get(overlay_key(material)) or _off_record())
        return {
            "provider": material["provider"],
            "network": overlay_network(material),
            "state": record["state"],
            "code": record["code"],
            "params": dict(record["params"]),
            "address": record["address"],
            "is_hub_seen": record["is_hub_seen"],
            "work": self._lanes[material["provider"]].status(),
        }

    def join(self, hub_id: str) -> dict:
        """Join one hub's network, on its provider's lane.

        Args:
            hub_id: The hub, by its id.

        Returns:
            Empty when the step was taken; ``overlay_missing`` when the hub
            names no network, ``busy`` while the lane works.
        """
        return self._submit(hub_id, OVERLAY_STATE_JOINING)

    def leave(self, hub_id: str) -> dict:
        """Leave one hub's network, on its provider's lane.

        Args:
            hub_id: The hub, by its id.

        Returns:
            Empty when the step was taken; ``overlay_missing`` when the hub
            names no network, ``busy`` while the lane works.
        """
        return self._submit(hub_id, OVERLAY_STATE_LEAVING)

    def release_hub(self, hub_id: str) -> int:
        """Leave a hub's network when no other hub joined names it.

        Args:
            hub_id: The hub being let go of.

        Returns:
            1 when a leave was started, 0 otherwise.
        """
        self.refresh_bindings()
        with self._lock:
            material = self._known.pop(hub_id, None)
            if material is None:
                return 0
            key = overlay_key(material)
            is_shared = any(
                overlay_key(other) == key
                for other_id, other in self._materials.items()
                if other_id != hub_id
            )
            record = self._records.get(key) or _off_record()
            is_on = record["state"] in (OVERLAY_STATE_ON, OVERLAY_STATE_JOINING)
        if is_shared or not is_on:
            return 0
        self._log(f"leaving {overlay_network(material)}, which no hub joined names")
        self._lanes[material["provider"]].submit(
            OVERLAY_STATE_LEAVING,
            functools.partial(self._run_step, material, OVERLAY_STATE_LEAVING),
            if_busy=IF_BUSY_KEEP_ONE,
        )
        return 1

    def release(self) -> int:
        """Let go of nothing: the daemons hold the networks.

        Returns:
            How many networks stay joined.
        """
        with self._lock:
            return sum(
                1
                for record in self._records.values()
                if record["state"] == OVERLAY_STATE_ON
            )

    def refresh(self) -> None:
        """Read the bindings again and have the poll look at every network now."""
        self.refresh_bindings()
        self._news.set()

    def refresh_bindings(self) -> None:
        """Take each hub's overlay object as the sessions hold it now."""
        current = {}
        for hub_id, material in self._bindings_of():
            if hub_id and isinstance(material, dict):
                current[hub_id] = dict(material)
        with self._lock:
            is_changed = current != self._materials
            self._materials = current
            self._known.update(current)
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
            for material in self._materials.values():
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
                    and record["state"] != OVERLAY_STATE_ON
                ):
                    continue
                if previous != record:
                    self._records[key] = record
                    is_changed = True
        if is_changed:
            self._on_change()

    def start(self) -> None:
        """Probe on a thread of its own, every ``CLIENT_OVERLAY_POLL_INTERVAL_S``."""
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
                self._resume()
                self.probe()
            except Exception as error:  # noqa: BLE001 - the poll must survive
                self._log(f"overlay: could not look at the networks: {error}")
            self._news.wait(timeout=CLIENT_OVERLAY_POLL_INTERVAL_S)

    def _resume(self) -> None:
        """Have the platform start EasyTier where networks wait for it."""
        with self._lock:
            has_easytier = any(
                material["provider"] == "easytier"
                for material in self._materials.values()
            )
        if not has_easytier:
            return
        try:
            self._platform.easytier_resume()
        except OverlayControlError as error:
            self._log(f"overlay: could not start EasyTier: {error.code}")

    def _submit(self, hub_id: str, step: str) -> dict:
        self.refresh_bindings()
        with self._lock:
            material = self._materials.get(hub_id)
        if material is None:
            return {"code": "overlay_missing", "params": {"hub_id": hub_id}}
        lane = self._lanes[material["provider"]]
        if lane.is_working:
            return {"code": "busy", "params": {"step": lane.status()["step"]}}
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
