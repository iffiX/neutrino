"""The code-server block: which accounts a device runs code-server for.

Each instance is code-server serving one account's editor in the browser,
behind the agent's forwarder on one port. The hub generates each
instance's token secret once and keeps it sealed in the device's
``code_server.json``; the agent receives it opened. Each instance is
published to clients as a web entry they open with a token the ``service``
stream mints for one open.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.constants import (
    DEVICE_CODE_SERVER_MODULE,
    DEVICE_CODE_SERVER_SECRET_KEY,
)
from neutrino_hub.modules.devices.desired_state import code_server_agent_config
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    CodeServerConfigUpdate,
    CodeServerDeviceView,
    CodeServerInstanceView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    store_config,
)

MODULE = DEVICE_CODE_SERVER_MODULE

CODE_ACCOUNT_DUPLICATE = "account_duplicate"
CODE_PORT_DUPLICATE = "port_duplicate"


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> CodeServerDeviceView:
    """One device's code-server: the release, the instances and the machine's accounts.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The release the machine reports, the instances as configured, each
        with whether the machine reports it answering and why not, and the
        human accounts the machine last reported.
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
            CodeServerInstanceView(
                account=account,
                port=int(instance.get("port", 0)),
                is_running=bool(seen.get("is_running")),
                code=str(seen.get("code", "") or ""),
            )
        )
    return CodeServerDeviceView(
        **context.fields(),
        version=str(context.details.get("version", "") or ""),
        instances=instances,
        accounts=[str(name) for name in runtime.device_accounts.get(context.key, [])],
        is_active=context.is_active,
    )


router: APIRouter = module_router(
    MODULE, view_model=CodeServerDeviceView, build_view=device_view
)


@router.post("/set", response_model=CodeServerDeviceView)
def update_settings(
    update: CodeServerConfigUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> CodeServerDeviceView:
    """Replace the instances.

    An instance's token secret is generated the first time its account is
    saved, and sealed beside it. The agent checks the instances as it will
    receive them, each with its secret opened.

    Args:
        update: The device and its instances.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 400 ``account_duplicate`` or ``port_duplicate`` for
            two instances sharing one; 409 ``agent_offline``; 400 with the
            agent's code when it refuses the configuration.
        VaultLockedError: If a secret has to be made and the vault is locked.
    """
    context = device_context(runtime, MODULE, update.device_id)
    accounts: set = set()
    ports: set = set()
    for instance in update.instances:
        if instance.account.lower() in accounts:
            raise _refusal(CODE_ACCOUNT_DUPLICATE, account=instance.account)
        if instance.port in ports:
            raise _refusal(CODE_PORT_DUPLICATE, port=instance.port)
        accounts.add(instance.account.lower())
        ports.add(instance.port)
    stored = {
        "instances": [
            {
                "account": instance.account,
                "port": instance.port,
                DEVICE_CODE_SERVER_SECRET_KEY: (
                    runtime.desired_states.sealed_code_server_secret(
                        context.key, instance.account
                    )
                ),
            }
            for instance in update.instances
        ]
    }
    store_config(runtime, context, code_server_agent_config(stored), stored=stored)
    return device_view(runtime, context)


def _refusal(code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": dict(params)},
    )
