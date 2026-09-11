"""Which overlay this box is a member of, read off the router configuration.

There is no file of its own. An overlay is already a row in
``config/router/network.json`` — the one thing the firewall has to know about
it — so the choice is which row is there, and the exposure switch on the
Network page keeps editing the row it always did.
"""

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
