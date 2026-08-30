"""The ZFS tab: disks, pools, datasets, and the Samba hand-off.

Unlike every other tab there is no config file behind this one: a pool's
truth is written on its member disks, so reads go straight to the tools and
each action returns the fresh view. The dangerous questions — "really wipe
these disks", "really destroy this pool" — are asked by the page; the routes
assume the asking already happened.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.samba.config import SHARE_NAME_PATTERN, SambaShare
from neutrino_hub.modules.zfs.constants import (
    ZFS_COMPRESSIONS,
    ZFS_DATASET_NAME_PATTERN,
    ZFS_POOL_NAME_PATTERN,
    ZFS_RECORDSIZES,
    ZFS_RESERVED_POOL_NAMES,
    ZFS_VDEV_LAYOUTS,
)
from neutrino_hub.modules.zfs.ops import (
    ZfsDataset,
    ZfsDatasetManager,
    ZfsDiskScanner,
    ZfsPoolManager,
    ZfsPoolReader,
    is_zfs_installed,
)
from neutrino_hub.utils.subprocess_run import CommandError
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ZfsDatasetCreate,
    ZfsDatasetRequest,
    ZfsDatasetView,
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
    ZfsView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/zfs", tags=["zfs"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=ZfsView)
async def read_zfs(runtime: PanelRuntime = Depends(get_runtime)) -> ZfsView:
    """Read the whole storage picture.

    Args:
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/pools", response_model=ZfsView)
async def create_pool(
    request: ZfsPoolCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Create a pool with one vdev.

    Args:
        request: Name, layout, and the member disks by id.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.

    Raises:
        HTTPException: 400 on a bad name or layout, 502 when zpool refuses.
    """
    _validate_pool_name(request.name)
    _validate_vdev(request.layout, request.devices)
    await _work(
        lambda: ZfsPoolManager().create(
            name=request.name,
            layout=request.layout,
            devices=request.devices,
            is_forced=request.is_forced,
        )
    )
    return await asyncio.to_thread(_build_view, runtime)


@router.delete("/pools/{name}", response_model=ZfsView)
async def destroy_pool(
    name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Destroy a pool and everything on it.

    Shares pointing into the pool are removed with it — a share of a
    directory that no longer exists is only a confusing error later.

    Args:
        name: The pool. The page asked for its name to be typed back.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.

    Raises:
        HTTPException: 502 when zpool refuses.
    """
    mountpoints = [
        dataset.mountpoint
        for dataset in await asyncio.to_thread(ZfsPoolReader().datasets)
        if dataset.name == name or dataset.name.startswith(f"{name}/")
    ]
    await _work(lambda: ZfsPoolManager().destroy(name))
    await _drop_shares(runtime, mountpoints)
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/pools/{name}/scrub", response_model=ZfsView)
async def scrub(name: str, runtime: PanelRuntime = Depends(get_runtime)) -> ZfsView:
    """Start scrubbing a pool.

    Args:
        name: The pool.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    await _work(lambda: ZfsPoolManager().start_scrub(name))
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/pools/{name}/scrub/stop", response_model=ZfsView)
async def stop_scrub(
    name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Stop a running scrub.

    Args:
        name: The pool.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    await _work(lambda: ZfsPoolManager().stop_scrub(name))
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/pools/{name}/expand", response_model=ZfsView)
async def expand_pool(
    name: str, request: ZfsPoolExpand, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Grow a pool by another vdev, permanently.

    Args:
        name: The pool.
        request: The new vdev's layout and disks.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.

    Raises:
        HTTPException: 400 on a bad layout, 502 when zpool refuses.
    """
    _validate_vdev(request.layout, request.devices)
    await _work(
        lambda: ZfsPoolManager().add_vdev(
            pool=name,
            layout=request.layout,
            devices=request.devices,
            is_forced=request.is_forced,
        )
    )
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/pools/{name}/replace", response_model=ZfsView)
async def replace_disk(
    name: str, request: ZfsReplaceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Swap a member disk for a fresh one and start the resilver.

    Args:
        name: The pool.
        request: The old member and the new disk.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    await _work(
        lambda: ZfsPoolManager().replace(
            pool=name, old_device=request.old_device, new_device=request.new_device
        )
    )
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/pools/{name}/offline", response_model=ZfsView)
async def offline_disk(
    name: str,
    request: ZfsDiskActionRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsView:
    """Take a member disk offline, ready to be pulled.

    Args:
        name: The pool.
        request: The member device.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    await _work(lambda: ZfsPoolManager().offline(pool=name, device=request.device))
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/pools/{name}/online", response_model=ZfsView)
async def online_disk(
    name: str,
    request: ZfsDiskActionRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ZfsView:
    """Bring an offlined member back into service.

    Args:
        name: The pool.
        request: The member device.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    await _work(lambda: ZfsPoolManager().online(pool=name, device=request.device))
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/import/{name}", response_model=ZfsView)
async def import_pool(
    name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Import a pool found on attached disks.

    Args:
        name: The pool as the import scan listed it.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    await _work(lambda: ZfsPoolManager().import_pool(name))
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/datasets", response_model=ZfsView)
async def create_dataset(
    request: ZfsDatasetCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Create a dataset.

    Args:
        request: Pool, name, and compression.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.

    Raises:
        HTTPException: 400 on a bad name or compression, 502 when zfs refuses.
    """
    _validate_dataset_path(request.name)
    _validate_tunables(request.compression, request.recordsize)
    _validate_mountpoint(request.mountpoint)
    await _work(
        lambda: ZfsDatasetManager().create(
            pool=request.pool,
            name=request.name,
            compression=request.compression,
            recordsize=request.recordsize,
            mountpoint=request.mountpoint,
        )
    )
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/datasets/destroy", response_model=ZfsView)
async def destroy_dataset(
    request: ZfsDatasetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Destroy a dataset and its files.

    Args:
        request: The dataset. The page asked for its name to be typed back.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    dataset = await asyncio.to_thread(_find_dataset, request.dataset)
    await _work(lambda: ZfsDatasetManager().destroy(request.dataset))
    await _drop_shares(runtime, [dataset.mountpoint])
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/datasets/share", response_model=ZfsView)
async def share_dataset(
    request: ZfsShareRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Expose a dataset over Samba.

    The share is an ordinary entry in the Samba configuration, named after
    the dataset's last path piece; everything else — users, passwords,
    directory permissions — is the Samba module's existing machinery.

    Args:
        request: The dataset and who may open the share.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.

    Raises:
        HTTPException: 400 when the share cannot be made, 502 when applying
            the Samba configuration fails.
    """
    dataset = await asyncio.to_thread(_find_dataset, request.dataset)
    if not dataset.mountpoint.startswith("/"):
        raise _bad_request(f"{request.dataset} is not mounted")

    config = runtime.samba()
    if any(share.path == dataset.mountpoint for share in config.shares):
        raise _bad_request(f"{request.dataset} is already shared")
    name = request.dataset.rsplit("/", 1)[-1]
    if not SHARE_NAME_PATTERN.match(name):
        raise _bad_request(f"{name!r} does not work as a share name")
    if any(share.name == name for share in config.shares):
        raise _bad_request(f"a share named {name!r} already exists")
    for user in request.users:
        if user not in config.users:
            raise _bad_request(f"{user!r} is not a Samba user")

    config.shares.append(
        SambaShare(
            name=name,
            path=dataset.mountpoint,
            comment=f"ZFS dataset {request.dataset}",
            valid_users=list(request.users),
        )
    )
    runtime.write_samba(config)
    try:
        await runtime.apply_samba()
    except CommandError as error:
        raise _bad_gateway(str(error)) from error
    return await asyncio.to_thread(_build_view, runtime)


@router.post("/datasets/unshare", response_model=ZfsView)
async def unshare_dataset(
    request: ZfsDatasetRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ZfsView:
    """Remove a dataset's Samba share, leaving its files alone.

    Args:
        request: The dataset.
        runtime: The shared runtime.

    Returns:
        The ZFS tab payload.
    """
    dataset = await asyncio.to_thread(_find_dataset, request.dataset)
    await _drop_shares(runtime, [dataset.mountpoint])
    return await asyncio.to_thread(_build_view, runtime)


def _build_view(runtime: PanelRuntime) -> ZfsView:
    if not is_zfs_installed():
        return ZfsView(is_installed=False, samba=_samba_view(runtime))

    reader = ZfsPoolReader()
    pools = reader.pools()
    datasets = reader.datasets()
    disks = ZfsDiskScanner().scan(pool_members=reader.member_pools(pools))
    shares_by_path = {share.path: share.name for share in runtime.samba().shares}

    dataset_views = [
        ZfsDatasetView(
            name=dataset.name,
            used_bytes=dataset.used_bytes,
            available_bytes=dataset.available_bytes,
            mountpoint=dataset.mountpoint,
            compression=dataset.compression,
            compressratio=dataset.compressratio,
            recordsize_bytes=dataset.recordsize_bytes,
            share=shares_by_path.get(dataset.mountpoint),
        )
        for dataset in datasets
    ]

    return ZfsView(
        is_installed=True,
        pools=[
            ZfsPoolView(
                name=pool.name,
                state=pool.state,
                size_bytes=pool.size_bytes,
                allocated_bytes=pool.allocated_bytes,
                capacity_percent=pool.capacity_percent,
                fragmentation_percent=pool.fragmentation_percent,
                vdevs=[
                    ZfsVdevView(
                        name=vdev.name,
                        layout=vdev.layout,
                        state=vdev.state,
                        members=[
                            ZfsVdevMemberView(
                                name=member.name,
                                state=member.state,
                                read_errors=member.read_errors,
                                write_errors=member.write_errors,
                                checksum_errors=member.checksum_errors,
                                is_resilvering=member.is_resilvering,
                            )
                            for member in vdev.members
                        ],
                    )
                    for vdev in pool.vdevs
                ],
                scan=ZfsScanView(
                    kind=pool.scan.kind,
                    percent=pool.scan.percent,
                    eta=pool.scan.eta,
                    summary=pool.scan.summary,
                ),
                errors=pool.errors,
                datasets=[
                    view
                    for view in dataset_views
                    if view.name == pool.name or view.name.startswith(f"{pool.name}/")
                ],
            )
            for pool in pools
        ],
        disks=[
            ZfsDiskView(
                device=disk.device,
                by_id=disk.by_id,
                size_bytes=disk.size_bytes,
                model=disk.model,
                serial=disk.serial,
                is_rotational=disk.is_rotational,
                transport=disk.transport,
                wwn=disk.wwn,
                by_path=disk.by_path,
                fstype=disk.fstype,
                pool=disk.pool,
                is_available=disk.is_available,
                smart_passed=disk.smart_passed,
                temperature_c=disk.temperature_c,
            )
            for disk in disks
            if not disk.is_system
        ],
        importable=[
            ZfsImportableView(name=candidate.name, state=candidate.state)
            for candidate in reader.importable()
        ],
        samba=_samba_view(runtime),
    )


def _samba_view(runtime: PanelRuntime) -> ZfsSambaView:
    try:
        samba = runtime.services.status("samba")
        is_ready = samba.is_installed and samba.is_active
    except KeyError:
        is_ready = False
    return ZfsSambaView(
        is_ready=is_ready,
        users=runtime.samba().users if is_ready else [],
    )


def _find_dataset(name: str) -> ZfsDataset:
    for dataset in ZfsPoolReader().datasets():
        if dataset.name == name:
            return dataset
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"{name} is not a dataset"
    )


async def _drop_shares(runtime: PanelRuntime, mountpoints: list[str]) -> None:
    """Remove any Samba shares rooted at these paths, if there are any.

    A failure applying Samba here is reported, not fatal: the storage action
    already happened, and the stale share is visible on the Samba page.
    """
    config = runtime.samba()
    kept = [share for share in config.shares if share.path not in mountpoints]
    if len(kept) == len(config.shares):
        return
    config.shares = kept
    runtime.write_samba(config)
    try:
        await runtime.apply_samba()
    except CommandError:
        pass


async def _work(action) -> None:
    try:
        await asyncio.to_thread(action)
    except CommandError as error:
        raise _bad_gateway(str(error)) from error


def _validate_pool_name(name: str) -> None:
    if not ZFS_POOL_NAME_PATTERN.match(name):
        raise _bad_request(
            "pool names start with a letter and use lower-case letters, "
            "digits, _ and -, up to 30"
        )
    if name in ZFS_RESERVED_POOL_NAMES:
        raise _bad_request(f"{name!r} means something to zpool itself; pick another")


def _validate_vdev(layout: str, devices: list[str]) -> None:
    minimum = ZFS_VDEV_LAYOUTS.get(layout)
    if minimum is None:
        raise _bad_request(f"unknown vdev layout {layout!r}")
    if len(devices) < minimum:
        raise _bad_request(f"{layout} needs at least {minimum} disks")
    if layout == "single" and len(devices) > 1:
        raise _bad_request("a single-disk vdev takes exactly one disk")


def _validate_dataset_path(name: str) -> None:
    """Check a dataset path: slash-separated pieces, each a plain name.

    Args:
        name: The path under the pool, for example ``nfs/home``.

    Raises:
        HTTPException: 400 when a piece breaks the naming rules.
    """
    pieces = name.split("/")
    if not pieces or any(not ZFS_DATASET_NAME_PATTERN.match(piece) for piece in pieces):
        raise _bad_request(
            "dataset paths are names of lower-case letters, digits, _ and -, "
            "joined by slashes, for example nfs/home"
        )


# Mounting a dataset over these would bury the operating system alive.
FORBIDDEN_MOUNT_ROOTS = (
    "bin",
    "boot",
    "dev",
    "etc",
    "lib",
    "lib64",
    "proc",
    "run",
    "sbin",
    "sys",
    "usr",
)


def _validate_mountpoint(mountpoint: str | None) -> None:
    if mountpoint is None:
        return
    if (
        not mountpoint.startswith("/")
        or mountpoint == "/"
        or ".." in mountpoint
        or any(character.isspace() for character in mountpoint)
    ):
        raise _bad_request("the mountpoint must be an absolute path such as /srv/data")
    if mountpoint.split("/")[1] in FORBIDDEN_MOUNT_ROOTS:
        raise _bad_request(f"{mountpoint} would sit over the operating system")


def _validate_tunables(compression: str, recordsize: str) -> None:
    if compression not in ZFS_COMPRESSIONS:
        raise _bad_request(f"compression must be one of: {', '.join(ZFS_COMPRESSIONS)}")
    if recordsize not in ZFS_RECORDSIZES:
        raise _bad_request(f"recordsize must be one of: {', '.join(ZFS_RECORDSIZES)}")


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _bad_gateway(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
