"""The round trip to an overlay peer whose engine gives none.

NetBird reports no latency for a peer it reaches through a relay. The hub
measures one itself, one ICMP echo to the peer's overlay address, from the
address sampler's thread, so a page that reads the peers waits on no echo.
A peer whose echo got no answer reads as no latency.

Not pure: sends echoes.
"""

import re
import subprocess
import threading

from neutrino_hub.modules.overlay.constants import OVERLAY_PEER_ECHO_TIMEOUT_S
from neutrino_hub.platforms.constants import (
    PLATFORM_OS_DARWIN,
    PLATFORM_OS_WINDOWS,
)
from neutrino_hub.platforms.detect import hub_os
from neutrino_hub.utils.subprocess_run import run

# The round trip in a ping's reply line, on every system and in every
# language Windows prints it in: ``time=0.4 ms``, ``time<1ms``, ``时间=3ms``.
_ROUND_TRIP = re.compile(r"[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms")


def echo_command(address: str, system: str) -> list:
    """The command that sends one ICMP echo to an address.

    Args:
        address: The peer's overlay address.
        system: ``linux``, ``darwin`` or ``windows``.

    Returns:
        The argument vector.
    """
    seconds = str(int(OVERLAY_PEER_ECHO_TIMEOUT_S))
    if system == PLATFORM_OS_WINDOWS:
        return [
            "ping",
            "-n",
            "1",
            "-w",
            str(int(OVERLAY_PEER_ECHO_TIMEOUT_S * 1000)),
            address,
        ]
    if system == PLATFORM_OS_DARWIN:
        return ["ping", "-c", "1", "-t", seconds, address]
    return ["ping", "-c", "1", "-W", seconds, address]


def round_trip_ms(output: str) -> "float | None":
    """The round trip one ping printed.

    Args:
        output: What ``ping`` wrote.

    Returns:
        Milliseconds, or None when the echo got no answer.
    """
    found = _ROUND_TRIP.search(output)
    return float(found.group(1)) if found else None


def echo_ms(address: str) -> "float | None":
    """Send one ICMP echo and read its round trip.

    Args:
        address: The peer's overlay address.

    Returns:
        Milliseconds, or None when there was no answer or no ``ping``.
    """
    try:
        result = run(
            echo_command(address, hub_os()),
            timeout_s=OVERLAY_PEER_ECHO_TIMEOUT_S + 2,
            is_checked=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not result.is_success:
        return None
    return round_trip_ms(result.stdout)


class OverlayPeerLatencies:
    """The last round trip the hub measured to each relayed peer."""

    def __init__(self, *, echo=echo_ms):
        """
        Args:
            echo: Sends one echo to an address and returns its milliseconds.
        """
        self._echo = echo
        self._lock = threading.Lock()
        self._measured: dict = {}

    def refresh(self, addresses: list) -> None:
        """Measure each address once, and forget every other.

        Args:
            addresses: The relayed peers' overlay addresses.
        """
        measured = {address: self._echo(address) for address in addresses}
        with self._lock:
            self._measured = measured

    def latency_of(self, address: str) -> "float | None":
        """The round trip last measured to one address.

        Args:
            address: The peer's overlay address.

        Returns:
            Milliseconds; None when it was not measured or got no answer.
        """
        with self._lock:
            return self._measured.get(address)
