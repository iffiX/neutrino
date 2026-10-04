"""NetBird's part of the overlay machinery, given through the edition table.

The overlay module, the router's pass, the proxy's TUN and the channel reach
NetBird's daemon and its stored settings through this one class, so a tree
without NetBird runs the same code with EasyTier alone.
"""

from neutrino_hub.modules.netbird.config import read_stored
from neutrino_hub.modules.netbird.ops import (
    NetbirdInboundGate,
    NetbirdRouteSelector,
    NetbirdStatusReader,
)
from neutrino_hub.modules.netbird.provisioner import NetbirdProvisioner
from neutrino_hub.modules.overlay.constants import OVERLAY_NETBIRD


class NetbirdOverlayPart:
    """What the rest of the hub asks of the hub's own NetBird.

    Attributes:
        provisioner: What installs the engine.
    """

    provisioner = NetbirdProvisioner

    def address(self) -> str:
        """The hub's address on the overlay, as the daemon reports it.

        Returns:
            The address, possibly with its prefix length; empty while none.
        """
        return str(NetbirdStatusReader().survey().netbird_ip or "")

    def name(self) -> str:
        """The hub's name on the overlay, as the daemon reports it.

        Returns:
            The ``fqdn``; empty while none.
        """
        return str(NetbirdStatusReader().survey().fqdn or "")

    def server_urls(self) -> list:
        """The management plane, signal server, relays and STUN servers.

        Returns:
            The URLs the daemon reports.
        """
        return list(NetbirdStatusReader().survey().server_urls)

    def peer_endpoints(self) -> list:
        """Every peer endpoint and relay the daemon reports.

        Returns:
            The endpoints, as written.
        """
        return list(NetbirdStatusReader().survey().peer_endpoints)

    def material(self) -> "dict | None":
        """What a client joins the overlay with.

        Returns:
            ``{provider, setup_key, management_url, fqdn, hub_address}``;
            None when no setup key is kept or the vault cannot unseal it.
        """
        config = read_stored()
        if not config.has_setup_key:
            return None
        try:
            setup_key = config.setup_key()
        except ValueError:
            return None
        survey = NetbirdStatusReader().survey()
        return {
            "provider": OVERLAY_NETBIRD,
            "setup_key": setup_key,
            "management_url": config.management_url,
            "fqdn": str(survey.fqdn or ""),
            "hub_address": str(survey.netbird_ip or "").split("/")[0],
        }

    def deselect(self, route: str) -> bool:
        """Tell the daemon to stop using one route.

        Args:
            route: The route's destination network.

        Returns:
            True when the daemon took it away.
        """
        return NetbirdRouteSelector().deselect(route)

    def gate(self, *, is_blocked: bool) -> str:
        """Make the daemon's own inbound setting agree with the exposure switch.

        Args:
            is_blocked: Whether the overlay's peers are kept out.

        Returns:
            What was changed, empty when the daemon already agreed.

        Raises:
            subprocess.CalledProcessError: When the daemon refuses.
        """
        return NetbirdInboundGate().converge(is_blocked=is_blocked)


# The part, by the overlay's key.
NETBIRD_OVERLAY_PART = (OVERLAY_NETBIRD, NetbirdOverlayPart)
