"""The networks a device's shares answer, derived from this hub's own fence."""

from neutrino_hub.modules.router.share_fence import allowed_subnets, share_subnets
from tests.conftest import lan_entry, network_config, wan_entry


def test_allowed_subnets_carries_exposed_networks_where_no_lan_has_a_role():
    assert allowed_subnets([], ["192.168.100.1/24"]) == ["192.168.100.0/24"]
    assert allowed_subnets(
        ["192.168.93.1/24"], ["192.168.100.1/24", "192.168.93.1/24", "", "bad"]
    ) == ["192.168.93.0/24", "192.168.100.0/24"]
    assert allowed_subnets([], [None, ""]) == []


def test_a_router_fences_its_shares_to_the_served_lan():
    network = network_config(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1", is_exposed=True),
    )

    subnets = share_subnets(
        network=network,
        link_addresses={"enp1s0": "192.168.100.1/24", "enp2s0": "10.0.0.5/24"},
        device_addresses={},
    )

    assert subnets == ["192.168.100.0/24"]


def test_an_exposed_overlay_is_allowed_where_the_firewall_already_lets_it_in():
    network = network_config(lan_entry("enp1s0", address="192.168.100.1"))

    subnets = share_subnets(
        network=network,
        link_addresses={"enp1s0": "192.168.100.1/24"},
        device_addresses={"wt0": "100.88.178.129/16"},
    )

    assert subnets == ["192.168.100.0/24", "100.88.0.0/16"]


def test_a_closed_overlay_stays_out_of_the_share_fence():
    network = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "netbird", "is_exposed": False}],
    )

    subnets = share_subnets(
        network=network,
        link_addresses={"enp1s0": "192.168.100.1/24"},
        device_addresses={"wt0": "100.88.178.129/16"},
    )

    assert subnets == ["192.168.100.0/24"]
