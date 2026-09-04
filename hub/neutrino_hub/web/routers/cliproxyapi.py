"""The AI page: the gateway's status, keys, usage, and applying changes.

The upstream providers themselves are edited on the same page, against
``/api/ai``; a change there takes effect when this page's apply runs, which
re-renders the YAML and restarts the service. Usage answers come from the
store the panel's collector fills — never from the gateway directly, whose
queue hands every record out exactly once.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from neutrino_hub.modules.cliproxyapi.accounts import (
    CliproxyApiAccount,
    CliproxyApiAccountClient,
    CliproxyApiAccountError,
)
from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_LOGIN_KINDS
from neutrino_hub.modules.cliproxyapi.management_key import read_management_key
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
from neutrino_hub.modules.credentials.vault import VaultError, VaultLockedError
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.constants import WEB_JOURNAL_LINE_LIMIT
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import (
    CliproxyApiAccountsView,
    CliproxyApiAccountView,
    CliproxyApiApplyResult,
    CliproxyApiHealthBucket,
    CliproxyApiJournalView,
    CliproxyApiKeyCreate,
    CliproxyApiKeyView,
    CliproxyApiLoginCode,
    CliproxyApiLoginStart,
    CliproxyApiLoginStateView,
    CliproxyApiLoginView,
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

# What each management API refusal answers with. Anything else is the gateway
# failing to answer at all, which is a 502.
ACCOUNT_ERROR_STATUS = {
    "unknown_account": status.HTTP_404_NOT_FOUND,
    "login_expired": status.HTTP_404_NOT_FOUND,
    "unsupported_kind": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


@router.get("", response_model=CliproxyApiStatusView)
def read_status() -> CliproxyApiStatusView:
    """Read the AI gateway's state, probing it when it should be up.

    Returns:
        Install state, service state, keys, and what the probe found. The
        client keys are unsealed here, in full, for the panel that asked.

    Raises:
        VaultLockedError: If there is no data key to unseal them with.
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
        The usage view. Providers come in served order, then the accounts the
        gateway is still holding a token file for; an account it no longer
        lists keeps its stored cells and gets no row, as a deleted provider
        does. A gateway that cannot be asked contributes no account rows.

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
        ]
        + [
            _usage_account(
                account, provider_rows.get(account.name) or store.empty_provider_row()
            )
            for account in _accounts_quietly()
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
def generate_key(request: CliproxyApiKeyCreate) -> CliproxyApiStatusView:
    """Generate a client key and put it into service immediately.

    Args:
        request: What the key is for.

    Returns:
        The state after the change.

    Raises:
        VaultLockedError: If there is no data key to seal the new key under.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        config.client_keys.append(CliproxyApiClientKey.generated(request.name))
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


@router.get("/accounts", response_model=CliproxyApiAccountsView)
def read_accounts() -> CliproxyApiAccountsView:
    """List the subscription accounts the gateway is serving with.

    Returns:
        The accounts and the flows this gateway can start.

    Raises:
        HTTPException: 502 with ``gateway_unreachable`` when the gateway does
            not answer, which includes it not running yet.
    """
    accounts = _account_call(lambda client: client.list_accounts())
    return CliproxyApiAccountsView(
        accounts=[CliproxyApiAccountView(**vars(account)) for account in accounts],
        login_kinds=list(CLIPROXYAPI_LOGIN_KINDS),
    )


@router.delete("/accounts/{name}", response_model=CliproxyApiAccountsView)
def delete_account(name: str) -> CliproxyApiAccountsView:
    """Sign an account out; whatever it was serving stops now.

    Args:
        name: The account's token file, as the list reports it.

    Returns:
        The accounts after the change.

    Raises:
        HTTPException: 404 with ``unknown_account``, 502 with
            ``gateway_unreachable``.
    """
    _account_call(lambda client: client.delete_account(name))
    return read_accounts()


@router.post("/account_logins", response_model=CliproxyApiLoginView)
def start_login(request: CliproxyApiLoginStart) -> CliproxyApiLoginView:
    """Begin a login and answer with what the person has to open.

    Args:
        request: Which flow to start.

    Returns:
        The flow, carrying the URL and the handle to poll.

    Raises:
        HTTPException: 422 with ``unsupported_kind`` for a flow this gateway
            does not carry, 502 with ``gateway_unreachable``.
    """
    login = _account_call(lambda client: client.start_login(request.kind))
    return CliproxyApiLoginView(**vars(login))


@router.get("/account_logins/{state}", response_model=CliproxyApiLoginStateView)
def read_login(state: str) -> CliproxyApiLoginStateView:
    """Ask where a login has got to.

    Args:
        state: The handle the start returned.

    Returns:
        ``pending`` while it is open, then ``complete`` or ``failed``.

    Raises:
        HTTPException: 502 with ``gateway_unreachable``.
    """
    return CliproxyApiLoginStateView(
        **vars(_account_call(lambda client: client.read_login(state)))
    )


@router.put("/account_logins/{state}/code", response_model=CliproxyApiLoginStateView)
def submit_login_code(
    state: str, request: CliproxyApiLoginCode
) -> CliproxyApiLoginStateView:
    """Hand back the code a redirect flow's browser came away with.

    The gateway exchanges it behind the call, so the answer is the flow's
    state as it stands and the outcome arrives on a later poll.

    Args:
        state: The handle the start returned.
        request: The code, or the whole address the browser was sent to.

    Returns:
        Where the login has got to right now.

    Raises:
        HTTPException: 404 with ``login_expired`` when the gateway no longer
            holds the flow, 502 with ``gateway_unreachable``.
    """
    _account_call(lambda client: client.submit_code(state, request.code))
    return read_login(state)


@router.delete("/account_logins/{state}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_login(state: str) -> None:
    """Drop a login nobody finished.

    Args:
        state: The handle the start returned.

    Raises:
        HTTPException: 404 with ``login_expired`` when the gateway has already
            forgotten it, 502 with ``gateway_unreachable``.
    """
    _account_call(lambda client: client.cancel_login(state))


def _account_client() -> CliproxyApiAccountClient:
    """A client aimed at this box's gateway, with the key it was rendered with."""
    return CliproxyApiAccountClient(
        port=load_config().listen_port, management_key=read_management_key()
    )


def _account_call(action):
    """Run one management API call, wording its refusal as the panel's own.

    Args:
        action: What to do with the client.

    Returns:
        Whatever the action returned.

    Raises:
        HTTPException: Carrying ``{code, params}``; 404 for an account or a
            login the gateway does not have, 422 for a flow it cannot start,
            502 for a gateway that does not answer.
    """
    try:
        return action(_account_client())
    except CliproxyApiAccountError as error:
        raise HTTPException(
            status_code=ACCOUNT_ERROR_STATUS.get(
                error.code, status.HTTP_502_BAD_GATEWAY
            ),
            detail={"code": error.code, "params": error.params},
        ) from error


def _accounts_quietly() -> list[CliproxyApiAccount]:
    """Every signed-in account, empty where the gateway cannot be asked.

    Returns:
        The accounts. A page that is mostly about something else does not fail
        because the gateway is down, so the refusal is swallowed here.
    """
    try:
        return _account_client().list_accounts()
    except CliproxyApiAccountError:
        return []


def _account_count() -> int:
    """How many accounts are signed in, 0 when the gateway cannot say."""
    return len(_accounts_quietly())


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
    keys = [_key_view(key) for key in config.client_keys]
    is_reachable = False
    probe_message = ""
    served_models: list[str] = []
    if service.is_active:
        is_reachable, probe_message, served_models = applier.probe(
            port=config.listen_port,
            client_key=next((view.key for view in keys if view.key), None),
        )
    providers = AiProviderRegistry().list_records()
    today = CliproxyApiUsageStore().today_counters()
    return CliproxyApiStatusView(
        is_installed=applier.is_installed,
        is_active=service.is_active,
        listen_port=config.listen_port,
        client_keys=keys,
        is_reachable=is_reachable,
        probe_message=probe_message,
        served_models=served_models,
        enabled_provider_count=sum(
            1 for p in providers if p.is_enabled and p.secret_id
        ),
        is_serving_stale=applier.is_serving_stale,
        requests_today=today["requests"],
        tokens_today=today["input_tokens"] + today["output_tokens"],
        account_count=_account_count() if service.is_active else 0,
    )


def _key_view(key: CliproxyApiClientKey) -> CliproxyApiKeyView:
    """One client key, unsealed for the panel that asked for it.

    Args:
        key: The stored record.

    Returns:
        The view. A record whose seal does not open still gets a row, without
        key material, so the page can name it and revoke it.

    Raises:
        VaultLockedError: If there is no data key on this box.
    """
    try:
        material = key.open_key()
    except VaultLockedError:
        raise
    except VaultError:
        material = ""
    return CliproxyApiKeyView(
        id=key.id, name=key.name, key=material, created_at=key.created_at
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


def _usage_account(account: CliproxyApiAccount, row: dict) -> CliproxyApiUsageProvider:
    """One account's usage row, named the way the Accounts panel names it."""
    return CliproxyApiUsageProvider(
        provider_id=account.name,
        name=account.label or account.email or account.name,
        kind=account.provider,
        is_account=True,
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        health=[CliproxyApiHealthBucket(**bucket) for bucket in row["health"]],
        **{field: row[field] for field in zero_counters()},
    )
