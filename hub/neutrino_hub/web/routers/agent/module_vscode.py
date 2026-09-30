"""The VS Code block: which accounts a device runs VS Code in the browser for.

Each instance is Microsoft's standalone CLI serving the web editor as one
account on one port, behind a connection token the hub generates for it once
and keeps sealed in the device's ``vscode.json``. A Windows machine starts an
instance as its account only with that account's password, so each instance
there names a login from the Credentials page. Each instance is published to
clients as a web entry they open only through their own loopback, with the
token the ``service`` stream hands them.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.constants import (
    DEVICE_VSCODE_LOGIN_KEY,
    DEVICE_VSCODE_MODULE,
    DEVICE_VSCODE_TOKEN_KEY,
)
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    VscodeConfigUpdate,
    VscodeDeviceView,
    VscodeInstanceView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    store_config,
)

MODULE = DEVICE_VSCODE_MODULE
# The platform whose instances start only with the account's password.
OS_WINDOWS = "windows"
LOGIN_KIND = "login"

CODE_ACCOUNT_DUPLICATE = "account_duplicate"
CODE_PORT_DUPLICATE = "port_duplicate"
CODE_CREDENTIAL_MISSING = "credential_missing"
CODE_UNKNOWN_CREDENTIAL = "unknown_credential"


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> VscodeDeviceView:
    """One device's VS Code: the instances and the machine's accounts.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The instances as configured, each with the login it runs as, whether
        the machine reports it running and why not, and the human accounts
        the machine last reported.
    """
    reported = {
        str(instance.get("account", "")): instance
        for instance in context.details.get("instances") or []
        if isinstance(instance, dict)
    }
    instances = []
    for instance in context.config.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        account = str(instance.get("account", ""))
        seen = reported.get(account, {})
        instances.append(
            VscodeInstanceView(
                account=account,
                port=int(instance.get("port", 0)),
                login_id=str(instance.get(DEVICE_VSCODE_LOGIN_KEY, "") or ""),
                is_running=bool(seen.get("is_running")),
                code=str(seen.get("code", "") or ""),
            )
        )
    return VscodeDeviceView(
        **context.fields(),
        instances=instances,
        accounts=[str(name) for name in runtime.device_accounts.get(context.key, [])],
        is_active=context.is_active,
    )


router: APIRouter = module_router(
    MODULE, view_model=VscodeDeviceView, build_view=device_view
)


@router.post("/set", response_model=VscodeDeviceView)
def update_settings(
    update: VscodeConfigUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> VscodeDeviceView:
    """Replace the instances.

    An instance's connection token is generated the first time its account
    is saved, and sealed beside it.

    Args:
        update: The device and its instances.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 400 ``account_duplicate`` or ``port_duplicate`` for
            two instances sharing one, ``unknown_credential`` for a login
            the vault does not hold, ``credential_missing`` for an instance
            of a Windows machine with no login; 409 ``agent_offline``; 400
            with the agent's code when it refuses the configuration.
        VaultLockedError: If a token has to be made and the vault is locked.
    """
    context = device_context(runtime, MODULE, update.device_id)
    is_windows = runtime.device_platform.get(context.key, {}).get("os") == OS_WINDOWS
    vault = SecretVault()
    accounts: set = set()
    ports: set = set()
    for instance in update.instances:
        if instance.account.lower() in accounts:
            raise _refusal(CODE_ACCOUNT_DUPLICATE, account=instance.account)
        if instance.port in ports:
            raise _refusal(CODE_PORT_DUPLICATE, port=instance.port)
        accounts.add(instance.account.lower())
        ports.add(instance.port)
        if instance.login_id:
            record = vault.get(instance.login_id)
            if record is None or record.kind != LOGIN_KIND:
                raise _refusal(CODE_UNKNOWN_CREDENTIAL, field=DEVICE_VSCODE_LOGIN_KEY)
        elif is_windows:
            raise _refusal(CODE_CREDENTIAL_MISSING, account=instance.account)
    checked = [
        {"account": instance.account, "port": instance.port}
        for instance in update.instances
    ]
    stored = [
        {
            **entry,
            DEVICE_VSCODE_LOGIN_KEY: instance.login_id,
            DEVICE_VSCODE_TOKEN_KEY: runtime.desired_states.sealed_vscode_token(
                context.key, instance.account
            ),
        }
        for entry, instance in zip(checked, update.instances)
    ]
    store_config(runtime, context, {"instances": checked}, stored={"instances": stored})
    return device_view(runtime, context)


def _refusal(code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": dict(params)},
    )
