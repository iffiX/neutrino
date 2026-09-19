"""The Modules page of a device, and one door for every module block.

``/api/agent/module`` reads every module a device could host, each as its
agent last reported it beside what the hub asks of it, and its four presses
write one ``want`` each into ``config/devices/<id>/modules.json``: install
``installed``, start ``running``, stop ``stopped``, uninstall ``absent``.
The state is pushed at once, and what the machine reports afterwards is
shown; an install's or an uninstall's lines arrive on a ``log`` stream the
agent opens, which the list names by its task.

The file share, the git server, the container engine and ZFS are hosted by
devices, one desired state per device per module under ``config/``, and
each module's block is built here: the per-device read, the push, and the
import that turns what the machine's latest report carries into the hub's
configuration where the hub holds none yet, plus the helpers the block's
own routes share: a configuration is checked on the agent before it is
stored and pushed, and an imperative verb runs on the agent to its close
and answers the device's fresh view.

Every refusal is ``{code, params}``; a device whose agent holds no socket
cannot be edited or driven, and says so with ``agent_offline``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.agent_module_cache import (
    platform_keys,
    resolve_platform_entry,
)
from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_CONFIGURED_WANTS,
    CHANNEL_MODULE_STATE_ABSENT,
    CHANNEL_MODULE_STATE_INSTALLED,
    CHANNEL_MODULE_STATE_RUNNING,
    CHANNEL_MODULE_STATE_STOPPED,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_VERB_VALIDATE,
)
from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_INSTALLER_USER,
    DEVICE_MODULE_COMMAND_TIMEOUT_S,
    DEVICE_MODULE_REPORT_WAIT_S,
    DEVICE_MODULE_VALIDATE_TIMEOUT_S,
)
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.registry import DeviceRegistry, ManagedDevice
from neutrino_hub.modules.services.constants import SERVICES_PUBLISHED_MODULES
from neutrino_hub.web.channel_serve import module_task_label
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ApplyResult,
    DeviceModuleListView,
    DeviceModuleRequest,
    DeviceModuleView,
    DeviceRequest,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/agent/module", tags=["module"], dependencies=[Depends(require_session)]
)

CODE_AGENT_OFFLINE = "agent_offline"
CODE_DEVICE_UNKNOWN = "device_unknown"
CODE_COMMAND_FAILED = "command_failed"
CODE_MODULE_UNKNOWN = "module_unknown"
CODE_MODULE_NOT_OPTIONAL = "module_not_optional"
CODE_NO_PLATFORM_BUILD = "no_platform_build"
CODE_MODULE_CONFIGURED = "module_configured"

# What a module reads as until its agent has said.
STATE_UNKNOWN = "unknown"


@dataclass
class DeviceModuleContext:
    """One device as a module's routes see it.

    Attributes:
        key: The device key.
        device: The stored device.
        module: The module name.
        config: The module's stored configuration for this device.
        want: What the hub asks of the module here; empty when it asks
            nothing.
        is_online: Whether its agent holds a socket.
        host: Where the device is.
        state: The module's state on the machine, as last reported.
        is_active: Whether its unit runs, as last reported.
        code: Why it failed, typed.
        params: What the wording names.
        details: The live reads the last report carried.
    """

    key: str
    device: ManagedDevice
    module: str
    config: dict = field(default_factory=dict)
    want: str = ""
    is_online: bool = False
    host: str = ""
    state: str = STATE_UNKNOWN
    is_active: bool = False
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

    def observe(self, runtime: PanelRuntime) -> None:
        """Read the module's state again from the device's latest report."""
        observed = module_status(runtime, self.key, self.module)
        self.state = observed["state"]
        self.is_active = observed["is_active"]
        self.code = observed["code"]
        self.params = observed["params"]
        self.details = observed["details"]


@router.get("", response_model=DeviceModuleListView)
def list_modules(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceModuleListView:
    """Read every module a device could run, and where each stands.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime, for what the agent last reported.

    Returns:
        The modules, unsupported ones included so the panel can say why,
        each with what the hub asks of it and the task carrying its
        install or uninstall lines, when one has run.

    Raises:
        HTTPException: 404 ``device_unknown`` when no device has the id.
    """
    device = _require_device(device_id)
    key = device.id
    platform = runtime.device_platform.get(key, {})
    keys = platform_keys(platform)
    modules = []
    for name, manifest in load_module_manifests().items():
        platforms = manifest.get("platforms", {})
        _, entry = resolve_platform_entry(manifest, platform)
        modules.append(
            DeviceModuleView(
                name=name,
                title=manifest.get("title", name),
                description=manifest.get("description", ""),
                kind=manifest.get("kind", ""),
                installer=manifest.get("installer", ""),
                # With no platform reported yet, nothing is ruled out: the
                # agent will say what it cannot do once it beats.
                is_supported=(any(key in platforms for key in keys) if keys else True),
                is_native=(entry == {}),
                source=manifest.get("source", ""),
                license=manifest.get("license", ""),
                corresponding_source=manifest.get("corresponding_source", ""),
                want=runtime.desired_states.want_of(key, name),
                is_configured=bool(runtime.desired_states.read(key, name)),
                task_id=module_task_id(runtime, key, name),
                **module_status(runtime, key, name),
            )
        )
    return DeviceModuleListView(
        modules=modules,
        is_agent_managed=device.is_managed,
        is_agent_online=runtime.agent_sessions.is_online(key),
    )


@router.post("/install", response_model=DeviceModuleListView)
def install_module(
    request: DeviceModuleRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceModuleListView:
    """Ask for one module's package on a device, and nothing configured.

    Args:
        request: The device and the module.
        runtime: The shared runtime.

    Returns:
        The modules after ``want: installed`` was written and pushed.

    Raises:
        HTTPException: 404 ``module_unknown`` for a module with no manifest,
            404 ``device_unknown`` for an id no device has, 400
            ``module_not_optional`` for a module the person installs
            themselves, 409 ``no_platform_build`` when the manifest offers
            the device's platform nothing, 409 ``agent_offline`` when the
            device has no socket.
    """
    return _set_want(runtime, request, CHANNEL_MODULE_STATE_INSTALLED)


@router.post("/start", response_model=DeviceModuleListView)
def start_module(
    request: DeviceModuleRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceModuleListView:
    """Ask for one module configured and running on a device.

    Args:
        request: The device and the module.
        runtime: The shared runtime.

    Returns:
        The modules after ``want: running`` was written and pushed.

    Raises:
        HTTPException: As :func:`install_module`.
    """
    return _set_want(runtime, request, CHANNEL_MODULE_STATE_RUNNING)


@router.post("/stop", response_model=DeviceModuleListView)
def stop_module(
    request: DeviceModuleRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceModuleListView:
    """Ask for one module configured and stopped on a device.

    Args:
        request: The device and the module.
        runtime: The shared runtime.

    Returns:
        The modules after ``want: stopped`` was written and pushed.

    Raises:
        HTTPException: As :func:`install_module`.
    """
    return _set_want(runtime, request, CHANNEL_MODULE_STATE_STOPPED)


@router.post("/uninstall", response_model=DeviceModuleListView)
def uninstall_module(
    request: DeviceModuleRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceModuleListView:
    """Ask for one module off a device; its data stays.

    Args:
        request: The device and the module.
        runtime: The shared runtime.

    Returns:
        The modules after ``want: absent`` was written and pushed.

    Raises:
        HTTPException: As :func:`install_module`.
    """
    return _set_want(runtime, request, CHANNEL_MODULE_STATE_ABSENT)


def module_router(
    module: str, *, view_model, build_view, import_config: "Callable | None" = None
) -> APIRouter:
    """The router one device-hosted module's block talks to.

    Args:
        module: The module name, which ends the path prefix.
        view_model: The per-device response model.
        build_view: Called with ``(runtime, context)``; returns the
            per-device view.
        import_config: Called with the ``details`` of the device's latest
            report; returns the configuration they amount to. None for a
            module that imports nothing, which then has no import route.

    Returns:
        A router carrying the per-device read, the push and the import,
        for the module's own routes to join.
    """
    router = APIRouter(
        prefix=f"/api/agent/module/{module}",
        tags=["module"],
        dependencies=[Depends(require_session)],
    )

    @router.get("", response_model=view_model)
    def read_device(device_id: str, runtime: PanelRuntime = Depends(get_runtime)):
        return build_view(runtime, device_context(runtime, module, device_id))

    @router.post("/apply", response_model=ApplyResult)
    def apply_device(
        request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
    ):
        context = device_context(runtime, module, request.device_id)
        require_online(context)
        push_state(runtime, context.key)
        return ApplyResult(is_applied=True, message="pushed")

    if import_config is not None:

        @router.post("/import", response_model=view_model)
        def import_device(
            request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
        ):
            context = device_context(runtime, module, request.device_id)
            import_details(runtime, context, import_config)
            return build_view(runtime, context)

    return router


def import_details(
    runtime: PanelRuntime, context: DeviceModuleContext, import_config: Callable
) -> None:
    """Make what the machine reports the hub's configuration for it.

    Args:
        runtime: The shared runtime.
        context: The device, holding the details its agent last reported.
        import_config: Called with those details; returns the configuration,
            empty for a module that imports nothing, which then writes
            nothing.

    Raises:
        HTTPException: 409 ``module_configured`` when the hub already holds
            a configuration for the module on this device, 409
            ``agent_offline`` when the device has no socket.
    """
    if context.config:
        raise _refusal(
            status.HTTP_409_CONFLICT,
            CODE_MODULE_CONFIGURED,
            device_id=context.key,
            module=context.module,
        )
    require_online(context)
    config = dict(import_config(context.details))
    if not config:
        return
    runtime.desired_states.write(context.key, context.module, config)
    context.config = dict(config)
    if context.want in CHANNEL_MODULE_CONFIGURED_WANTS:
        push_state(runtime, context.key)
    _recompose_published(runtime, context.module)


def is_hosted(runtime: PanelRuntime, key: str, module: str) -> bool:
    """Whether the hub configures one module on one device."""
    return (
        runtime.desired_states.want_of(key, module) in CHANNEL_MODULE_CONFIGURED_WANTS
    )


def device_context(
    runtime: PanelRuntime, module: str, device_id: str
) -> DeviceModuleContext:
    """One device as a module's routes see it.

    Args:
        runtime: The shared runtime.
        module: The module name.
        device_id: The device id the request named.

    Returns:
        The context.

    Raises:
        HTTPException: 404 ``device_unknown`` when no managed device
            answers to the id.
    """
    device = DeviceRegistry().get(device_id)
    if device is None or not device.is_managed:
        raise _refusal(
            status.HTTP_404_NOT_FOUND, CODE_DEVICE_UNKNOWN, device_id=device_id
        )
    key = device.id
    context = DeviceModuleContext(
        key=key,
        device=device,
        module=module,
        config=runtime.desired_states.read(key, module),
        want=runtime.desired_states.want_of(key, module),
        is_online=runtime.agent_sessions.is_online(key),
        host=runtime.device_address.get(key, ""),
    )
    context.observe(runtime)
    return context


def module_status(runtime: PanelRuntime, key: str, module: str) -> dict:
    """Where one module stands on one device, as its agent last reported.

    Args:
        runtime: The shared runtime.
        key: The device.
        module: The module name.

    Returns:
        ``{"state", "is_active", "code", "params", "details"}``; the state
        is ``unknown`` until the agent has said.
    """
    reported = runtime.device_modules.get(key, {}).get(module) or {}
    details = reported.get("details")
    return {
        "state": str(reported.get("state", STATE_UNKNOWN) or STATE_UNKNOWN),
        "is_active": bool(reported.get("is_active", False)),
        "code": str(reported.get("code") or ""),
        "params": dict(reported.get("params") or {}),
        "details": dict(details) if isinstance(details, dict) else {},
    }


def module_task_id(runtime: PanelRuntime, key: str, module: str) -> str:
    """The newest task carrying one module's install or uninstall lines.

    Args:
        runtime: The shared runtime, which holds the tasks.
        key: The device.
        module: The module name.

    Returns:
        The task id, running or finished, or empty when the agent has
        opened no ``log`` stream for it since the panel started.
    """
    label = module_task_label(key, module)
    for stream in reversed(runtime.tasks.streams()):
        if stream.label == label:
            return stream.id
    return ""


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
        verdict = runtime.agent_sessions.run_stream_from_thread(
            context.key,
            CHANNEL_STREAM_COMMAND,
            {
                "module": context.module,
                "verb": CHANNEL_VERB_VALIDATE,
                "config": dict(config),
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
    runtime: PanelRuntime, context: DeviceModuleContext, verb: str, args: dict
) -> dict:
    """Run one of the module's verbs on the device and wait for its close.

    The agent reports at once after a command that took, and the context
    is read again from that report, so a view answered after this call
    shows the machine as the command left it.

    Args:
        runtime: The shared runtime.
        context: The device.
        verb: The verb, spelled without the module's name.
        args: What the verb takes.

    Returns:
        The close's ``params``: ``{"exit_code", "output"}``, with ``result``
        beside them for a verb that reads.

    Raises:
        HTTPException: 409 ``agent_offline`` when the device has no socket,
            502 with the agent's code when the command failed or could not
            be asked.
    """
    require_online(context)
    serial = runtime.agent_sessions.report_serial_of(context.key)
    try:
        info = runtime.agent_sessions.run_stream_from_thread(
            context.key,
            CHANNEL_STREAM_COMMAND,
            {"module": context.module, "verb": verb, **args},
            timeout=DEVICE_MODULE_COMMAND_TIMEOUT_S,
        )
    except AgentOfflineError:
        raise _refusal(
            status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=context.key
        )
    except StreamRefusedError as error:
        raise _refusal(status.HTTP_502_BAD_GATEWAY, error.code, **error.params)
    params = dict(info.get("params") or {})
    if info.get("code") or int(params.get("exit_code", 1) or 0) != 0:
        output = str(params.pop("output", "") or "").strip()
        params.pop("exit_code", None)
        params.pop("result", None)
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
    context.observe(runtime)
    return params


def _set_want(
    runtime: PanelRuntime, request: DeviceModuleRequest, want: str
) -> DeviceModuleListView:
    """Write one module's ``want`` on one device, push it, and answer the list.

    Args:
        runtime: The shared runtime.
        request: The device and the module.
        want: What the device is to make of the module.

    Returns:
        The modules after the write and the push.

    Raises:
        HTTPException: 404 ``module_unknown`` for a module with no manifest,
            404 ``device_unknown`` for an id no device has, 400
            ``module_not_optional`` for a user-tier module, 409
            ``no_platform_build`` when the manifest offers the device's
            platform nothing, 409 ``agent_offline`` when the device has no
            socket, 502 when the socket did not take the state in time.
    """
    manifest = load_module_manifests().get(request.module)
    module = request.module
    if manifest is None:
        raise _refusal(status.HTTP_404_NOT_FOUND, CODE_MODULE_UNKNOWN, name=module)
    if str(manifest.get("installer", "")) == AGENT_MODULE_INSTALLER_USER:
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_MODULE_NOT_OPTIONAL, name=module
        )
    key = _require_device(request.device_id).id
    platform = runtime.device_platform.get(key, {})
    _, entry = resolve_platform_entry(manifest, platform)
    if entry is None and platform:
        raise _refusal(status.HTTP_409_CONFLICT, CODE_NO_PLATFORM_BUILD, module=module)
    if not runtime.agent_sessions.is_online(key):
        raise _refusal(status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=key)
    runtime.desired_states.set_want(key, module, want)
    push_state(runtime, key)
    _recompose_published(runtime, module)
    return list_modules(request.device_id, runtime)


def _require_device(device_id: str) -> ManagedDevice:
    """The device an id names, managed or not.

    Args:
        device_id: A stored id or a ``scan:<mac>`` id.

    Returns:
        The device.

    Raises:
        HTTPException: 404 ``device_unknown`` when no device has the id.
    """
    device = DeviceRegistry().get(device_id)
    if device is None:
        raise _refusal(
            status.HTTP_404_NOT_FOUND, CODE_DEVICE_UNKNOWN, device_id=device_id
        )
    return device


def _recompose_published(runtime: PanelRuntime, module: str) -> None:
    """Say the published list may read differently, for the modules it reads.

    Args:
        runtime: The shared runtime.
        module: The module whose desired state was written.
    """
    if module in SERVICES_PUBLISHED_MODULES:
        runtime.published_services.schedule_refresh()


def _refusal(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": dict(params)}
    )
