"""Which overlays this box runs, read off the router configuration.

There is no file of its own. An overlay is already a row in
``config/router/network.json`` — the one thing the firewall has to know about
it — so whether an engine runs is a field on its row, and the exposure switch
on the Network page keeps editing the row it always did.
"""

from neutrino_hub.modules.overlay.constants import OVERLAY_ENGINES
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig, RouterOverlay


def enabled_providers(network: RouterNetworkConfig) -> list[str]:
    """Which overlays this configuration runs.

    Args:
        network: The parsed router configuration.

    Returns:
        The provider keys of the enabled rows, in the engine table's order;
        empty when none runs.
    """
    enabled = {overlay.provider for overlay in network.enabled_overlays}
    return [key for key in OVERLAY_ENGINES if key in enabled]


def set_enabled(
    network: RouterNetworkConfig, provider: str, *, is_enabled: bool
) -> bool:
    """Turn one overlay on or off in the configuration.

    A row is added the first time an engine is turned on, open; a row turned
    off keeps its exposure for the day it is turned on again. The rows are
    kept in the engine table's order.

    Args:
        network: The parsed router configuration, edited in place.
        provider: A key of :data:`OVERLAY_ENGINES`.
        is_enabled: Whether the engine runs from now on.

    Returns:
        Whether anything changed.

    Raises:
        ValueError: For a provider that is not one of them.
    """
    if provider not in OVERLAY_ENGINES:
        raise ValueError(f"there is no overlay called {provider}")
    rows = {overlay.provider: overlay for overlay in network.overlays}
    row = rows.get(provider)
    if row is None:
        if not is_enabled:
            return False
        rows[provider] = RouterOverlay(provider=provider, is_enabled=True)
    elif row.is_enabled == is_enabled:
        return False
    else:
        row.is_enabled = is_enabled
    network.overlays = [rows[key] for key in OVERLAY_ENGINES if key in rows]
    return True
