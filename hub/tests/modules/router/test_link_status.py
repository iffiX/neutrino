"""The interfaces' state on macOS and Windows, read through psutil.

What these pin: an address outside loopback is where the box is reached, a
port is every interface holding an IPv4 address outside loopback, and the
default route comes from ``route -n get default`` on macOS and from
``Get-NetRoute`` on Windows, lowest metric first. The IPv6 addresses kept
for a peer elsewhere are the global ones no system mark calls temporary,
deprecated, tentative or duplicate, read on Linux, macOS and Windows.
"""

import json
import socket

import pytest

from tests.conftest import FakePowerShell, FakePsutil, FakeTools
from neutrino_hub.modules.router import link_status
from neutrino_hub.modules.router.link_status import (
    LINK_KIND_ETHERNET,
    LINK_WINDOWS_IPV6_SCRIPT,
    LINK_WINDOWS_ROUTE_SCRIPT,
    RouterLinkStatus,
    admin_up_interfaces,
    device_addresses,
    device_ipv6_addresses,
    system_default_routes,
)

ROUTE_GET_DEFAULT = """\
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING,GLOBAL>
"""

# The proxy's TUN device address on macOS and Windows.
TUN_ADDRESS = "198.18.0.1"  # scan: allow


@pytest.fixture
def machine(monkeypatch) -> FakePsutil:
    held = FakePsutil()
    held.addresses = {
        "lo0": [(socket.AF_INET, "127.0.0.1", "255.0.0.0")],
        "en0": [
            (FakePsutil.AF_LINK, "02:00:5e:10:00:01", None),
            (socket.AF_INET, "192.168.1.20", "255.255.255.0"),
        ],
        "utun4": [(socket.AF_INET, "100.92.10.4", "255.255.0.0")],
        "awdl0": [(FakePsutil.AF_LINK, "6e:01:02:03:04:05", None)],
        "Ethernet 2": [
            (FakePsutil.AF_LINK, "02-00-5E-10-00-02", None),
            (socket.AF_INET, "10.0.0.7", "255.255.255.0"),
        ],
    }
    held.stats = {
        "lo0": (True, 0),
        "en0": (True, 1000),
        "utun4": (True, 0),
        "awdl0": (False, 0),
        "Ethernet 2": (False, 0),
    }
    monkeypatch.setattr(link_status, "psutil", held)
    return held


def test_every_address_outside_loopback_is_where_the_box_is_reached(elsewhere, machine):
    assert device_addresses() == {
        "en0": "192.168.1.20/24",
        "utun4": "100.92.10.4/16",
        "Ethernet 2": "10.0.0.7/24",
    }


def test_a_port_is_every_interface_holding_an_ipv4_address(elsewhere, machine):
    links = RouterLinkStatus().all_links()

    assert [link.name for link in links] == ["Ethernet 2", "en0", "utun4"]
    en0 = links[1]
    assert en0.kind == LINK_KIND_ETHERNET
    assert en0.is_present and en0.is_up
    assert en0.ipv4_address == "192.168.1.20/24"
    assert en0.mac_address == "02:00:5e:10:00:01"
    assert en0.speed_mbps == 1000
    assert links[0].mac_address == "02:00:5e:10:00:02"
    assert not links[0].is_up
    assert links[0].speed_mbps is None


@pytest.mark.feature("proxy")
@pytest.mark.parametrize(
    ("system", "tun_device"), [("darwin", "utun225"), ("win32", "neutrino_tun")]
)
def test_the_proxys_tun_is_no_network_of_the_box(
    monkeypatch, machine, system, tun_device
):
    """It was listed for exposure, and its /30 offered to NetBird as a LAN."""
    from neutrino_hub.platforms import detect

    monkeypatch.setattr(detect.sys, "platform", system)
    machine.addresses[tun_device] = [(socket.AF_INET, TUN_ADDRESS, "255.255.255.252")]
    machine.stats[tun_device] = (True, 0)

    assert tun_device not in device_addresses()
    assert tun_device not in [link.name for link in RouterLinkStatus().all_links()]
    assert tun_device not in admin_up_interfaces()


def test_the_interfaces_that_are_up(elsewhere, machine):
    assert admin_up_interfaces() == {"lo0", "en0", "utun4"}


def test_macos_reads_its_default_route_from_route(on_darwin, monkeypatch):
    tools = FakeTools()
    tools.answers[("route", "-n", "get", "default")] = ROUTE_GET_DEFAULT
    monkeypatch.setattr(link_status, "run", tools)

    assert system_default_routes() == [
        {"dev": "en0", "metric": 0, "gateway": "192.168.1.1"}
    ]
    assert RouterLinkStatus().default_gateway() == "192.168.1.1"
    assert RouterLinkStatus().gateway_for("en0") == "192.168.1.1"


def test_macos_without_a_default_route_has_none(on_darwin, monkeypatch):
    tools = FakeTools()
    tools.failing.add(("route",))
    monkeypatch.setattr(link_status, "run", tools)

    assert system_default_routes() == []
    assert RouterLinkStatus().default_gateway() is None


def test_windows_reads_its_default_routes_lowest_metric_first(on_windows, monkeypatch):
    powershell = FakePowerShell(
        {
            LINK_WINDOWS_ROUTE_SCRIPT: {
                "routes": [
                    {"dev": "Wi-Fi", "gateway": "10.1.1.1", "metric": 55},
                    {"dev": "Ethernet", "gateway": "192.168.1.1", "metric": 25},
                    {"dev": "wt0", "gateway": "0.0.0.0", "metric": 5},
                ]
            }
        }
    )
    monkeypatch.setattr(link_status, "run_powershell", powershell)

    assert system_default_routes() == [
        {"dev": "wt0", "metric": 5},
        {"dev": "Ethernet", "metric": 25, "gateway": "192.168.1.1"},
        {"dev": "Wi-Fi", "metric": 55, "gateway": "10.1.1.1"},
    ]
    assert RouterLinkStatus().default_gateway() is None
    assert RouterLinkStatus().gateway_for("Ethernet") == "192.168.1.1"


def test_windows_with_one_route_answers_it_bare(on_windows, monkeypatch):
    powershell = FakePowerShell(
        {LINK_WINDOWS_ROUTE_SCRIPT: {"routes": {"dev": "Ethernet", "metric": 1}}}
    )
    monkeypatch.setattr(link_status, "run_powershell", powershell)

    assert system_default_routes() == [{"dev": "Ethernet", "metric": 1}]


def test_windows_that_cannot_run_powershell_has_no_route(on_windows, monkeypatch):
    monkeypatch.setattr(
        link_status, "run_powershell", FakePowerShell(error=OSError("absent"))
    )

    assert system_default_routes() == []


# --- the IPv6 addresses a peer elsewhere can keep using ---

IP_ADDR_SHOW = [
    {
        "ifname": "lo",
        "addr_info": [
            {"family": "inet6", "local": "::1", "prefixlen": 128, "scope": "host"}
        ],
    },
    {
        "ifname": "enp1s0",
        "addr_info": [
            {"family": "inet", "local": "192.168.8.1", "prefixlen": 24},
            {
                "family": "inet6",
                "local": "fd00:8::1",
                "prefixlen": 64,
                "scope": "global",
            },
            {
                "family": "inet6",
                "local": "2001:db8::1",
                "prefixlen": 64,
                "scope": "global",
                "dynamic": True,
                "mngtmpaddr": True,
            },
            {
                "family": "inet6",
                "local": "2001:db8::a1",
                "prefixlen": 64,
                "scope": "global",
                "temporary": True,
                "dynamic": True,
            },
            {
                "family": "inet6",
                "local": "2001:db8::d1",
                "prefixlen": 64,
                "scope": "global",
                "deprecated": True,
            },
            {
                "family": "inet6",
                "local": "2001:db8::e1",
                "prefixlen": 64,
                "scope": "global",
                "tentative": True,
            },
            {
                "family": "inet6",
                "local": "2001:db8::f1",
                "prefixlen": 64,
                "scope": "global",
                "dadfailed": True,
                "tentative": True,
            },
            {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"},
        ],
    },
    {"ifname": "enp2s0", "addr_info": []},
]

IFCONFIG = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
\tinet6 ::1 prefixlen 128
\tinet6 fe80::1%lo0 prefixlen 64 scopeid 0x1
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 02:00:5e:10:00:01
\tinet6 fe80::10:1%en0 prefixlen 64 secured scopeid 0x4
\tinet6 2001:db8::1 prefixlen 64 autoconf secured
\tinet6 2001:db8::a1 prefixlen 64 autoconf temporary
\tinet6 2001:db8::d1 prefixlen 64 deprecated autoconf
\tinet6 2001:db8::e1 prefixlen 64 tentative
\tinet6 fd00:8::5 prefixlen 64
\tinet 192.168.1.20 netmask 0xffffff00 broadcast 192.168.1.255
utun3: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
\tinet6 fe80::ce81%utun3 prefixlen 64 scopeid 0x10
"""


def test_linux_keeps_the_global_addresses_no_flag_marks_unstable(monkeypatch):
    tools = FakeTools()
    tools.answers[("ip", "-json", "addr", "show")] = json.dumps(IP_ADDR_SHOW)
    monkeypatch.setattr(link_status, "run", tools)
    monkeypatch.setattr(link_status, "is_linux", lambda: True)
    monkeypatch.setattr(link_status, "hub_os", lambda: "linux")

    assert device_ipv6_addresses() == {"enp1s0": ["fd00:8::1/64", "2001:db8::1/64"]}


def test_linux_that_cannot_read_its_addresses_has_none(monkeypatch):
    tools = FakeTools()
    tools.failing.add(("ip",))
    monkeypatch.setattr(link_status, "run", tools)
    monkeypatch.setattr(link_status, "is_linux", lambda: True)
    monkeypatch.setattr(link_status, "hub_os", lambda: "linux")

    assert device_ipv6_addresses() == {}


def test_macos_reads_the_words_ifconfig_prints_after_an_address(on_darwin, monkeypatch):
    tools = FakeTools()
    tools.answers[("ifconfig",)] = IFCONFIG
    monkeypatch.setattr(link_status, "run", tools)

    assert device_ipv6_addresses() == {"en0": ["2001:db8::1/64", "fd00:8::5/64"]}


def test_windows_keeps_a_preferred_address_that_is_not_temporary(
    on_windows, monkeypatch
):
    powershell = FakePowerShell(
        {
            LINK_WINDOWS_IPV6_SCRIPT: {
                "addresses": [
                    {
                        "dev": "Ethernet",
                        "address": "2001:db8::1",
                        "prefixlen": 64,
                        "state": "Preferred",
                        "suffix": "Link",
                    },
                    {
                        "dev": "Ethernet",
                        "address": "2001:db8::a1",
                        "prefixlen": 64,
                        "state": "Preferred",
                        "suffix": "Random",
                    },
                    {
                        "dev": "Ethernet",
                        "address": "2001:db8::d1",
                        "prefixlen": 64,
                        "state": "Deprecated",
                        "suffix": "Link",
                    },
                    {
                        "dev": "Ethernet",
                        "address": "fd00:8::7",
                        "prefixlen": 64,
                        "state": "Preferred",
                        "suffix": "Manual",
                    },
                    {
                        "dev": "Ethernet",
                        "address": "fe80::1%12",
                        "prefixlen": 64,
                        "state": "Preferred",
                        "suffix": "Link",
                    },
                    {
                        "dev": "Loopback Pseudo-Interface 1",
                        "address": "::1",
                        "prefixlen": 128,
                        "state": "Preferred",
                        "suffix": "WellKnown",
                    },
                ]
            }
        }
    )
    monkeypatch.setattr(link_status, "run_powershell", powershell)

    assert device_ipv6_addresses() == {"Ethernet": ["2001:db8::1/64", "fd00:8::7/64"]}


def test_windows_that_cannot_run_powershell_has_no_ipv6_address(
    on_windows, monkeypatch
):
    monkeypatch.setattr(
        link_status, "run_powershell", FakePowerShell(error=OSError("absent"))
    )

    assert device_ipv6_addresses() == {}
