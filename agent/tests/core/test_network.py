"""The report's network section, as pure functions.

The link is the interface holding the socket's own address; an address no
interface holds still names the link; IPv6 addresses count; and a machine
with no readable interfaces still reports the address it spoke from.
"""

from neutrino_agent.core.network import describe, link_of

ETH = {
    "name": "eth0",
    "mac": "02:00:00:00:00:01",
    "addresses": ["192.0.2.10", "fe80::ff:fe00:1"],
}
WLAN = {"name": "wlan0", "mac": "02:00:00:00:00:02", "addresses": ["10.0.0.5"]}
TUN = {"name": "tun0", "mac": "", "addresses": ["10.8.0.2"]}
INTERFACES = [ETH, WLAN, TUN]


def test_the_link_is_the_interface_holding_the_sockets_address():
    assert link_of("10.0.0.5", INTERFACES) is WLAN
    assert describe("10.0.0.5", INTERFACES) == {
        "link": {
            "interface": "wlan0",
            "mac": "02:00:00:00:00:02",
            "address": "10.0.0.5",
        },
        "interfaces": INTERFACES,
    }


def test_an_address_no_interface_holds_still_names_the_link():
    assert link_of("203.0.113.9", INTERFACES) is None
    assert describe("203.0.113.9", INTERFACES)["link"] == {
        "interface": "",
        "mac": "",
        "address": "203.0.113.9",
    }


def test_an_ipv6_address_finds_its_interface():
    assert link_of("fe80::ff:fe00:1", INTERFACES) is ETH
    assert describe("fe80::ff:fe00:1", INTERFACES)["link"]["interface"] == "eth0"


def test_an_interface_without_a_mac_still_holds_its_address():
    assert describe("10.8.0.2", INTERFACES)["link"] == {
        "interface": "tun0",
        "mac": "",
        "address": "10.8.0.2",
    }


def test_with_no_interfaces_the_link_is_the_address_alone():
    assert link_of("192.0.2.10", []) is None
    assert describe("192.0.2.10", []) == {
        "link": {"interface": "", "mac": "", "address": "192.0.2.10"},
        "interfaces": [],
    }


def test_an_empty_address_matches_no_interface():
    assert link_of("", [{"name": "x", "mac": "", "addresses": [""]}]) is None
    assert describe("", INTERFACES)["link"] == {
        "interface": "",
        "mac": "",
        "address": "",
    }
