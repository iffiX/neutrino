"""The Ollama block: where the module stands, its models and its pulls.

The module's configuration is empty and the hub keeps no file for it. The
models are read and changed through Ollama's own API at its port on the
machine, which the hub reaches through a forward of its transport on its
own loopback; a pull is a background task of the hub's that outlives the
page (agent/modules/ollama.md, "The model list is the hub's, through a
forward of its own").
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.constants import DEVICE_OLLAMA_MODULE
from neutrino_hub.modules.devices.ollama_models import (
    CODE_UNREACHABLE,
    OllamaApiClient,
    is_model_name,
    model_rows,
)
from neutrino_hub.web.models import OllamaDeviceView, OllamaModelRequest
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    panel_details,
    require_online,
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
    """One device's Ollama: its row as last reported, its models while it answers, and its pulls.

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
            models = model_rows(client.tags(), client.ps())
        except (ConnectionError, OSError) as error:
            fields["code"] = CODE_UNREACHABLE
            fields["params"] = {"detail": str(error)[:300]}
    return OllamaDeviceView(
        **fields,
        version=str(context.details.get("version", "") or ""),
        details=panel_details(context.details),
        is_running=is_running,
        models=models,
        total_bytes=sum(model["size_bytes"] for model in models),
        pulls=runtime.ollama_pulls.pulls(context.key),
    )


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
    return device_view(runtime, context)


@router.post(
    "/loaded/remove",
    response_model=OllamaDeviceView,
)
def unload_model(
    request: OllamaModelRequest, runtime: PanelRuntime = Depends(get_runtime)
):
    """Take one model out of the machine's memory.

    Raises:
        HTTPException: 404 ``ollama_model_unknown {name}``; 409
            ``agent_offline`` and ``ollama_not_running``; 502
            ``ollama_unreachable {detail}``.
    """
    context = running_context(runtime, request.device_id)
    _call(runtime, context, "unload", request.name)
    return device_view(runtime, context)


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
