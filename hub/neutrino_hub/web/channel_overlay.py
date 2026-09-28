"""What a client needs to join the hub's overlay as an ordinary peer.

NetBird's material is the kept setup key, its management plane and the hub's
name on the overlay; EasyTier's is the network's name, its secret and the
address the hub's engine listens on. The state frame and the enrolment link
carry the same object, ``None`` whenever there is nothing to join with.
"""

from neutrino_hub.modules.easytier.constants import EASYTIER_PEER_PORT
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.netbird.config import read_stored as read_netbird
from neutrino_hub.modules.netbird.ops import NetbirdStatusReader
from neutrino_hub.modules.overlay.config import provider_of
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.modules.router.constants import ROUTER_ROLE_WAN
from neutrino_hub.modules.router.link_status import device_addresses


def overlay_material(runtime) -> "dict | None":
    """The join material of the overlay this box runs.

    Args:
        runtime: The shared runtime, for the network configuration.

    Returns:
        ``{provider, setup_key, management_url, fqdn}`` for NetBird,
        ``{provider, network_name, network_secret, peer}`` for EasyTier;
        None when no overlay runs, NetBird has no kept key, EasyTier has no
        network or no address to dial, or the vault is locked.
    """
    network = runtime.network()
    provider = provider_of(network)
    if provider == OVERLAY_NETBIRD:
        return _netbird_material()
    if provider == OVERLAY_EASYTIER:
        return _easytier_material(runtime)
    return None


def easytier_join_host(runtime) -> str:
    """What another machine dials to reach this box's EasyTier engine.

    Args:
        runtime: The shared runtime.

    Returns:
        An address of this box, the uplink's first. Empty when this box
        holds no address outside its overlays.
    """
    addresses = device_addresses()
    network = runtime.network()
    overlays = set(network.overlay_device_names)
    uplinks = [
        interface.name
        for interface in network.interfaces
        if interface.role == ROUTER_ROLE_WAN
    ]
    for name in uplinks + sorted(addresses):
        if name in overlays or name not in addresses:
            continue
        return addresses[name].split("/")[0]
    return ""


def _netbird_material() -> "dict | None":
    """The kept setup key and the hub's overlay name, or None."""
    config = read_netbird()
    if not config.has_setup_key:
        return None
    try:
        setup_key = config.setup_key()
    except ValueError:
        return None
    return {
        "provider": OVERLAY_NETBIRD,
        "setup_key": setup_key,
        "management_url": config.management_url,
        "fqdn": str(NetbirdStatusReader().survey().fqdn or ""),
    }


def _easytier_material(runtime) -> "dict | None":
    """The network's name, its secret and the hub's engine address, or None."""
    config = read_easytier()
    if not config.is_configured:
        return None
    host = easytier_join_host(runtime)
    if not host:
        return None
    try:
        secret = config.secret()
    except ValueError:
        return None
    return {
        "provider": OVERLAY_EASYTIER,
        "network_name": config.network_name,
        "network_secret": secret,
        "peer": f"tcp://{host}:{EASYTIER_PEER_PORT}",
    }
