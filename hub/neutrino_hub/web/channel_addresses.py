"""Every address the hub answers the channel on.

The set is the firewall's: every exposed interface, whatever its role, and
every exposed overlay, plus the overlay's own name where its daemon reports
one. An enrolment link carries it, both state documents carry it under
their hash, and the address sampler pushes both when it changes.
"""

from fastapi import HTTPException, status

from neutrino_hub.modules.overlay.ops import overlay_parts
from neutrino_hub.modules.overlay.direct_config import (
    OverlayDirectConfig,
    read_direct,
)
from neutrino_hub.modules.overlay.relay_config import read_relay
from neutrino_hub.modules.overlay.relay_ops import is_relay_configured
from neutrino_hub.modules.router.constants import ROUTER_OVERLAY_NETBIRD
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.web.agent_tls import certificate_fingerprint
from neutrino_hub.web.constants import (
    WEB_AGENT_LOOPBACK_HOST,
    WEB_DEFAULT_AGENT_LISTEN_PORT,
)


def channel_urls(runtime) -> list[str]:
    """Every address a machine can be told to reach the agent channel on.

    Args:
        runtime: The shared runtime, for the network configuration and the
            port.

    Returns:
        Base ``https`` URLs: one per host :func:`channel_hosts` returns, in
        its order, every enabled interface's among them while Direct is on;
        then the public address the person stated for Direct, while it is on;
        and last the relay's address while it is on and configured.
    """
    port = runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
    direct = _stored_direct()
    hosts = channel_hosts(runtime.network(), is_direct=direct.is_enabled)
    urls = [f"https://{host}:{port}" for host in hosts]
    for added in (direct.public_url if direct.is_enabled else "", relay_url()):
        if added and added not in urls:
            urls.append(added)
    return urls


def _stored_direct() -> OverlayDirectConfig:
    """The stored Direct settings; a file that does not read is Direct off."""
    try:
        return read_direct()
    except ValueError:
        return OverlayDirectConfig()


def own_agent_urls(runtime) -> list[str]:
    """The addresses the hub's own agent is given: loopback first.

    The agent on the hub's machine reaches the agent port over loopback
    whatever is exposed, so its list holds loopback even when nothing is.

    Args:
        runtime: The shared runtime, for the network configuration and the
            port.

    Returns:
        ``https://127.0.0.1:<agent port>``, then :func:`channel_urls`.
    """
    port = runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
    loopback = f"https://{WEB_AGENT_LOOPBACK_HOST}:{port}"
    return [loopback, *(url for url in channel_urls(runtime) if url != loopback)]


def relay_url() -> str:
    """The relay's address while it is on and configured.

    Returns:
        ``https://<host>:<public-port>``, an IPv6 host in brackets; empty
        while the relay is off or names no host, account or key.
    """
    try:
        config = read_relay()
    except ValueError:
        return ""
    if not config.is_enabled or not is_relay_configured(config):
        return ""
    return config.url


def channel_hosts(network, *, is_direct: bool = False) -> list[str]:
    """Every address and name the box answers on.

    A served network contributes its configured address, every other exposed
    interface the address its live link holds, an interface the configuration
    does not name counting as :meth:`RouterNetworkConfig.exposed_device_names_on`
    reads it, and an exposed NetBird
    overlay its name as well, so a peer on the overlay reaches the hub after
    its overlay address moved. While Direct is on, every enabled interface
    that is not exposed follows the exposed ones: the agent port answers
    there, and nothing else of the box.

    Args:
        network: The router configuration.
        is_direct: Whether Direct is on.

    Returns:
        The hosts, in configuration order, the overlay's name last.
    """
    configured = {
        interface.device_name: interface.lan.address
        for interface in network.lan_interfaces
        if interface.lan.address
    }
    live = device_addresses()
    hosts = []
    names = network.exposed_device_names_on(list(live))
    names += [
        name for name in network.exposed_overlay_device_names if name not in names
    ]
    if is_direct:
        names += [name for name in network.enabled_device_names if name not in names]
    for name in names:
        address = configured.get(name, "") or live.get(name, "").split("/")[0]
        if address and address not in hosts:
            hosts.append(address)
    name = overlay_name(network)
    if name and name not in hosts:
        hosts.append(name)
    return hosts


def overlay_name(network) -> str:
    """The name the box answers to on its exposed NetBird overlay.

    Args:
        network: The router configuration.

    Returns:
        The ``fqdn`` the daemon reports, empty when the overlay is not
        exposed, not running, or has no name.
    """
    overlay = network.overlay(ROUTER_OVERLAY_NETBIRD)
    part = overlay_parts().get(ROUTER_OVERLAY_NETBIRD)
    if overlay is None or not overlay.is_exposed or part is None:
        return ""
    return part().name()


def enrollment_link_parts(runtime, *, is_hub: bool = False) -> tuple[list, str]:
    """What every enrollment link carries besides its ticket.

    Args:
        runtime: The shared runtime.
        is_hub: Whether the link is for the agent on the hub's own machine,
            which is given loopback first and is never refused for want of
            an exposed address.

    Returns:
        The agent channel's URLs and the certificate fingerprint.

    Raises:
        HTTPException: 400 when no served network has an address, so there is
            nothing for a machine to reach the panel at; 409 with
            ``{"code": "agent_tls_missing"}`` when the channel has no
            certificate to pin.
    """
    urls = own_agent_urls(runtime) if is_hub else channel_urls(runtime)
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
