"""The Settings tab: password, config backup and restore, versions."""

import io
import platform
import tarfile
import time

import psutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.web.auth import hash_password, verify_password
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import AboutView, PasswordChange, PasswordChangeResult
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.xray.constants import XRAY_BINARY

router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_session)]
)

# The one version both packages share; an agent reporting a different one
# is asked to upgrade rather than negotiated with.
GATEWAY_VERSION = HUB_VERSION
RESTORE_SIZE_LIMIT_BYTES = 32 * 1024 * 1024


@router.put("/password", response_model=PasswordChangeResult)
def change_password(
    request: PasswordChange, runtime: PanelRuntime = Depends(get_runtime)
) -> PasswordChangeResult:
    """Replace the panel password.

    Every existing session is dropped, so a password change also logs out any
    other browser that was still holding one.

    Args:
        request: The current and new passwords.
        runtime: The shared runtime.

    Returns:
        Whether the change went through.

    Raises:
        HTTPException: 400 when the current password is wrong or the new one is
            too short.
    """
    settings = read_config("web/settings.json")
    if not verify_password(
        request.current_password, settings.get("admin_password_hash", "")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="current password is wrong"
        )
    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the new password needs at least 8 characters",
        )
    new_hash = hash_password(request.new_password)
    settings["admin_password_hash"] = new_hash
    write_config("web/settings.json", settings)
    runtime.sessions.update_password_hash(new_hash)
    return PasswordChangeResult(is_changed=True)


@router.get("/backup")
def backup() -> StreamingResponse:
    """Download the whole ``config/`` directory as a tarball.

    Restoring this on a fresh machine and running the installer reproduces the
    appliance, which is why it includes the device keys.

    Returns:
        A streaming ``.tar.gz`` download.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(UTILS_CONFIG_DIR, arcname="config")
    buffer.seek(0)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buffer,
        media_type="application/gzip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="neutrino_config_{stamp}.tar.gz"'
            )
        },
    )


@router.post("/restore")
async def restore(file: UploadFile) -> dict:
    """Replace ``config/`` from an uploaded backup.

    Args:
        file: The uploaded ``.tar.gz``.

    Returns:
        Whether the restore succeeded.

    Raises:
        HTTPException: 400 when the archive is too large, unreadable, or holds
            a member that would land outside ``config/``. This endpoint
            unpacks as root, so where each member resolves to is checked
            rather than where its name appears to start.
    """
    payload = await file.read(RESTORE_SIZE_LIMIT_BYTES + 1)
    if len(payload) > RESTORE_SIZE_LIMIT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="backup is too large"
        )
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = [_checked_member(member) for member in archive.getmembers()]
            # The data filter is the second line of defence, not the first:
            # it also refuses absolute paths, traversal and special files.
            archive.extractall(
                path=UTILS_CONFIG_DIR.parent, members=members, filter="data"
            )
    except tarfile.TarError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unreadable backup: {error}",
        ) from error
    return {"is_restored": True}


def _checked_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
    """Confirm one archive member may be written, and hand it back.

    A name beginning with ``config/`` proves nothing: ``config/../../etc/x``
    begins that way and lands in ``/etc``. What settles it is where the path
    resolves to once joined to the destination.

    Args:
        member: The member about to be unpacked.

    Returns:
        The same member, when it is safe to write.

    Raises:
        HTTPException: 400 when the member would escape ``config/`` or is not
            an ordinary file or directory.
    """
    if not (member.isreg() or member.isdir()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"a backup holds only files and directories: {member.name}",
        )
    destination = (UTILS_CONFIG_DIR.parent / member.name).resolve()
    if destination != UTILS_CONFIG_DIR and not destination.is_relative_to(
        UTILS_CONFIG_DIR
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unexpected path in backup: {member.name}",
        )
    return member


@router.get("/about", response_model=AboutView)
def about() -> AboutView:
    """Read component versions and host uptime.

    Returns:
        Version strings for the panel and xray, plus the kernel and uptime.
    """
    xray_version = run([XRAY_BINARY, "version"], is_checked=False).stdout
    return AboutView(
        xray_version=(xray_version.splitlines() or ["not installed"])[0],
        gateway_version=GATEWAY_VERSION,
        kernel=platform.release(),
        uptime_s=int(time.time() - psutil.boot_time()),
    )
