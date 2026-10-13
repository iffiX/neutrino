"""The interfaces' state on macOS and Windows, read through psutil.

What these pin: an address outside loopback is where the box is reached, a
port is every interface holding an IPv4 address outside loopback, and the
default route comes from ``route -n get default`` on macOS and from
iphlpapi on Windows, lowest metric first. The IPv6 addresses kept
for a peer elsewhere are the global ones no system mark calls temporary,
deprecated, tentative or duplicate, read on Linux, macOS and Windows. The
proxy's TUN and the desktop client's files adapter are no network of the box.
"""

import json
import socket
from pathlib import Path

import pytest

from tests.conftest import FakeIphlpapiTables, FakePsutil, FakeTools
from neutrino_hub.modules.router import link_status
from neutrino_hub.modules.router.constants import ROUTER_CLIENT_FILES_ADAPTER_NAME
from neutrino_hub.modules.router.link_status import (
    LINK_KIND_ETHERNET,
    RouterLinkStatus,
    admin_up_interfaces,
    device_addresses,
    device_ipv6_addresses,
    system_default_routes,
)
from neutrino_hub.platforms import win32
from neutrino_hub.system import windows_net

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


def test_windows_reads_its_default_routes_from_iphlpapi(on_windows, monkeypatch):
    """Two routes at one metric, from tables a Windows machine recorded."""
    monkeypatch.setattr(windows_net, "_READER", FakeIphlpapiTables.recorded())

    assert system_default_routes() == [
        {"dev": "Ethernet Instance 0 2", "metric": 15, "gateway": "192.168.10.1"},
        {"dev": "Ethernet Instance 0 3", "metric": 15, "gateway": "10.10.2.1"},
    ]
    assert RouterLinkStatus().default_gateway() == "192.168.10.1"
    assert RouterLinkStatus().gateway_for("Ethernet Instance 0 3") == "10.10.2.1"


def test_windows_whose_route_table_cannot_be_read_has_no_route(on_windows, monkeypatch):
    monkeypatch.setattr(
        windows_net, "_READER", FakeIphlpapiTables(error=OSError(5, "denied"))
    )

    assert system_default_routes() == []
    assert RouterLinkStatus().default_gateway() is None


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
    addresses = [
        ("2001:db8::1", "Preferred", "Link"),
        ("2001:db8::a1", "Preferred", "Random"),
        ("2001:db8::d1", "Deprecated", "Link"),
        ("fd00:8::7", "Preferred", "Manual"),
        ("fe80::1", "Preferred", "Link"),
    ]
    found = [
        {
            "dev": "Ethernet",
            "address": address,
            "prefixlen": 64,
            "state": state,
            "suffix": suffix,
        }
        for address, state, suffix in addresses
    ]
    asked = []

    def unicast_addresses(family):
        asked.append(family)
        return found

    monkeypatch.setattr(windows_net, "unicast_addresses", unicast_addresses)

    assert device_ipv6_addresses() == {"Ethernet": ["2001:db8::1/64", "fd00:8::7/64"]}
    assert asked == [win32.AF_INET6]


def test_windows_reads_its_ipv6_addresses_from_iphlpapi(on_windows, monkeypatch):
    """The recorded machine's temporary, link-local and loopback addresses
    are left out; its RA address is kept."""
    monkeypatch.setattr(windows_net, "_READER", FakeIphlpapiTables.recorded())

    assert device_ipv6_addresses() == {
        "Ethernet Instance 0 3": ["2001:db8:b:0:c60a:c2e9:531e:532f/64"]
    }


def test_windows_whose_address_table_cannot_be_read_has_no_ipv6_address(
    on_windows, monkeypatch
):
    monkeypatch.setattr(
        windows_net, "_READER", FakeIphlpapiTables(error=OSError(5, "denied"))
    )

    assert device_ipv6_addresses() == {}


# --- the desktop client's files adapter ---

# The address the client gives its files adapter on Windows.
ADAPTER_ADDRESS = "198.19.255.1"  # scan: allow

CLIENT_CONSTANTS = (
    Path(__file__).resolve().parents[4] / "client/desktop/neutrino_client/constants.py"
)


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_the_clients_files_adapter_is_no_network_of_the_box(
    monkeypatch, machine, system
):
    """It was listed as exposed, opened in the firewall and named in links."""
    from neutrino_hub.platforms import detect

    monkeypatch.setattr(detect.sys, "platform", system)
    adapter = ROUTER_CLIENT_FILES_ADAPTER_NAME
    machine.addresses[adapter] = [(socket.AF_INET, ADAPTER_ADDRESS, "255.255.255.0")]
    machine.stats[adapter] = (True, 0)

    assert adapter not in device_addresses()
    assert adapter not in [link.name for link in RouterLinkStatus().all_links()]
    assert adapter not in admin_up_interfaces()


def test_the_clients_files_adapter_is_left_out_on_linux_too(monkeypatch):
    from types import SimpleNamespace

    listed = [
        {
            "ifname": "lo",
            "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}],
        },
        {
            "ifname": "enp1s0",
            "addr_info": [{"family": "inet", "local": "192.168.1.2", "prefixlen": 24}],
        },
        {
            "ifname": ROUTER_CLIENT_FILES_ADAPTER_NAME,
            "addr_info": [
                {"family": "inet", "local": ADAPTER_ADDRESS, "prefixlen": 24},
                {
                    "family": "inet6",
                    "scope": "global",
                    "local": "2001:db8::1",
                    "prefixlen": 64,
                },
            ],
        },
    ]
    monkeypatch.setattr(link_status, "is_linux", lambda: True)
    monkeypatch.setattr(link_status, "hub_os", lambda: "linux")
    monkeypatch.setattr(
        link_status,
        "run",
        lambda *arguments, **keywords: SimpleNamespace(
            is_success=True, stdout=json.dumps(listed)
        ),
    )

    assert device_addresses() == {"enp1s0": "192.168.1.2/24"}
    assert device_ipv6_addresses() == {}


def test_the_adapters_name_is_the_one_the_client_gives_it():
    assert (
        f'CLIENT_FILES_ADAPTER_NAME = "{ROUTER_CLIENT_FILES_ADAPTER_NAME}"'
        in CLIENT_CONSTANTS.read_text(encoding="utf-8")
    )
