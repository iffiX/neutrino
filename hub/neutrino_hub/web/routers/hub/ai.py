"""The AI providers the gateway forwards to.

One provider is one endpoint and one credential reference: ``secret_id``
names a ``token`` the Credentials page holds, the gateway's own renderer
resolves it, and a device's Dev Setup is pointed at what the providers
serve. No key material passes through these routes in either direction.
The providers the hub generates from each machine's Ollama are read here
and written by nobody. Each served name's context length and each cloud
name's price are read here, and the lengths and prices a person set are
written here.
"""

import operator

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.ai.constants import (
    AI_CONTEXT_LENGTH_MAX,
    AI_CONTEXT_LENGTH_MIN,
    AI_PRICE_MAX,
    AI_PRICE_MIN,
    AI_PROVIDER_KINDS,
)
from neutrino_hub.modules.ai.context_lengths import (
    read_set_lengths,
    write_set_lengths,
)
from neutrino_hub.modules.ai.model_prices import (
    is_default_price,
    price_refusal,
    read_set_prices,
    write_set_prices,
)
from neutrino_hub.modules.ai.registry import (
    AiProviderRecord,
    AiProviderRegistry,
)
from neutrino_hub.modules.ai.vendors import endpoint_of, load_vendors, vendor_endpoints
from neutrino_hub.modules.clients.ai_keys import gateway_models
from neutrino_hub.modules.cliproxyapi.ops import read_ollama_providers
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.shell_bridge import device_name
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.models import (
    AiModelUpdate,
    AiModelView,
    AiOllamaProviderListView,
    AiOllamaProviderView,
    AiProviderCreate,
    AiProviderListView,
    AiProviderModelView,
    AiProviderOrderUpdate,
    AiProviderRequest,
    AiProviderUpdate,
    AiProviderView,
    AiVendorView,
)

TOKEN_KIND = "token"

router = APIRouter(
    prefix="/api/hub/ai",
    tags=["ai"],
    dependencies=[Depends(require_session)],
)


@router.get("", response_model=AiProviderListView)
def list_providers() -> AiProviderListView:
    """Read every stored AI provider, and the vendor presets of the provider form.

    Returns:
        The providers, in served order, each with the vendor and endpoint
        its base URL names; and the presets, in the table's order.
    """
    return _provider_list(AiProviderRegistry().list_records())


@router.get("/ollama", response_model=AiOllamaProviderListView)
def list_ollama_providers(runtime=Depends(get_runtime)) -> AiOllamaProviderListView:
    """Read the providers the hub generates from each machine's Ollama.

    Args:
        runtime: The shared runtime, for the hostname each machine reports.

    Returns:
        One row per machine whose Ollama feeds the gateway, by the machine's
        name.
    """
    registry = DeviceRegistry()
    rows = []
    for provider in read_ollama_providers():
        device = registry.get(provider["device_id"])
        name = (device_name(runtime, device) if device is not None else "") or provider[
            "device_id"
        ]
        rows.append(
            AiOllamaProviderView(
                device_id=provider["device_id"], name=name, models=provider["models"]
            )
        )
    return AiOllamaProviderListView(
        providers=sorted(rows, key=operator.attrgetter("name", "device_id"))
    )


@router.get("/model", response_model=AiModelView)
def read_models(runtime=Depends(get_runtime)) -> AiModelView:
    """Read every served name's context length with where it comes from, and each cloud name's price.

    Args:
        runtime: The shared runtime, whose served list and machines the
            lengths come from.

    Returns:
        The cloud names and then the Ollama names, each by name.
    """
    return AiModelView(**runtime.model_view())


@router.post("/model/set", response_model=AiModelView)
def update_models(request: AiModelUpdate, runtime=Depends(get_runtime)) -> AiModelView:
    """Store the lengths and prices a person set; a null takes a name back to its default.

    Nothing restarts: every online machine and client whose state changes is
    handed its state, and a price counts from the next record the collector
    folds. A price equal to the default, in the default's currency, is
    stored as none.

    Args:
        request: Lengths and prices by cloud name.
        runtime: The shared runtime, whose machines and clients are told.

    Returns:
        Every served name's context length and price after the change.

    Raises:
        HTTPException: 400 ``context_length_invalid {model, context_length,
            min, max}`` for a length outside 4096 to 10000000,
            ``price_invalid {model, price, min, max}`` for a price number
            outside 0 to 10000 or with more than 6 decimals,
            ``currency_invalid {model, currency}`` for a currency other than
            USD and CNY, and ``model_not_served {model}`` for a name that is
            no cloud name the gateway serves.
    """
    served = gateway_models(runtime.served_models)
    ollama = {
        name for provider in read_ollama_providers() for name in provider["models"]
    }
    cloud = set(served) - ollama
    for model, length in request.lengths.items():
        if length is None:
            continue
        if not AI_CONTEXT_LENGTH_MIN <= length <= AI_CONTEXT_LENGTH_MAX:
            raise _refused(
                "context_length_invalid",
                model=model,
                context_length=length,
                min=AI_CONTEXT_LENGTH_MIN,
                max=AI_CONTEXT_LENGTH_MAX,
            )
        if model not in cloud:
            raise _refused("model_not_served", model=model)
    for model, price in request.prices.items():
        if price is None:
            continue
        refusal = price_refusal(price.model_dump())
        if refusal is not None and refusal[0] == "price_invalid":
            raise _refused(
                "price_invalid",
                model=model,
                price=refusal[1],
                min=AI_PRICE_MIN,
                max=AI_PRICE_MAX,
            )
        if refusal is not None:
            raise _refused("currency_invalid", model=model, currency=refusal[1])
        if model not in cloud:
            raise _refused("model_not_served", model=model)
    defaults = {
        entry["model"]: entry["default_price"]
        for entry in runtime.model_view()["cloud"]
    }
    with CONFIG_WRITE_LOCK:
        if request.lengths:
            lengths = read_set_lengths()
            for model, length in request.lengths.items():
                if length is None:
                    lengths.pop(model, None)
                else:
                    lengths[model] = length
            write_set_lengths(lengths)
        if request.prices:
            prices = read_set_prices()
            for model, price in request.prices.items():
                held = None if price is None else price.model_dump()
                if held is None or is_default_price(held, defaults.get(model)):
                    prices.pop(model, None)
                else:
                    prices[model] = held
            write_set_prices(prices)
    if request.lengths:
        runtime.note_context_lengths()
    return AiModelView(**runtime.model_view())


@router.post("/provider/order/set", response_model=AiProviderListView)
def reorder_providers(request: AiProviderOrderUpdate) -> AiProviderListView:
    """Store a new served order.

    Args:
        request: Every stored provider id exactly once, in the new order.

    Returns:
        The providers, in the order now served.

    Raises:
        HTTPException: 400 with ``provider_order_mismatch`` when the ids are
            not a permutation of the stored ones.
    """
    registry = AiProviderRegistry()
    stored_ids = [record.id for record in registry.list_records()]
    if sorted(request.provider_ids) != sorted(stored_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "provider_order_mismatch",
                "params": {
                    "missing": sorted(set(stored_ids) - set(request.provider_ids)),
                    "unknown": sorted(set(request.provider_ids) - set(stored_ids)),
                    "duplicate": sorted(
                        {
                            provider_id
                            for provider_id in request.provider_ids
                            if request.provider_ids.count(provider_id) > 1
                        }
                    ),
                },
            },
        )
    return _provider_list(registry.reorder(request.provider_ids))


@router.post("/provider/add", response_model=AiProviderView)
def create_provider(request: AiProviderCreate) -> AiProviderView:
    """Store a new AI provider.

    Args:
        request: The provider's fields; ``secret_id`` names a stored token,
            or nothing.

    Returns:
        The stored provider.

    Raises:
        HTTPException: 400 when the kind is unknown, the name is empty, or
            ``secret_id`` names no stored token.
    """
    if request.secret_id is not None:
        _require_stored_token(request.secret_id)
    try:
        record = AiProviderRegistry().add(
            name=request.name,
            kind=request.kind,
            base_url=request.base_url,
            secret_id=request.secret_id,
            models=[model.model_dump() for model in request.models],
        )
    except ValueError as error:
        raise _refused_provider(request.kind) from error
    return _provider_view(record)


@router.post("/provider/set", response_model=AiProviderView)
def update_provider(request: AiProviderUpdate) -> AiProviderView:
    """Change parts of a provider.

    ``secret_id`` sent as null clears the reference; left out of the body, it
    stays as stored.

    Args:
        request: The provider's id and the fields to change.

    Returns:
        The provider after the change.

    Raises:
        HTTPException: 404 for an unknown id, 400 for an unknown kind or a
            ``secret_id`` naming no stored token.
    """
    provider_id = request.provider_id
    changes = {}
    if "secret_id" in request.model_fields_set:
        if request.secret_id is not None:
            _require_stored_token(request.secret_id)
        changes["secret_id"] = request.secret_id
    try:
        record = AiProviderRegistry().update(
            provider_id,
            name=request.name,
            kind=request.kind,
            base_url=request.base_url,
            is_enabled=request.is_enabled,
            models=(
                [model.model_dump() for model in request.models]
                if request.models is not None
                else None
            ),
            **changes,
        )
    except KeyError as error:
        raise _unknown_provider(provider_id) from error
    except ValueError as error:
        raise _refused_provider(request.kind) from error
    return _provider_view(record)


@router.post("/provider/remove")
def delete_provider(request: AiProviderRequest) -> dict:
    """Remove a provider; the token it referenced stays in the vault.

    Args:
        request: The provider's id.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 404 for an unknown id.
    """
    try:
        AiProviderRegistry().delete(request.provider_id)
    except KeyError as error:
        raise _unknown_provider(request.provider_id) from error
    return {}


def _refused(code: str, **params) -> HTTPException:
    """One 400 with its code and what the wording names.

    Args:
        code: The refusal's code.
        **params: What its wording names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": params},
    )


def _unknown_provider(provider_id: str) -> HTTPException:
    """One 404 for an id no stored provider has.

    Args:
        provider_id: What was asked for.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "provider_unknown", "params": {"provider": provider_id}},
    )


def _refused_provider(kind: str | None) -> HTTPException:
    """One 400 for a provider the registry would not store.

    Args:
        kind: The kind the request carried, None when it carried none.

    Returns:
        The exception to raise.
    """
    if kind is not None and kind not in AI_PROVIDER_KINDS:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "provider_kind_unknown", "params": {"kind": kind}},
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "provider_name_needed", "params": {}},
    )


def _require_stored_token(secret_id: str) -> None:
    """Refuse a reference the vault does not hold as a token.

    Args:
        secret_id: The submitted reference.

    Raises:
        HTTPException: 400 with ``unknown_credential`` naming ``secret_id``.
    """
    record = SecretVault().get(secret_id)
    if record is None or record.kind != TOKEN_KIND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unknown_credential", "params": {"field": "secret_id"}},
        )


def _provider_list(records: list) -> AiProviderListView:
    """The providers in their order, and the vendor presets.

    Args:
        records: The stored providers, in their order.

    Returns:
        The view.
    """
    vendors = load_vendors()
    endpoints = vendor_endpoints(vendors)
    return AiProviderListView(
        providers=[_provider_view(record, endpoints) for record in records],
        vendors=[AiVendorView(**vendor) for vendor in vendors],
    )


def _provider_view(
    record: AiProviderRecord, endpoints: "list | None" = None
) -> AiProviderView:
    """One provider, with the preset its base URL names."""
    if endpoints is None:
        endpoints = vendor_endpoints(load_vendors())
    endpoint = endpoint_of(record.kind, record.base_url, endpoints)
    is_preset = endpoint is not None and endpoint.is_preset
    return AiProviderView(
        id=record.id,
        name=record.name,
        kind=record.kind,
        base_url=record.base_url,
        secret_id=record.secret_id,
        is_enabled=record.is_enabled,
        models=[AiProviderModelView(**model) for model in record.models],
        created_at=record.created_at,
        vendor=endpoint.vendor if is_preset else "",
        endpoint=endpoint.id if is_preset else "",
    )
