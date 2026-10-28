"""The machine page's Available accounts: one form per account of a machine.

An available account is one of the machine's accounts the person added,
with what every feature of the account layer needs to know of it
(agent.md, "The two layers and the accounts"): on Windows its password as a
vault login, the folder its share serves, the shell its terminal and SSH
server start, and whether its AI tools use the hub's gateway. The rows live
in ``config/devices/<id>/accounts.json``; removing one takes it out of
every module that enables it and deletes what the hub generated for it.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import (
    AgentOfflineError,
    StreamRefusedError,
    VaultLockedError,
)
from neutrino_hub.modules.channel.constants import (
    CHANNEL_STREAM_COMMAND,
    CHANNEL_VERB_VALIDATE,
)
from neutrino_hub.modules.clients.ai_keys import (
    apply_keys,
    ensure_device_key,
    gateway_models,
    revoke_device_key,
)
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.constants import (
    DEVICE_MODULE_VALIDATE_TIMEOUT_S,
    DEVICE_PASSWORD_OS,
    DEVICE_TERMINAL_MODULE,
)
from neutrino_hub.modules.devices.module_table import (
    account_layer_names,
    gateway_instance_names,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    AccountCreate,
    AccountListView,
    AccountRequest,
    AccountToolsView,
    AccountView,
    SystemAccountView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    CODE_AGENT_OFFLINE,
    CODE_DEVICE_UNKNOWN,
    push_state,
)

router = APIRouter(
    prefix="/api/agent/module/account",
    tags=["module"],
    dependencies=[Depends(require_session)],
)

CODE_ACCOUNT_UNKNOWN = "account_unknown"
CODE_ACCOUNT_DUPLICATE = "account_duplicate"
CODE_CREDENTIAL_MISSING = "credential_missing"
CODE_PATH_INVALID = "path_invalid"
CODE_GATEWAY_NOT_SERVING = "gateway_not_serving"
CODE_CONFIG_UNWRITABLE = "config_unwritable"
# The vault kind a Windows account's password is stored as, and its label.
LOGIN_KIND = "login"
LOGIN_NAME = "{device} / {account}"
LOGIN_PASSWORD_FIELD = "password"


@router.get("", response_model=AccountListView)
def list_accounts(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> AccountListView:
    """Read a machine's available accounts and what the form needs beside them.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime.

    Returns:
        The rows in the order they were added, the machine's own accounts,
        its system, the gateway's models and whether the gateway serves.

    Raises:
        HTTPException: 404 ``device_unknown``.
    """
    key = _require_device(device_id).id
    return _view(runtime, key)


@router.post("/add", response_model=AccountListView)
def add_account(
    request: AccountCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> AccountListView:
    """Add an available account and push the machine's state.

    Args:
        request: The account's form.
        runtime: The shared runtime.

    Returns:
        The rows afterwards.

    Raises:
        HTTPException: 400 ``account_unknown {account}`` for an account the
            machine does not report, ``account_duplicate {account}``,
            ``credential_missing {account}`` for a Windows account with no
            password, ``path_invalid {path}`` for a path that is not
            absolute, the agent's own ``shell_program_unusable {path}``; 409
            ``gateway_not_serving`` for the AI tools turned on while the
            gateway serves no model, ``agent_offline``; 500
            ``config_unwritable``.
        VaultLockedError: When a password cannot be sealed.
    """
    key = _require_device(request.device_id).id
    store = DeviceAccountStore(runtime.desired_states)
    if store.get(key, request.account) is not None:
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_DUPLICATE, account=request.account
        )
    row = _checked_row(runtime, key, request, held=None)
    try:
        store.add(key, row)
    except ValueError:
        _delete_login(row.login_id)
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_DUPLICATE, account=request.account
        )
    except OSError as error:
        _delete_login(row.login_id)
        raise _config_unwritable(error) from error
    _settle_device_key(runtime, key)
    push_state(runtime, key)
    return _view(runtime, key)


@router.post("/set", response_model=AccountListView)
def set_account(
    request: AccountCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> AccountListView:
    """Replace an available account's row and push the machine's state.

    A new password is a new login and the old one is deleted; an empty one
    keeps the login the account has.

    Args:
        request: The account's form.
        runtime: The shared runtime.

    Returns:
        The rows afterwards.

    Raises:
        HTTPException: The refusals of ``add``; 400 ``account_unknown`` for
            an account that is not available.
        VaultLockedError: When a password cannot be sealed.
    """
    key = _require_device(request.device_id).id
    store = DeviceAccountStore(runtime.desired_states)
    held = store.get(key, request.account)
    if held is None:
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_UNKNOWN, account=request.account
        )
    row = _checked_row(runtime, key, request, held=held)
    try:
        store.replace(key, row)
    except OSError as error:
        if row.login_id != held.login_id:
            _delete_login(row.login_id)
        raise _config_unwritable(error) from error
    if row.login_id != held.login_id:
        _delete_login(held.login_id)
    _settle_device_key(runtime, key)
    push_state(runtime, key)
    return _view(runtime, key)


@router.post("/remove", response_model=AccountListView)
def remove_account(
    request: AccountRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> AccountListView:
    """Remove an available account from the machine and every module.

    Args:
        request: The device and the account.
        runtime: The shared runtime.

    Returns:
        The rows afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``; 500 ``config_unwritable``.
    """
    key = _require_device(request.device_id).id
    store = DeviceAccountStore(runtime.desired_states)
    try:
        removed = store.remove(key, request.account)
        was_enabled = runtime.desired_states.forget_account(key, request.account)
    except OSError as error:
        raise _config_unwritable(error) from error
    if removed is not None:
        _delete_login(removed.login_id)
    if set(was_enabled) & set(gateway_instance_names()):
        apply_keys()
    _settle_device_key(runtime, key)
    if runtime.agent_sessions.is_online(key):
        push_state(runtime, key)
    runtime.published_services.schedule_refresh()
    return _view(runtime, key)


def _view(runtime: PanelRuntime, key: str) -> AccountListView:
    """The machine's accounts as the page reads them."""
    store = DeviceAccountStore(runtime.desired_states)
    details = runtime.device_account_details.get(key, {})
    reported = _reported_tools(runtime, key)
    enabled_by = {
        module: set(runtime.desired_states.enabled_accounts(key, module))
        for module in account_layer_names()
    }
    models = gateway_models(runtime.served_models)
    return AccountListView(
        device_id=key,
        is_online=runtime.agent_sessions.is_online(key),
        accounts=[
            AccountView(
                account=row.account,
                has_login=bool(row.login_id),
                share_path=row.share_path,
                shell_path=row.shell_path,
                is_ai_tools_enabled=row.is_ai_tools_enabled,
                tool_configs=dict(row.tool_configs),
                modules=[
                    module
                    for module, names in enabled_by.items()
                    if row.account in names
                ],
                ai_tools=AccountToolsView(**reported.get(row.account, {})),
            )
            for row in store.accounts(key)
        ],
        system_accounts=[
            SystemAccountView(
                account=name,
                home=str((details.get(name) or {}).get("home", "") or ""),
                shell=str((details.get(name) or {}).get("shell", "") or ""),
            )
            for name in runtime.device_accounts.get(key, [])
        ],
        platform_os=str(runtime.device_platform.get(key, {}).get("os", "") or ""),
        models=models,
        is_gateway_serving=bool(models),
    )


def _reported_tools(runtime: PanelRuntime, key: str) -> dict:
    """Each account's AI tools result from the machine's last report."""
    report = runtime.agent_sessions.reports().get(key) or {}
    section = report.get("ai_tools") if isinstance(report, dict) else None
    results = {}
    for entry in (section or {}).get("accounts") or []:
        if not isinstance(entry, dict):
            continue
        params = entry.get("params")
        results[str(entry.get("account", ""))] = {
            "state": str(entry.get("state", "") or ""),
            "code": str(entry.get("code", "") or ""),
            "params": dict(params) if isinstance(params, dict) else {},
        }
    return results


def _checked_row(
    runtime: PanelRuntime, key: str, request: AccountCreate, *, held
) -> DeviceAccount:
    """The row a form amounts to, every refusal of the standard checked.

    Args:
        runtime: The shared runtime.
        key: The device.
        request: The form.
        held: The row being replaced, None on an add.

    Returns:
        The row, its login stored when the form carried a password.

    Raises:
        HTTPException: As :func:`add_account` says.
        VaultLockedError: When the password cannot be sealed.
    """
    platform = runtime.device_platform.get(key, {})
    is_windows = platform.get("os") == DEVICE_PASSWORD_OS
    reported = runtime.device_accounts.get(key, [])
    if request.account not in reported and (held is None or not reported):
        if request.account not in reported:
            raise _refusal(
                status.HTTP_400_BAD_REQUEST,
                CODE_ACCOUNT_UNKNOWN,
                account=request.account,
            )
    for path in (request.share_path, request.shell_path):
        if path and not _is_absolute(path, is_windows):
            raise _refusal(status.HTTP_400_BAD_REQUEST, CODE_PATH_INVALID, path=path)
    if is_windows and not request.password and (held is None or not held.login_id):
        raise _refusal(
            status.HTTP_400_BAD_REQUEST,
            CODE_CREDENTIAL_MISSING,
            account=request.account,
        )
    if request.is_ai_tools_enabled and not gateway_models(runtime.served_models):
        raise _refusal(status.HTTP_409_CONFLICT, CODE_GATEWAY_NOT_SERVING)
    if request.shell_path:
        _check_shell(runtime, key, request)
    login_id = held.login_id if held is not None else ""
    if request.password and is_windows:
        login_id = _store_login(key, request.account, request.password)
    return DeviceAccount(
        account=request.account,
        login_id=login_id,
        share_path=request.share_path,
        shell_path=request.shell_path,
        is_ai_tools_enabled=request.is_ai_tools_enabled,
        tool_configs=dict(request.tool_configs),
    )


def _check_shell(runtime: PanelRuntime, key: str, request: AccountCreate) -> None:
    """Ask the machine whether the shell runs, as the Terminal module's apply would.

    Raises:
        HTTPException: 409 ``agent_offline``; 400 with the agent's code,
            ``shell_program_unusable {path}`` among them.
    """
    if not runtime.agent_sessions.is_online(key):
        raise _refusal(status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=key)
    config = {
        "accounts": [{"account": request.account, "shell_path": request.shell_path}]
    }
    try:
        verdict = runtime.agent_sessions.run_stream_from_thread(
            key,
            CHANNEL_STREAM_COMMAND,
            {
                "module": DEVICE_TERMINAL_MODULE,
                "verb": CHANNEL_VERB_VALIDATE,
                "config": config,
            },
            timeout=DEVICE_MODULE_VALIDATE_TIMEOUT_S,
        )
    except AgentOfflineError:
        raise _refusal(status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=key)
    except StreamRefusedError as error:
        raise _refusal(status.HTTP_502_BAD_GATEWAY, error.code, **error.params)
    params = dict(verdict.get("params") or {})
    if verdict.get("code") or int(params.get("exit_code", 1) or 0) != 0:
        for name in ("exit_code", "output", "result"):
            params.pop(name, None)
        raise _refusal(
            status.HTTP_400_BAD_REQUEST,
            str(verdict.get("code") or "config_invalid"),
            **params,
        )


def _store_login(key: str, account: str, password: str) -> str:
    """Seal a Windows account's password as a vault login.

    Returns:
        The login's id.

    Raises:
        VaultLockedError: When the vault has no data key to seal under.
    """
    try:
        return (
            SecretVault()
            .add(
                kind=LOGIN_KIND,
                name=LOGIN_NAME.format(device=key[:8], account=account),
                secret={LOGIN_PASSWORD_FIELD: password},
            )
            .id
        )
    except (OSError, ValueError) as error:
        raise VaultLockedError() from error


def _delete_login(login_id: str) -> None:
    """Delete one login the hub stored, where there is one."""
    if not login_id:
        return
    try:
        SecretVault().delete(login_id)
    except (KeyError, OSError, ValueError):
        return


def _settle_device_key(runtime: PanelRuntime, key: str) -> None:
    """Mint the device's gateway key for its first account on the gateway,
    and revoke it once the last one is off."""
    if runtime.desired_states.is_ai_tools_enabled(key):
        device = DeviceRegistry().get(key)
        ensure_device_key(key, device.name if device else "")
        return
    revoke_device_key(key)


def _is_absolute(path: str, is_windows: bool) -> bool:
    """Whether a path is absolute in the machine's own form."""
    if is_windows:
        return len(path) >= 3 and path[1] == ":" and path[2] in "\\/"
    return path.startswith("/")


def _require_device(device_id: str):
    device = DeviceRegistry().get(device_id)
    if device is None or not device.is_managed:
        raise _refusal(
            status.HTTP_404_NOT_FOUND, CODE_DEVICE_UNKNOWN, device_id=device_id
        )
    return device


def _config_unwritable(error: OSError) -> HTTPException:
    return _refusal(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        CODE_CONFIG_UNWRITABLE,
        detail=str(error)[:200],
    )


def _refusal(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": dict(params)}
    )
