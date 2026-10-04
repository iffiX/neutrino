"""The proxy's two resolver lists in ``config/xray/routing.json``.

``remote_dns`` is asked through the exit for names whose traffic goes
through it, and ``direct_dns`` out the uplink for names whose traffic stays
direct. Each is a list of ``{address, port}`` asked in order. An empty
``direct_dns`` means the network's resolvers.

A file written before the lists holds one ``{address, port}`` under each
field. It reads as a list of that one resolver, and the direct field as an
empty list when its address is the former default.

Pure: this module reads parsed configuration.
"""

from neutrino_hub.modules.router.constants import ROUTER_RESOLVER_PORT
from neutrino_hub.modules.xray.constants import (
    XRAY_DIRECT_DNS_FIELD,
    XRAY_FORMER_DIRECT_DNS,
    XRAY_REMOTE_DNS_DEFAULT,
    XRAY_REMOTE_DNS_FIELD,
)


def read_resolvers(routing: dict, field: str) -> list[dict]:
    """One of the two resolver lists, in the order it is asked.

    Args:
        routing: Parsed ``config/xray/routing.json``.
        field: ``remote_dns`` or ``direct_dns``.

    Returns:
        Each resolver as ``{address, port}``; a row with no address is
        left out. A remote list that names none reads as the default list.
    """
    value = routing.get(field)
    if isinstance(value, dict):
        rows = [value]
        if (
            field == XRAY_DIRECT_DNS_FIELD
            and str(value.get("address", "")).strip() == XRAY_FORMER_DIRECT_DNS
        ):
            rows = []
    elif isinstance(value, list):
        rows = value
    else:
        rows = []
    resolvers = [_resolver(row) for row in rows if _is_named(row)]
    if not resolvers and field == XRAY_REMOTE_DNS_FIELD:
        return [dict(entry) for entry in XRAY_REMOTE_DNS_DEFAULT]
    return resolvers


def with_resolver_lists(routing: dict) -> dict:
    """The routing options with both resolver fields read as lists.

    Args:
        routing: Parsed ``config/xray/routing.json``.

    Returns:
        A copy whose ``remote_dns`` and ``direct_dns`` are lists.
    """
    return {
        **routing,
        XRAY_REMOTE_DNS_FIELD: read_resolvers(routing, XRAY_REMOTE_DNS_FIELD),
        XRAY_DIRECT_DNS_FIELD: read_resolvers(routing, XRAY_DIRECT_DNS_FIELD),
    }


def direct_resolvers(routing: dict, network_resolvers: list[dict]) -> list[dict]:
    """The resolvers the proxy's direct lookups ask.

    Args:
        routing: Parsed ``config/xray/routing.json``.
        network_resolvers: The network's resolvers, as ``{address, port}``.

    Returns:
        ``direct_dns`` when it lists any, else the network's resolvers.
    """
    return read_resolvers(routing, XRAY_DIRECT_DNS_FIELD) or [
        dict(entry) for entry in network_resolvers
    ]


def _is_named(row) -> bool:
    return isinstance(row, dict) and bool(str(row.get("address", "")).strip())


def _resolver(row: dict) -> dict:
    try:
        port = int(row.get("port", ROUTER_RESOLVER_PORT))
    except (TypeError, ValueError):
        port = ROUTER_RESOLVER_PORT
    return {"address": str(row["address"]).strip(), "port": port}
