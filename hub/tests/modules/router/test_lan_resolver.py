"""What a served interface tells the box to resolve with.

A manual address takes no resolver from anywhere, so a gateway set up as a
server or a side gateway came up with an address, a route and nothing to ask
a name of. It showed on every VM in the lab except Arch, whose resolver
happens to ship compiled-in fallback servers.
"""

from neutrino_hub.modules.router.interfaces import (
    RouterInterface,
    RouterLanSettings,
    RouterNetworkConfig,
)
from neutrino_hub.modules.router import routes


def test_a_served_interface_points_the_box_at_its_own_dnsmasq(monkeypatch):
    written = {}
    _stub_network_manager(monkeypatch, written)

    routes.RouterInterfaceApplier(network=_served("192.168.8.1")).apply_all()

    assert written["ipv4.dns"] == "192.168.8.1"
    assert written["ipv4.ignore-auto-dns"] == "yes"


def test_the_resolver_follows_the_address_rather_than_a_default(monkeypatch):
    written = {}
    _stub_network_manager(monkeypatch, written)

    routes.RouterInterfaceApplier(network=_served("10.9.0.1")).apply_all()

    assert written["ipv4.dns"] == "10.9.0.1"


def test_it_is_taken_in_place_rather_than_by_dropping_the_link():
    """Reactivating a LAN drops the panel session that asked for the change,
    so a resolver edit must not be one of the properties that does."""
    assert "ipv4.dns" not in routes.REACTIVATION_PROPERTIES


def _served(address: str) -> RouterNetworkConfig:
    return RouterNetworkConfig(
        interfaces=[
            RouterInterface(
                name="eth0",
                role="lan",
                lan=RouterLanSettings(
                    address=address, prefix_len=24, is_dhcp_enabled=False
                ),
            )
        ]
    )


def _stub_network_manager(monkeypatch, written: dict):
    """Every nmcli call replaced, keeping what would have been written."""
    monkeypatch.setattr(routes.network_manager, "device_kinds", dict)
    monkeypatch.setattr(
        routes.network_manager, "differing_properties", lambda *_: set()
    )
    monkeypatch.setattr(
        routes.network_manager, "connection_for_device", lambda name: None
    )
    monkeypatch.setattr(
        routes.network_manager,
        "modify",
        lambda connection, settings: written.update(settings),
    )
    monkeypatch.setattr(routes.network_manager, "activate", lambda *_: None)
    monkeypatch.setattr(routes.network_manager, "reapply_device", lambda *_, **__: None)
    monkeypatch.setattr(routes.network_manager, "connection_exists", lambda name: True)
    monkeypatch.setattr(routes.RouterDefaultRouteApplier, "apply", lambda self: [])
