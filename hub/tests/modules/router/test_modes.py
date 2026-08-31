"""The four shapes a gateway is set up as, and what each writes.

What is checked here is that a mode is only ever a naming of roles the router
layer already had — a mode that needed a new firewall shape would be a mode
that quietly does not work, and server mode was nearly one of those.
"""

import pytest

from neutrino_hub.modules.router.modes import (
    ROUTER_MODES,
    ROUTER_MODE_SIDE_GATEWAY,
    ROUTER_MODE_ONE_ARM,
    ROUTER_MODE_ROUTER,
    ROUTER_MODE_SERVER,
    RouterModePlanner,
)
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer

from tests.conftest import without_comments


def test_router_mode_is_an_uplink_and_a_served_network():
    plan = RouterModePlanner(
        mode=ROUTER_MODE_ROUTER, wan_names=("enp2s0",), lan_names=("enp1s0",)
    ).plan()

    assert [interface.name for interface in plan.wan_interfaces] == ["enp2s0"]
    assert [interface.name for interface in plan.lan_interfaces] == ["enp1s0"]
    assert plan.lan_interfaces[0].lan.is_dhcp_enabled


def test_the_lease_pool_leaves_the_low_addresses_alone():
    """Somebody pins a printer by hand at .10 and expects it to stay theirs."""
    plan = RouterModePlanner(mode=ROUTER_MODE_ROUTER, lan_names=("e",)).plan()

    lan = plan.lan_interfaces[0].lan
    assert lan.dhcp_range_start == "192.168.8.100"
    assert lan.dhcp_range_end == "192.168.8.200"


def test_a_network_too_small_for_that_pool_uses_all_of_it():
    plan = RouterModePlanner(
        mode=ROUTER_MODE_ROUTER,
        lan_names=("e",),
        lan_address="10.0.0.1",
        lan_prefix_len=29,
    ).plan()

    lan = plan.lan_interfaces[0].lan
    assert lan.dhcp_range_start == "10.0.0.1"
    assert lan.dhcp_range_end == "10.0.0.6"


def test_one_arm_goes_out_untagged_and_serves_on_a_tag():
    """What arrives on the wire is untagged, so that is the way out.

    Tagging the uplink too would need the switch told about a second VLAN
    before the port could reach anything, which is a machine that looks
    configured and has no way out.
    """
    plan = RouterModePlanner(mode=ROUTER_MODE_ONE_ARM, trunk_name="enp1s0").plan()

    trunk, wan, lan = plan.interfaces
    assert trunk.role == "split" and trunk.vlan is None
    assert wan.is_untagged and wan.vlan.parent == "enp1s0"
    assert wan.device_name == "enp1s0", "untagged traffic is the trunk port's own"
    assert lan.vlan.parent == "enp1s0" and lan.vlan.id == 3
    assert lan.device_name == "enp1s0.3"


def test_a_side_gateway_serves_no_leases_and_names_the_real_router():
    """The network's own router keeps handing out leases; two would fight."""
    plan = RouterModePlanner(
        mode=ROUTER_MODE_SIDE_GATEWAY,
        lan_names=("enp1s0",),
        lan_address="192.168.1.50",
        upstream_gateway="192.168.1.1",
    ).plan()

    lan = plan.lan_interfaces[0].lan
    assert not lan.is_dhcp_enabled
    assert lan.upstream_gateway == "192.168.1.1"
    assert plan.side_gateway_lans


def test_server_mode_routes_nothing_but_stays_reachable():
    """The failure this guards: an input chain that drops the panel too."""
    plan = RouterModePlanner(
        mode=ROUTER_MODE_SERVER, lan_names=("enp1s0",), lan_address="10.0.0.5"
    ).plan()

    rendered = RouterNftRenderer(network=plan, routing={}, xray_uid=None).render()

    assert 'iifname { "enp1s0" } accept' in rendered
    assert "masquerade" not in without_comments(rendered)
    assert not plan.wan_interfaces


@pytest.mark.parametrize("mode", [mode.key for mode in ROUTER_MODES])
def test_every_mode_renders_a_ruleset(mode):
    """A mode nobody can render is a mode that fails after it is chosen."""
    plan = RouterModePlanner(
        mode=mode, wan_names=("enp2s0",), lan_names=("enp1s0",), trunk_name="enp1s0"
    ).plan()

    rendered = RouterNftRenderer(network=plan, routing={}, xray_uid=None).render()

    assert "chain input" in rendered
    assert "chain forward" in rendered
