"""The Services tab: status, start/stop/enable, install/uninstall, journals."""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.registry import MODULE_SPECS, ModuleSpec
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.system.machine import ANY_ARCHITECTURE, machine_architecture
from neutrino_hub.utils.subprocess_run import CommandError, run
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    JournalView,
    ServiceListView,
    ServiceUninstallRequest,
    ServiceView,
    TaskStarted,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/services", tags=["services"], dependencies=[Depends(require_session)]
)

# Refused outright on a core unit. Not hidden in the panel and allowed through
# the API: the panel is not the only thing that can POST here, and a core
# service stopped by any route leaves the same dark box.
STOPPING_ACTIONS = ("stop", "disable")


@router.get("", response_model=ServiceListView)
def list_services(runtime: PanelRuntime = Depends(get_runtime)) -> ServiceListView:
    """Read every managed unit's state.

    Args:
        runtime: The shared runtime.

    Returns:
        One entry per managed unit.
    """
    return ServiceListView(
        services=[_to_view(entry) for entry in runtime.services.status_all()]
    )


@router.get("/{name}/journal", response_model=JournalView)
def journal(
    name: str, lines: int = 100, runtime: PanelRuntime = Depends(get_runtime)
) -> JournalView:
    """Read the tail of a unit's journal.

    Args:
        name: Panel-facing service name.
        lines: How many lines to return.
        runtime: The shared runtime.

    Returns:
        The journal text.

    Raises:
        HTTPException: 404 when the service is not managed.
    """
    try:
        return JournalView(text=runtime.services.journal(name, line_count=lines))
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error


@router.post("/{name}/install", response_model=TaskStarted)
async def install(
    name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> TaskStarted:
    """Install an optional module as a streamed background job.

    Once provisioned it is enabled and started: installing a thing and then
    leaving it dark would only add a second step that everyone performs.

    Args:
        name: Panel-facing module name.
        runtime: The shared runtime.

    Returns:
        The task id to stream on ``/ws/task/{task_id}``.

    Raises:
        HTTPException: 404 for a name the panel cannot install, 400 on a
            machine the module does not run on.
    """
    spec = _spec_or_404(name)
    if ANY_ARCHITECTURE not in spec.architectures:
        if machine_architecture() not in spec.architectures:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{name} does not run on this machine "
                    f"({machine_architecture()}); it runs on: "
                    f"{', '.join(spec.architectures)}"
                ),
            )
    stream = runtime.tasks.start(
        label=f"install {name}", source=_install_source(name, spec)
    )
    return TaskStarted(task_id=stream.id)


@router.post("/{name}/uninstall", response_model=TaskStarted)
async def uninstall(
    name: str,
    request: ServiceUninstallRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TaskStarted:
    """Remove an optional module as a streamed background job.

    Args:
        name: Panel-facing module name.
        request: Whether the module's data goes with it. It stays unless
            explicitly surrendered.
        runtime: The shared runtime.

    Returns:
        The task id to stream on ``/ws/task/{task_id}``.

    Raises:
        HTTPException: 404 for a name the panel cannot uninstall, 400 for a
            core module — netbird installs from here but never leaves from
            here, because removing the way back in from abroad is how the
            owner locks themselves out.
    """
    spec = _spec_or_404(name)
    if name in SYSTEM_CORE_UNITS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"{name} is a core service and cannot be uninstalled"),
        )
    stream = runtime.tasks.start(
        label=f"uninstall {name}",
        source=_uninstall_source(name, spec, is_data_kept=request.is_data_kept),
    )
    return TaskStarted(task_id=stream.id)


@router.post("/{name}/{action}", response_model=ServiceView)
def control(
    name: str, action: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ServiceView:
    """Start, stop, restart, enable, or disable a unit.

    Args:
        name: Panel-facing service name.
        action: The systemd verb to run.
        runtime: The shared runtime.

    Returns:
        The unit's state after the change.

    Raises:
        HTTPException: 404 for an unknown service, 400 for a disallowed action,
            502 when systemd refuses.
    """
    if name in SYSTEM_CORE_UNITS and action in STOPPING_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"{name} is a core service and cannot be {action}ped"),
        )
    try:
        runtime.services.control(name, action)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except CommandError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error
    return _to_view(runtime.services.status(name))


async def _install_source(name: str, spec: ModuleSpec) -> AsyncIterator[str]:
    async for line in _provisioner_stream(
        lambda report: spec.provisioner().provision(report=report)
    ):
        yield line
    yield f"enabling and starting {spec.unit}\n"
    await asyncio.to_thread(run, ["systemctl", "enable", "--now", spec.unit])
    yield f"{name} is installed and running\n"


async def _uninstall_source(
    name: str, spec: ModuleSpec, *, is_data_kept: bool
) -> AsyncIterator[str]:
    async for line in _provisioner_stream(
        lambda report: spec.provisioner().deprovision(
            is_data_kept=is_data_kept, report=report
        )
    ):
        yield line
    yield f"{name} is uninstalled\n"


async def _provisioner_stream(work) -> AsyncIterator[str]:
    """Run a provisioner in a thread, yielding its progress lines live.

    The provisioners are synchronous and report through a callback; the task
    stream wants an async iterator. A queue bridges the two, with a sentinel
    marking the end so the stream closes when the work does.

    Args:
        work: Callable taking the report callback and doing the job.

    Yields:
        Progress lines, then the result message.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def report(line: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, f"{line}\n")

    def finished(task: asyncio.Task) -> None:
        queue.put_nowait(None)

    job = asyncio.create_task(asyncio.to_thread(work, report))
    job.add_done_callback(finished)
    while True:
        line = await queue.get()
        if line is None:
            break
        yield line
    # Raises here when the work failed, which the task registry reports.
    result = job.result()
    yield f"{result.message}\n"


def _spec_or_404(name: str) -> ModuleSpec:
    spec = MODULE_SPECS.get(name)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{name} is not something the panel installs or removes",
        )
    return spec


def _to_view(entry) -> ServiceView:
    spec = MODULE_SPECS.get(entry.name)
    if spec is None:
        return ServiceView(
            name=entry.name,
            unit=entry.unit,
            is_installed=entry.is_installed,
            is_active=entry.is_active,
            is_enabled=entry.is_enabled,
            is_core=entry.name in SYSTEM_CORE_UNITS,
        )
    is_supported = (
        ANY_ARCHITECTURE in spec.architectures
        or machine_architecture() in spec.architectures
    )
    return ServiceView(
        name=entry.name,
        unit=entry.unit,
        is_installed=entry.is_installed,
        is_active=entry.is_active,
        is_enabled=entry.is_enabled,
        is_core=entry.name in SYSTEM_CORE_UNITS,
        is_installable=True,
        is_machine_supported=is_supported,
        unsupported_reason=(
            None
            if is_supported
            else (
                f"runs on {', '.join(spec.architectures)}; this machine is "
                f"{machine_architecture()}"
            )
        ),
        install_note=spec.install_note,
        data_description=spec.data_description,
    )
