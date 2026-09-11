"""Fixed values of the overlay module."""

from dataclasses import dataclass

from neutrino_hub.modules.netbird.constants import NETBIRD_UNIT

# What a machine may be reachable through from outside the building. One at a
# time: two overlays would each hand the box an address, a route to the served
# networks and a peer list, and nothing on the box says which of them a name
# resolves through.
OVERLAY_NONE = "none"
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
        device_name: The kernel interface it brings up, which the firewall
            rules name.
        peer_port: The UDP port its own peers knock on.
        unit: The systemd unit the hub drives it under.
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
    is_integrated: bool


OVERLAY_ENGINES = {
    OVERLAY_NETBIRD: OverlayEngine(
        key=OVERLAY_NETBIRD,
        title="NetBird",
        device_name="wt0",
        peer_port=51820,
        unit=NETBIRD_UNIT,
        is_integrated=True,
    ),
    OVERLAY_EASYTIER: OverlayEngine(
        key=OVERLAY_EASYTIER,
        title="EasyTier",
        device_name="easytier",
        peer_port=11010,
        unit=OVERLAY_EASYTIER_UNIT,
        is_integrated=True,
    ),
}

# None first: it is the answer for a machine nobody reaches from outside, and
# the order is the order the page draws.
OVERLAY_PROVIDERS = (OVERLAY_NONE,) + tuple(OVERLAY_ENGINES)
