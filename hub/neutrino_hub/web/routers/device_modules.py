"""One door for every device-hosted module page.

The file share, the git server, the container engine and ZFS are hosted by
devices, one desired state per device per module under ``config/``. Each
module's router is built here: the device list, the selection of which
devices host the module, and the per-device read, plus the helpers the
module's own sub-routes share: a configuration is checked on the agent
before it is stored and pushed, and an imperative verb runs on the agent to
its close and answers the device's fresh view.

Every refusal is ``{code, params}``; a device whose agent holds no socket
cannot be edited or driven, and says so with ``agent_offline``.
"""

from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.agent_module_controller import (
    ORDER_ACTION_INSTALL,
    ORDER_ACTION_UNINSTALL,
    ask_module,
)
from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.devices.constants import (
    DEVICE_MODULE_COMMAND_TIMEOUT_S,
    DEVICE_MODULE_REPORT_WAIT_S,
    DEVICE_MODULE_VALIDATE_TIMEOUT_S,
)
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.registry import DeviceRegistry, ManagedDevice
from neutrino_hub.modules.services.constants import SERVICES_PUBLISHED_MODULES
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ApplyResult,
    ModuleDeviceListView,
    ModuleDeviceSelection,
    ModuleDeviceView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

CODE_AGENT_OFFLINE = "agent_offline"
CODE_DEVICE_UNKNOWN = "device_unknown"
CODE_COMMAND_FAILED = "command_failed"

# What the row draws while an order stands, before the machine reports it.
ORDER_STEP_STATES = {
    ORDER_ACTION_INSTALL: "installing",
    ORDER_ACTION_UNINSTALL: "uninstalling",
}


@dataclass
class DeviceModuleContext:
    """One device as a module's routes see it.

    Attributes:
        key: The device key.
        device: The stored device.
        module: The module name.
        config: The module's stored configuration for this device.
        is_enabled: Whether the device should host the module.
        is_online: Whether its agent holds a socket.
        host: Where the device is.
        state: The module's state on the machine, as last reported.
        code: Why it failed, typed.
        params: What the wording names.
        details: The live reads the last report carried.
    """

    key: str
    device: ManagedDevice
    module: str
    config: dict = field(default_factory=dict)
    is_enabled: bool = False
    is_online: bool = False
    host: str = ""
    state: str = "unknown"
    code: str = ""
    params: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)

    def fields(self) -> dict:
        """What every per-device view carries beside its own fields."""
        return {
            "device_id": self.key,
            "host": self.host,
            "is_online": self.is_online,
            "state": self.state,
            "code": self.code,
            "params": dict(self.params),
        }


def module_router(module: str, *, view_model, build_view) -> APIRouter:
    """The router one device-hosted module's page talks to.

    Args:
        module: The module name, which is the path prefix.
        view_model: The per-device response model.
        build_view: Called with ``(runtime, context)``; returns the
            per-device view.

    Returns:
        A router carrying the device list, the selection and the
        per-device read, for the module's own sub-routes to join.
    """
    router = APIRouter(
        prefix=f"/api/{module}", tags=[module], dependencies=[Depends(require_session)]
    )

    @router.get("", response_model=ModuleDeviceListView)
    def list_devices(runtime: PanelRuntime = Depends(get_runtime)):
        return device_list(runtime, module)

    @router.put("/devices", response_model=ModuleDeviceListView)
    def select_devices(
        selection: ModuleDeviceSelection, runtime: PanelRuntime = Depends(get_runtime)
    ):
        return select_hosts(runtime, module, selection.device_ids)

    @router.get("/devices/{device_id}", response_model=view_model)
    def read_device(device_id: str, runtime: PanelRuntime = Depends(get_runtime)):
        return build_view(runtime, device_context(runtime, module, device_id))

    @router.post("/devices/{device_id}/apply", response_model=ApplyResult)
    def apply_device(device_id: str, runtime: PanelRuntime = Depends(get_runtime)):
        context = device_context(runtime, module, device_id)
        require_online(context)
        push_state(runtime, context.key)
        return ApplyResult(is_applied=True, message="pushed")

    return router


def device_list(runtime: PanelRuntime, module: str) -> ModuleDeviceListView:
    """Every stored device with an agent, and where the module stands on it.

    Args:
        runtime: The shared runtime.
        module: The module name.

    Returns:
        The rows, the hub box's own first, then by name.
    """
    rows = []
    for device in DeviceRegistry().all_stored():
        if not device.is_managed:
            continue
        key = device.mac_address.lower()
        state, code, params, _ = module_status(runtime, key, module)
        rows.append(
            ModuleDeviceView(
                device_id=key,
                name=device.name or runtime.client_hostname.get(key, "") or key,
                hostname=runtime.client_hostname.get(key, ""),
                is_online=runtime.agent_sessions.is_online(key),
                is_enabled=runtime.desired_states.is_enabled(key, module),
                state=state,
                code=code,
                params=params,
            )
        )
    rows.sort(key=_hub_first(runtime))
    return ModuleDeviceListView(devices=rows)


def select_hosts(
    runtime: PanelRuntime, module: str, device_ids: list
) -> ModuleDeviceListView:
    """Make exactly these devices host the module.

    A device newly on is ordered an install, one dropped an uninstall, and
    each changed device is handed its new state. A changed device whose
    agent is offline refuses the whole selection before anything is
    written.

    Args:
        runtime: The shared runtime.
        module: The module name.
        device_ids: The whole set of devices that should host it.

    Returns:
        The device list afterwards.

    Raises:
        HTTPException: 404 ``device_unknown`` for an id no managed device
            answers to, 409 ``agent_offline`` naming a changed device with
            no socket.
    """
    wanted = {str(device_id).lower() for device_id in device_ids}
    stored = {
        device.mac_address.lower(): device
        for device in DeviceRegistry().all_stored()
        if device.is_managed
    }
    for key in sorted(wanted - set(stored)):
        raise _refusal(status.HTTP_404_NOT_FOUND, CODE_DEVICE_UNKNOWN, device_id=key)
    changed = [
        key
        for key in sorted(stored)
        if (key in wanted) != runtime.desired_states.is_enabled(key, module)
    ]
    for key in changed:
        if not runtime.agent_sessions.is_online(key):
            raise _refusal(status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=key)
    manifest = load_module_manifests().get(module, {})
    for key in changed:
        is_enabled = key in wanted
        runtime.desired_states.set_enabled(key, module, is_enabled)
        reported = runtime.client_modules.get(key, {}).get(module) or {}
        ask_module(
            controller=runtime.agent_module_orders,
            mac_address=key,
            module=module,
            manifest=manifest,
            platform=runtime.client_platform.get(key, {}),
            is_enabled=is_enabled,
            reported_state=str(reported.get("state", "")),
        )
        try:
            push_state(runtime, key)
        except HTTPException:
            continue
    if changed:
        _recompose_published(runtime, module)
    return device_list(runtime, module)


def device_context(
    runtime: PanelRuntime, module: str, device_id: str
) -> DeviceModuleContext:
    """One device as a module's routes see it.

    Args:
        runtime: The shared runtime.
        module: The module name.
        device_id: The device key from the path.

    Returns:
        The context.

    Raises:
        HTTPException: 404 ``device_unknown`` when no managed device
            answers to the id.
    """
    key = device_id.lower()
    device = DeviceRegistry().get(key)
    if not device.is_managed:
        raise _refusal(status.HTTP_404_NOT_FOUND, CODE_DEVICE_UNKNOWN, device_id=key)
    state, code, params, details = module_status(runtime, key, module)
    return DeviceModuleContext(
        key=key,
        device=device,
        module=module,
        config=runtime.desired_states.read(key, module),
        is_enabled=runtime.desired_states.is_enabled(key, module),
        is_online=runtime.agent_sessions.is_online(key),
        host=runtime.client_address.get(key, ""),
        state=state,
        code=code,
        params=params,
        details=details,
    )


def module_status(runtime: PanelRuntime, key: str, module: str) -> tuple:
    """Where one module stands on one device.

    The machine answers for what is true; the controller answers for how
    the last thing somebody asked for went.

    Args:
        runtime: The shared runtime.
        key: The device.
        module: The module name.

    Returns:
        ``(state, code, params, details)``.
    """
    reported = runtime.client_modules.get(key, {}).get(module) or {}
    state = str(reported.get("state", "unknown") or "unknown")
    code = str(reported.get("code") or "")
    params = dict(reported.get("params") or {})
    details = (
        reported.get("details") if isinstance(reported.get("details"), dict) else {}
    )
    controller = runtime.agent_module_orders
    open_order = controller.open_order_for(key, module)
    failure = controller.failure_for(key, module)
    if open_order is not None:
        state = ORDER_STEP_STATES.get(open_order.action, state)
    elif failure is not None:
        state = "failed"
        code = failure.code
        params = dict(failure.params)
    return state, code, params, dict(details)


def require_online(context: DeviceModuleContext) -> None:
    """Refuse a device whose agent holds no socket.

    Args:
        context: The device.

    Raises:
        HTTPException: 409 ``agent_offline``.
    """
    if not context.is_online:
        raise _refusal(
            status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=context.key
        )


def store_config(runtime: PanelRuntime, context: DeviceModuleContext, config: dict):
    """Check a configuration on the agent, store it, and push it.

    Args:
        runtime: The shared runtime.
        context: The device.
        config: The module's whole configuration.

    Raises:
        HTTPException: 409 ``agent_offline`` when the device has no socket,
            400 with the agent's own code when it refuses the
            configuration, 502 when the agent could not be asked.
    """
    require_online(context)
    try:
        verdict = runtime.agent_sessions.validate_from_thread(
            context.key,
            context.module,
            config,
            timeout=DEVICE_MODULE_VALIDATE_TIMEOUT_S,
        )
    except AgentOfflineError:
        raise _refusal(
            status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=context.key
        )
    except StreamRefusedError as error:
        raise _refusal(status.HTTP_502_BAD_GATEWAY, error.code, **error.params)
    if not verdict.get("is_valid"):
        raise _refusal(
            status.HTTP_400_BAD_REQUEST,
            str(verdict.get("code") or "config_invalid"),
            **dict(verdict.get("params") or {}),
        )
    runtime.desired_states.write(context.key, context.module, config)
    context.config = dict(config)
    push_state(runtime, context.key)
    _recompose_published(runtime, context.module)


def push_state(runtime: PanelRuntime, key: str) -> None:
    """Hand one device the state it should hold now.

    Args:
        runtime: The shared runtime.
        key: The device.

    Raises:
        HTTPException: 409 ``agent_offline`` when it has no socket, 502
            when the socket did not take the state in time.
    """
    try:
        runtime.push_desired_state(key)
    except AgentOfflineError:
        raise _refusal(status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=key)
    except StreamRefusedError as error:
        raise _refusal(status.HTTP_502_BAD_GATEWAY, error.code, **error.params)


def run_command(
    runtime: PanelRuntime, context: DeviceModuleContext, action: str, args: dict
) -> dict:
    """Run one module command on the device and wait for its close.

    Args:
        runtime: The shared runtime.
        context: The device.
        action: The command's action on the wire.
        args: What the action takes.

    The agent reports at once after a command that took, and the context
    is read again from that report, so a view answered after this call
    shows the machine as the command left it.

    Returns:
        What the agent closed with: ``{"exit_code", "code", "params",
        "output"}``.

    Raises:
        HTTPException: 409 ``agent_offline`` when the device has no socket,
            502 with the agent's code when the command failed or could not
            be asked.
    """
    require_online(context)
    serial = runtime.agent_sessions.report_serial_of(context.key)
    try:
        info = runtime.agent_sessions.run_command_from_thread(
            context.key, action, dict(args), timeout=DEVICE_MODULE_COMMAND_TIMEOUT_S
        )
    except AgentOfflineError:
        raise _refusal(
            status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=context.key
        )
    except StreamRefusedError as error:
        raise _refusal(status.HTTP_502_BAD_GATEWAY, error.code, **error.params)
    if int(info.get("exit_code", 1) or 0) != 0:
        params = dict(info.get("params") or {})
        output = str(info.get("output", "") or "").strip()
        if output and "detail" not in params:
            params["detail"] = output[-500:]
        raise _refusal(
            status.HTTP_502_BAD_GATEWAY,
            str(info.get("code") or CODE_COMMAND_FAILED),
            **params,
        )
    runtime.agent_sessions.wait_for_report_from_thread(
        context.key, serial, DEVICE_MODULE_REPORT_WAIT_S
    )
    context.state, context.code, context.params, context.details = module_status(
        runtime, context.key, context.module
    )
    return dict(info)


def _recompose_published(runtime: PanelRuntime, module: str) -> None:
    """Say the published list may read differently, for the modules it reads.

    Args:
        runtime: The shared runtime.
        module: The module whose desired state was written.
    """
    if module in SERVICES_PUBLISHED_MODULES:
        runtime.published_services.schedule_refresh()


def _hub_first(runtime: PanelRuntime):
    """A sort key putting the hub box's own device first, then by name."""
    own_addresses = {
        interface.lan.address for interface in runtime.network().lan_interfaces
    }

    def key_of(row: ModuleDeviceView) -> tuple:
        is_hub = runtime.client_address.get(row.device_id, "") in own_addresses
        return (not is_hub, row.name.lower())

    return key_of


def _refusal(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": dict(params)}
    )
