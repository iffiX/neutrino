"""The Ollama block: where the module stands, its settings, its models and its pulls.

The module's configuration is its settings, ``{keep_alive, gpus}``, which the
hub keeps in ``config/devices/<id>/ollama.json`` beside ``kept_models``,
the models a person loaded (agent/modules/ollama.md, "The settings are the
hub's"). The models are read and changed through Ollama's own API at its
port on the machine, which the hub reaches through a forward of its
transport on its own loopback; a pull is a background task of the hub's
that outlives the page, and a kept model is loaded again whenever the
server lost it (agent/modules/ollama.md, "The model list is the hub's,
through a forward of its own").
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.constants import (
    DEVICE_OLLAMA_KEPT_MODELS_KEY,
    DEVICE_OLLAMA_MODULE,
)
from neutrino_hub.modules.devices.desired_state import ollama_settings
from neutrino_hub.modules.devices.ollama_models import (
    CODE_UNREACHABLE,
    OllamaApiClient,
    is_model_name,
    model_names,
    model_rows,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.models import (
    DeviceGpuView,
    OllamaDeviceView,
    OllamaModelRequest,
    OllamaResourcesView,
    OllamaSettingsUpdate,
)
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    panel_details,
    require_online,
    store_config,
    write_module_config,
)

MODULE = DEVICE_OLLAMA_MODULE
# The refusals of the model routes.
CODE_NOT_RUNNING = "ollama_not_running"
CODE_NAME_INVALID = "ollama_model_name_invalid"
CODE_MODEL_UNKNOWN = "ollama_model_unknown"
CODE_PULL_UNKNOWN = "ollama_pull_unknown"


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> OllamaDeviceView:
    """One device's Ollama: its row as last reported, its settings and resources, its models while it answers, and its pulls.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The view; ``code`` and ``params`` ``ollama_unreachable {detail}``
        when the models could not be read.
    """
    fields = context.fields()
    is_running = context.is_online and bool(context.details.get("is_running"))
    models = []
    if is_running:
        try:
            client = OllamaApiClient(runtime.ollama_address(context.key))
            models = model_rows(
                client.tags(), client.ps(), runtime.ollama_kept.loading(context.key)
            )
        except (ConnectionError, OSError) as error:
            fields["code"] = CODE_UNREACHABLE
            fields["params"] = {"detail": str(error)[:300]}
    return OllamaDeviceView(
        **fields,
        version=str(context.details.get("version", "") or ""),
        details=panel_details(context.details),
        is_running=is_running,
        **ollama_settings(context.config),
        resources=machine_resources(runtime.device_metrics.get(context.key)),
        models=models,
        total_bytes=sum(model["size_bytes"] for model in models),
        pulls=runtime.ollama_pulls.pulls(context.key),
    )


def machine_resources(metrics: "dict | None") -> OllamaResourcesView:
    """What a machine has for its models, from its last report's metrics. Pure.

    Args:
        metrics: ``machine.metrics`` as last reported; None before a report.

    Returns:
        Its GPUs, and its memory in use and in all, in MiB; the memory null
        while the report names no total.
    """
    metrics = metrics if isinstance(metrics, dict) else {}
    gpus = [
        DeviceGpuView.model_validate(gpu)
        for gpu in metrics.get("gpus") or []
        if isinstance(gpu, dict)
    ]
    total = metrics.get("memory_total_mb")
    percent = metrics.get("memory_percent")
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        return OllamaResourcesView(gpus=gpus)
    used = round(total * percent / 100) if isinstance(percent, (int, float)) else None
    return OllamaResourcesView(gpus=gpus, memory_used_mb=used, memory_total_mb=total)


def running_context(runtime: PanelRuntime, device_id: str) -> DeviceModuleContext:
    """The device, refused unless its Ollama answers as last reported.

    Args:
        runtime: The shared runtime.
        device_id: The device.

    Returns:
        The context.

    Raises:
        HTTPException: 409 ``agent_offline``, 409 ``ollama_not_running``.
    """
    context = device_context(runtime, MODULE, device_id)
    require_online(context)
    if not context.details.get("is_running"):
        raise _refusal(status.HTTP_409_CONFLICT, CODE_NOT_RUNNING)
    return context


router: APIRouter = module_router(
    MODULE, view_model=OllamaDeviceView, build_view=device_view
)


@router.post(
    "/set",
    response_model=OllamaDeviceView,
)
def update_settings(
    update: OllamaSettingsUpdate, runtime: PanelRuntime = Depends(get_runtime)
):
    """Store the settings after the agent checked them, and push them; the configure restarts the server.

    Raises:
        HTTPException: 409 ``agent_offline``; 400 with the agent's code
            when it refuses the settings; 500 ``config_unwritable``.
    """
    context = device_context(runtime, MODULE, update.device_id)
    config = {**context.config, "keep_alive": update.keep_alive}
    if update.gpus is None:
        config.pop("gpus", None)
    else:
        config["gpus"] = [gpu.model_dump() for gpu in update.gpus]
    store_config(runtime, context, config)
    return device_view(runtime, context)


@router.post(
    "/model/add",
    response_model=OllamaDeviceView,
)
def pull_model(
    request: OllamaModelRequest, runtime: PanelRuntime = Depends(get_runtime)
):
    """Put a pull at the end of the machine's queue.

    Raises:
        HTTPException: 400 ``ollama_model_name_invalid {name}``; 409
            ``agent_offline`` and ``ollama_not_running``.
    """
    name = request.name.strip()
    if not is_model_name(name):
        raise _refusal(status.HTTP_400_BAD_REQUEST, CODE_NAME_INVALID, name=name)
    context = running_context(runtime, request.device_id)
    runtime.ollama_pulls.add(context.key, name)
    return device_view(runtime, context)


@router.post(
    "/pull/remove",
    response_model=OllamaDeviceView,
)
def cancel_pull(
    request: OllamaModelRequest, runtime: PanelRuntime = Depends(get_runtime)
):
    """End a running pull, or take a waiting or failed one off the queue.

    Raises:
        HTTPException: 404 ``ollama_pull_unknown {name}``.
    """
    context = device_context(runtime, MODULE, request.device_id)
    if not runtime.ollama_pulls.cancel(context.key, request.name):
        raise _refusal(status.HTTP_404_NOT_FOUND, CODE_PULL_UNKNOWN, name=request.name)
    return device_view(runtime, context)


@router.post(
    "/model/remove",
    response_model=OllamaDeviceView,
)
def remove_model(
    request: OllamaModelRequest, runtime: PanelRuntime = Depends(get_runtime)
):
    """Delete one model from the machine.

    Raises:
        HTTPException: 404 ``ollama_model_unknown {name}``; 409
            ``agent_offline`` and ``ollama_not_running``; 502
            ``ollama_unreachable {detail}``.
    """
    context = running_context(runtime, request.device_id)
    _call(runtime, context, "delete", request.name)
    _keep(runtime, context, request.name, is_kept=False)
    runtime.ollama_gateway.refresh(context.key)
    return device_view(runtime, context)


@router.post(
    "/loaded/add",
    response_model=OllamaDeviceView,
)
def load_model(
    request: OllamaModelRequest, runtime: PanelRuntime = Depends(get_runtime)
):
    """Keep one pulled model in the machine's memory until its unload, its load started on the hub.

    Raises:
        HTTPException: 404 ``ollama_model_unknown {name}``; 409
            ``agent_offline`` and ``ollama_not_running``; 502
            ``ollama_unreachable {detail}``; 500 ``config_unwritable``.
    """
    context = running_context(runtime, request.device_id)
    try:
        address = runtime.ollama_address(context.key)
        names = model_names(OllamaApiClient(address).tags())
    except (ConnectionError, OSError) as error:
        raise _refusal(
            status.HTTP_502_BAD_GATEWAY, CODE_UNREACHABLE, detail=str(error)[:300]
        )
    if request.name not in names:
        raise _refusal(status.HTTP_404_NOT_FOUND, CODE_MODEL_UNKNOWN, name=request.name)
    _keep(runtime, context, request.name, is_kept=True)
    runtime.ollama_kept.load(context.key, address, request.name)
    return device_view(runtime, context)


@router.post(
    "/loaded/remove",
    response_model=OllamaDeviceView,
)
def unload_model(
    request: OllamaModelRequest, runtime: PanelRuntime = Depends(get_runtime)
):
    """Take one model out of the machine's memory, and out of the kept models.

    Raises:
        HTTPException: 404 ``ollama_model_unknown {name}``; 409
            ``agent_offline`` and ``ollama_not_running``; 502
            ``ollama_unreachable {detail}``; 500 ``config_unwritable``.
    """
    context = running_context(runtime, request.device_id)
    _keep(runtime, context, request.name, is_kept=False)
    _call(runtime, context, "unload", request.name)
    return device_view(runtime, context)


def _keep(
    runtime: PanelRuntime, context: DeviceModuleContext, name: str, *, is_kept: bool
) -> None:
    """Add a name to the machine's kept models or take it off; nothing reaches the machine.

    Raises:
        HTTPException: 500 ``config_unwritable``.
    """
    with CONFIG_WRITE_LOCK:
        stored = runtime.desired_states.read(context.key, MODULE)
        held = stored.get(DEVICE_OLLAMA_KEPT_MODELS_KEY)
        kept = [model for model in held or [] if isinstance(model, str)]
        if (name in kept) == is_kept:
            return
        kept = kept + [name] if is_kept else [model for model in kept if model != name]
        config = {**stored, DEVICE_OLLAMA_KEPT_MODELS_KEY: kept}
        write_module_config(runtime, context.key, MODULE, config)
    context.config = config


def _call(runtime: PanelRuntime, context: DeviceModuleContext, verb: str, name: str):
    """One call of Ollama's API that names a model, its failures as refusals."""
    try:
        client = OllamaApiClient(runtime.ollama_address(context.key))
        getattr(client, verb)(name)
    except KeyError:
        raise _refusal(status.HTTP_404_NOT_FOUND, CODE_MODEL_UNKNOWN, name=name)
    except (ConnectionError, OSError) as error:
        raise _refusal(
            status.HTTP_502_BAD_GATEWAY, CODE_UNREACHABLE, detail=str(error)[:300]
        )


def _refusal(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": dict(params)}
    )
