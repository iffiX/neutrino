"""The scope a caller arrived from, and where a device is on it.

A served LAN is a scope named by its network CIDR, the overlay is one from
the address the hub's own overlay interface holds, and everything else is
``link`` with the address the caller reached. A device's address in a
scope is its link address when that is inside, else the first reported
IPv4 address inside, else the link address; IPv6 is never considered.
"""

from neutrino_hub.modules.services.host_scope import (
    HostScope,
    device_host_for,
    link_scope,
    scope_of,
    served_scopes,
)
from tests.conftest import lan_entry, network_config

LAN = HostScope(
    id="192.168.100.0/24", cidr="192.168.100.0/24", hub_address="192.168.100.1"
)
OVERLAY = HostScope(id="overlay", cidr="100.64.0.0/16", hub_address="100.64.0.1")
SERVED = [LAN, OVERLAY]


def interfaces(*addresses: str) -> list:
    return [{"name": "eth0", "mac": "aa:bb:cc:dd:ee:ff", "addresses": list(addresses)}]


# --- the served scopes ---


def test_each_served_lan_is_a_scope_named_by_its_network():
    network = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        lan_entry("wlp3s0", address="192.168.101.1", prefix_len=25),
    )

    assert served_scopes(network, {}) == [
        LAN,
        HostScope(
            id="192.168.101.0/25", cidr="192.168.101.0/25", hub_address="192.168.101.1"
        ),
    ]


def test_the_overlay_scope_comes_from_the_hubs_own_overlay_address():
    network = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "netbird"}],
    )

    scopes = served_scopes(
        network, {"wt0": "100.64.0.1/16", "enp1s0": "192.168.100.1/24"}
    )

    assert scopes == [LAN, OVERLAY]


def test_an_overlay_holding_no_address_is_no_scope():
    network = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "netbird"}],
    )

    assert served_scopes(network, {}) == [LAN]
    assert served_scopes(network, {"wt0": "fd00::1/64"}) == [LAN]


# --- the caller's scope ---


def test_a_peer_inside_a_served_lan_is_in_that_lan():
    assert scope_of("192.168.100.9", "192.168.100.1", SERVED) == LAN


def test_a_peer_inside_the_overlay_is_in_the_overlay():
    assert scope_of("100.64.3.7", "100.64.0.1", SERVED) == OVERLAY


def test_a_peer_anywhere_else_is_on_the_link_it_reached():
    scope = scope_of("203.0.113.5", "198.51.100.2", SERVED)

    assert scope == link_scope("198.51.100.2")
    assert (scope.id, scope.cidr, scope.hub_address) == (
        "link",
        "",
        "198.51.100.2",
    )


def test_a_peer_that_is_no_ipv4_address_is_on_the_link():
    assert scope_of("fe80::1", "192.168.100.1", SERVED).id == "link"
    assert scope_of("testclient", "testserver", SERVED) == link_scope("testserver")
    assert scope_of("", "192.168.100.1", []) == link_scope("192.168.100.1")


# --- the device's address in a scope ---


def test_the_link_address_wins_when_it_is_inside_the_scope():
    reported = interfaces("192.168.100.40", "192.168.100.7")

    assert device_host_for(LAN, reported, "192.168.100.7") == "192.168.100.7"


def test_the_first_reported_address_inside_the_scope_stands_in():
    reported = interfaces("172.17.0.1", "100.64.9.2", "100.64.9.3")

    assert device_host_for(OVERLAY, reported, "192.168.100.7") == "100.64.9.2"


def test_a_prefixed_address_is_read_bare():
    assert device_host_for(OVERLAY, interfaces("100.64.9.2/16"), "10.0.0.2") == (
        "100.64.9.2"
    )


def test_with_nothing_inside_the_scope_the_link_address_stands():
    reported = interfaces("172.17.0.1", "10.0.0.2")

    assert device_host_for(OVERLAY, reported, "192.168.100.7") == "192.168.100.7"
    assert device_host_for(OVERLAY, [], "192.168.100.7") == "192.168.100.7"
    assert device_host_for(OVERLAY, ["nonsense"], "192.168.100.7") == "192.168.100.7"


def test_ipv6_is_never_considered():
    reported = interfaces("fd00:64::2", "2001:db8::7")

    assert device_host_for(OVERLAY, reported, "192.168.100.7") == "192.168.100.7"
    assert device_host_for(LAN, reported, "fd00:100::7") == "fd00:100::7"


def test_the_link_scope_is_the_link_address_whatever_was_reported():
    reported = interfaces("192.168.100.7", "100.64.9.2")

    assert device_host_for(link_scope("198.51.100.2"), reported, "203.0.113.9") == (
        "203.0.113.9"
    )
