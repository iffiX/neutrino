"""The Settings tab: the panel's own port, password, backup and versions."""

import hashlib
import io
import json
import platform
import asyncio
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
    unwrap_data_key,
    write_state_key,
)
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)
from neutrino_hub.utils.passwords import (
    PASSWORDS_PANEL_RULES,
    PasswordRuleError,
    validate,
)
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.utils.constants import is_dev_root_set
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

# The archive every backup travels as: one plain tar.gz whose first member
# names what it is, whose second lists every following member's digest, and
# whose rest is the ``config/`` tree as it stands — which after the vault
# rework holds no unsealed secret.
BACKUP_MANIFEST_MEMBER = "neutrino_backup.json"
BACKUP_SUMS_MEMBER = "SHA256SUMS"
BACKUP_KIND = "neutrino_config_backup"
BACKUP_FORMAT_VERSION = 2
BACKUP_EXTENSIONS = (".tar.gz", ".tgz")
BACKUP_VAULT_MEMBER = "credentials/vault.json"

# The 400s the panel turns into its own sentences.
BACKUP_ERROR_WRONG_EXTENSION = "backup_wrong_extension"
BACKUP_ERROR_UNRECOGNIZED = "backup_unrecognized"
BACKUP_ERROR_CORRUPT = "backup_corrupt"
BACKUP_ERROR_PASSPHRASE_NEEDED = "vault_passphrase_needed"
BACKUP_ERROR_PASSPHRASE_WRONG = "vault_passphrase_wrong"


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
        HTTPException: 400 with ``password_wrong`` when the current password
            does not match, or the rule code the new one was refused with.
    """
    settings = read_config(PANEL_SETTINGS_FILE)
    if not verify_password(
        request.current_password, settings.get("admin_password_hash", "")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "password_wrong", "params": {}},
        )
    try:
        validate(request.new_password, PASSWORDS_PANEL_RULES)
    except PasswordRuleError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error.code, "params": error.params},
        ) from error
    new_hash = hash_password(request.new_password)
    settings["admin_password_hash"] = new_hash
    write_config(PANEL_SETTINGS_FILE, settings)
    runtime.sessions.update_password_hash(new_hash)
    return PasswordChangeResult(is_changed=True)


@router.post("/backup")
def backup() -> StreamingResponse:
    """Download the whole ``config/`` directory as one plain archive.

    Restoring this on a fresh machine and running the installer reproduces
    the appliance. The archive travels plainly because ``config/`` holds no
    unsealed secret: the vault's data key rides only wrapped under the master
    passphrase, which is what a restore asks for.

    Returns:
        A streaming ``.tar.gz`` download: the manifest, the digest list, then
        the ``config/`` tree.
    """
    with CONFIG_WRITE_LOCK:
        directories, files = _config_snapshot()
    manifest = json.dumps(
        {"kind": BACKUP_KIND, "version": BACKUP_FORMAT_VERSION}, indent=2
    ).encode()
    sums = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {path}\n" for path, content in files
    ).encode()
    outer = io.BytesIO()
    with tarfile.open(fileobj=outer, mode="w:gz") as archive:
        _add_member(archive, BACKUP_MANIFEST_MEMBER, manifest)
        _add_member(archive, BACKUP_SUMS_MEMBER, sums)
        _add_directory(archive, "config")
        for path in directories:
            _add_directory(archive, f"config/{path}")
        for path, content in files:
            _add_member(archive, f"config/{path}", content)
    outer.seek(0)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        outer,
        media_type="application/gzip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="neutrino_config_{stamp}.tar.gz"'
            )
        },
    )


def _config_snapshot() -> tuple[list[str], list[tuple[str, bytes]]]:
    """Read the whole ``config/`` tree into memory, in one consistent pass.

    Returns:
        The directory paths and the file paths with their bytes, both
        config-relative and sorted.
    """
    directories: list[str] = []
    files: list[tuple[str, bytes]] = []
    for path in sorted(UTILS_CONFIG_DIR.rglob("*")):
        relative = str(path.relative_to(UTILS_CONFIG_DIR))
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files.append((relative, path.read_bytes()))
    return directories, files


def _add_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o600
    member.mtime = int(time.time())
    archive.addfile(member, io.BytesIO(payload))


def _add_directory(archive: tarfile.TarFile, name: str) -> None:
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.mode = 0o700
    member.mtime = int(time.time())
    archive.addfile(member)


@router.post("/restore")
async def restore(
    file: UploadFile,
    vault_passphrase: str = Form(""),
    runtime: PanelRuntime = Depends(get_runtime),
) -> dict:
    """Replace ``config/`` from an uploaded backup.

    Nothing touches disk until the file has proven itself: the name, the
    manifest, every member's digest, and the vault passphrase are all settled
    in memory first, so a foreign, damaged or locked file leaves the box
    exactly as it was. The passphrase is always required — it is what turns
    the archive's wrapped data key back into a working vault.

    Args:
        file: The uploaded ``.tar.gz`` backup.
        vault_passphrase: The master passphrase of the box the backup left.

    Returns:
        Whether the restore succeeded.

    Raises:
        HTTPException: 400 when the file is too large, is not named like a
            backup, does not carry this panel's manifest, fails a digest,
            holds a member that would land outside ``config/``, or the
            passphrase is missing or wrong. This endpoint unpacks as root, so
            where each member resolves to is checked rather than where its
            name appears to start.
    """
    name = file.filename or ""
    if not name.endswith(BACKUP_EXTENSIONS):
        raise _coded_bad_request(BACKUP_ERROR_WRONG_EXTENSION)
    blob = await file.read(RESTORE_SIZE_LIMIT_BYTES + 1)
    if len(blob) > RESTORE_SIZE_LIMIT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="backup is too large"
        )
    contents = _read_archive(blob)
    _check_manifest(contents)
    _check_digests(contents)
    data_key = _unwrapped_key(contents, vault_passphrase)
    with CONFIG_WRITE_LOCK:
        try:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
                members = [
                    _checked_member(_renamed_member(member))
                    for member in archive.getmembers()
                    if member.name not in (BACKUP_MANIFEST_MEMBER, BACKUP_SUMS_MEMBER)
                ]
                # The data filter is the second line of defence, not the
                # first: it also refuses absolute paths, traversal and
                # special files.
                archive.extractall(
                    path=UTILS_CONFIG_DIR.parent, members=members, filter="data"
                )
        except (tarfile.TarError, EOFError, OSError) as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unreadable backup: {error}",
            ) from error
        write_state_key(data_key)
    # The restored decisions are made true without another command: apply
    # runs as a streamed task the modal shows, and the panel restarts itself
    # last, because the password hash and settings it holds are the old
    # box's until it does.
    stream = runtime.tasks.start(
        label="apply the restored configuration", source=_restore_apply_source()
    )
    return {"is_restored": True, "task_id": stream.id}


async def _restore_apply_source():
    """Apply everything the restore brought, then hand the panel over.

    Yields:
        Progress lines for the task stream.
    """
    yield "applying the restored configuration\n"
    process = await asyncio.create_subprocess_exec(
        "nhub",
        "apply",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        yield line.decode("utf-8", "replace")
    code = await process.wait()
    if code != 0:
        yield f"error: nhub apply exited {code}\n"
        return
    if is_dev_root_set():
        yield "development root: restart the panel by hand to pick up the settings\n"
        return
    yield "restarting the panel; sign in with the restored password\n"
    # Detached, two seconds out: the restart must not kill the process that
    # is still streaming this line to the browser.
    await asyncio.create_subprocess_exec(
        "systemd-run",
        "--collect",
        "--on-active=2",
        "systemctl",
        "restart",
        "neutrino_hub_web.service",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


def _read_archive(blob: bytes) -> dict[str, bytes]:
    """Read every regular member of the uploaded archive into memory.

    Args:
        blob: The uploaded file.

    Returns:
        Member name to bytes, in archive order.

    Raises:
        HTTPException: 400 ``backup_unrecognized`` when it does not open as a
            tar.gz at all.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            return {
                member.name: archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isreg()
            }
    # A truncated gzip stream surfaces as EOFError or BadGzipFile (an
    # OSError), not as a TarError.
    except (tarfile.TarError, EOFError, OSError, AttributeError) as error:
        raise _coded_bad_request(BACKUP_ERROR_UNRECOGNIZED) from error


def _check_manifest(contents: dict[str, bytes]) -> None:
    """Confirm the archive opens with this panel's manifest.

    Args:
        contents: The archive's regular members.

    Raises:
        HTTPException: 400 ``backup_unrecognized`` when the first member is
            not the manifest, or it names another kind or version.
    """
    if next(iter(contents), None) != BACKUP_MANIFEST_MEMBER:
        raise _coded_bad_request(BACKUP_ERROR_UNRECOGNIZED)
    try:
        manifest = json.loads(contents[BACKUP_MANIFEST_MEMBER])
    except ValueError as error:
        raise _coded_bad_request(BACKUP_ERROR_UNRECOGNIZED) from error
    if not isinstance(manifest, dict) or manifest.get("kind") != BACKUP_KIND:
        raise _coded_bad_request(BACKUP_ERROR_UNRECOGNIZED)
    if manifest.get("version") != BACKUP_FORMAT_VERSION:
        raise _coded_bad_request(BACKUP_ERROR_UNRECOGNIZED)


def _check_digests(contents: dict[str, bytes]) -> None:
    """Confirm every member matches the digest list, and the list its members.

    Args:
        contents: The archive's regular members.

    Raises:
        HTTPException: 400 ``backup_corrupt`` when the digest list is
            missing, a member fails its digest, or the two sides disagree
            about what the archive holds.
    """
    if BACKUP_SUMS_MEMBER not in contents:
        raise _coded_bad_request(BACKUP_ERROR_CORRUPT)
    listed: dict[str, str] = {}
    for line in contents[BACKUP_SUMS_MEMBER].decode("utf-8", "replace").splitlines():
        digest, _, path = line.partition("  ")
        if not digest or not path:
            raise _coded_bad_request(BACKUP_ERROR_CORRUPT)
        listed[path] = digest
    members = {
        name.partition("/")[2]: content
        for name, content in contents.items()
        if name not in (BACKUP_MANIFEST_MEMBER, BACKUP_SUMS_MEMBER)
    }
    if set(members) != set(listed):
        raise _coded_bad_request(BACKUP_ERROR_CORRUPT)
    for path, content in members.items():
        if hashlib.sha256(content).hexdigest() != listed[path]:
            raise _coded_bad_request(BACKUP_ERROR_CORRUPT)


def _unwrapped_key(contents: dict[str, bytes], vault_passphrase: str) -> bytes:
    """Open the archive's wrapped data key with the passphrase.

    Args:
        contents: The archive's regular members.
        vault_passphrase: What the uploader typed.

    Returns:
        The data key the restored vault opens with.

    Raises:
        HTTPException: 400 ``vault_passphrase_needed`` when none was given,
            ``vault_passphrase_wrong`` when it does not open the key, and
            ``backup_corrupt`` when the archive's vault store is missing or
            carries no usable wrapped key.
    """
    stored = contents.get(f"config/{BACKUP_VAULT_MEMBER}")
    if stored is None:
        raise _coded_bad_request(BACKUP_ERROR_CORRUPT)
    try:
        wrapped = json.loads(stored).get("wrapped_key")
    except (ValueError, AttributeError) as error:
        raise _coded_bad_request(BACKUP_ERROR_CORRUPT) from error
    if not vault_passphrase:
        raise _coded_bad_request(BACKUP_ERROR_PASSPHRASE_NEEDED)
    try:
        return unwrap_data_key(vault_passphrase, wrapped)
    except VaultPassphraseError as error:
        raise _coded_bad_request(BACKUP_ERROR_PASSPHRASE_WRONG) from error
    except VaultError as error:
        raise _coded_bad_request(BACKUP_ERROR_CORRUPT) from error


def _coded_bad_request(code: str) -> HTTPException:
    """One 400 the panel turns into a sentence of its own.

    Args:
        code: The name the panel switches on.

    Returns:
        The exception to raise.
    """
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": code})


def _renamed_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
    """Point the archive's ``config`` root at the directory this box uses.

    The archive's top segment is always ``config``; what the directory is
    called on the box restoring it is the box's own business — an installed
    hub keeps it at ``/etc/neutrino/hub`` — so the segment is mapped rather
    than trusted to match.

    Args:
        member: The member about to be unpacked.

    Returns:
        The member, renamed onto the real directory.

    Raises:
        HTTPException: 400 when the member does not live under ``config``.
    """
    root, _, rest = member.name.partition("/")
    if root != "config":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unexpected path in backup: {member.name}",
        )
    member.name = UTILS_CONFIG_DIR.name + (f"/{rest}" if rest else "")
    return member


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
