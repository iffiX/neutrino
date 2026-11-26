"""The vendor presets of the provider form, and the vendor a provider's base URL names.

A preset fills the form's kind, base URL and model names; the stored record
names no vendor. A provider's vendor and endpoint are the ones whose base
URL equals the provider's, and the price lookup reads them the same way
(hub_components/ai.md, "Vendor presets").

The table is read by the functions here; the matching is pure.
"""

import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from neutrino_hub.modules.ai.constants import (
    AI_KIND_ENDPOINT,
    AI_KIND_VENDORS,
    AI_VENDORS_PATH,
)

# The table as read at its first use, by path.
_VENDORS: dict = {}


@dataclass(frozen=True)
class AiVendorEndpoint:
    """One endpoint a provider's base URL can name.

    Attributes:
        vendor: The vendor's id, such as ``deepseek``, or a kind for a
            kind's own endpoint.
        id: The endpoint's id, such as ``api_cn``.
        base_url: Its base URL.
        price_provider: The models.dev provider its requests are priced at.
        is_plan: Whether it is a coding plan's endpoint.
        models: The model names its preset fills.
        is_preset: Whether the provider form offers it.
    """

    vendor: str
    id: str
    base_url: str
    price_provider: str
    is_plan: bool = False
    models: tuple = field(default_factory=tuple)
    is_preset: bool = True


def load_vendors(path=AI_VENDORS_PATH) -> list:
    """The preset table, read once per path.

    Args:
        path: The table's file.

    Returns:
        ``{id, endpoints: [{id, base_url, price_provider, is_plan,
        models}]}`` per vendor, in the table's order.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If it is not the table's JSON.
    """
    key = str(path)
    if key not in _VENDORS:
        with open(path, encoding="utf-8") as stream:
            held = json.load(stream)
        vendors = held.get("vendors") if isinstance(held, dict) else None
        if not isinstance(vendors, list):
            raise ValueError(f"{path} holds no vendors")
        _VENDORS[key] = [vendor for vendor in vendors if isinstance(vendor, dict)]
    return _VENDORS[key]


def vendor_endpoints(vendors: list) -> list:
    """Every endpoint a base URL can name: the presets', then each kind's own.

    Args:
        vendors: The preset table, as :func:`load_vendors` gives it.

    Returns:
        :class:`AiVendorEndpoint` each.
    """
    endpoints = []
    for vendor in vendors:
        for endpoint in vendor.get("endpoints") or []:
            endpoints.append(
                AiVendorEndpoint(
                    vendor=str(vendor.get("id", "")),
                    id=str(endpoint.get("id", "")),
                    base_url=str(endpoint.get("base_url", "")),
                    price_provider=str(endpoint.get("price_provider", "")),
                    is_plan=bool(endpoint.get("is_plan", False)),
                    models=tuple(str(model) for model in endpoint.get("models") or []),
                )
            )
    for kind, (base_url, price_provider) in AI_KIND_VENDORS.items():
        endpoints.append(
            AiVendorEndpoint(
                vendor=kind,
                id=AI_KIND_ENDPOINT,
                base_url=base_url,
                price_provider=price_provider,
                is_preset=False,
            )
        )
    return endpoints


def price_providers(vendors: list) -> set:
    """Every models.dev provider an endpoint's requests are priced at.

    Args:
        vendors: The preset table.

    Returns:
        The providers' ids.
    """
    return {
        endpoint.price_provider
        for endpoint in vendor_endpoints(vendors)
        if endpoint.price_provider
    }


def endpoint_of(kind: str, base_url: str, endpoints: list) -> "AiVendorEndpoint | None":
    """The endpoint a provider's base URL names.

    Args:
        kind: The provider's kind.
        base_url: Its base URL, empty for the kind's default.
        endpoints: Every endpoint, as :func:`vendor_endpoints` gives them.

    Returns:
        The endpoint whose base URL equals the provider's, compared without
        a trailing slash and with the host in any case; for an empty base URL
        the kind's own endpoint; None for **Custom**.
    """
    if not base_url.strip():
        if kind not in AI_KIND_VENDORS:
            return None
        base_url = AI_KIND_VENDORS[kind][0]
    wanted = _comparable(base_url)
    for endpoint in endpoints:
        if _comparable(endpoint.base_url) == wanted:
            return endpoint
    return None


def _comparable(url: str) -> str:
    """A base URL with no trailing slash and its scheme and host in lower case."""
    parts = urlsplit(url.strip())
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            parts.query,
            parts.fragment,
        )
    )
