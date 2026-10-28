"""One router for every module of the account layer.

``GET /api/agent/module/<module>`` and ``POST /api/agent/module/<module>/set``
are served for each account-layer row of the description table: Terminal,
the file share, the SSH server, VS Code, code-server, CloudCLI, Codeg and
SiYuan. The view lists every available account with whether the module
enables it and what the machine reports of its instance; the set replaces
the enabled accounts, generating each newly enabled account's secrets, a
SiYuan account's gateway key among them and voided for an account it
disables, and writes ``want: running`` with it as an apply of a
configuration does (protocol.md, "The account layer in the state").
"""

import functools

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_STATE_RUNNING,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_VERB_VALIDATE,
)
from neutrino_hub.modules.clients.ai_keys import apply_keys, settle_instance_keys
from neutrino_hub.modules.devices.accounts import DeviceAccountStore
from neutrino_hub.modules.devices.constants import (
    DEVICE_AGENT_MODULES,
    DEVICE_MODULE_VALIDATE_TIMEOUT_S,
    DEVICE_SAMBA_MODULE,
    DEVICE_SSH_SERVER_MODULE,
    DEVICE_TERMINAL_MODULE,
    DEVICE_VSCODE_MODULE,
    DEVICE_VSCODE_TERMS_KEY,
    DEVICE_VSCODE_TERMS_URL,
)
from neutrino_hub.modules.devices.desired_state import smb_user
from neutrino_hub.modules.devices.folder_shares import folder_shares
from neutrino_hub.modules.devices.module_table import (
    DeviceModuleRow,
    account_layer_rows,
    gateway_instance_names,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    EnabledAccountRowView,
    EnabledAccountsUpdate,
    EnabledAccountsView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    CODE_AGENT_OFFLINE,
    DeviceModuleContext,
    device_context,
    module_router,
    push_state,
    recompose_published,
    require_online,
    require_terms,
    write_module_config,
)

CODE_ACCOUNT_UNKNOWN = "account_unknown"
CODE_ACCOUNT_DUPLICATE = "account_duplicate"
CODE_ACCOUNT_HOME_UNKNOWN = "account_home_unknown"
CODE_SHARE_NAME_TAKEN = "share_name_taken"
CODE_CONFIG_UNWRITABLE = "config_unwritable"


def device_view(
    row: DeviceModuleRow, runtime: PanelRuntime, context: DeviceModuleContext
) -> EnabledAccountsView:
    """One account-layer module on one device: every available account.

    Args:
        row: The module's row in the description table.
        runtime: The shared runtime.
        context: The device.

    Returns:
        The view: each available account with whether the module enables it,
        the port the agent took and whether the instance runs as last
        reported, and the module's own field on each row; the module's own
        view fields beside them. A file share row runs while the machine
        reports its Home share served, and the row of an enabled account
        with no share path whose home the machine has not reported carries
        ``account_home_unknown {account}``.
    """
    store = DeviceAccountStore(runtime.desired_states)
    enabled = runtime.desired_states.enabled_accounts(context.key, row.name)
    platform = runtime.device_platform.get(context.key, {})
    homes = runtime.device_account_details.get(context.key, {})
    reported = {
        str(instance.get("account", "")): instance
        for instance in context.details.get("instances") or []
        if isinstance(instance, dict)
    }
    served = {
        str(share.get("name", "") or "")
        for share in context.details.get("shares") or []
        if isinstance(share, dict)
    }
    rows = []
    for account in store.accounts(context.key):
        seen = reported.get(account.account, {})
        params = seen.get("params")
        fields = {
            "account": account.account,
            "is_enabled": account.account in enabled,
            "port": _port(seen.get("port")),
            "is_running": bool(seen.get("is_running")),
            "code": str(seen.get("code", "") or ""),
            "params": dict(params) if isinstance(params, dict) else {},
        }
        if row.name in (DEVICE_TERMINAL_MODULE, DEVICE_SSH_SERVER_MODULE):
            fields["shell_path"] = account.shell_path
        if row.name == DEVICE_SAMBA_MODULE:
            fields["share_path"] = account.share_path
            fields["user"] = smb_user(account.account, platform)
            fields["is_running"] = account.account in served
            home = str((homes.get(account.account) or {}).get("home", "") or "")
            if fields["is_enabled"] and not account.share_path and not home:
                fields["code"] = CODE_ACCOUNT_HOME_UNKNOWN
                fields["params"] = {"account": account.account}
        rows.append(EnabledAccountRowView(**fields))
    extra = {"version": str(context.details.get("version", "") or "")}
    if row.name == DEVICE_SSH_SERVER_MODULE:
        extra["host_key_fingerprint"] = str(
            context.details.get("host_key_fingerprint", "") or ""
        )
    if row.name == DEVICE_VSCODE_MODULE:
        extra["is_terms_accepted"] = bool(context.config.get(DEVICE_VSCODE_TERMS_KEY))
        extra["terms_url"] = DEVICE_VSCODE_TERMS_URL
    return EnabledAccountsView(
        **context.fields(), accounts=rows, is_active=context.is_active, **extra
    )


def replace_accounts(
    row: DeviceModuleRow, update: EnabledAccountsUpdate, runtime: PanelRuntime
) -> EnabledAccountsView:
    """Replace one module's enabled accounts on one device.

    Each newly enabled account gets the fields the row seals, generated
    once; a disabled account keeps its record for its next enabling. The
    agent checks the module's section as the state will carry it before the
    change holds, and the module is wanted running with it.

    Args:
        row: The module's row in the description table.
        update: The device and the enabled accounts, in the order checked.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 400 ``account_unknown {account}`` for an account that
            is not available, ``account_duplicate {account}``; 409
            ``terms_not_accepted {module}`` for VS Code before its terms,
            ``agent_offline``; 400 ``share_name_taken {name}`` for a file
            share account a folder share's name takes; 400 with the agent's
            code when it refuses the configuration; 500 ``config_unwritable``.
        VaultLockedError: When a secret has to be sealed and the vault is
            locked.
    """
    context = device_context(runtime, row.name, update.device_id)
    require_terms(runtime, context.key, row.name)
    require_online(context)
    available = {
        account.account
        for account in DeviceAccountStore(runtime.desired_states).accounts(context.key)
    }
    chosen: list = []
    for account in update.accounts:
        if account not in available:
            raise _refusal(
                status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_UNKNOWN, account=account
            )
        if account in chosen:
            raise _refusal(
                status.HTTP_400_BAD_REQUEST, CODE_ACCOUNT_DUPLICATE, account=account
            )
        chosen.append(account)
    if row.name == DEVICE_SAMBA_MODULE:
        _refuse_folder_share_names(chosen, context.config)
    previous = dict(context.config)
    is_keyed = row.name in gateway_instance_names()
    try:
        written = runtime.desired_states.set_enabled_accounts(
            context.key, row.name, chosen
        )
        if is_keyed:
            device = DeviceRegistry().get(context.key)
            settle_instance_keys(
                runtime.desired_states,
                context.key,
                row.name,
                device.name if device else "",
            )
            written = runtime.desired_states.read(context.key, row.name)
    except OSError as error:
        raise _config_unwritable(error) from error
    try:
        _validate(runtime, context, written)
    except HTTPException:
        write_module_config(runtime, context.key, row.name, previous)
        if is_keyed:
            apply_keys()
        raise
    context.config = written
    if row.name not in DEVICE_AGENT_MODULES:
        try:
            runtime.desired_states.set_want(
                context.key, row.name, CHANNEL_MODULE_STATE_RUNNING
            )
        except OSError as error:
            raise _config_unwritable(error) from error
    push_state(runtime, context.key)
    recompose_published(runtime, row.name)
    return device_view(row, runtime, context)


def _refuse_folder_share_names(accounts: list, stored: dict) -> None:
    """Refuse an account whose Home share would take a folder share's name.

    Raises:
        HTTPException: 400 ``share_name_taken {name}``, naming the folder
            share.
    """
    for share in folder_shares(stored):
        if any(account.lower() == share["name"].lower() for account in accounts):
            raise _refusal(
                status.HTTP_400_BAD_REQUEST, CODE_SHARE_NAME_TAKEN, name=share["name"]
            )


def _validate(runtime: PanelRuntime, context: DeviceModuleContext, config: dict):
    """Ask the agent whether the module's section holds together."""
    try:
        verdict = runtime.agent_sessions.run_stream_from_thread(
            context.key,
            CHANNEL_STREAM_COMMAND,
            {
                "module": context.module,
                "verb": CHANNEL_VERB_VALIDATE,
                "config": runtime.module_agent_config(
                    context.key, context.module, config
                ),
            },
            timeout=DEVICE_MODULE_VALIDATE_TIMEOUT_S,
        )
    except AgentOfflineError:
        raise _refusal(
            status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=context.key
        )
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


def _port(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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


def _accounts_router(row: DeviceModuleRow) -> APIRouter:
    """The router one account-layer module talks to: the read, the apply, the set."""
    router = module_router(
        row.name,
        view_model=EnabledAccountsView,
        build_view=functools.partial(device_view, row),
    )

    @router.post("/set", response_model=EnabledAccountsView)
    def update_accounts(
        update: EnabledAccountsUpdate, runtime: PanelRuntime = Depends(get_runtime)
    ):
        """Replace the enabled accounts, as :func:`replace_accounts` says."""
        return replace_accounts(row, update, runtime)

    return router


# One router per account-layer module, by module name, in the table's order.
ROUTERS = {row.name: _accounts_router(row) for row in account_layer_rows()}
