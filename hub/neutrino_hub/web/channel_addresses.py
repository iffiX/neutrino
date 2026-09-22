"""Every address the hub answers the channel on.

The set is the firewall's: every exposed interface, whatever its role, and
every exposed overlay, plus the overlay's own name where its daemon reports
one. An enrolment link carries it, both state documents carry it under
their hash, and the address sampler pushes both when it changes.
"""

from fastapi import HTTPException, status

from neutrino_hub.modules.netbird.ops import NetbirdStatusReader
from neutrino_hub.modules.router.constants import ROUTER_OVERLAY_NETBIRD
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.web.agent_tls import certificate_fingerprint
from neutrino_hub.web.constants import WEB_DEFAULT_AGENT_LISTEN_PORT


def channel_urls(runtime) -> list[str]:
    """Every address a machine can be told to reach the agent channel on.

    A served network contributes its configured address, every other exposed
    interface the address its live link holds, and an exposed NetBird
    overlay its name as well, so a peer on the overlay reaches the hub after
    its overlay address moved.

    Args:
        runtime: The shared runtime, for the network configuration and the
            port.

    Returns:
        Base ``https`` URLs, in configuration order, one per address, the
        overlay's name last.
    """
    port = runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
    network = runtime.network()
    configured = {
        interface.device_name: interface.lan.address
        for interface in network.lan_interfaces
        if interface.lan.address
    }
    live = None
    hosts = []
    for name in network.exposed_interfaces:
        address = configured.get(name, "")
        if not address:
            if live is None:
                live = device_addresses()
            address = live.get(name, "").split("/")[0]
        if address and address not in hosts:
            hosts.append(address)
    name = overlay_name(network)
    if name and name not in hosts:
        hosts.append(name)
    return [f"https://{host}:{port}" for host in hosts]


def overlay_name(network) -> str:
    """The name the box answers to on its exposed NetBird overlay.

    Args:
        network: The router configuration.

    Returns:
        The ``fqdn`` the daemon reports, empty when the overlay is not
        exposed, not running, or has no name.
    """
    overlay = network.overlay(ROUTER_OVERLAY_NETBIRD)
    if overlay is None or not overlay.is_exposed:
        return ""
    return str(NetbirdStatusReader().survey().fqdn or "")


def enrollment_link_parts(runtime) -> tuple[list, str]:
    """What every enrollment link carries besides its ticket.

    Args:
        runtime: The shared runtime.

    Returns:
        The agent channel's URLs and the certificate fingerprint.

    Raises:
        HTTPException: 400 when no served network has an address, so there is
            nothing for a machine to reach the panel at; 409 with
            ``{"code": "agent_tls_missing"}`` when the channel has no
            certificate to pin.
    """
    urls = channel_urls(runtime)
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "no_reachable_address", "params": {}},
        )
    try:
        fingerprint = certificate_fingerprint()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_tls_missing", "params": {}},
        ) from error
    return urls, fingerprint
