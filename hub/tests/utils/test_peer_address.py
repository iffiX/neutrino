"""A peer's address as every judge of one reads it: a mapped IPv4 address
as its IPv4 address, everything else as it came."""

import pytest

from neutrino_hub.utils.peer_address import unmapped


@pytest.mark.parametrize(
    ("address", "read"),
    [
        ("::ffff:192.168.8.20", "192.168.8.20"),
        ("::ffff:127.0.0.1", "127.0.0.1"),
        ("::FFFF:10.0.0.1", "10.0.0.1"),
        ("192.168.8.20", "192.168.8.20"),
        ("2001:db8::20", "2001:db8::20"),
        ("::1", "::1"),
        ("::127.0.0.1", "::127.0.0.1"),
        ("fe80::1%eth0", "fe80::1%eth0"),
        ("testclient", "testclient"),
        ("", ""),
    ],
)
def test_only_a_mapped_address_changes(address, read):
    assert unmapped(address) == read
