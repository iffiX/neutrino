"""The Containers tab: declared containers beside what actually runs.

A declared container goes through config/ — save the group, apply the group —
and comes out the other side as a systemd unit via Quadlet. The live list
shows every container podman knows, including ones started by hand at a
shell, each with start/stop/restart and a shell of its own.
"""

import shutil

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.podman.config import PodmanConfig, PodmanContainer
from neutrino_hub.modules.podman.ops import (
    PodmanContainerController,
    PodmanStatusReader,
    list_image_tags,
)
from neutrino_hub.utils.subprocess_run import CommandError, run
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ApplyResult,
    PodmanContainerListUpdate,
    PodmanMirrorListUpdate,
    PodmanContainerStateView,
    PodmanContainerView,
    PodmanSettingsView,
    PodmanTagListView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/podman", tags=["podman"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=PodmanSettingsView)
def read_settings(runtime: PanelRuntime = Depends(get_runtime)) -> PodmanSettingsView:
    """Read the declarations and the live container list.

    Args:
        runtime: The shared runtime.

    Returns:
        Declared containers as configured, every container podman knows about
        right now, and the engine's own state.
    """
    config = runtime.podman()
    declared = [container.name for container in config.containers]
    is_installed = shutil.which("podman") is not None
    version = ""
    if is_installed:
        version_output = run(["podman", "--version"], is_checked=False).stdout
        # "podman version 4.9.3"
        parts = version_output.split()
        version = parts[2] if len(parts) > 2 else ""
    return PodmanSettingsView(
        containers=[
            PodmanContainerView(**container.to_dict())
            for container in config.containers
        ],
        mirrors=config.mirrors,
        running=[
            PodmanContainerStateView(**vars(state))
            for state in PodmanStatusReader().survey(declared_names=declared)
        ],
        is_installed=is_installed,
        is_active=runtime.services.status("podman").is_active,
        version=version,
    )


@router.put("/containers", response_model=PodmanSettingsView)
def update_containers(
    update: PodmanContainerListUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> PodmanSettingsView:
    """Replace the declared container list.

    Args:
        update: The new declarations.
        runtime: The shared runtime.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 400 when the configuration does not hold together.
    """
    config = runtime.podman()
    config.containers = [
        PodmanContainer.from_dict(container.model_dump())
        for container in update.containers
    ]
    try:
        runtime.write_podman(config)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return read_settings(runtime)


@router.put("/mirrors", response_model=PodmanSettingsView)
def update_mirrors(
    update: PodmanMirrorListUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> PodmanSettingsView:
    """Replace the docker.io mirror list.

    Args:
        update: The new mirrors, in the order pulls should try them.
        runtime: The shared runtime.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 400 when an entry is not a registry host.
    """
    config = runtime.podman()
    config.mirrors = update.mirrors
    try:
        runtime.write_podman(config)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return read_settings(runtime)


@router.post("/apply", response_model=ApplyResult)
async def apply(runtime: PanelRuntime = Depends(get_runtime)) -> ApplyResult:
    """Render the Quadlet files from the declarations and reconcile systemd.

    Args:
        runtime: The shared runtime.

    Returns:
        Whether the apply succeeded and what was done. A failure is reported
        rather than raised, so the panel shows the reason beside the button.
    """
    try:
        message = await runtime.apply_podman()
    except (CommandError, ValueError, FileNotFoundError) as error:
        return ApplyResult(is_applied=False, message=str(error))
    return ApplyResult(is_applied=True, message=message)


@router.get("/tags", response_model=PodmanTagListView)
def image_tags(image: str) -> PodmanTagListView:
    """List an image's recent tags, so picking one is a click, not a guess.

    Args:
        image: The image reference, with or without a tag.

    Returns:
        Recent tags from Docker Hub, or none for other registries and for a
        hub that cannot be reached — typing a tag by hand always works.
    """
    return PodmanTagListView(tags=list_image_tags(image))


@router.post("/containers/{name}/{action}", response_model=PodmanSettingsView)
def control(
    name: str, action: str, runtime: PanelRuntime = Depends(get_runtime)
) -> PodmanSettingsView:
    """Start, stop or restart one container.

    Args:
        name: The container's name, which must exist in podman's own list —
            the panel controls containers, it does not conjure them.
        action: ``start``, ``stop`` or ``restart``.
        runtime: The shared runtime.

    Returns:
        The settings view afterwards.

    Raises:
        HTTPException: 404 for a container podman does not know, 400 for a
            bad action, 502 when the container refuses.
    """
    config = runtime.podman()
    declared = [container.name for container in config.containers]
    states = PodmanStatusReader().survey(declared_names=declared)
    state = next((entry for entry in states if entry.name == name), None)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{name!r} is not a container podman knows",
        )
    try:
        PodmanContainerController().control(name, action, is_declared=state.is_declared)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except CommandError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error
    return read_settings(runtime)
