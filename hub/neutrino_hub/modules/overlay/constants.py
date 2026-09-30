"""Fixed values of the overlay module."""

from dataclasses import dataclass

from neutrino_hub.modules.netbird.constants import NETBIRD_UNIT

# What a machine may be reachable through from outside the building. Any of
# them, all at once or none; the engine table's order is the order the panel
# draws them and the order a client is handed their material in.
OVERLAY_NETBIRD = "netbird"
OVERLAY_EASYTIER = "easytier"

# The unit the EasyTier engine becomes, named here because the overlay module
# owns the table; the module that drives it reads the name from here.
OVERLAY_EASYTIER_UNIT = "neutrino_hub_easytier.service"


@dataclass(frozen=True)
class OverlayEngine:
    """One overlay implementation this hub can run.

    Attributes:
        key: What the configuration stores.
        title: The product's own name, which is the same in every language.
        device_name: The kernel interface the hub names for it, which the
            firewall rules name. EasyTier in console mode picks its own, and
            that one is found at run time by the address it holds.
        peer_port: The UDP port its own peers knock on.
        unit: The systemd unit the hub drives it under.
        subnet: The network its addresses come from when the product fixes
            one; empty when the network is configured or found at run time.
        is_integrated: Whether this hub can actually run it yet. An engine
            that is named but not integrated is offered and refused, rather
            than hidden: the choice is what the page is about, and a missing
            third option reads as a hub that cannot have one.
    """

    key: str
    title: str
    device_name: str
    peer_port: int
    unit: str
    subnet: str
    is_integrated: bool


OVERLAY_ENGINES = {
    OVERLAY_NETBIRD: OverlayEngine(
        key=OVERLAY_NETBIRD,
        title="NetBird",
        device_name="wt0",
        peer_port=51820,
        unit=NETBIRD_UNIT,
        subnet="100.64.0.0/10",
        is_integrated=True,
    ),
    OVERLAY_EASYTIER: OverlayEngine(
        key=OVERLAY_EASYTIER,
        title="EasyTier",
        device_name="easytier",
        peer_port=11010,
        unit=OVERLAY_EASYTIER_UNIT,
        subnet="",
        is_integrated=True,
    ),
}

# How long an engine just started is given to hold an address before the
# converge step goes on without it.
OVERLAY_ADDRESS_WAIT_S = 20.0
OVERLAY_ADDRESS_POLL_S = 0.5

# A route an overlay installs for every address. The hub's way out is its own
# uplink, so such a route is deleted wherever it appears.
OVERLAY_DEFAULT_ROUTE = "0.0.0.0/0"
