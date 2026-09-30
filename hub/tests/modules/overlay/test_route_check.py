"""Whether two overlays, or an overlay and the box's own networks, collide.

Two engines at once each bring an address range and the routes their peers
publish, and neither knows about the other or about the LAN. What is pinned
here is which collisions the hub refuses: an overlay's own network landing on
another network before it is turned on, a default route wherever it appears,
and a learned route that overlaps a network of the box or of the other
overlay.
"""

from neutrino_hub.modules.overlay.route_check import (
    OverlayRouteConflict,
    OverlaySubnetOverlap,
    find_route_conflicts,
    find_subnet_overlap,
)

LAN = "192.168.100.0/24"
NETBIRD = ["100.64.0.0/10"]


def test_networks_apart_are_accepted():
    assert (
        find_subnet_overlap({"netbird": NETBIRD, "easytier": ["10.0.0.0/24"]}, [LAN])
        is None
    )


def test_an_overlay_on_the_lan_is_named_with_the_lan():
    overlap = find_subnet_overlap({"easytier": ["192.168.100.0/25"]}, [LAN])

    assert overlap == OverlaySubnetOverlap(
        provider="easytier", subnet="192.168.100.0/25", conflict=LAN
    )


def test_two_overlays_on_one_network_are_named():
    overlap = find_subnet_overlap(
        {"netbird": NETBIRD, "easytier": ["100.100.0.0/16"]}, [LAN]
    )

    assert overlap == OverlaySubnetOverlap(
        provider="netbird", subnet="100.64.0.0/10", conflict="100.100.0.0/16"
    )


def test_an_overlay_with_no_known_network_overlaps_nothing():
    assert find_subnet_overlap({"easytier": []}, [LAN]) is None


def test_a_default_route_is_refused_on_any_overlay():
    conflicts = find_route_conflicts(
        {"netbird": ["0.0.0.0/0"]}, {"netbird": NETBIRD}, [LAN]
    )

    assert conflicts == [
        OverlayRouteConflict(provider="netbird", route="0.0.0.0/0", conflict="")
    ]
    assert conflicts[0].is_default


def test_a_learned_route_onto_the_lan_is_refused():
    conflicts = find_route_conflicts(
        {"easytier": ["192.168.100.0/24", "10.20.0.0/24"]},
        {"easytier": ["10.0.0.0/24"]},
        [LAN],
    )

    assert conflicts == [
        OverlayRouteConflict(provider="easytier", route=LAN, conflict=LAN)
    ]


def test_a_learned_route_onto_the_other_overlay_is_refused():
    conflicts = find_route_conflicts(
        {"easytier": ["100.64.5.0/24"]},
        {"netbird": NETBIRD, "easytier": ["10.0.0.0/24"]},
        [LAN],
    )

    assert conflicts[0].conflict == "100.64.0.0/10"


def test_an_overlays_route_to_its_own_network_is_its_own():
    assert (
        find_route_conflicts(
            {"netbird": ["100.64.0.0/16"]}, {"netbird": NETBIRD}, [LAN]
        )
        == []
    )
