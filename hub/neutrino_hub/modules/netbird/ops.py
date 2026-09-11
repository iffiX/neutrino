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
from datetime import datetime, timezone
from pathlib import Path

from neutrino_hub.modules.netbird.constants import (
    NETBIRD_ACTIVE_PROFILE_PATH,
    NETBIRD_BINARY_PATH,
    NETBIRD_BLOCK_INBOUND_KEY,
    NETBIRD_INBOUND_TIMEOUT_S,
    NETBIRD_LEGACY_CONFIG_PATH,
    NETBIRD_STATE_DIR,
)
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
        rx_bytes: Received from the peer over the tunnel, when known.
        tx_bytes: Sent to it, when known.
        last_handshake_s: Seconds since the tunnel last shook hands, which is
            how long ago the peer was certainly there.
    """

    fqdn: str
    netbird_ip: str
    is_connected: bool
    connection_type: str
    latency_ms: int | None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    last_handshake_s: int | None = None


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
        result = run([str(NETBIRD_BINARY_PATH), "status", "--json"], is_checked=False)
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
                    rx_bytes=_counter(entry.get("transferReceived")),
                    tx_bytes=_counter(entry.get("transferSent")),
                    last_handshake_s=_age_s(entry.get("lastWireguardHandshake")),
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


def _counter(value) -> "int | None":
    """One traffic counter the daemon reported.

    Args:
        value: What the peer entry carried.

    Returns:
        The count, None when the daemon reported none.
    """
    return int(value) if isinstance(value, (int, float)) else None


def _age_s(value) -> "int | None":
    """How long ago a timestamp the daemon reported was.

    Args:
        value: An RFC 3339 timestamp, as the daemon writes them.

    Returns:
        Whole seconds since then, None when there is no timestamp or it never
        happened.

    """
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.year <= 1971:
        return None
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    return int(seconds) if seconds >= 0 else 0


class NetbirdInboundGate:
    """Whether NetBird itself accepts inbound connections on the overlay.

    The exposure switch has to reach here, because the daemon does not leave
    the firewall to us: within ten seconds of any reload it inserts an accept
    for its own interface at the top of whatever input chain it finds, this
    hub's included. A rule we render and it overrides is a switch that reads
    as closed and is open, so closing the overlay tells NetBird as well.
    """

    def state(self) -> bool | None:
        """What the daemon was last told about inbound connections.

        Returns:
            True when it is blocking them, False when it is not, and None
            when nothing on this box says either way.
        """
        for path in self._state_paths():
            try:
                stored = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if NETBIRD_BLOCK_INBOUND_KEY in stored:
                return bool(stored[NETBIRD_BLOCK_INBOUND_KEY])
        return None

    def converge(self, *, is_blocked: bool) -> str:
        """Make the daemon agree, and only then.

        Two things about ``netbird up`` are settled by what it does rather
        than by what reads well, both measured on a running client: it is a
        no-op while the client is already connected, so the session is taken
        down first the way an enrollment does; and the flag is sticky, so
        leaving it off keeps whatever was stored last rather than clearing
        it, and the value is always stated.

        Args:
            is_blocked: Whether inbound connections should be refused.

        Returns:
            A note for the apply summary, empty when nothing had to change.
            Setting it re-establishes the session, so a state that already
            agrees is left alone: a network apply must not cost the overlay a
            reconnection every time somebody saves an unrelated interface.

        Raises:
            subprocess.CalledProcessError: If the daemon refuses to come back up.
        """
        if self.state() == is_blocked:
            return ""
        status = NetbirdStatusReader().survey()
        if not status.is_installed or not status.is_enrolled:
            return ""
        run([str(NETBIRD_BINARY_PATH), "down"], is_checked=False, timeout_s=30)
        run(
            [
                str(NETBIRD_BINARY_PATH),
                "up",
                f"--block-inbound={'true' if is_blocked else 'false'}",
            ],
            timeout_s=NETBIRD_INBOUND_TIMEOUT_S,
        )
        return "overlay closed" if is_blocked else "overlay opened"

    def _state_paths(self) -> list:
        paths = []
        try:
            active = json.loads(NETBIRD_ACTIVE_PROFILE_PATH.read_text())
            name = str(active.get("name", "") or "")
        except (OSError, ValueError):
            name = ""
        if name and Path(name).name == name:
            paths.append(NETBIRD_STATE_DIR / f"{name}.json")
        paths.append(NETBIRD_LEGACY_CONFIG_PATH)
        return paths


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
            subprocess.CalledProcessError: If the daemon or the management
                plane refuses.
        """
        # Down first so a re-enrollment with a new key or plane succeeds;
        # harmless when not enrolled.
        run([str(NETBIRD_BINARY_PATH), "down"], is_checked=False, timeout_s=30)
        command = [str(NETBIRD_BINARY_PATH), "up", "--setup-key", setup_key]
        if management_url:
            command += ["--management-url", management_url]
        run(command, timeout_s=JOIN_TIMEOUT_S)
