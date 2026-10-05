"""Every address the hub answers the channel on.

The set is the firewall's: every exposed interface, whatever its role, and
every exposed overlay, plus the overlay's own name where its daemon reports
one. An enrolment link carries it, both state documents carry it under
their hash, and the address sampler pushes both when it changes.
"""

import ipaddress

from fastapi import HTTPException, status

from neutrino_hub.modules.overlay.constants import (
    OVERLAY_DIRECT_INTERFACES_ADDED,
    OVERLAY_DIRECT_INTERFACES_EXPOSED,
    OVERLAY_DIRECT_INTERFACES_NONE,
)
from neutrino_hub.modules.overlay.ops import overlay_parts
from neutrino_hub.modules.overlay.direct_config import (
    OverlayDirectConfig,
    read_direct,
)
from neutrino_hub.modules.overlay.relay_config import read_relay
from neutrino_hub.modules.overlay.relay_ops import is_relay_configured
from neutrino_hub.modules.router.constants import ROUTER_OVERLAY_NETBIRD
from neutrino_hub.modules.router.link_status import (
    device_addresses,
    device_ipv6_addresses,
)
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
        its order, every enabled interface's and the stable IPv6 addresses
        among them while Direct is on; then the public address the person
        stated for Direct, while it is on; and last the relay's address while
        it is on and configured. An IPv6 address is written in brackets.
        Each address is listed once, however it was spelled.
    """
    direct = _stored_direct()
    urls = _own_urls(runtime, direct, is_direct=direct.is_enabled)
    relay = relay_url()
    if relay and relay not in urls:
        urls.append(relay)
    return urls


def direct_urls(runtime, direct: OverlayDirectConfig) -> list[str]:
    """What Direct adds to ``urls``, whether it is on or off.

    Args:
        runtime: The shared runtime, for the network configuration and the
            port.
        direct: Direct's settings.

    Returns:
        The members :func:`channel_urls` holds with Direct on and not with
        it off, in their order, each once.
    """
    without = _own_urls(runtime, direct, is_direct=False)
    return [
        url for url in _own_urls(runtime, direct, is_direct=True) if url not in without
    ]


def direct_interface_state(runtime) -> str:
    """How Direct stands with the hub's interface addresses.

    Args:
        runtime: The shared runtime, for the network configuration and the
            port.

    Returns:
        ``added`` when Direct adds an interface's address to ``urls``;
        ``exposed`` when it adds none because every address the hub holds
        already answers on the agent port; ``none`` when the hub holds no
        address to answer on.
    """
    unstated = OverlayDirectConfig()
    without = _own_urls(runtime, unstated, is_direct=False)
    if any(url not in without for url in _own_urls(runtime, unstated, is_direct=True)):
        return OVERLAY_DIRECT_INTERFACES_ADDED
    if without:
        return OVERLAY_DIRECT_INTERFACES_EXPOSED
    return OVERLAY_DIRECT_INTERFACES_NONE


def channel_url(host: str, port: int) -> str:
    """The agent port's base URL on one host, one spelling per address.

    Args:
        host: An address or a name; an IPv6 address is bare.
        port: The port.

    Returns:
        ``https://<host>:<port>``: an IP address in its standard form, an
        IPv6 one compressed and in brackets, a name in lower case.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return f"https://{host.lower()}:{port}"
    if address.version == 6:
        return f"https://[{address}]:{port}"
    return f"https://{address}:{port}"


def _own_urls(runtime, direct: OverlayDirectConfig, *, is_direct: bool) -> list:
    """The hub's own addresses on the agent port, the relay aside.

    Args:
        runtime: The shared runtime.
        direct: Direct's settings, for its public address.
        is_direct: Whether to list what Direct adds.

    Returns:
        One URL per host :func:`channel_hosts` returns, then the public
        address while ``is_direct``, each address once.
    """
    port = runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
    urls = []
    for host in channel_hosts(runtime.network(), is_direct=is_direct):
        url = channel_url(host, port)
        if url not in urls:
            urls.append(url)
    if is_direct and direct.public_host:
        public = channel_url(direct.public_host, direct.public_port)
        if public not in urls:
            urls.append(public)
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
    loopback = channel_url(WEB_AGENT_LOOPBACK_HOST, port)
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
    its overlay address moved. While Direct is on, the exposed interfaces'
    stable IPv6 addresses follow, then every enabled interface that is not
    exposed by its IPv4 address and then its stable IPv6 addresses: the
    agent port answers there, and nothing else of the box.

    Args:
        network: The router configuration.
        is_direct: Whether Direct is on.

    Returns:
        The hosts, in configuration order, each group's IPv4 addresses
        before its IPv6 ones, an IPv6 address bare, the overlay's name last.
    """
    configured = {
        interface.device_name: interface.lan.address
        for interface in network.lan_interfaces
        if interface.lan.address
    }
    live = device_addresses()
    held_ipv6 = device_ipv6_addresses() if is_direct else {}
    present = list(live) + [name for name in held_ipv6 if name not in live]
    exposed = network.exposed_device_names_on(present)
    answering = exposed + [
        name for name in network.exposed_overlay_device_names if name not in exposed
    ]
    hosts = []
    _add_ipv4(hosts, answering, configured, live)
    if is_direct:
        _add_ipv6(hosts, exposed, held_ipv6)
        enabled = [
            name for name in network.enabled_device_names if name not in answering
        ]
        _add_ipv4(hosts, enabled, configured, live)
        _add_ipv6(hosts, enabled, held_ipv6)
    name = overlay_name(network)
    if name and name not in hosts:
        hosts.append(name)
    return hosts


def _add_ipv4(hosts: list, names: list, configured: dict, live: dict) -> None:
    """Add each device's IPv4 address: the configured one, else its live one.

    Args:
        hosts: The hosts so far, added to.
        names: The devices, in order.
        configured: Device name to a served network's configured address.
        live: Device name to the IPv4 address with its prefix it holds now.
    """
    for name in names:
        address = configured.get(name, "") or live.get(name, "").split("/")[0]
        if address and address not in hosts:
            hosts.append(address)


def _add_ipv6(hosts: list, names: list, held: dict) -> None:
    """Add each device's stable IPv6 addresses, bare.

    Args:
        hosts: The hosts so far, added to.
        names: The devices, in order.
        held: Device name to its stable IPv6 addresses with their prefixes.
    """
    for name in names:
        for held_address in held.get(name, []):
            address = held_address.split("/")[0]
            if address not in hosts:
                hosts.append(address)


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
