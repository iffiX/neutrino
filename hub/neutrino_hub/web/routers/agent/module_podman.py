"""The Podman block: which devices run an engine, and each one's containers.

A declared container is the device's desired state, checked on the agent,
stored and pushed, and comes out the other side as a systemd unit on the
device. The live list shows every container the device's podman knows,
including ones started by hand at a shell, each with start, stop and
restart and its unit's journal.
"""

import httpx
from fastapi import APIRouter, Depends, Query

from neutrino_hub.web.constants import WEB_JOURNAL_LINE_LIMIT
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    JournalView,
    PodmanContainerListUpdate,
    PodmanContainerRequest,
    PodmanContainerStateView,
    PodmanContainerView,
    PodmanDeviceView,
    PodmanMirrorListUpdate,
    PodmanTagListView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    run_command,
    store_config,
)

MODULE = "podman"
COMMAND_CONTROL = "podman_control"
COMMAND_JOURNAL = "podman_journal"
CONTROL_START = "start"
CONTROL_STOP = "stop"
CONTROL_RESTART = "restart"
TAGS_TIMEOUT_S = 10.0


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> PodmanDeviceView:
    """One device's engine: the declarations beside what actually runs.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        Declared containers as configured, every container the device's
        podman knows, and the engine's own state.
    """
    details = context.details
    config = context.config
    return PodmanDeviceView(
        **context.fields(),
        containers=[
            PodmanContainerView(**container)
            for container in config.get("containers", [])
        ],
        mirrors=[str(mirror) for mirror in config.get("mirrors", [])],
        running=[
            PodmanContainerStateView(**state)
            for state in details.get("containers") or []
            if isinstance(state, dict)
        ],
        is_installed=context.state == "installed",
        is_active=bool(details.get("is_active")),
        version=str(details.get("version", "") or ""),
    )


router: APIRouter = module_router(
    MODULE, view_model=PodmanDeviceView, build_view=device_view
)


@router.post("/container/set", response_model=PodmanDeviceView)
def update_containers(
    update: PodmanContainerListUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> PodmanDeviceView:
    """Replace the declared container list.

    Args:
        update: The device, and the new declarations.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 400 with the agent's code when
            the configuration does not hold together.
    """
    context = device_context(runtime, MODULE, update.device_id)
    config = dict(context.config)
    config["containers"] = [container.model_dump() for container in update.containers]
    store_config(runtime, context, config)
    return device_view(runtime, context)


@router.post("/mirror/set", response_model=PodmanDeviceView)
def update_mirrors(
    update: PodmanMirrorListUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> PodmanDeviceView:
    """Replace the docker.io mirror list.

    Args:
        update: The device, and the new mirrors, in the order pulls should
            try them.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.
    """
    context = device_context(runtime, MODULE, update.device_id)
    config = dict(context.config)
    config["mirrors"] = list(update.mirrors)
    store_config(runtime, context, config)
    return device_view(runtime, context)


@router.get("/tag", response_model=PodmanTagListView)
def image_tags(device_id: str, image: str) -> PodmanTagListView:
    """List an image's recent tags, so picking one is a click, not a guess.

    Args:
        device_id: The device, from the query, which the listing does not
            depend on.
        image: The image reference, with or without a tag.

    Returns:
        Recent tags from Docker Hub, or none for other registries and for
        a hub that cannot be reached.
    """
    del device_id
    return PodmanTagListView(tags=list_image_tags(image))


@router.get("/container/journal", response_model=JournalView)
def container_journal(
    device_id: str,
    name: str,
    lines: int = Query(default=100, ge=1, le=WEB_JOURNAL_LINE_LIMIT),
    runtime: PanelRuntime = Depends(get_runtime),
) -> JournalView:
    """Read the tail of one container unit's journal on the device.

    Args:
        device_id: The device, from the query.
        name: The container's name, from the query.
        lines: How many lines to keep.
        runtime: The shared runtime.

    Returns:
        The journal text.

    Raises:
        HTTPException: 409 ``agent_offline``, 502 with the agent's code.
    """
    context = device_context(runtime, MODULE, device_id)
    info = run_command(runtime, context, COMMAND_JOURNAL, {"name": name})
    text = str(info.get("output", "") or "")
    return JournalView(text="\n".join(text.splitlines()[-lines:]))


@router.post("/container/start", response_model=PodmanDeviceView)
def start_container(
    request: PodmanContainerRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> PodmanDeviceView:
    """Start one container on the device.

    Args:
        request: The device and the container's name.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 502 with the agent's code:
            ``container_unknown``, ``command_failed``.
    """
    return _control(runtime, request, CONTROL_START)


@router.post("/container/stop", response_model=PodmanDeviceView)
def stop_container(
    request: PodmanContainerRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> PodmanDeviceView:
    """Stop one container on the device.

    Args:
        request: The device and the container's name.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 502 with the agent's code:
            ``container_unknown``, ``command_failed``.
    """
    return _control(runtime, request, CONTROL_STOP)


@router.post("/container/restart", response_model=PodmanDeviceView)
def restart_container(
    request: PodmanContainerRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> PodmanDeviceView:
    """Stop and start one container on the device.

    Args:
        request: The device and the container's name.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 502 with the agent's code:
            ``container_unknown``, ``command_failed``.
    """
    return _control(runtime, request, CONTROL_RESTART)


def _control(
    runtime: PanelRuntime, request: PodmanContainerRequest, action: str
) -> PodmanDeviceView:
    """Run one control verb on one container and answer the fresh view."""
    context = device_context(runtime, MODULE, request.device_id)
    run_command(
        runtime, context, COMMAND_CONTROL, {"name": request.name, "action": action}
    )
    return device_view(runtime, context)


def hub_tags_url(image: str) -> str | None:
    """The Docker Hub API endpoint listing an image's tags.

    Args:
        image: An image reference, with or without the ``docker.io/``
            prefix and with or without a tag.

    Returns:
        The URL, or None for an image not hosted on Docker Hub.
    """
    base = image.strip()
    if base.startswith("docker.io/"):
        base = base[len("docker.io/") :]
    elif "." in base.split("/", 1)[0]:
        return None
    colon = base.rfind(":")
    if colon > base.rfind("/"):
        base = base[:colon]
    if "/" not in base:
        base = f"library/{base}"
    if (
        base.count("/") != 1
        or not base.replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(".", "")
        .isalnum()
    ):
        return None
    return (
        f"https://hub.docker.com/v2/repositories/{base}/tags"
        f"?page_size=25&ordering=last_updated"
    )


def list_image_tags(image: str) -> list[str]:
    """Fetch an image's recent tags from Docker Hub, best effort.

    Args:
        image: An image reference.

    Returns:
        Tag names, newest first, possibly empty.
    """
    url = hub_tags_url(image)
    if url is None:
        return []
    try:
        response = httpx.get(url, timeout=TAGS_TIMEOUT_S, follow_redirects=True)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    if response.status_code != 200 or not isinstance(payload, dict):
        return []
    return [
        entry["name"]
        for entry in payload.get("results", [])
        if isinstance(entry, dict) and entry.get("name")
    ]
