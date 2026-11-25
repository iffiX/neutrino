"""The machine page's Available accounts: one form per account of a machine.

An available account is one of the machine's accounts the person added,
with what every feature of the account layer needs to know of it
(agent/accounts.md, "Available accounts"): on Windows its password as a
vault login, the folder its share serves, the shell its terminal and SSH
server start, and whether its AI tools use the hub's gateway. The rows live
in ``config/devices/<id>/accounts.json``. Every account added is tested by
the agent first; the first one added to a machine with no default account
becomes the default, enabled in Terminal, the SSH server and every installed
module of the account layer. Removing one takes it out of every module that
enables it and deletes what the hub generated for it; the default is never
removed.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_VERB_ACCOUNT_TEST,
    CHANNEL_VERB_VALIDATE,
)
from neutrino_hub.modules.clients.ai_keys import (
    apply_keys,
    ensure_device_key,
    gateway_models,
    revoke_device_key,
    settle_instance_keys,
    settle_module_keys,
)
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.constants import (
    DEVICE_ACCOUNTS_NAME,
    DEVICE_LOGIN_KIND,
    DEVICE_LOGIN_NAME,
    DEVICE_LOGIN_PASSWORD_FIELD,
    DEVICE_PASSWORD_OS,
    DEVICE_SAMBA_MODULE,
    DEVICE_TERMINAL_MODULE,
)
from neutrino_hub.modules.devices.module_table import (
    account_layer_names,
    gateway_instance_names,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
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
    CODE_COMMAND_FAILED,
    CODE_DEVICE_UNKNOWN,
    account_home,
    ask_machine,
    push_state,
    require_share_folder,
)

router = APIRouter(
    prefix="/api/agent/module/account",
    tags=["module"],
    dependencies=[Depends(require_session)],
)

CODE_ACCOUNT_UNKNOWN = "account_unknown"
CODE_ACCOUNT_DUPLICATE = "account_duplicate"
CODE_ACCOUNT_IS_DEFAULT = "account_is_default"
CODE_CREDENTIAL_MISSING = "credential_missing"
CODE_PATH_INVALID = "path_invalid"
CODE_GATEWAY_NOT_SERVING = "gateway_not_serving"
CODE_CONFIG_UNWRITABLE = "config_unwritable"


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
    """Test an account, add it as available and push the machine's state.

    On a machine with no default account the account becomes the default:
    it is enabled first in Terminal, the SSH server and every module of the
    account layer whose ``want`` is neither empty nor ``absent``, with its
    secrets generated, and the container modules' keys follow its AI switch.
    The agent checks each changed module's section first, and a refusal
    writes nothing.

    Args:
        request: The account's form.
        runtime: The shared runtime.

    Returns:
        The rows afterwards.

    Raises:
        HTTPException: 400 ``account_unknown {account}`` for an account the
            machine does not report, ``account_duplicate {account}``,
            ``credential_missing {account}`` for a Windows account with no
            password, the test's ``credential_invalid {account}``,
            ``account_logon_refused {account, detail}`` and
            ``account_no_login {account}``, ``path_invalid {path}`` for a
            path that is not absolute, the agent's own
            ``shell_program_unusable {path}``, ``share_path_missing {name,
            path}`` or ``share_path_link {name, path}`` for a share path the
            machine reads as no real folder, the agent's refusal of a
            changed module's section; 409 ``gateway_not_serving`` for the AI
            tools turned on while the gateway serves no model,
            ``agent_offline``; 500 ``config_unwritable``.
        VaultLockedError: When a password or a secret cannot be sealed.
    """
    key = _require_device(request.device_id).id
    store = DeviceAccountStore(runtime.desired_states)
    if store.get(key, request.account) is not None:
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_DUPLICATE, account=request.account
        )
    is_default = not store.default_account(key)
    modules = runtime.desired_states.default_modules(key) if is_default else []
    row = _checked_row(
        runtime,
        key,
        request,
        held=None,
        is_shared=DEVICE_SAMBA_MODULE in modules,
    )
    previous = {
        name: runtime.desired_states.read(key, name)
        for name in (DEVICE_ACCOUNTS_NAME, *modules)
    }
    try:
        with CONFIG_WRITE_LOCK:
            store.add(key, row, is_default=is_default)
            written = {
                module: runtime.desired_states.enable_default(key, module)
                for module in modules
            }
    except ValueError:
        _delete_login(row.login_id)
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_DUPLICATE, account=request.account
        )
    except (OSError, VaultLockedError) as error:
        _undo_add(runtime, key, row.login_id, previous)
        if isinstance(error, VaultLockedError):
            raise
        raise _config_unwritable(error) from error
    try:
        for module, config in written.items():
            _validate_section(runtime, key, module, config)
    except HTTPException:
        _undo_add(runtime, key, row.login_id, previous)
        raise
    if is_default:
        _settle_gateway_keys(runtime, key)
    _settle_device_key(runtime, key)
    push_state(runtime, key)
    if modules:
        runtime.published_services.schedule_refresh()
    return _view(runtime, key)


@router.post("/set", response_model=AccountListView)
def set_account(
    request: AccountCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> AccountListView:
    """Replace an available account's row and push the machine's state.

    A new password is tested first, as ``add`` tests one, and is a new
    login, the old one deleted; an empty one keeps the login the account
    has. An AI switch changed settles the account's SiYuan key, and on the
    default account the container modules' keys.

    Args:
        request: The account's form.
        runtime: The shared runtime.

    Returns:
        The rows afterwards.

    Raises:
        HTTPException: The refusals of ``add``, the folder read also of
            the account's home for an empty share path while the file share
            enables it; 400 ``account_unknown`` for an account that is not
            available.
        VaultLockedError: When a password cannot be sealed.
    """
    key = _require_device(request.device_id).id
    store = DeviceAccountStore(runtime.desired_states)
    held = store.get(key, request.account)
    if held is None:
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_UNKNOWN, account=request.account
        )
    is_shared = request.account in (
        runtime.desired_states.enabled_accounts(key, DEVICE_SAMBA_MODULE)
    )
    row = _checked_row(runtime, key, request, held=held, is_shared=is_shared)
    try:
        store.replace(key, row)
    except OSError as error:
        if row.login_id != held.login_id:
            _delete_login(row.login_id)
        raise _config_unwritable(error) from error
    if row.login_id != held.login_id:
        _delete_login(held.login_id)
    if row.is_ai_tools_enabled != held.is_ai_tools_enabled:
        _settle_gateway_keys(runtime, key)
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
        HTTPException: 400 ``account_is_default {account}`` for the
            machine's default account; 404 ``device_unknown``; 500
            ``config_unwritable``.
    """
    key = _require_device(request.device_id).id
    store = DeviceAccountStore(runtime.desired_states)
    if request.account and request.account == store.default_account(key):
        raise _refusal(
            status.HTTP_400_BAD_REQUEST,
            CODE_ACCOUNT_IS_DEFAULT,
            account=request.account,
        )
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
    reported = reported_tools(runtime, key)
    enabled_by = {
        module: set(runtime.desired_states.enabled_accounts(key, module))
        for module in account_layer_names()
    }
    models = gateway_models(runtime.served_models)
    return AccountListView(
        device_id=key,
        is_online=runtime.agent_sessions.is_online(key),
        default_account=store.default_account(key),
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


def reported_tools(runtime: PanelRuntime, key: str) -> dict:
    """Each account's AI tools result from the machine's last report.

    Args:
        runtime: The shared runtime.
        key: The device.

    Returns:
        Account to ``{state, code, params}``, for each account the report's
        ``ai_tools`` section names.
    """
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
    runtime: PanelRuntime,
    key: str,
    request: AccountCreate,
    *,
    held,
    is_shared: bool = False,
) -> DeviceAccount:
    """The row a form amounts to, every refusal of the standard checked.

    An added account, and a new Windows password, are tested by the agent's
    ``account_test`` before anything is stored.

    Args:
        runtime: The shared runtime.
        key: The device.
        request: The form.
        held: The row being replaced, None on an add.
        is_shared: Whether the file share enables the account once written,
            so its home is read for an empty share path.

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
        if path and not is_machine_path_absolute(path, is_windows):
            raise _refusal(status.HTTP_400_BAD_REQUEST, CODE_PATH_INVALID, path=path)
    if is_windows and not request.password and (held is None or not held.login_id):
        raise _refusal(
            status.HTTP_400_BAD_REQUEST,
            CODE_CREDENTIAL_MISSING,
            account=request.account,
        )
    if request.is_ai_tools_enabled and not gateway_models(runtime.served_models):
        raise _refusal(status.HTTP_409_CONFLICT, CODE_GATEWAY_NOT_SERVING)
    if held is None or (is_windows and request.password):
        test_account(
            runtime, key, request.account, request.password if is_windows else ""
        )
    if request.shell_path:
        _check_shell(runtime, key, request)
    folder = request.share_path
    if not folder and is_shared:
        folder = account_home(runtime, key, request.account)
    if folder:
        require_share_folder(runtime, key, name=request.account, path=folder)
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
    config = {
        "accounts": [{"account": request.account, "shell_path": request.shell_path}]
    }
    ask_machine(
        runtime,
        key,
        {
            "module": DEVICE_TERMINAL_MODULE,
            "verb": CHANNEL_VERB_VALIDATE,
            "config": config,
        },
        fallback_code="config_invalid",
    )


def test_account(runtime: PanelRuntime, key: str, account: str, password: str) -> None:
    """Have the machine's agent test an account before it is written.

    On Windows one logon with the password; on Linux and macOS the account's
    login shell and its home (agent/accounts.md, "Available accounts").

    Args:
        runtime: The shared runtime.
        key: The device.
        account: The account.
        password: Its password on Windows; empty elsewhere.

    Raises:
        HTTPException: 409 ``agent_offline``; 400 with the test's code,
            ``credential_invalid {account}``, ``account_logon_refused
            {account, detail}`` or ``account_no_login {account}``; 502 when
            the stream is refused.
    """
    ask_machine(
        runtime,
        key,
        {
            "module": CHANNEL_COMMAND_MODULE_AGENT,
            "verb": CHANNEL_VERB_ACCOUNT_TEST,
            "account": account,
            "password": password,
        },
        fallback_code=CODE_COMMAND_FAILED,
    )


def _validate_section(runtime: PanelRuntime, key: str, module: str, config: dict):
    """Ask the agent whether one module's section holds together as written.

    Raises:
        HTTPException: As :func:`ask_machine` says, with the agent's code.
    """
    ask_machine(
        runtime,
        key,
        {
            "module": module,
            "verb": CHANNEL_VERB_VALIDATE,
            "config": runtime.module_agent_config(key, module, config),
        },
        fallback_code="config_invalid",
    )


def _undo_add(runtime: PanelRuntime, key: str, login_id: str, previous: dict) -> None:
    """Put back each file an add wrote, as it was, and delete the login it stored.

    Args:
        runtime: The shared runtime.
        key: The device.
        login_id: The vault login the add stored; empty for none.
        previous: File name, ``accounts`` or a module's, to what it held
            before the add.
    """
    try:
        with CONFIG_WRITE_LOCK:
            for name, config in previous.items():
                runtime.desired_states.write(key, name, config)
    except OSError:
        pass
    _delete_login(login_id)


def _settle_gateway_keys(runtime: PanelRuntime, key: str) -> None:
    """Give the keys of SiYuan's accounts and of the container modules the AI switches as they stand.

    Raises:
        HTTPException: 500 ``config_unwritable``.
    """
    device = DeviceRegistry().get(key)
    name = device.name if device else ""
    try:
        for module in gateway_instance_names():
            if runtime.desired_states.read(key, module):
                settle_instance_keys(runtime.desired_states, key, module, name)
        settle_module_keys(runtime.desired_states, key, name)
    except OSError as error:
        raise _config_unwritable(error) from error


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
                kind=DEVICE_LOGIN_KIND,
                name=DEVICE_LOGIN_NAME.format(device=key[:8], account=account),
                secret={DEVICE_LOGIN_PASSWORD_FIELD: password},
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


def is_machine_path_absolute(path: str, is_windows: bool) -> bool:
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
