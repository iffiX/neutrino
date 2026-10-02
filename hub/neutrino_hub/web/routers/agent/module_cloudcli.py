"""The CloudCLI block: which accounts a device runs CloudCLI for.

Each instance is CloudCLI serving one account's AI coding sessions in the
browser, behind the agent's forwarder on one port. The hub generates each
instance's administrator password and token secret once and keeps both
sealed in the device's ``cloudcli.json``; the agent receives them opened. A
Windows machine starts an instance as its account only with that account's
password, so each instance there names a login from the Credentials page.
Saving the instances gives the device its own key to the AI gateway. Each
instance is published to clients as a web entry they open at the device's
address with a token the ``service`` stream mints for one open.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.clients.ai_keys import device_gateway, ensure_device_key
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.constants import (
    DEVICE_CLOUDCLI_LOGIN_KEY,
    DEVICE_CLOUDCLI_MODULE,
    DEVICE_CLOUDCLI_PASSWORD_KEY,
    DEVICE_CLOUDCLI_SECRET_KEY,
)
from neutrino_hub.modules.devices.desired_state import cloudcli_agent_config
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    CloudcliConfigUpdate,
    CloudcliDeviceView,
    CloudcliInstanceView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    store_config,
)

MODULE = DEVICE_CLOUDCLI_MODULE
# The platform whose instances start only with the account's password.
OS_WINDOWS = "windows"
LOGIN_KIND = "login"

CODE_ACCOUNT_DUPLICATE = "account_duplicate"
CODE_PORT_DUPLICATE = "port_duplicate"
CODE_CREDENTIAL_MISSING = "credential_missing"
CODE_UNKNOWN_CREDENTIAL = "unknown_credential"


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> CloudcliDeviceView:
    """One device's CloudCLI: the instances and the machine's accounts.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The instances as configured, each with the login it runs as, whether
        the machine reports it answering and why not, and the human accounts
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
            CloudcliInstanceView(
                account=account,
                port=int(instance.get("port", 0)),
                login_id=str(instance.get(DEVICE_CLOUDCLI_LOGIN_KEY, "") or ""),
                is_running=bool(seen.get("is_running")),
                code=str(seen.get("code", "") or ""),
            )
        )
    return CloudcliDeviceView(
        **context.fields(),
        instances=instances,
        accounts=[str(name) for name in runtime.device_accounts.get(context.key, [])],
        is_active=context.is_active,
    )


router: APIRouter = module_router(
    MODULE, view_model=CloudcliDeviceView, build_view=device_view
)


@router.post("/set", response_model=CloudcliDeviceView)
def update_settings(
    update: CloudcliConfigUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> CloudcliDeviceView:
    """Replace the instances.

    An instance's password and token secret are generated the first time
    its account is saved, and sealed beside it; the device's gateway key is
    minted when it holds none. The agent checks the instances as it will
    receive them: each with both secrets opened, the gateway and the
    device's key, and on Windows its login's password.

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
        VaultLockedError: If a secret has to be made and the vault is locked.
    """
    context = device_context(runtime, MODULE, update.device_id)
    platform = runtime.device_platform.get(context.key, {})
    is_windows = platform.get("os") == OS_WINDOWS
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
                raise _refusal(CODE_UNKNOWN_CREDENTIAL, field=DEVICE_CLOUDCLI_LOGIN_KEY)
        elif is_windows:
            raise _refusal(CODE_CREDENTIAL_MISSING, account=instance.account)
    stored = {
        "instances": [
            {
                "account": instance.account,
                "port": instance.port,
                DEVICE_CLOUDCLI_LOGIN_KEY: instance.login_id,
                **{
                    field: runtime.desired_states.sealed_cloudcli_secret(
                        context.key, instance.account, field
                    )
                    for field in (
                        DEVICE_CLOUDCLI_PASSWORD_KEY,
                        DEVICE_CLOUDCLI_SECRET_KEY,
                    )
                },
            }
            for instance in update.instances
        ]
    }
    ensure_device_key(context.key, context.device.name)
    scope = runtime.device_scope.get(context.key)
    sent = cloudcli_agent_config(
        stored,
        platform,
        device_gateway(context.key, scope.hub_address if scope is not None else ""),
    )
    store_config(runtime, context, sent, stored=stored)
    return device_view(runtime, context)


def _refusal(code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": dict(params)},
    )
