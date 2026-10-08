"""NetBird's driver: its CLI, run as this person against the packaged daemon.

Besides joining, leaving and asking where this machine stands, the driver
says what a NetBird overlay object means for the virtual network line: the
membership it belongs to, the network it names, and where the hub is on it.
"""

import json
import subprocess
import urllib.parse

from neutrino_client.constants import (
    CLIENT_OVERLAY_JOIN_TIMEOUT_S,
    CLIENT_OVERLAY_STATUS_TIMEOUT_S,
)
from neutrino_client.exceptions import OverlayControlError
from neutrino_client.netbird.constants import (
    NETBIRD_DAEMON_DOWN_MARKS,
    NETBIRD_DEFAULT_MANAGEMENT_URL,
    NETBIRD_NETWORK,
    NETBIRD_PROVIDER,
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


def _detail(result) -> str:
    """A finished CLI's last words."""
    return (result.stderr or result.stdout or "").strip()[-200:]


def _address(value) -> str:
    """An address without its prefix length."""
    return str(value or "").split("/", 1)[0]


def _peer_details(status: dict) -> list:
    """The peers ``netbird status --json`` lists, each an object."""
    peers = status.get("peers")
    details = peers.get("details") if isinstance(peers, dict) else None
    return [peer for peer in details or [] if isinstance(peer, dict)]


def _connected_peers(status: dict) -> list:
    """The connected peers, by address or else by name, sorted."""
    return sorted(
        {
            _address(peer.get("netbirdIp")) or str(peer.get("fqdn", "") or "")
            for peer in _peer_details(status)
            if peer.get("status") == "Connected"
        }
    )


class OverlayNetbirdDriver:
    """NetBird's CLI, run as this person against the packaged daemon."""

    provider = NETBIRD_PROVIDER

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform, which runs the carried CLI.
        """
        self._platform = platform

    @staticmethod
    def key(material: dict) -> str:
        """The membership a NetBird object belongs to.

        Args:
            material: The hub's overlay object.

        Returns:
            ``netbird:<management>``.
        """
        return "netbird:" + netbird_management_key(material.get("management_url", ""))

    @staticmethod
    def network(material: dict) -> str:
        """The network a NetBird object names, in the words a row shows.

        Args:
            material: The hub's overlay object.

        Returns:
            The management server's host.
        """
        key = netbird_management_key(material.get("management_url", ""))
        return urllib.parse.urlsplit(key).hostname or ""

    @staticmethod
    def hub_network(network: str) -> str:
        """The network the hub's address is looked for in.

        Args:
            network: The prefix of the network this machine is on, empty
                when not known.

        Returns:
            ``network``, else NetBird's own prefix.
        """
        return network or NETBIRD_NETWORK

    @staticmethod
    def hub_name(material: dict) -> str:
        """The hub's name on the network, for a hub no address names there.

        Args:
            material: The hub's overlay object.

        Returns:
            NetBird's name for the hub, empty for none.
        """
        return str(material.get("fqdn", "") or "")

    def status(self, material: dict) -> dict:
        """Where this machine stands on the network the object names.

        Args:
            material: The hub's overlay object.

        Returns:
            ``{"is_on", "is_other_network", "address", "network",
            "is_hub_seen", "peers"}``; the hub is seen when its peer is
            ``Connected``, and ``peers`` are the connected peers by
            address, sorted.

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
                "peers": [],
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
            "network": NETBIRD_NETWORK if is_on else "",
            "is_hub_seen": is_on and self._sees(status, material),
            "peers": _connected_peers(status) if is_on else [],
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
                "overlay_other_network", {"network": self.network(material)}
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
        for peer in _peer_details(status):
            if peer.get("status") != "Connected":
                continue
            if address and _address(peer.get("netbirdIp")) == address:
                return True
            if fqdn and str(peer.get("fqdn", "")).rstrip(".") == fqdn:
                return True
        return False
