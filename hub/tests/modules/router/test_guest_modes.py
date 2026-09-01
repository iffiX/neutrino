"""A machine the hub is a guest on keeps its own addresses.

Two of the four modes are somebody else's machine — a VPS, a laptop — where
the panel answers on the address a port already has. The mode is what says
so, and a machine is wholly one kind or the other: there is no half-managed
state, because sharing an interface with another manager is where every bug
in this area has come from.
"""

import pytest

from neutrino_hub.modules.router import routes
from neutrino_hub.modules.router.interfaces import (
    RouterInterface,
    RouterLanSettings,
    RouterNetworkConfig,
)
from neutrino_hub.modules.router.modes import (
    ROUTER_LAYOUT_ONE_ARM,
    ROUTER_MODE_ROUTER,
    ROUTER_MODE_SERVER,
    ROUTER_MODE_SIDE_GATEWAY,
    RouterModePlanner,
)

GUEST_MODES = (ROUTER_MODE_SERVER, ROUTER_MODE_SIDE_GATEWAY)
OWNER_MODES = (ROUTER_MODE_ROUTER, ROUTER_LAYOUT_ONE_ARM)

# Every way the applier can reach the machine, so that "it did nothing" is a
# claim about the whole surface rather than about the parts one test knows.
APPLIER_DRIVERS = (
    "add_vlan",
    "clear_addresses",
    "remove_vlan",
    "set_address",
    "set_default_route",
    "set_down",
    "set_mac",
    "set_up",
)


@pytest.mark.parametrize("mode", GUEST_MODES)
def test_a_guest_mode_addresses_nothing(mode):
    network = _planned(mode)

    assert network.interfaces
    assert not network.is_addressing_owned


@pytest.mark.parametrize("mode", OWNER_MODES)
def test_an_owner_mode_addresses_the_machine(mode):
    network = _planned(mode)

    assert network.interfaces
    assert network.is_addressing_owned


@pytest.mark.parametrize("mode", GUEST_MODES + OWNER_MODES)
def test_the_mode_survives_a_round_trip(mode):
    network = _planned(mode)

    assert RouterNetworkConfig.from_dict(network.to_dict()).mode == network.mode


def test_a_router_on_one_wire_is_stored_as_a_router():
    """One trunk going out untagged and serving on a tag is a wiring, not a
    mode. Two names for one mode is two things to keep in step."""
    assert _planned(ROUTER_LAYOUT_ONE_ARM).mode == ROUTER_MODE_ROUTER


def test_applying_an_unaddressed_interface_calls_nothing(monkeypatch):
    """Not "writes the same values": a machine somebody else configured is one
    no property is read from and no connection is brought up on."""
    calls = _record_calls(monkeypatch)
    network = _one_lan(mode=ROUTER_MODE_SERVER)

    changes = routes.RouterInterfaceApplier(network=network).apply_all()

    assert changes == []
    assert calls == []


def test_applying_an_addressed_interface_still_writes(monkeypatch):
    calls = _record_calls(monkeypatch)
    network = _one_lan(mode=ROUTER_MODE_ROUTER)

    routes.RouterInterfaceApplier(network=network).apply_all()

    assert "set_address" in calls


def test_a_port_appearing_later_answers_to_the_box_it_appeared_on():
    """A machine is wholly a guest or wholly an owner, so a port nobody has
    configured yet is whatever the machine is."""
    network = _planned(ROUTER_MODE_SERVER)
    network.replace(network.interface_or_new("eth9"))

    assert not network.is_addressing_owned


def _planned(mode: str) -> RouterNetworkConfig:
    """One mode's configuration, given ports it can actually use."""
    return RouterModePlanner(
        mode=mode,
        port_names=("eth0", "eth1"),
        wan_names=("eth0",),
        lan_names=("eth1",),
        trunk_name="eth1",
        lan_address="192.168.8.1",
        upstream_gateway="192.168.1.1",
    ).plan()


def _one_lan(*, mode: str) -> RouterNetworkConfig:
    return RouterNetworkConfig(
        mode=mode,
        interfaces=[
            RouterInterface(
                name="eth0",
                role="lan",
                lan=RouterLanSettings(
                    address="10.0.0.5", prefix_len=24, is_dhcp_enabled=False
                ),
            )
        ],
    )


def _record_calls(monkeypatch) -> list:
    """Replace every route to the machine with one that notes it was taken.

    Returns:
        The list the names land in, in the order they are called.
    """
    calls: list = []

    def answer(name: str):
        def recorded(*arguments, **keywords):
            calls.append(name)
            return True

        return recorded

    for name in APPLIER_DRIVERS:
        monkeypatch.setattr(routes.links, name, answer(name))
    monkeypatch.setattr(routes.links, "addresses_on", lambda name: [])
    monkeypatch.setattr(routes.links, "exists", lambda name: True)
    monkeypatch.setattr(routes.links, "carried_state", lambda devices: {})
    monkeypatch.setattr(routes.stack, "running_managers", lambda: ["networkd"])
    monkeypatch.setattr(routes.links, "restore_state", answer("restore_state"))
    for driver, method in (
        (routes.RouterDhcpClient, "stop"),
        (routes.RouterDhcpClient, "start"),
        (routes.RouterDhcpClient, "restart"),
    ):
        monkeypatch.setattr(driver, method, answer(f"dhcp.{method}"))
    monkeypatch.setattr(
        routes.RouterDhcpClient, "is_running", property(lambda self: False)
    )
    monkeypatch.setattr(routes.resolver, "point_at", answer("resolver"))

    # A list, because the applier adds what it returns to its own changes.
    def stood_down(interfaces=()):
        calls.append("stand_down")
        return []

    monkeypatch.setattr(routes.stack, "stand_down", stood_down)
    monkeypatch.setattr(routes.RouterDefaultRouteApplier, "apply", lambda self: [])
    monkeypatch.setattr(
        routes.RouterLinkStatus, "all_links", lambda self: [_wired("eth0")]
    )
    return calls


def _wired(name: str):
    """One ethernet link, as the reader would report it."""
    from neutrino_hub.modules.router.link_status import LinkStatus

    return LinkStatus(name=name, kind="ethernet", is_present=True, is_up=True)


def test_an_uplink_is_rendered_before_its_client_is_started(monkeypatch, tmp_path):
    """The unit reads its configuration at exec. A client started before
    anything wrote one exits saying so and is restarted into the same nothing,
    which is an uplink that never gets an address at all."""
    order: list = []
    # After the general stubs, which also stand in for the client.
    _record_calls(monkeypatch)
    monkeypatch.setattr(
        routes, "_write_dhcp_config", lambda device, metric: order.append("render")
    )
    monkeypatch.setattr(
        routes.RouterDhcpClient, "start", lambda self: order.append("start")
    )
    network = RouterNetworkConfig(interfaces=[RouterInterface(name="eth0", role="wan")])

    routes.RouterInterfaceApplier(network=network).apply_all()

    assert order == ["render", "start"]


def test_applying_again_does_not_hand_the_machine_over_twice(monkeypatch):
    """`neutrino_hub_router.service` applies on every boot and every restart.
    Redoing the handover each time takes the addresses off and puts them back
    for no reason, with whoever is connected over one of them in the gap."""
    calls = _record_calls(monkeypatch)
    # Nothing left running, which is what a machine already handed over looks
    # like from the second apply onwards.
    monkeypatch.setattr(routes.stack, "running_managers", list)
    network = _one_lan(mode=ROUTER_MODE_ROUTER)

    routes.RouterInterfaceApplier(network=network).apply_all()

    assert "stand_down" not in calls
    assert "restore_state" not in calls


def test_a_port_that_stops_being_an_uplink_stops_taking_leases(monkeypatch):
    """A round trip through the WAN role and back is the ordinary way somebody
    tries a port out. Left behind, the lease client keeps asking on a network
    that serves its own addresses, and puts whatever it is given — or invents
    — on a port the gateway is meant to be the router of."""
    calls = _record_calls(monkeypatch)
    stopped: list = []
    monkeypatch.setattr(
        routes.RouterDhcpClient, "stop", lambda self: stopped.append(self.unit)
    )
    network = _one_lan(mode=ROUTER_MODE_ROUTER)

    routes.RouterInterfaceApplier(network=network).apply(network.interfaces[0])

    assert stopped == ["neutrino_hub_dhcpcd@eth0.service"]
    assert "dhcp.start" not in calls
