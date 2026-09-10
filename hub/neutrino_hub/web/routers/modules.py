"""The Modules tab: status, start/stop/enable, install/uninstall, journals."""

import asyncio
import subprocess
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status

from neutrino_hub.modules.registry import MODULE_SPECS, ModuleSpec
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.system.machine import ANY_ARCHITECTURE, machine_architecture
from neutrino_hub.system.provisioning import plan_for
from neutrino_hub.utils.subprocess_run import command_failure_text, run
from neutrino_hub.web.constants import WEB_JOURNAL_LINE_LIMIT
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    JournalView,
    ModuleInstallPlanView,
    ModuleInstallRequest,
    ModuleListView,
    ModuleUninstallRequest,
    ModuleView,
    ProvisionConsentView,
    TaskListView,
    TaskStarted,
    TaskView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/modules", tags=["modules"], dependencies=[Depends(require_session)]
)

# Refused outright on a core unit. Not hidden in the panel and allowed through
# the API: the panel is not the only thing that can POST here, and a core
# service stopped by any route leaves the same dark box.
STOPPING_ACTIONS = ("stop", "disable")


@router.get("", response_model=ModuleListView)
def list_modules(runtime: PanelRuntime = Depends(get_runtime)) -> ModuleListView:
    """Read every managed unit's state.

    Args:
        runtime: The shared runtime.

    Returns:
        One entry per managed unit.
    """
    return ModuleListView(
        modules=[_to_view(entry) for entry in runtime.services.status_all()]
    )


@router.get("/tasks", response_model=TaskListView)
def list_tasks(runtime: PanelRuntime = Depends(get_runtime)) -> TaskListView:
    """Read the background jobs this panel is still running.

    Args:
        runtime: The shared runtime.

    Returns:
        One entry per unfinished job, with the label it was started under. A
        page reads this on load: the id it was streaming lived in the browser,
        the job did not, so a reload used to leave an install running with
        nothing watching it and a live Install button beside it.
    """
    return TaskListView(
        tasks=[
            TaskView(id=stream.id, label=stream.label)
            for stream in runtime.tasks.running_all()
        ]
    )


@router.get("/{name}/journal", response_model=JournalView)
def journal(
    name: str,
    lines: int = Query(default=100, ge=1, le=WEB_JOURNAL_LINE_LIMIT),
    runtime: PanelRuntime = Depends(get_runtime),
) -> JournalView:
    """Read the tail of a unit's journal.

    Args:
        name: Panel-facing service name.
        lines: How many lines to return, at most
            :data:`WEB_JOURNAL_LINE_LIMIT`. Unbounded, this reads a whole unit
            journal into one response; negative, journalctl rejects the option
            and its usage message is rendered as though it were log output.
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


@router.get("/{name}/install_plan", response_model=ModuleInstallPlanView)
def install_plan(name: str) -> ModuleInstallPlanView:
    """What installing this module on this machine would actually do.

    The panel asks before it offers the button, so anything a person would
    want to have been asked about — a kernel module compiled against the
    running kernel, a third-party repository — is a decision rather than a
    surprise in a log.

    Args:
        name: Panel-facing module name.

    Returns:
        The plan, with an empty consent list for the ordinary module that
        only installs packages.

    Raises:
        HTTPException: 404 for a name the panel cannot install.
    """
    spec = _spec_or_404(name)
    plan = plan_for(spec.provisioner())
    return ModuleInstallPlanView(
        name=name,
        is_consent_needed=plan.is_consent_needed,
        consents=[
            ProvisionConsentView(code=consent.code, detail=consent.detail)
            for consent in plan.consents
        ],
    )


@router.post("/{name}/install", response_model=TaskStarted)
async def install(
    name: str,
    request: ModuleInstallRequest | None = None,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TaskStarted:
    """Install an optional module as a streamed background job.

    Once provisioned it is enabled and started: installing a thing and then
    leaving it dark would only add a second step that everyone performs.

    Args:
        name: Panel-facing module name.
        request: Whether the person agreed to what the plan listed.
        runtime: The shared runtime.

    Returns:
        The task id to stream on ``/ws/task/{task_id}``.

    Returns the running job's id when one is already installing this module,
    so a second press joins the first rather than starting a second install.

    Raises:
        HTTPException: 404 for a name the panel cannot install, 400 on a
            machine the module does not run on, and 409 when the plan needs
            agreement that did not arrive with the request.
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
    is_consented = request.is_consented if request is not None else False
    if plan_for(spec.provisioner()).is_consent_needed and not is_consented:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"installing {name} here needs agreement that was not given",
        )
    # One at a time. Two installs of one module are two downloads writing one
    # path and two package managers on one lock: the second corrupts what the
    # first fetched, and the browser only ever sees the log of whichever
    # started last.
    running = runtime.tasks.running(f"install {name}")
    if running is not None:
        return TaskStarted(task_id=running.id)
    stream = runtime.tasks.start(
        label=f"install {name}",
        source=_install_source(name, spec, is_consented=is_consented),
    )
    return TaskStarted(task_id=stream.id)


@router.post("/{name}/uninstall", response_model=TaskStarted)
async def uninstall(
    name: str,
    request: ModuleUninstallRequest,
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
            core module. netbird is not one: a gateway routes, resolves and
            serves without it, so it installs and leaves from here like any
            other optional module.
    """
    spec = _spec_or_404(name)
    if name in SYSTEM_CORE_UNITS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"{name} is a core service and cannot be uninstalled"),
        )
    running = runtime.tasks.running(f"uninstall {name}")
    if running is not None:
        return TaskStarted(task_id=running.id)
    stream = runtime.tasks.start(
        label=f"uninstall {name}",
        source=_uninstall_source(name, spec, is_data_kept=request.is_data_kept),
    )
    return TaskStarted(task_id=stream.id)


@router.post("/{name}/{action}", response_model=ModuleView)
def control(
    name: str, action: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ModuleView:
    """Start, stop, restart, enable, or disable a unit.

    Args:
        name: Panel-facing service name.
        action: The systemd verb to run.
        runtime: The shared runtime.

    Returns:
        The unit's state after the change.

    Raises:
        HTTPException: 404 for an unknown service, 400 for a disallowed action
            or a module that is not installed, 502 when systemd refuses.
    """
    if name in SYSTEM_CORE_UNITS and action in STOPPING_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"{name} is a core service and cannot be {action}ped"),
        )
    try:
        state = runtime.services.status(name)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    if not state.is_installed:
        # Said here rather than let through: systemd's answer is "Unit
        # x.service does not exist", which reaches the page as an error about
        # a file when the thing to know is that the module is not installed.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} is not installed, so there is nothing to {action}",
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
    except (subprocess.SubprocessError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=command_failure_text(error),
        ) from error
    return _to_view(runtime.services.status(name))


def _provision(spec: ModuleSpec, *, is_consented: bool, report):
    """Run a provisioner, passing consent only to one that asks for it.

    Most provisioners take no such argument, and adding one to every module
    for the sake of the two that need it would be a parameter nobody reads.

    Args:
        spec: The module being installed.
        is_consented: Whether the person agreed to the plan.
        report: Sink for progress lines.

    Returns:
        What the provisioner did.
    """
    provisioner = spec.provisioner()
    if getattr(provisioner, "plan", None) is None:
        return provisioner.provision(report=report)
    return provisioner.provision(is_consented=is_consented, report=report)


async def _install_source(
    name: str, spec: ModuleSpec, *, is_consented: bool
) -> AsyncIterator[str]:
    async for line in _provisioner_stream(
        lambda report: _provision(spec, is_consented=is_consented, report=report)
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


def _to_view(entry) -> ModuleView:
    spec = MODULE_SPECS.get(entry.name)
    if spec is None:
        return ModuleView(
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
    return ModuleView(
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
