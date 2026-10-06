"""A managed machine's AI tools: whether they use the hub's gateway.

The setting is the Modules page's Global configuration, one per machine,
kept in the device's ``ai_tools.json``. It acts on the accounts with an
instance in the machine's VS Code, CloudCLI or code-server configuration,
whose tools the agent points at the gateway with cc-switch run as each
account. Turning it on mints the device's gateway key and turning it off
revokes it; every write pushes the device's state, and the machine's report
says what each account came to.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.clients.ai_keys import (
    ensure_device_key,
    gateway_models,
    revoke_device_key,
)
from neutrino_hub.modules.devices.constants import DEVICE_AI_TOOLS_NAME
from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    AiToolAccountView,
    AiToolConfigUpdate,
    AiToolDeviceView,
    DeviceRequest,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    push_state,
    require_online,
)

CODE_GATEWAY_NOT_SERVING = "gateway_not_serving"
# An account's result in the report that a press on the chip tries again.
AI_TOOL_STATE_FAILED = "failed"
# An account's result that leaves it on the gateway.
AI_TOOL_STATE_SWITCHED = "switched"
CODE_CONFIG_UNWRITABLE = "config_unwritable"

router = APIRouter(
    prefix="/api/agent/module/ai_tool",
    tags=["module"],
    dependencies=[Depends(require_session)],
)


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> AiToolDeviceView:
    """One machine's AI tools: the setting, the gateway, each account's result.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The view, each account's result read from the machine's last report.
    """
    stored = runtime.desired_states.ai_tools(context.key)
    models = gateway_models(runtime.served_models)
    report = runtime.agent_sessions.reports().get(context.key) or {}
    section = report.get("ai_tools") if isinstance(report, dict) else None
    reported = {
        str(entry.get("account", "")): entry
        for entry in (section or {}).get("accounts") or []
        if isinstance(entry, dict)
    }
    accounts = []
    for account, _, modules in runtime.desired_states.ai_tool_accounts(context.key):
        seen = reported.get(account, {})
        accounts.append(
            AiToolAccountView(
                account=account,
                modules=list(modules),
                state=str(seen.get("state", "") or ""),
                code=str(seen.get("code", "") or ""),
                params=dict(seen.get("params") or {}),
            )
        )
    return AiToolDeviceView(
        device_id=context.key,
        is_online=context.is_online,
        is_enabled=stored["is_enabled"],
        is_in_use=_is_in_use(
            stored["is_enabled"],
            [entry.account for entry in accounts],
            reported,
        ),
        is_gateway_serving=bool(models),
        tool_configs=stored["tool_configs"],
        models=models,
        accounts=accounts,
    )


@router.get("", response_model=AiToolDeviceView)
def read_device(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> AiToolDeviceView:
    """One machine's AI tools setting.

    Args:
        device_id: The device.
        runtime: The shared runtime.

    Returns:
        The view.

    Raises:
        HTTPException: 404 ``device_unknown``.
    """
    return device_view(runtime, _context(runtime, device_id))


@router.post("/enable", response_model=AiToolDeviceView)
def enable(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> AiToolDeviceView:
    """Point the machine's AI tools at the gateway.

    On a setting already on whose machine reported an account ``failed``,
    the press puts a fresh retry mark on the section, so the agent tries
    again.

    Args:
        request: The device.
        runtime: The shared runtime.

    Returns:
        The view afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``; 409 ``agent_offline``; 409
            ``gateway_not_serving`` while the gateway serves no model; 500
            ``config_unwritable``.
        VaultLockedError: When the device's key cannot be minted.
    """
    context = _context(runtime, request.device_id)
    require_online(context)
    if not gateway_models(runtime.served_models):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": CODE_GATEWAY_NOT_SERVING, "params": {}},
        )
    if ensure_device_key(context.key, context.device.name) is None:
        raise VaultLockedError()
    is_retried = runtime.desired_states.is_ai_tools_enabled(
        context.key
    ) and _has_failed_account(runtime, context.key)
    _write(runtime, context.key, is_enabled=True)
    if is_retried:
        try:
            DeviceRetryMarks().mark(context.key, DEVICE_AI_TOOLS_NAME)
        except OSError as error:
            raise _unwritable(error) from error
    push_state(runtime, context.key)
    return device_view(runtime, context)


@router.post("/disable", response_model=AiToolDeviceView)
def disable(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> AiToolDeviceView:
    """Point the machine's AI tools back where they were.

    On a setting already off whose machine reported an account ``failed``,
    a switch back that could not run, the press puts a fresh retry mark on
    the section, so the agent tries again.

    Args:
        request: The device.
        runtime: The shared runtime.

    Returns:
        The view afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``; 409 ``agent_offline``; 500
            ``config_unwritable``.
    """
    context = _context(runtime, request.device_id)
    require_online(context)
    is_retried = not runtime.desired_states.is_ai_tools_enabled(
        context.key
    ) and _has_failed_account(runtime, context.key)
    _write(runtime, context.key, is_enabled=False)
    revoke_device_key(context.key)
    if is_retried:
        try:
            DeviceRetryMarks().mark(context.key, DEVICE_AI_TOOLS_NAME)
        except OSError as error:
            raise _unwritable(error) from error
    push_state(runtime, context.key)
    return device_view(runtime, context)


@router.post("/set", response_model=AiToolDeviceView)
def set_tool_configs(
    update: AiToolConfigUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> AiToolDeviceView:
    """Replace the tool choices.

    Args:
        update: The device and its choices, cleaned as the client cleans
            them.
        runtime: The shared runtime.

    Returns:
        The view afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``; 409 ``agent_offline``; 500
            ``config_unwritable``.
    """
    context = _context(runtime, update.device_id)
    require_online(context)
    held = _write(runtime, context.key, tool_configs=update.tool_configs)
    if held["is_enabled"]:
        push_state(runtime, context.key)
    return device_view(runtime, context)


def _is_in_use(is_enabled: bool, listed: list, reported: dict) -> bool:
    """Whether any account of the machine is still on the gateway.

    Args:
        is_enabled: The stored setting.
        listed: The accounts the setting acts on.
        reported: Each account's result as the machine last reported it.

    Returns:
        True for an account ``switched``, one ``failed`` while the setting
        is off, since its switch back could not run, and one not reported
        while the setting is on; with no account at all, the setting.
    """
    if not listed and not reported:
        return is_enabled
    for entry in reported.values():
        state = entry.get("state")
        if state == AI_TOOL_STATE_SWITCHED:
            return True
        if state == AI_TOOL_STATE_FAILED and not is_enabled:
            return True
    return is_enabled and any(account not in reported for account in listed)


def _has_failed_account(runtime: PanelRuntime, key: str) -> bool:
    """Whether the machine's last report has an account ``failed``."""
    report = runtime.agent_sessions.reports().get(key) or {}
    section = report.get("ai_tools") if isinstance(report, dict) else None
    return any(
        isinstance(entry, dict) and entry.get("state") == AI_TOOL_STATE_FAILED
        for entry in (section or {}).get("accounts") or []
    )


def _context(runtime: PanelRuntime, device_id: str) -> DeviceModuleContext:
    return device_context(runtime, DEVICE_AI_TOOLS_NAME, device_id)


def _write(runtime: PanelRuntime, key: str, **fields) -> dict:
    """Write the setting; a ``config/`` that cannot be written is a 500."""
    try:
        return runtime.desired_states.set_ai_tools(key, **fields)
    except OSError as error:
        raise _unwritable(error) from error


def _unwritable(error: OSError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": CODE_CONFIG_UNWRITABLE,
            "params": {"detail": str(error)[:200]},
        },
    )
