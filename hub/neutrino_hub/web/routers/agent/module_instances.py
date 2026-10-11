"""One router for every program run as a person's account.

``GET /api/agent/module/<module>`` and ``POST /api/agent/module/<module>/set``
are served for each row of that kind in the description table, with the
module's own view and body models. Each instance is one account on one port
behind the agent's forwarder, and the hub generates the fields the row seals
the first time the account is saved and keeps them sealed in the device's
file; the agent checks the instances as the state will carry them, the
seals opened and, on a Windows machine, each login's password.
"""

import functools

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.constants import (
    DEVICE_INSTANCE_LOGIN_KEY,
    DEVICE_VSCODE_TERMS_KEY,
    DEVICE_VSCODE_TERMS_URL,
)
from neutrino_hub.modules.devices.module_table import (
    DeviceModuleRow,
    account_program_rows,
)
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    CloudcliConfigUpdate,
    CloudcliDeviceView,
    CloudcliInstanceView,
    CodeServerConfigUpdate,
    CodeServerDeviceView,
    CodeServerInstanceView,
    VscodeConfigUpdate,
    VscodeDeviceView,
    VscodeInstanceView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    require_terms,
    store_config,
)

# The platform whose instances start only with the account's password.
OS_WINDOWS = "windows"
LOGIN_KIND = "login"

CODE_ACCOUNT_DUPLICATE = "account_duplicate"
CODE_PORT_DUPLICATE = "port_duplicate"
CODE_CREDENTIAL_MISSING = "credential_missing"
CODE_UNKNOWN_CREDENTIAL = "unknown_credential"

# Each module's own models: the device view, one instance of it, and the
# body of a set. A view field beyond the shared ones is filled when the
# model declares it.
MODELS = {
    "vscode": (VscodeDeviceView, VscodeInstanceView, VscodeConfigUpdate),
    "code_server": (
        CodeServerDeviceView,
        CodeServerInstanceView,
        CodeServerConfigUpdate,
    ),
    "cloudcli": (CloudcliDeviceView, CloudcliInstanceView, CloudcliConfigUpdate),
}
# The view fields a module's model may declare beyond the shared ones.
VIEW_FIELD_VERSION = "version"
VIEW_FIELD_TERMS = "is_terms_accepted"


def device_view(row: DeviceModuleRow, runtime: PanelRuntime, context):
    """One device's module: the instances and the machine's accounts.

    Args:
        row: The module's row in the description table.
        runtime: The shared runtime.
        context: The device.

    Returns:
        The module's own view: the instances as configured, each with
        whether the machine reports it running and why not, and the login it
        runs as where the row names one; the human accounts the machine last
        reported; the release the machine reports where the view declares
        ``version``; and whether the person accepted the terms, with their
        address, where it declares ``is_terms_accepted``.
    """
    view_model, instance_model, _ = MODELS[row.name]
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
        fields = {
            "account": account,
            "port": int(instance.get("port", 0)),
            "is_running": bool(seen.get("is_running")),
            "code": str(seen.get("code", "") or ""),
        }
        if row.is_login_named:
            fields[DEVICE_INSTANCE_LOGIN_KEY] = str(
                instance.get(DEVICE_INSTANCE_LOGIN_KEY, "") or ""
            )
        instances.append(instance_model(**fields))
    extra = {}
    if VIEW_FIELD_VERSION in view_model.model_fields:
        extra[VIEW_FIELD_VERSION] = str(context.details.get("version", "") or "")
    if VIEW_FIELD_TERMS in view_model.model_fields:
        extra[VIEW_FIELD_TERMS] = bool(context.config.get(DEVICE_VSCODE_TERMS_KEY))
        extra["terms_url"] = DEVICE_VSCODE_TERMS_URL
    return view_model(
        **context.fields(),
        instances=instances,
        accounts=[str(name) for name in runtime.device_accounts.get(context.key, [])],
        is_active=context.is_active,
        **extra,
    )


def replace_instances(row: DeviceModuleRow, update, runtime: PanelRuntime):
    """Replace one module's instances on one device.

    Each field the row seals is generated the first time its account is
    saved, and sealed beside it; the file's other fields, VS Code's terms
    acceptance among them, stay. The agent checks the instances as it will
    receive them.

    Args:
        row: The module's row in the description table.
        update: The device and its instances, the module's own body model.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 400 ``account_duplicate`` or ``port_duplicate`` for
            two instances sharing one; for a row that names a login, 400
            ``unknown_credential`` for a login the vault does not hold and
            ``credential_missing`` for an instance of a Windows machine with
            no login; 409 ``terms_not_accepted`` for VS Code before the
            person accepted the terms on this machine; 409
            ``agent_offline``; 400 with the agent's code when it refuses
            the configuration.
        VaultLockedError: If a seal has to be made and the vault is locked.
    """
    context = device_context(runtime, row.name, update.device_id)
    require_terms(runtime, context.key, row.name)
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
        if not row.is_login_named:
            continue
        if instance.login_id:
            record = vault.get(instance.login_id)
            if record is None or record.kind != LOGIN_KIND:
                raise _refusal(CODE_UNKNOWN_CREDENTIAL, field=DEVICE_INSTANCE_LOGIN_KEY)
        elif is_windows:
            raise _refusal(CODE_CREDENTIAL_MISSING, account=instance.account)
    stored = {key: value for key, value in context.config.items() if key != "instances"}
    stored["instances"] = [
        _record(row, runtime, context, instance) for instance in update.instances
    ]
    store_config(runtime, context, stored)
    return device_view(row, runtime, context)


def _record(
    row: DeviceModuleRow, runtime: PanelRuntime, context: DeviceModuleContext, instance
) -> dict:
    """One instance as the module's file stores it: its fields, then its seals."""
    record = {"account": instance.account, "port": instance.port}
    if row.is_login_named:
        record[DEVICE_INSTANCE_LOGIN_KEY] = instance.login_id
    for sealed in row.sealed_fields:
        record[sealed.key] = runtime.desired_states.sealed_instance_field(
            context.key, row.name, instance.account, sealed.key
        )
    return record


def _refusal(code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": dict(params)},
    )


def _instances_router(row: DeviceModuleRow) -> APIRouter:
    """The router one module of the kind talks to: the read, the apply, the set."""
    view_model, _, update_model = MODELS[row.name]
    router = module_router(
        row.name,
        view_model=view_model,
        build_view=functools.partial(device_view, row),
    )

    @router.post("/set", response_model=view_model)
    def update_settings(
        update: update_model, runtime: PanelRuntime = Depends(get_runtime)
    ):
        """Replace the instances, as :func:`replace_instances` says."""
        return replace_instances(row, update, runtime)

    return router


# One router per program run as an account, by module name, in the table's
# order.
ROUTERS = {row.name: _instances_router(row) for row in account_program_rows()}
