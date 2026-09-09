"""The ZFS page: which devices carry the tools, and each one's storage.

There is no configuration behind this page: a pool's truth is written on
its member disks, so reads come from the device's last report and each
verb runs on the device and answers the fresh view. The dangerous
questions, really wipe these disks, really destroy this pool, are asked by
the page; the routes assume the asking already happened. Sharing a dataset
is the one verb that writes: the share is an ordinary entry in the device's
Samba configuration.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    ZfsDatasetCreate,
    ZfsDatasetRequest,
    ZfsDatasetView,
    ZfsDeviceView,
    ZfsDiskActionRequest,
    ZfsDiskView,
    ZfsImportableView,
    ZfsPoolCreate,
    ZfsPoolExpand,
    ZfsPoolView,
    ZfsReplaceRequest,
    ZfsSambaView,
    ZfsScanView,
    ZfsShareRequest,
    ZfsVdevMemberView,
    ZfsVdevView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.device_modules import (
    DeviceModuleContext,
    device_context,
    module_router,
    run_command,
    store_config,
)

MODULE = "zfs"
SAMBA_MODULE = "samba"
COMMAND_OP = "zfs_op"
COMMAND_SCAN = "zfs_scan"


def device_view(runtime: PanelRuntime, context: DeviceModuleContext) -> ZfsDeviceView:
    """One device's whole storage picture, as last reported.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The ZFS page payload for the device.
    """
    details = context.details
    samba_config = runtime.desired_states.read(context.key, SAMBA_MODULE)
    shares_by_path = {
        str(share.get("path", "")): str(share.get("name", ""))
        for share in samba_config.get("shares", [])
        if isinstance(share, dict)
    }
    dataset_views = [
        ZfsDatasetView(
            **dataset, share=shares_by_path.get(str(dataset.get("mountpoint")))
        )
        for dataset in details.get("datasets") or []
        if isinstance(dataset, dict)
    ]
    pools = []
    for pool in details.get("pools") or []:
        if not isinstance(pool, dict):
            continue
        pools.append(
            ZfsPoolView(
                name=pool["name"],
                state=str(pool.get("state", "")),
                size_bytes=int(pool.get("size_bytes", 0)),
                allocated_bytes=int(pool.get("allocated_bytes", 0)),
                capacity_percent=int(pool.get("capacity_percent", 0)),
                fragmentation_percent=int(pool.get("fragmentation_percent", 0)),
                vdevs=[
                    ZfsVdevView(
                        name=vdev.get("name", ""),
                        layout=vdev.get("layout", ""),
                        state=vdev.get("state", ""),
                        members=[
                            ZfsVdevMemberView(**member)
                            for member in vdev.get("members") or []
                        ],
                    )
                    for vdev in pool.get("vdevs") or []
                ],
                scan=ZfsScanView(**(pool.get("scan") or {})),
                errors=str(pool.get("errors", "") or ""),
                datasets=[
                    view
                    for view in dataset_views
                    if view.name == pool["name"]
                    or view.name.startswith(f"{pool['name']}/")
                ],
            )
        )
    samba_status = runtime.client_modules.get(context.key, {}).get(SAMBA_MODULE) or {}
    samba_details = samba_status.get("details") or {}
    is_samba_ready = (
        samba_status.get("state") == "installed"
        and runtime.desired_states.is_enabled(context.key, SAMBA_MODULE)
        and bool(samba_details.get("is_active"))
    )
    return ZfsDeviceView(
        **context.fields(),
        is_installed=context.state == "installed",
        pools=pools,
        disks=[
            ZfsDiskView(**disk)
            for disk in details.get("disks") or []
            if isinstance(disk, dict)
        ],
        importable=[
            ZfsImportableView(**candidate)
            for candidate in details.get("importable") or []
            if isinstance(candidate, dict)
        ],
        samba=ZfsSambaView(
            is_ready=is_samba_ready,
            users=(
                [str(user) for user in samba_config.get("users", [])]
                if is_samba_ready
                else []
            ),
        ),
    )


router: APIRouter = module_router(
    MODULE, view_model=ZfsDeviceView, build_view=device_view
)


@router.post("/devices/{device_id}/scan", response_model=ZfsDeviceView)
def scan_disks(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsDeviceView:
    """Ask every disk on the device for its SMART verdict.

    Args:
        device_id: The device.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.
    """
    context = device_context(runtime, MODULE, device_id)
    run_command(runtime, context, COMMAND_SCAN, {})
    return device_view(runtime, context)


@router.post("/devices/{device_id}/pools", response_model=ZfsDeviceView)
def create_pool(
    device_id: str, request: ZfsPoolCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsDeviceView:
    """Create a pool with one vdev.

    Args:
        device_id: The device.
        request: Name, layout, and the member disks by id.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 502 with the agent's code for
            a bad name or layout or when zpool refuses.
    """
    return _op(runtime, device_id, "create_pool", request.model_dump())


@router.delete("/devices/{device_id}/pools/{name}", response_model=ZfsDeviceView)
def destroy_pool(
    device_id: str, name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsDeviceView:
    """Destroy a pool and everything on it.

    Shares pointing into the pool are removed with it.

    Args:
        device_id: The device.
        name: The pool. The page asked for its name to be typed back.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.
    """
    context = device_context(runtime, MODULE, device_id)
    mountpoints = [
        str(dataset.get("mountpoint", ""))
        for dataset in context.details.get("datasets") or []
        if isinstance(dataset, dict)
        and (
            dataset.get("name") == name
            or str(dataset.get("name", "")).startswith(f"{name}/")
        )
    ]
    _drop_shares(runtime, device_id, mountpoints)
    run_command(
        runtime, context, COMMAND_OP, {"op": "destroy_pool", "args": {"name": name}}
    )
    return device_view(runtime, context)


@router.post("/devices/{device_id}/pools/{name}/scrub", response_model=ZfsDeviceView)
def scrub(
    device_id: str, name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsDeviceView:
    """Start scrubbing a pool."""
    return _op(runtime, device_id, "scrub", {"name": name})


@router.post(
    "/devices/{device_id}/pools/{name}/scrub/stop", response_model=ZfsDeviceView
)
def stop_scrub(
    device_id: str, name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsDeviceView:
    """Stop a running scrub."""
    return _op(runtime, device_id, "stop_scrub", {"name": name})


@router.post("/devices/{device_id}/pools/{name}/expand", response_model=ZfsDeviceView)
def expand_pool(
    device_id: str,
    name: str,
    request: ZfsPoolExpand,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Grow a pool by another vdev, permanently."""
    return _op(
        runtime, device_id, "expand_pool", {"name": name, **request.model_dump()}
    )


@router.post("/devices/{device_id}/pools/{name}/replace", response_model=ZfsDeviceView)
def replace_disk(
    device_id: str,
    name: str,
    request: ZfsReplaceRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Swap a member disk for a fresh one and start the resilver."""
    return _op(runtime, device_id, "replace", {"name": name, **request.model_dump()})


@router.post("/devices/{device_id}/pools/{name}/offline", response_model=ZfsDeviceView)
def offline_disk(
    device_id: str,
    name: str,
    request: ZfsDiskActionRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Take a member disk offline, ready to be pulled."""
    return _op(runtime, device_id, "offline", {"name": name, "device": request.device})


@router.post("/devices/{device_id}/pools/{name}/online", response_model=ZfsDeviceView)
def online_disk(
    device_id: str,
    name: str,
    request: ZfsDiskActionRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Bring an offlined member back into service."""
    return _op(runtime, device_id, "online", {"name": name, "device": request.device})


@router.post("/devices/{device_id}/import/{name}", response_model=ZfsDeviceView)
def import_pool(
    device_id: str, name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsDeviceView:
    """Import a pool found on attached disks."""
    return _op(runtime, device_id, "import_pool", {"name": name})


@router.post("/devices/{device_id}/datasets", response_model=ZfsDeviceView)
def create_dataset(
    device_id: str,
    request: ZfsDatasetCreate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Create a dataset."""
    return _op(runtime, device_id, "create_dataset", request.model_dump())


@router.post("/devices/{device_id}/datasets/destroy", response_model=ZfsDeviceView)
def destroy_dataset(
    device_id: str,
    request: ZfsDatasetRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Destroy a dataset and its files; its share goes with it."""
    context = device_context(runtime, MODULE, device_id)
    dataset = _find_dataset(context, request.dataset)
    _drop_shares(runtime, device_id, [str(dataset.get("mountpoint", ""))])
    run_command(
        runtime,
        context,
        COMMAND_OP,
        {"op": "destroy_dataset", "args": {"dataset": request.dataset}},
    )
    return device_view(runtime, context)


@router.post("/devices/{device_id}/datasets/share", response_model=ZfsDeviceView)
def share_dataset(
    device_id: str,
    request: ZfsShareRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Expose a dataset over the device's Samba.

    The share is an ordinary entry in the device's Samba configuration,
    named after the dataset's last path piece.

    Args:
        device_id: The device.
        request: The dataset and who may open the share.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 404 ``dataset_unknown``, 400 ``dataset_unmounted``,
            ``share_exists``, ``share_name_taken`` or ``share_user_unknown``,
            409 ``agent_offline``, and the agent's own refusal of the Samba
            configuration.
    """
    context = device_context(runtime, MODULE, device_id)
    dataset = _find_dataset(context, request.dataset)
    mountpoint = str(dataset.get("mountpoint", ""))
    if not mountpoint.startswith("/"):
        raise _bad_request("dataset_unmounted", dataset=request.dataset)
    samba = device_context(runtime, SAMBA_MODULE, device_id)
    config = dict(samba.config)
    shares = list(config.get("shares", []))
    if any(share.get("path") == mountpoint for share in shares):
        raise _bad_request("share_exists", dataset=request.dataset)
    name = request.dataset.rsplit("/", 1)[-1]
    if any(share.get("name") == name for share in shares):
        raise _bad_request("share_name_taken", name=name)
    users = config.get("users", [])
    for user in request.users:
        if user not in users:
            raise _bad_request("share_user_unknown", user=user)
    shares.append(
        {
            "name": name,
            "path": mountpoint,
            "comment": f"ZFS dataset {request.dataset}",
            "is_read_only": False,
            "valid_users": list(request.users),
        }
    )
    config["shares"] = shares
    store_config(runtime, samba, config)
    return device_view(runtime, context)


@router.post("/devices/{device_id}/datasets/unshare", response_model=ZfsDeviceView)
def unshare_dataset(
    device_id: str,
    request: ZfsDatasetRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsDeviceView:
    """Remove a dataset's Samba share, leaving its files alone."""
    context = device_context(runtime, MODULE, device_id)
    dataset = _find_dataset(context, request.dataset)
    _drop_shares(runtime, device_id, [str(dataset.get("mountpoint", ""))])
    return device_view(runtime, context)


def _op(runtime: PanelRuntime, device_id: str, op: str, args: dict) -> ZfsDeviceView:
    """Run one storage verb on the device and answer its view."""
    context = device_context(runtime, MODULE, device_id)
    run_command(runtime, context, COMMAND_OP, {"op": op, "args": dict(args)})
    return device_view(runtime, context)


def _find_dataset(context: DeviceModuleContext, name: str) -> dict:
    for dataset in context.details.get("datasets") or []:
        if isinstance(dataset, dict) and dataset.get("name") == name:
            return dataset
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "dataset_unknown", "params": {"dataset": name}},
    )


def _drop_shares(runtime: PanelRuntime, device_id: str, mountpoints: list) -> None:
    """Remove any Samba shares rooted at these paths, if there are any."""
    samba = device_context(runtime, SAMBA_MODULE, device_id)
    config = dict(samba.config)
    kept = [
        share
        for share in config.get("shares", [])
        if share.get("path") not in mountpoints
    ]
    if len(kept) == len(config.get("shares", [])):
        return
    config["shares"] = kept
    store_config(runtime, samba, config)


def _bad_request(code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail={"code": code, "params": params}
    )
