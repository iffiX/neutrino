"""Which overlay a router configuration names, and changing it.

The row in ``config/router/network.json`` is the whole record, so these pin
what reading and writing it mean: one member at a time, the exposure switch
survives a change of engine, and a configuration written before any of this
existed still says what the firewall used to do.
"""

import pytest

from neutrino_hub.modules.overlay.config import provider_of, set_provider
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_NETBIRD,
    OVERLAY_NONE,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig


def config(overlays) -> RouterNetworkConfig:
    """A router configuration carrying exactly these overlay entries."""
    return RouterNetworkConfig.from_dict({"mode": "router", "overlays": overlays})


def test_no_row_is_no_overlay():
    assert provider_of(config([])) == OVERLAY_NONE


def test_the_row_names_the_overlay():
    assert provider_of(config([{"provider": OVERLAY_NETBIRD}])) == OVERLAY_NETBIRD


def test_a_configuration_older_than_overlays_keeps_what_the_firewall_did():
    network = RouterNetworkConfig.from_dict({"mode": "router"})

    assert provider_of(network) == OVERLAY_NETBIRD
    assert network.overlays[0].is_exposed


def test_choosing_an_overlay_writes_one_row():
    network = config([])

    assert set_provider(network, OVERLAY_NETBIRD)
    assert [overlay.provider for overlay in network.overlays] == [OVERLAY_NETBIRD]


def test_choosing_none_takes_the_row_away():
    network = config([{"provider": OVERLAY_NETBIRD}])

    assert set_provider(network, OVERLAY_NONE)
    assert network.overlays == []


def test_a_row_keeps_its_own_exposure_when_the_others_go():
    network = config(
        [
            {"provider": OVERLAY_NETBIRD, "is_exposed": True},
            {"provider": OVERLAY_EASYTIER, "is_exposed": False},
        ]
    )

    set_provider(network, OVERLAY_EASYTIER)

    assert network.overlays[0].is_exposed is False


def test_an_engine_does_not_inherit_the_one_it_replaced():
    network = config([{"provider": OVERLAY_NETBIRD, "is_exposed": False}])

    set_provider(network, OVERLAY_EASYTIER)

    assert network.overlays[0].is_exposed is True


def test_choosing_what_is_already_stored_changes_nothing():
    network = config([{"provider": OVERLAY_NETBIRD}])

    assert set_provider(network, OVERLAY_NETBIRD) is False


def test_two_rows_are_reduced_to_the_one_chosen():
    network = config([{"provider": OVERLAY_NETBIRD}, {"provider": OVERLAY_EASYTIER}])

    assert set_provider(network, OVERLAY_EASYTIER)
    assert [overlay.provider for overlay in network.overlays] == [OVERLAY_EASYTIER]


def test_an_overlay_nobody_runs_is_refused():
    with pytest.raises(ValueError):
        set_provider(config([]), "tailscale")
