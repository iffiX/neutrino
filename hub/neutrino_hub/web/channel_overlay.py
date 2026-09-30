"""What a client needs to join the hub's overlay as an ordinary peer.

NetBird's material is the kept setup key, its management plane and the hub's
name on the overlay. EasyTier's follows its mode: in manual mode the network's
name, its secret and the address the hub's engine listens on; in console mode
the console's address and whether it runs in secure mode. Both EasyTier
shapes name the hub's own address on the overlay. The state frame and the
enrolment link carry the same object, ``None`` whenever there is nothing to
join with.
"""

from neutrino_hub.modules.easytier.constants import (
    EASYTIER_MODE_CONSOLE,
    EASYTIER_MODE_MANUAL,
    EASYTIER_PEER_PORT,
)
from neutrino_hub.modules.easytier.ops import EasyTierStatusReader
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.netbird.config import read_stored as read_netbird
from neutrino_hub.modules.netbird.ops import NetbirdStatusReader
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.modules.router.constants import ROUTER_ROLE_WAN
from neutrino_hub.modules.router.link_status import device_addresses


def overlay_materials(runtime) -> list:
    """The join material of every overlay this box runs.

    Args:
        runtime: The shared runtime, for the network configuration.

    Returns:
        One object per running overlay that has material, in the engine
        table's order: ``{provider, setup_key, management_url, fqdn}`` for
        NetBird; ``{provider, mode, network_name, network_secret, peer,
        hub_address}`` for EasyTier in manual mode and ``{provider, mode,
        config_server, is_secure_mode, hub_address}`` in console mode. An
        overlay is left out when NetBird has no kept key, EasyTier has no
        network, no address to dial or no console address, or the vault is
        locked.
    """
    materials = []
    for provider in enabled_providers(runtime.network()):
        if provider == OVERLAY_NETBIRD:
            material = _netbird_material()
        elif provider == OVERLAY_EASYTIER:
            material = _easytier_material(runtime)
        else:
            material = None
        if material is not None:
            materials.append(material)
    return materials


def overlay_material(runtime) -> "dict | None":
    """The join material of the preferred overlay this box runs.

    Args:
        runtime: The shared runtime, for the network configuration.

    Returns:
        The first of :func:`overlay_materials`, None when there is none.
    """
    materials = overlay_materials(runtime)
    return materials[0] if materials else None


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
    """What a client joins the hub's EasyTier network with in its mode, or None."""
    config = read_easytier()
    if not config.is_configured:
        return None
    if config.is_console_mode:
        try:
            config_server = config.config_server()
        except ValueError:
            return None
        instances = EasyTierStatusReader().instances()
        return {
            "provider": OVERLAY_EASYTIER,
            "mode": EASYTIER_MODE_CONSOLE,
            "config_server": config_server,
            "is_secure_mode": config.is_secure_mode,
            "hub_address": _host(instances[0].address) if instances else "",
        }
    host = easytier_join_host(runtime)
    if not host:
        return None
    try:
        secret = config.secret()
    except ValueError:
        return None
    return {
        "provider": OVERLAY_EASYTIER,
        "mode": EASYTIER_MODE_MANUAL,
        "network_name": config.network_name,
        "network_secret": secret,
        "peer": f"tcp://{host}:{EASYTIER_PEER_PORT}",
        "hub_address": _host(config.address),
    }


def _host(address: str) -> str:
    """An address without its prefix length."""
    return address.split("/")[0]
