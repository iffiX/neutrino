"""The TUN device's start line and route plan, rendered from plain facts.

What these pin: tun2socks starts on the named device pointed at xray's
loopback inbound; each address kept out is one host route through the
gateway, in address order, ahead of the two halves onto the device; an
address on a local network, a duplicate or anything not IPv4 gets no route;
and the macOS commands and the Windows documents say the same routes.
"""

import pytest

from neutrino_hub.modules.tun.renderer import (
    TunPlan,
    TunRoute,
    darwin_address_command,
    darwin_route_command,
    darwin_scoped_default_route,
    is_tun_wanted,
    render_start_line,
    render_tun_plan,
    windows_route_document,
)

# The upper half of the address space and the device's own address, as
# the plan names them.
UPPER_HALF = "128.0.0.0/1"  # scan: allow
TUN_ADDRESS = "198.18.0.1"  # scan: allow


def plan(**facts) -> TunPlan:
    given = {
        "device": "utun225",
        "start_argv": ["/app/bin/tun2socks"],
        "uplink": "en0",
        "gateway": "192.168.1.1",
        "local_networks": ["192.168.1.20/24"],
        "kept_out": [],
        "forwarding_devices": [],
        **facts,
    }
    return render_tun_plan(**given)


@pytest.mark.parametrize(
    ("device", "binary"),
    [
        ("utun225", "/Library/Application Support/Neutrino/hub/app/bin/tun2socks"),
        ("neutrino_tun", "C:\\Program Files\\Neutrino\\hub\\bin\\tun2socks.exe"),
    ],
)
def test_tun2socks_starts_on_the_device_pointed_at_the_local_inbound(device, binary):
    assert render_start_line(binary=binary, device=device, socks_port=10087) == [
        binary,
        "--device",
        f"tun://{device}",
        "--proxy",
        "socks5://127.0.0.1:10087",
        "--mtu",
        "1500",
        "--loglevel",
        "warn",
    ]


@pytest.mark.parametrize(
    ("routing", "has_exit", "is_wanted"),
    [
        ({}, True, False),
        ({"is_proxy_enabled": True}, True, False),
        ({"is_local_proxy_enabled": True}, True, True),
        ({"is_overlay_proxy_enabled": True}, True, True),
        (
            {"is_local_proxy_enabled": True, "is_overlay_proxy_enabled": True},
            True,
            True,
        ),
        ({"is_local_proxy_enabled": True}, False, False),
    ],
)
def test_the_device_is_wanted_for_the_hub_or_the_overlays_with_an_exit(
    routing, has_exit, is_wanted
):
    assert is_tun_wanted(routing, has_exit=has_exit) is is_wanted


def test_each_address_kept_out_is_a_host_route_ahead_of_the_halves():
    rendered = plan(kept_out=["203.0.113.10", "223.5.5.5", "198.51.100.4"])

    assert rendered.routes == (
        TunRoute("198.51.100.4/32", "en0", "192.168.1.1"),
        TunRoute("203.0.113.10/32", "en0", "192.168.1.1"),
        TunRoute("223.5.5.5/32", "en0", "192.168.1.1"),
        TunRoute("0.0.0.0/1", "utun225"),
        TunRoute(UPPER_HALF, "utun225"),
    )
    assert rendered.address == TUN_ADDRESS
    assert rendered.prefix_length == 30


def test_an_address_on_the_link_a_duplicate_or_a_name_gets_no_route():
    """The gateway and a neighbour are on the link already, and the
    connected route is longer than either half."""
    rendered = plan(
        kept_out=[
            "192.168.1.1",
            "192.168.1.77",
            "223.5.5.5",
            "223.5.5.5",
            "exit.example.net",
            "2001:db8::1",
            "127.0.0.1",
            "",
        ]
    )

    assert [route.destination for route in rendered.routes] == [
        "223.5.5.5/32",
        "0.0.0.0/1",
        UPPER_HALF,
    ]


def test_an_uplink_with_no_gateway_keeps_its_routes_on_the_interface():
    rendered = plan(gateway="", kept_out=["223.5.5.5"])

    assert rendered.routes[0] == TunRoute("223.5.5.5/32", "en0", "")
    assert darwin_route_command("add", rendered.routes[0]) == [
        "route",
        "-n",
        "add",
        "-host",
        "223.5.5.5",
        "-interface",
        "en0",
    ]


def test_a_plan_reads_back_what_it_wrote():
    rendered = plan(kept_out=["223.5.5.5"], forwarding_devices=["utun4", "utun4"])

    assert TunPlan.from_dict(rendered.to_dict()) == rendered
    assert rendered.forwarding_devices == ("utun4",)


def test_macos_addresses_the_utun_to_itself_and_routes_by_host_or_net():
    rendered = plan(kept_out=["223.5.5.5"])

    assert darwin_address_command(rendered) == [
        "ifconfig",
        "utun225",
        TUN_ADDRESS,
        TUN_ADDRESS,
        "mtu",
        "1500",
        "up",
    ]
    assert [darwin_route_command("add", route) for route in rendered.routes] == [
        ["route", "-n", "add", "-host", "223.5.5.5", "192.168.1.1"],
        ["route", "-n", "add", "-net", "0.0.0.0/1", "-interface", "utun225"],
        ["route", "-n", "add", "-net", UPPER_HALF, "-interface", "utun225"],
    ]
    assert darwin_route_command("delete", rendered.routes[-1])[2] == "delete"


def test_windows_names_the_next_hop_or_the_link():
    rendered = plan(
        device="neutrino_tun",
        uplink="Ethernet",
        gateway="192.168.1.1",
        kept_out=["223.5.5.5"],
    )

    assert [windows_route_document(route) for route in rendered.routes] == [
        {
            "prefix": "223.5.5.5/32",
            "alias": "Ethernet",
            "next_hop": "192.168.1.1",
            "metric": 1,
        },
        {
            "prefix": "0.0.0.0/1",
            "alias": "neutrino_tun",
            "next_hop": "0.0.0.0",
            "metric": 1,
        },
        {
            "prefix": UPPER_HALF,
            "alias": "neutrino_tun",
            "next_hop": "0.0.0.0",
            "metric": 1,
        },
    ]


def test_the_plan_keeps_the_uplink_gateway_for_the_scoped_default():
    rendered = plan(kept_out=["223.5.5.5"])

    scoped = darwin_scoped_default_route(rendered)

    assert rendered.gateway == "192.168.1.1"
    assert scoped == TunRoute("0.0.0.0/0", "en0", "192.168.1.1", is_scoped=True)
    assert darwin_route_command("add", scoped) == [
        "route",
        "-n",
        "add",
        "-ifscope",
        "en0",
        "-net",
        "0.0.0.0/0",
        "192.168.1.1",
    ]
    assert TunRoute.from_dict(scoped.to_dict()) == scoped
    assert darwin_scoped_default_route(plan(gateway="")) is None
