"""The round trip the hub measures to a relayed overlay peer.

What these pin: the echo command each system takes, the round trip read
from every form ``ping`` prints it in, no answer read as none, and a
refresh keeping only the addresses it was given.
"""

import pytest

from neutrino_hub.modules.overlay.peer_latency import (
    OverlayPeerLatencies,
    echo_command,
    round_trip_ms,
)


@pytest.mark.parametrize(
    "system, command",
    [
        ("linux", ["ping", "-c", "1", "-W", "2", "100.64.0.9"]),
        ("darwin", ["ping", "-c", "1", "-t", "2", "100.64.0.9"]),
        ("windows", ["ping", "-n", "1", "-w", "2000", "100.64.0.9"]),
    ],
)
def test_one_echo_per_system(system, command):
    assert echo_command("100.64.0.9", system) == command


@pytest.mark.parametrize(
    "output, expected",
    [
        ("64 bytes from 100.64.0.9: icmp_seq=1 ttl=64 time=41.6 ms", 41.6),
        ("Reply from 100.64.0.9: bytes=32 time=3ms TTL=64", 3.0),
        ("Reply from 100.64.0.9: bytes=32 time<1ms TTL=64", 1.0),
        ("来自 100.64.0.9 的回复: 字节=32 时间=12ms TTL=64", 12.0),
        ("1 packets transmitted, 0 received, 100% packet loss", None),
    ],
)
def test_the_round_trip_is_read_from_every_form(output, expected):
    assert round_trip_ms(output) == expected


def test_a_refresh_keeps_the_addresses_it_was_given():
    answers = {"100.64.0.9": 41.6, "100.64.0.10": None}
    latencies = OverlayPeerLatencies(echo=answers.get)
    latencies.refresh(["100.64.0.9", "100.64.0.10"])
    latencies.refresh(["100.64.0.9"])

    assert latencies.latency_of("100.64.0.9") == 41.6
    assert latencies.latency_of("100.64.0.10") is None
    assert latencies.latency_of("100.64.0.11") is None
