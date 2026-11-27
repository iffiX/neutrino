"""The IPv6 loopback a listener a browser opens binds.

What these pin: ``::1`` added after an IPv4 address on a machine with the
IPv6 loopback, and never after an IPv6 address or on a machine without it;
a socket bound to ``[::1]`` at a port, IPv6 alone, and a held one refused.
"""

import socket

import pytest

from neutrino_hub.utils.loopback_listen import (
    bind_ipv6_loopback,
    has_ipv6_loopback,
    is_ipv4_host,
    with_ipv6_loopback,
)


def _ipv6() -> bool:
    return True


def _no_ipv6() -> bool:
    return False


@pytest.mark.parametrize(
    ("host", "is_ipv6", "hosts"),
    [
        ("0.0.0.0", _ipv6, ["0.0.0.0", "::1"]),  # scan: allow
        ("127.0.0.1", _ipv6, ["127.0.0.1", "::1"]),
        ("::", _ipv6, ["::"]),
        ("::1", _ipv6, ["::1"]),
        ("0.0.0.0", _no_ipv6, ["0.0.0.0"]),  # scan: allow
    ],
)
def test_the_ipv6_loopback_follows_an_ipv4_address_alone(host, is_ipv6, hosts):
    assert with_ipv6_loopback(host, is_ipv6) == hosts


def test_an_ipv4_host_is_told_from_an_ipv6_one_and_a_name():
    assert is_ipv4_host("10.0.0.1")
    assert not is_ipv4_host("::1")
    assert not is_ipv4_host("localhost")


@pytest.mark.skipif(not has_ipv6_loopback(), reason="no IPv6 loopback")
def test_a_socket_binds_the_ipv6_loopback_and_a_held_one_is_refused():
    first = bind_ipv6_loopback(0)
    try:
        port = first.getsockname()[1]
        first.listen()
        assert first.family == socket.AF_INET6
        assert first.getsockname()[0] == "::1"
        assert first.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
        with pytest.raises(OSError):
            bind_ipv6_loopback(port)
    finally:
        first.close()
