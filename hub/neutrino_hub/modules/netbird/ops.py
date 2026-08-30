"""Reading and driving the box's NetBird enrollment.

There is nothing to render here: NetBird keeps its own state under
``/etc/netbird``, and the subnet routes live on the management plane, not on
this box. What the gateway owns is joining, and telling the truth about what
the daemon is doing.

Leaving is deliberately absent. NetBird is the way back into this box, and a
"disconnect" button pressed from abroad is a lockout; a hand at a local
shell has ``netbird down``.
"""

import json
from dataclasses import dataclass, field

from neutrino_hub.utils.subprocess_run import run

# Long enough for the first handshake with the management plane; `netbird up`
# returns once the engine is started or the key is rejected.
JOIN_TIMEOUT_S = 90


@dataclass
class NetbirdPeer:
    """One other machine on the overlay, as this box sees it.

    Attributes:
        fqdn: The peer's overlay name.
        netbird_ip: Its overlay address.
        is_connected: Whether a tunnel to it is up right now.
        connection_type: ``P2P`` when direct, ``Relayed`` when through a
            relay — worth showing, because relayed is what a hostile network
            path looks like.
        latency_ms: Round trip to the peer, when known.
    """

    fqdn: str
    netbird_ip: str
    is_connected: bool
    connection_type: str
    latency_ms: int | None


@dataclass
class NetbirdState:
    """What the daemon reports, reshaped for the page.

    Attributes:
        is_installed: Whether the binary exists at all.
        version: The daemon's version.
        daemon_status: NetBird's own word — ``NeedsLogin``, ``Connected``…
        is_enrolled: Whether the box has joined a network. False is what the
            page's join box keys off.
        is_management_connected: Whether the management plane is reachable —
            false with an enrollment is the "open the local-proxy switch"
            situation, and the page says so.
        management_url: Which management plane it enrolled with.
        netbird_ip: This box's overlay address.
        fqdn: This box's overlay name.
        peers: The other machines, connected ones first.
    """

    is_installed: bool
    version: str = ""
    daemon_status: str = ""
    is_enrolled: bool = False
    is_management_connected: bool = False
    management_url: str = ""
    netbird_ip: str = ""
    fqdn: str = ""
    peers: list[NetbirdPeer] = field(default_factory=list)


class NetbirdStatusReader:
    """Reads what the daemon is doing right now."""

    def survey(self) -> NetbirdState:
        """Read the daemon's status.

        Returns:
            The reshaped state; ``is_installed`` False when the binary or the
            daemon is not there to ask.
        """
        result = run(["netbird", "status", "--json"], is_checked=False)
        if not result.is_success:
            return NetbirdState(is_installed=False)
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError:
            return NetbirdState(is_installed=False)

        management = status.get("management") or {}
        peers = []
        for entry in (status.get("peers") or {}).get("details") or []:
            latency = entry.get("latency")
            peers.append(
                NetbirdPeer(
                    fqdn=entry.get("fqdn", ""),
                    netbird_ip=entry.get("netbirdIp", ""),
                    is_connected=entry.get("status", "") == "Connected",
                    connection_type=entry.get("connectionType", ""),
                    # The daemon reports nanoseconds; the page wants a number
                    # a person can compare with a ping.
                    latency_ms=(
                        int(latency / 1_000_000)
                        if isinstance(latency, (int, float)) and latency > 0
                        else None
                    ),
                )
            )
        peers.sort(key=lambda peer: (not peer.is_connected, peer.fqdn))

        return NetbirdState(
            is_installed=True,
            version=status.get("daemonVersion", ""),
            daemon_status=status.get("daemonStatus", ""),
            is_enrolled=status.get("daemonStatus", "") != "NeedsLogin",
            is_management_connected=bool(management.get("connected")),
            management_url=management.get("url", ""),
            netbird_ip=status.get("netbirdIp", ""),
            fqdn=status.get("fqdn", ""),
            peers=peers,
        )


class NetbirdEnroller:
    """Joins the box to a NetBird network."""

    def join(self, *, setup_key: str, management_url: str = "") -> None:
        """Enroll with a setup key.

        The key is used and forgotten: it enrolls once, NetBird keeps the
        machine identity under ``/etc/netbird``, and nothing of the key
        belongs in ``config/`` or anywhere else.

        Args:
            setup_key: The key from the management console.
            management_url: A self-hosted management plane; empty uses
                NetBird's own.

        Raises:
            CommandError: If the daemon or the management plane refuses.
        """
        # Down first so a re-enrollment with a new key or plane succeeds;
        # harmless when not enrolled.
        run(["netbird", "down"], is_checked=False, timeout_s=30)
        command = ["netbird", "up", "--setup-key", setup_key]
        if management_url:
            command += ["--management-url", management_url]
        run(command, timeout_s=JOIN_TIMEOUT_S)
