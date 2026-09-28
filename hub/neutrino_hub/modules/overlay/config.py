"""Which overlay this box is a member of, read off the router configuration.

There is no file of its own. An overlay is already a row in
``config/router/network.json`` — the one thing the firewall has to know about
it — so the choice is which row is there, and the exposure switch on the
Network page keeps editing the row it always did.
"""

import ipaddress
from urllib.parse import urlparse

from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.netbird.constants import NETBIRD_CLOUD_DOMAIN
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_ENGINES,
    OVERLAY_NONE,
    OVERLAY_PROVIDERS,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig, RouterOverlay


def provider_of(network: RouterNetworkConfig) -> str:
    """Which overlay this configuration runs.

    Args:
        network: The parsed router configuration.

    Returns:
        The provider key, :data:`OVERLAY_NONE` when no row is there. A
        configuration carrying more than one row — which nothing writes any
        more — reads as the first one the engine table knows.
    """
    for overlay in network.overlays:
        if overlay.provider in OVERLAY_ENGINES:
            return overlay.provider
    return OVERLAY_NONE


def set_provider(network: RouterNetworkConfig, provider: str) -> bool:
    """Make the configuration name this overlay and no other.

    Args:
        network: The parsed router configuration, edited in place.
        provider: A member of :data:`OVERLAY_PROVIDERS`.

    Returns:
        Whether anything changed.

    Raises:
        ValueError: For a provider that is not one of them.
    """
    if provider not in OVERLAY_PROVIDERS:
        raise ValueError(f"there is no overlay called {provider}")
    if provider_of(network) == provider and len(network.overlays) <= 1:
        return False
    # Kept rather than defaulted: turning an overlay off and on again is not
    # how somebody re-opens a box they deliberately went quiet on.
    exposures = {overlay.provider: overlay.is_exposed for overlay in network.overlays}
    network.overlays = (
        []
        if provider == OVERLAY_NONE
        else [
            RouterOverlay(provider=provider, is_exposed=exposures.get(provider, True))
        ]
    )
    return True


def overlay_name_matchers(easytier: EasyTierConfig) -> list[str]:
    """The names this box's overlay daemons look up, as xray domain matchers.

    Args:
        easytier: The stored EasyTier network.

    Returns:
        ``domain:`` for NetBird's hosted servers, then one ``full:`` per
        EasyTier peer host, in configuration order. A ``ring://`` peer and a
        peer addressed by a literal address name nothing to look up.
    """
    matchers = [f"domain:{NETBIRD_CLOUD_DOMAIN}"]
    for uri in easytier.peers:
        parsed = urlparse(uri)
        host = parsed.hostname or ""
        if parsed.scheme == "ring" or not host or _is_literal(host):
            continue
        matcher = f"full:{host}"
        if matcher not in matchers:
            matchers.append(matcher)
    return matchers


def _is_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
