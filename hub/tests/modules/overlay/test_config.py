"""Which overlays a router configuration runs, and turning one on or off.

The rows in ``config/router/network.json`` are the whole record, so these pin
what reading and writing them mean: any set of engines at once, the exposure
switch survives an engine going off and on again, and the 0.4.0 shape, one
row naming one provider, reads as that one on and the others off.
"""

import pytest

from neutrino_hub.modules.overlay.config import enabled_providers, set_enabled
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig


def config(overlays) -> RouterNetworkConfig:
    """A router configuration carrying exactly these overlay entries."""
    return RouterNetworkConfig.from_dict({"mode": "router", "overlays": overlays})


def test_no_row_runs_no_overlay():
    assert enabled_providers(config([])) == []


def test_the_0_4_shape_reads_as_that_one_on_and_the_others_off():
    network = config([{"provider": OVERLAY_EASYTIER, "is_exposed": True}])

    assert enabled_providers(network) == [OVERLAY_EASYTIER]


@pytest.mark.feature("netbird")
def test_the_0_4_shape_is_written_back_in_the_new_one():
    network = config([{"provider": OVERLAY_NETBIRD}])

    assert network.to_dict()["overlays"] == [
        {"provider": OVERLAY_NETBIRD, "is_enabled": True, "is_exposed": True}
    ]


@pytest.mark.feature("netbird")
def test_a_configuration_older_than_overlays_keeps_what_the_firewall_did():
    network = RouterNetworkConfig.from_dict({"mode": "router"})

    assert enabled_providers(network) == [OVERLAY_NETBIRD]
    assert network.overlays[0].is_exposed


@pytest.mark.feature("netbird")
def test_both_engines_run_at_once_in_the_engine_order():
    network = config(
        [
            {"provider": OVERLAY_EASYTIER, "is_enabled": True},
            {"provider": OVERLAY_NETBIRD, "is_enabled": True},
        ]
    )

    assert enabled_providers(network) == [OVERLAY_NETBIRD, OVERLAY_EASYTIER]


def test_turning_an_engine_on_adds_an_open_row():
    network = config([])

    assert set_enabled(network, OVERLAY_EASYTIER, is_enabled=True)
    assert network.overlays[0].provider == OVERLAY_EASYTIER
    assert network.overlays[0].is_exposed is True


@pytest.mark.feature("netbird")
def test_a_second_engine_joins_the_first_in_the_engine_order():
    network = config([{"provider": OVERLAY_EASYTIER}])

    set_enabled(network, OVERLAY_NETBIRD, is_enabled=True)

    assert [overlay.provider for overlay in network.overlays] == [
        OVERLAY_NETBIRD,
        OVERLAY_EASYTIER,
    ]
    assert enabled_providers(network) == [OVERLAY_NETBIRD, OVERLAY_EASYTIER]


@pytest.mark.feature("netbird")
def test_turning_an_engine_off_keeps_its_row_and_its_exposure():
    network = config([{"provider": OVERLAY_NETBIRD, "is_exposed": False}])

    assert set_enabled(network, OVERLAY_NETBIRD, is_enabled=False)
    assert network.overlays[0].is_enabled is False
    assert network.overlays[0].is_exposed is False

    set_enabled(network, OVERLAY_NETBIRD, is_enabled=True)

    assert network.overlays[0].is_exposed is False


def test_an_engine_that_is_off_takes_no_device_and_no_port():
    network = config(
        [
            {"provider": OVERLAY_NETBIRD, "is_enabled": False},
            {"provider": OVERLAY_EASYTIER, "is_enabled": True},
        ]
    )

    assert network.exposed_overlay_device_names == ["easytier"]
    assert network.exposed_overlay_peer_ports == [11010]
    assert network.overlay(OVERLAY_NETBIRD) is None


@pytest.mark.feature("netbird")
def test_setting_what_is_already_stored_changes_nothing():
    network = config([{"provider": OVERLAY_NETBIRD}])

    assert set_enabled(network, OVERLAY_NETBIRD, is_enabled=True) is False
    assert set_enabled(network, OVERLAY_EASYTIER, is_enabled=False) is False
    assert len(network.overlays) == 1


def test_an_overlay_nobody_runs_is_refused():
    with pytest.raises(ValueError):
        set_enabled(config([]), "tailscale", is_enabled=True)
