"""The Settings tab: the panel's own port, password, backup and versions."""

import io
import platform
import tarfile
import time

import psutil
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from neutrino_hub.modules.credentials.vault import (
    VaultError,
    VaultPassphraseError,
    is_sealed,
    seal_bytes,
    unseal_bytes,
)
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.web.auth import hash_password, verify_password
from neutrino_hub.web.constants import (
    WEB_DEFAULT_LISTEN_PORT,
    WEB_PORT_MAX,
    WEB_PORT_MIN,
    WEB_RESTART_DELAY_S,
)
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    AboutView,
    BackupRequest,
    PanelSettings,
    PasswordChange,
    PasswordChangeResult,
)
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
PANEL_SETTINGS_FILE = "web/settings.json"

# The 400s the panel turns into its own sentences.
BACKUP_ERROR_PASSPHRASE_NEEDED = "backup_passphrase_needed"
BACKUP_ERROR_PASSPHRASE_WRONG = "backup_passphrase_wrong"


@router.get("", response_model=PanelSettings)
def read_settings(runtime: PanelRuntime = Depends(get_runtime)) -> PanelSettings:
    """Read the panel's own settings.

    Args:
        runtime: The shared runtime.

    Returns:
        The port the panel answers on.
    """
    return PanelSettings(
        listen_port=int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))
    )


@router.put("", response_model=PanelSettings)
def update_settings(
    request: PanelSettings,
    background: BackgroundTasks,
    runtime: PanelRuntime = Depends(get_runtime),
) -> PanelSettings:
    """Move the panel to another port.

    The answer goes out first and the restart happens behind it, because the
    process serving this request is the one being restarted: the browser is
    told where to look before the socket it asked on closes.

    Args:
        request: The port to answer on.
        background: Where the restart is queued.
        runtime: The shared runtime.

    Returns:
        The port the panel is moving to.

    Raises:
        HTTPException: 400 when the port is not one a listener may take.
    """
    if not WEB_PORT_MIN <= request.listen_port <= WEB_PORT_MAX:
        raise _bad_request(
            f"a port is {WEB_PORT_MIN} to {WEB_PORT_MAX}; {request.listen_port} is not"
        )
    settings = read_config(PANEL_SETTINGS_FILE)
    if int(settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT)) == request.listen_port:
        return request
    settings["listen_port"] = request.listen_port
    write_config(PANEL_SETTINGS_FILE, settings)
    runtime.settings["listen_port"] = request.listen_port
    background.add_task(_restart_panel)
    return request


def _restart_panel() -> None:
    """Restart the unit this is running inside.

    ``--no-block`` and a moment's wait, for the same reason everything else
    the hub asks systemd for uses them: the job stops the process making the
    request, and waiting on it would be waiting on itself.
    """
    time.sleep(WEB_RESTART_DELAY_S)
    run(
        ["systemctl", "restart", "--no-block", SYSTEM_CORE_UNITS["web"]],
        is_checked=False,
    )


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


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
    settings = read_config(PANEL_SETTINGS_FILE)
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
    write_config(PANEL_SETTINGS_FILE, settings)
    runtime.sessions.update_password_hash(new_hash)
    return PasswordChangeResult(is_changed=True)


@router.post("/backup")
def backup(request: BackupRequest) -> StreamingResponse:
    """Download the whole ``config/`` directory, plain or sealed.

    Restoring this on a fresh machine and running the installer reproduces the
    appliance, which is why it includes the device keys. Under a passphrase
    the whole archive travels as one sealed container — the vault's master key
    rides inside it, protected with everything else.

    Args:
        request: The passphrase to seal the archive under; blank downloads it
            plain.

    Returns:
        A streaming download: a ``.tar.gz``, or a ``.sealed`` container.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(UTILS_CONFIG_DIR, arcname="config")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if request.passphrase:
        payload = seal_bytes(buffer.getvalue(), request.passphrase)
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="neutrino_config_{stamp}.sealed"'
                )
            },
        )
    buffer.seek(0)
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
async def restore(file: UploadFile, passphrase: str = Form("")) -> dict:
    """Replace ``config/`` from an uploaded backup.

    A sealed container is opened in memory before anything is written, so a
    missing or wrong passphrase leaves the box exactly as it was.

    Args:
        file: The uploaded ``.tar.gz`` or ``.sealed`` container.
        passphrase: What the container was sealed under, blank for a plain
            archive.

    Returns:
        Whether the restore succeeded.

    Raises:
        HTTPException: 400 when the archive is too large, unreadable, holds a
            member that would land outside ``config/``, or is sealed and the
            passphrase is missing or wrong. This endpoint unpacks as root, so
            where each member resolves to is checked rather than where its
            name appears to start.
    """
    payload = await file.read(RESTORE_SIZE_LIMIT_BYTES + 1)
    if len(payload) > RESTORE_SIZE_LIMIT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="backup is too large"
        )
    if is_sealed(payload):
        if not passphrase:
            raise _coded_bad_request(BACKUP_ERROR_PASSPHRASE_NEEDED)
        try:
            payload = unseal_bytes(payload, passphrase)
        except VaultPassphraseError as error:
            raise _coded_bad_request(BACKUP_ERROR_PASSPHRASE_WRONG) from error
        except VaultError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unreadable backup: {error}",
            ) from error
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


def _coded_bad_request(code: str) -> HTTPException:
    """One 400 the panel turns into a sentence of its own.

    Args:
        code: The name the panel switches on.

    Returns:
        The exception to raise.
    """
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": code})


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
