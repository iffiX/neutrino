"""The AI page: the gateway's status, keys, usage, and applying changes.

The upstream providers themselves are edited on the Credentials page; a
change there takes effect when this page's apply runs, which re-renders the
YAML and restarts the service. Usage answers come from the store the panel's
collector fills — never from the gateway directly, whose queue hands every
record out exactly once.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.ops import (
    CliproxyApiConfigApplier,
    load_config,
    save_config,
)
from neutrino_hub.modules.cliproxyapi.usage_store import (
    USAGE_RANGE_BUCKETS,
    CliproxyApiUsageStore,
    zero_counters,
)
from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.constants import WEB_JOURNAL_LINE_LIMIT
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import (
    CliproxyApiApplyResult,
    CliproxyApiHealthBucket,
    CliproxyApiJournalView,
    CliproxyApiKeyCreate,
    CliproxyApiKeyView,
    CliproxyApiSettingsUpdate,
    CliproxyApiStatusView,
    CliproxyApiUsageBucket,
    CliproxyApiUsageKey,
    CliproxyApiUsageProvider,
    CliproxyApiUsageRates,
    CliproxyApiUsageTotals,
    CliproxyApiUsageView,
)

router = APIRouter(
    prefix="/api/cliproxyapi",
    tags=["cliproxyapi"],
    dependencies=[Depends(require_session)],
)


@router.get("", response_model=CliproxyApiStatusView)
def read_status() -> CliproxyApiStatusView:
    """Read the AI gateway's state, probing it when it should be up.

    Returns:
        Install state, service state, keys, and what the probe found.
    """
    return _status()


@router.get("/usage", response_model=CliproxyApiUsageView)
def usage(
    range_name: str = Query(default="day", alias="range"),
    key_id: str | None = None,
) -> CliproxyApiUsageView:
    """Read accumulated usage: rates, totals, the series, keys, providers.

    Args:
        range_name: ``day`` answers in 24 hourly buckets; ``week``, ``month``
            and ``year`` in 7, 30 and 365 daily ones.
        key_id: Narrow the totals, rates, series and providers to one client
            key; ``keys`` always lists every key, because the filter's own
            options are built from it.

    Returns:
        The usage view; providers come in served order.

    Raises:
        HTTPException: 422 with ``invalid_range`` for an unknown range, 404
            with ``unknown_key`` for a key neither stored nor ever seen.
    """
    if range_name not in USAGE_RANGE_BUCKETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_range", "params": {"range": range_name}},
        )
    store = CliproxyApiUsageStore()
    key_rows = store.key_rows(range_name)
    if key_id is not None:
        known = {row["key_id"] for row in key_rows} | {
            key.id for key in load_config().client_keys
        }
        if key_id not in known:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "unknown_key", "params": {"key_id": key_id}},
            )
    device_names = _device_names()
    provider_rows = store.provider_rows(range_name, key_id=key_id)
    return CliproxyApiUsageView(
        range=range_name,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rates=CliproxyApiUsageRates(**store.rates(key_id=key_id)),
        totals=CliproxyApiUsageTotals(**store.totals(range_name, key_id=key_id)),
        series=[
            CliproxyApiUsageBucket(**entry)
            for entry in store.series(range_name, key_id=key_id)
        ],
        keys=[
            CliproxyApiUsageKey(**row, device_name=device_names.get(row["key_id"]))
            for row in key_rows
        ],
        providers=[
            _usage_provider(
                record, provider_rows.get(record.id) or store.empty_provider_row()
            )
            for record in AiProviderRegistry().list_records()
        ],
    )


@router.get("/journal", response_model=CliproxyApiJournalView)
def journal(
    lines: int = Query(default=200, ge=1, le=WEB_JOURNAL_LINE_LIMIT),
) -> CliproxyApiJournalView:
    """Read the tail of the gateway's journal.

    Args:
        lines: How many lines to return, at most :data:`WEB_JOURNAL_LINE_LIMIT`.

    Returns:
        The journal lines, most recent last.
    """
    text = SystemdServiceController().journal("cliproxyapi", line_count=lines)
    return CliproxyApiJournalView(lines=text.splitlines())


@router.post("/keys", response_model=CliproxyApiStatusView)
def mint_key(request: CliproxyApiKeyCreate) -> CliproxyApiStatusView:
    """Mint a client key and put it into service immediately.

    Args:
        request: What the key is for.

    Returns:
        The state after the change.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        config.client_keys.append(CliproxyApiClientKey.minted(request.name))
        save_config(config)
    _apply_quietly()
    return _status()


@router.delete("/keys/{key_id}", response_model=CliproxyApiStatusView)
def delete_key(key_id: str) -> CliproxyApiStatusView:
    """Revoke a client key; whatever used it stops working now.

    Args:
        key_id: The key to revoke.

    Returns:
        The state after the change.

    Raises:
        HTTPException: 404 for an unknown key.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        remaining = [key for key in config.client_keys if key.id != key_id]
        if len(remaining) == len(config.client_keys):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="unknown key"
            )
        config.client_keys = remaining
        save_config(config)
    _apply_quietly()
    return _status()


@router.put("", response_model=CliproxyApiStatusView)
def update_settings(request: CliproxyApiSettingsUpdate) -> CliproxyApiStatusView:
    """Change the listen port.

    Args:
        request: The new settings.

    Returns:
        The state after the change.

    Raises:
        HTTPException: 400 when the settings do not validate.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        config.listen_port = request.listen_port
        try:
            config.validate()
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        save_config(config)
    _apply_quietly()
    return _status()


@router.post("/apply", response_model=CliproxyApiApplyResult)
def apply() -> CliproxyApiApplyResult:
    """Re-render the YAML from current state and restart the gateway.

    Returns:
        What happened.

    Raises:
        HTTPException: 400 when the stored settings do not validate.
    """
    try:
        message = CliproxyApiConfigApplier().apply()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return CliproxyApiApplyResult(message=message)


def _apply_quietly() -> None:
    """Apply after a key or settings change; the status reflects failures."""
    try:
        CliproxyApiConfigApplier().apply()
    except ValueError:
        return


def _status() -> CliproxyApiStatusView:
    applier = CliproxyApiConfigApplier()
    config = load_config()
    service = SystemdServiceController().status("cliproxyapi")
    is_reachable = False
    probe_message = ""
    if service.is_active:
        first_key = config.client_keys[0].key if config.client_keys else None
        is_reachable, probe_message = applier.probe(
            port=config.listen_port, client_key=first_key
        )
    providers = AiProviderRegistry().list_records()
    today = CliproxyApiUsageStore().today_counters()
    return CliproxyApiStatusView(
        is_installed=applier.is_installed,
        is_active=service.is_active,
        listen_port=config.listen_port,
        client_keys=[CliproxyApiKeyView(**key.to_dict()) for key in config.client_keys],
        is_reachable=is_reachable,
        probe_message=probe_message,
        enabled_provider_count=sum(
            1 for p in providers if p.is_enabled and p.secret_id
        ),
        is_serving_stale=applier.is_serving_stale,
        requests_today=today["requests"],
        tokens_today=today["input_tokens"] + today["output_tokens"],
    )


def _device_names() -> dict[str, str]:
    """Client key id to the name of the device holding it, as of now."""
    names = {}
    for device in DeviceRegistry().all_stored():
        key_id = device.client.ai_key_id
        if key_id:
            names[key_id] = device.name or device.mac_address
    return names


def _usage_provider(record, row: dict) -> CliproxyApiUsageProvider:
    """One provider's usage row, from a stored or an empty row."""
    return CliproxyApiUsageProvider(
        provider_id=record.id,
        name=record.name,
        kind=record.kind,
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        health=[CliproxyApiHealthBucket(**bucket) for bucket in row["health"]],
        **{field: row[field] for field in zero_counters()},
    )
