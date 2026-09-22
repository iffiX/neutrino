"""The Settings tab: the panel's own port, password, backup and versions."""

import hashlib
import io
import json
import platform
import asyncio
import sys
import tarfile
import time
from dataclasses import asdict
from datetime import datetime, timezone

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

from neutrino_hub.exceptions import (
    HubUpdateError,
    PasswordRefusedError,
    VaultPassphraseError,
)
from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_RELATION_CURRENT,
    HUB_UPDATE_RELATION_MAJOR,
    HUB_UPDATE_STAGE_FAILED,
    HUB_UPDATE_STAGE_PREPARING,
    HUB_UPDATE_STAGES_IN_UNIT,
    HUB_UPDATE_TASK_LABEL,
)
from neutrino_hub.modules.hub_update.installer import (
    HubUpdateInstaller,
    check_space,
    free_bytes,
)
from neutrino_hub.modules.hub_update.release import (
    HubRelease,
    HubReleaseChecker,
    relation,
)
from neutrino_hub.modules.hub_update.state import HubUpdateRecord, HubUpdateStateFile
from neutrino_hub.system.installation import is_packaged
from neutrino_hub.modules.credentials.vault import (
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
from neutrino_hub.utils.passwords import PASSWORDS_PANEL_RULES, validate
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.system.sandbox import outside_sandbox
from neutrino_hub.utils.constants import is_dev_root_set
from neutrino_hub.web.auth import hash_password, verify_password
from neutrino_hub.web.constants import (
    WEB_DEFAULT_LANGUAGE,
    WEB_DEFAULT_LISTEN_PORT,
    WEB_DEFAULT_THEME,
    WEB_LANGUAGES,
    WEB_PORT_MAX,
    WEB_PORT_MIN,
    WEB_RESTART_DELAY_S,
    WEB_THEMES,
)
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.identity import hub_name, set_hub_name
from neutrino_hub.web.models import (
    AboutView,
    AcknowledgementView,
    HubReleaseLatestView,
    HubReleaseScanView,
    HubReleaseView,
    HubUpdateRecordView,
    HubUpdateRequest,
    PanelSettings,
    PasswordChange,
    PasswordChangeResult,
    TaskStarted,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_VERSION
from neutrino_hub.modules.easytier.constants import EASYTIER_VERSION
from neutrino_hub.modules.netbird.constants import NETBIRD_VERSION
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.xray import geodata
from neutrino_hub.modules.xray.constants import XRAY_BINARY, XRAY_VERSION

router = APIRouter(
    prefix="/api/hub/setting", tags=["setting"], dependencies=[Depends(require_session)]
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
BACKUP_ERROR_TOO_LARGE = "backup_too_large"
BACKUP_ERROR_UNEXPECTED_PATH = "backup_unexpected_path"
BACKUP_ERROR_UNEXPECTED_MEMBER = "backup_unexpected_member"
# The 422s the page words when it is asked for a language or a theme nobody
# ships.
SETTINGS_ERROR_LANGUAGE_UNKNOWN = "language_unknown"
SETTINGS_ERROR_THEME_UNKNOWN = "theme_unknown"
# The 422 the page words when it is asked to name the hub nothing.
SETTINGS_ERROR_HUB_NAME_REQUIRED = "hub_name_required"
# The 409s and the 502 the update panel words.
UPDATE_ERROR_NOT_PACKAGED = "hub_not_packaged"
UPDATE_ERROR_IN_PROGRESS = "update_in_progress"
UPDATE_ERROR_UNREACHABLE = "release_unreachable"
UPDATE_ERROR_NOT_LATEST = "release_not_latest"
UPDATE_ERROR_NOT_NEWER = "release_not_newer"
UPDATE_ERROR_MAJOR = "release_major"
# How long the staging task waits for a progress line before it looks again
# at whether the staging is done.
UPDATE_PROGRESS_WAIT_S = 0.5


@router.get("", response_model=PanelSettings)
def read_settings(runtime: PanelRuntime = Depends(get_runtime)) -> PanelSettings:
    """Read the panel's own settings.

    Args:
        runtime: The shared runtime.

    Returns:
        The port the panel answers on, the language and the palette it is
        drawn in, and the name clients show this hub as.
    """
    return PanelSettings(
        listen_port=int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT)),
        language=str(runtime.settings.get("language", WEB_DEFAULT_LANGUAGE)),
        theme=str(runtime.settings.get("theme", WEB_DEFAULT_THEME)),
        hub_name=hub_name(),
    )


@router.post("/set", response_model=PanelSettings)
def update_settings(
    request: PanelSettings,
    background: BackgroundTasks,
    runtime: PanelRuntime = Depends(get_runtime),
) -> PanelSettings:
    """Write the panel's own settings.

    A port change restarts the panel, and the answer goes out first with the
    restart behind it: the process serving this request is the one being
    restarted, so the browser is told where to look before the socket it
    asked on closes.

    Args:
        request: The port to answer on, the language and the palette to draw
            in, and the hub's name. A body leaving one of those out leaves it
            as it is.
        background: Where the restart is queued.
        runtime: The shared runtime.

    Returns:
        The port the panel is moving to, the language and the palette it is
        drawn in, and the hub's name.

    Raises:
        HTTPException: 400 when the port is not one a listener may take, 422
            with ``language_unknown`` for a language this panel does not
            ship, 422 with ``theme_unknown`` for a theme it does not have,
            and 422 with ``hub_name_required`` for a blank name.
    """
    if not WEB_PORT_MIN <= request.listen_port <= WEB_PORT_MAX:
        raise _coded_bad_request(
            "port_out_of_range",
            minimum=WEB_PORT_MIN,
            maximum=WEB_PORT_MAX,
            value=request.listen_port,
        )
    if request.language not in WEB_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SETTINGS_ERROR_LANGUAGE_UNKNOWN,
                "params": {"language": request.language},
            },
        )
    if request.theme not in WEB_THEMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SETTINGS_ERROR_THEME_UNKNOWN,
                "params": {"theme": request.theme},
            },
        )
    is_renaming = "hub_name" in request.model_fields_set
    if is_renaming and not request.hub_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": SETTINGS_ERROR_HUB_NAME_REQUIRED, "params": {}},
        )
    settings = read_config(PANEL_SETTINGS_FILE)
    stored_language = str(settings.get("language", WEB_DEFAULT_LANGUAGE))
    language = (
        request.language if "language" in request.model_fields_set else stored_language
    )
    stored_theme = str(settings.get("theme", WEB_DEFAULT_THEME))
    theme = request.theme if "theme" in request.model_fields_set else stored_theme
    is_moving = (
        int(settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT)) != request.listen_port
    )
    if is_moving or language != stored_language or theme != stored_theme:
        settings["listen_port"] = request.listen_port
        settings["language"] = language
        settings["theme"] = theme
        write_config(PANEL_SETTINGS_FILE, settings)
        runtime.settings["listen_port"] = request.listen_port
        runtime.settings["language"] = language
        runtime.settings["theme"] = theme
    if is_renaming:
        set_hub_name(request.hub_name)
    if is_moving:
        background.add_task(_restart_panel)
    return PanelSettings(
        listen_port=request.listen_port,
        language=language,
        theme=theme,
        hub_name=hub_name(),
    )


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


@router.post("/password/set", response_model=PasswordChangeResult)
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
    except PasswordRefusedError as error:
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
        raise _coded_bad_request(BACKUP_ERROR_TOO_LARGE, limit=RESTORE_SIZE_LIMIT_BYTES)
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
            raise _coded_bad_request(BACKUP_ERROR_CORRUPT) from error
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
    # Outside the panel's sandbox: apply touches the whole machine, and a
    # child of this unit inherits its hardening.
    # Unbuffered, or a piped apply says nothing until it exits and minutes
    # of work read as a hang.
    process = await asyncio.create_subprocess_exec(
        *outside_sandbox(["env", "PYTHONUNBUFFERED=1", "nhub", "apply"]),
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
        raise RuntimeError(f"nhub apply exited {code}")
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
    except ValueError as error:
        raise _coded_bad_request(BACKUP_ERROR_CORRUPT) from error


def _coded_bad_request(code: str, **params) -> HTTPException:
    """One 400 the panel turns into a sentence of its own.

    Args:
        code: The name the panel switches on.
        params: The values that sentence names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": params},
    )


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
        raise _coded_bad_request(BACKUP_ERROR_UNEXPECTED_PATH, path=member.name)
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
        raise _coded_bad_request(BACKUP_ERROR_UNEXPECTED_MEMBER, path=member.name)
    destination = (UTILS_CONFIG_DIR.parent / member.name).resolve()
    if destination != UTILS_CONFIG_DIR and not destination.is_relative_to(
        UTILS_CONFIG_DIR
    ):
        raise _coded_bad_request(BACKUP_ERROR_UNEXPECTED_PATH, path=member.name)
    return member


def _geodata_installed() -> str:
    """Name the release behind each geodata database the box loads.

    Returns:
        One `database release` pair per file, in name order. A box that has
        never taken a newer release names what the package carries.
    """
    return " · ".join(
        f"{name.removesuffix('.dat')} {release}"
        for name, release in sorted(geodata.installed().releases.items())
    )


@router.get("/about", response_model=AboutView)
def about() -> AboutView:
    """Read the version of every carried component, and host uptime.

    Returns:
        A version string per carried component, the acknowledgements the
        licenses of what this hub conveys oblige, plus kernel and uptime.
    """
    xray_version = run([XRAY_BINARY, "version"], is_checked=False).stdout
    return AboutView(
        xray_version=(xray_version.splitlines() or ["not installed"])[0],
        gateway_version=GATEWAY_VERSION,
        cliproxyapi_version=CLIPROXYAPI_VERSION,
        python_version=sys.version.split()[0],
        geodata_version=_geodata_installed(),
        kernel=platform.release(),
        uptime_s=int(time.time() - psutil.boot_time()),
        acknowledgements=_acknowledgements(),
    )


@router.get("/release", response_model=HubReleaseView)
def read_release(runtime: PanelRuntime = Depends(get_runtime)) -> HubReleaseView:
    """The hub's own version and where its last update stands.

    Args:
        runtime: The shared runtime, for the staging task if one runs.

    Returns:
        The version, whether this hub can update itself, the last update's
        record with a run that died marked as such, and the staging task.
    """
    installer = _update_installer()
    running = runtime.tasks.running(HUB_UPDATE_TASK_LABEL)
    record = installer.state.load()
    is_in_unit = record is not None and record.stage in HUB_UPDATE_STAGES_IN_UNIT
    record = installer.state.settle(
        is_unit_active=installer.is_unit_active() if is_in_unit else False,
        is_task_running=running is not None,
    )
    return HubReleaseView(
        current=HUB_VERSION,
        is_packaged=is_packaged(),
        update=None if record is None else HubUpdateRecordView(**asdict(record)),
        task_id=None if running is None else running.id,
    )


@router.post("/release/scan", response_model=HubReleaseScanView)
async def scan_release() -> HubReleaseScanView:
    """Read the newest release and how it stands to this hub.

    Returns:
        The newest release, or none published; whether it is newer, a new
        major, and whether a rollback package can be had; the room the
        update needs and has.

    Raises:
        HTTPException: 409 ``hub_not_packaged`` from a checkout, 502
            ``release_unreachable`` when GitHub does not answer with a
            release.
    """
    if not is_packaged():
        raise _conflict(UPDATE_ERROR_NOT_PACKAGED)
    installer = _update_installer()
    try:
        found = await asyncio.to_thread(installer.checker.latest)
        is_rollback_available = found is not None and await asyncio.to_thread(
            installer.is_rollback_available, HUB_VERSION
        )
    except (OSError, ValueError) as error:
        raise _unreachable() from error
    if found is None:
        return HubReleaseScanView(current=HUB_VERSION)
    standing = relation(HUB_VERSION, found.version)
    needed, free = free_bytes(
        found.asset_size,
        is_rollback_fetched=not installer.is_rollback_present(HUB_VERSION),
    )
    return HubReleaseScanView(
        current=HUB_VERSION,
        latest=HubReleaseLatestView(
            version=found.version,
            published_at=found.published_at,
            notes=found.notes,
            page_url=found.page_url,
            size_bytes=found.asset_size,
        ),
        is_newer=standing != HUB_UPDATE_RELATION_CURRENT,
        is_major=standing == HUB_UPDATE_RELATION_MAJOR,
        is_rollback_available=is_rollback_available,
        needed_bytes=needed,
        free_bytes=free,
        is_space_enough=free >= needed,
    )


@router.post("/release/install", response_model=TaskStarted)
async def install_release(
    request: HubUpdateRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> TaskStarted:
    """Stage the newest release and hand its install to systemd.

    Args:
        request: The version the person confirmed.
        runtime: The shared runtime, whose task streams the staging.

    Returns:
        The job whose output ``/ws/hub/task`` streams; it ends as the panel
        restarts under the new package.

    Raises:
        HTTPException: 409 ``hub_not_packaged``, ``update_in_progress``,
            ``release_not_latest`` when the newest release is not the one
            confirmed, ``release_not_newer``, ``release_major``, or
            ``disk_space_short``; 502 ``release_unreachable``.
    """
    if not is_packaged():
        raise _conflict(UPDATE_ERROR_NOT_PACKAGED)
    installer = _update_installer()
    if runtime.tasks.running(HUB_UPDATE_TASK_LABEL) is not None:
        raise _conflict(UPDATE_ERROR_IN_PROGRESS)
    if installer.is_unit_active():
        raise _conflict(UPDATE_ERROR_IN_PROGRESS)
    try:
        found = await asyncio.to_thread(installer.checker.latest)
    except (OSError, ValueError) as error:
        raise _unreachable() from error
    if found is None or found.version != request.version:
        raise _conflict(
            UPDATE_ERROR_NOT_LATEST, version="" if found is None else found.version
        )
    standing = relation(HUB_VERSION, found.version)
    if standing == HUB_UPDATE_RELATION_CURRENT:
        raise _conflict(UPDATE_ERROR_NOT_NEWER, version=found.version)
    if standing == HUB_UPDATE_RELATION_MAJOR:
        raise _conflict(UPDATE_ERROR_MAJOR, version=found.version)
    try:
        check_space(
            found.asset_size,
            is_rollback_fetched=not installer.is_rollback_present(HUB_VERSION),
        )
    except HubUpdateError as error:
        raise _conflict(error.code, **error.params) from error
    installer.state.save(
        HubUpdateRecord(
            stage=HUB_UPDATE_STAGE_PREPARING,
            from_version=HUB_VERSION,
            to_version=found.version,
            started_at=_stamp_now(),
        )
    )
    stream = runtime.tasks.start(
        label=HUB_UPDATE_TASK_LABEL,
        source=_update_source(installer, found, port=_listen_port(runtime)),
    )
    return TaskStarted(task_id=stream.id)


async def _update_source(
    installer: HubUpdateInstaller, found: HubRelease, *, port: int
):
    """Stage the release in a thread, relaying its progress, then hand over.

    Args:
        installer: What stages and launches.
        found: The release to install.
        port: The panel's port, for the unit's gate.

    Yields:
        Progress lines for the task stream.

    Raises:
        HubUpdateError: When the staging or the launch fails; the record
            says why.
    """
    loop = asyncio.get_running_loop()
    lines: asyncio.Queue = asyncio.Queue()

    def say(line: str) -> None:
        loop.call_soon_threadsafe(lines.put_nowait, line)

    yield f"staging {found.asset_name} of {found.tag}\n"
    staging = asyncio.ensure_future(
        asyncio.to_thread(
            installer.prepare, found, current=HUB_VERSION, port=port, on_progress=say
        )
    )
    while not staging.done():
        try:
            line = await asyncio.wait_for(lines.get(), timeout=UPDATE_PROGRESS_WAIT_S)
        except asyncio.TimeoutError:
            continue
        yield f"{line}\n"
    while not lines.empty():
        yield f"{lines.get_nowait()}\n"
    try:
        plan = staging.result()
    except HubUpdateError as error:
        _record_failure(installer.state, found, error)
        raise
    yield "handing the install to systemd; the panel restarts now\n"
    await asyncio.to_thread(installer.launch, plan)


def _record_failure(
    state: HubUpdateStateFile, found: HubRelease, error: HubUpdateError
) -> None:
    """Write why the staging stopped, keeping when it started."""
    record = state.load()
    started_at = record.started_at if record is not None else _stamp_now()
    state.save(
        HubUpdateRecord(
            stage=HUB_UPDATE_STAGE_FAILED,
            from_version=HUB_VERSION,
            to_version=found.version,
            started_at=started_at,
            finished_at=_stamp_now(),
            reason=error.code,
            output=str(error.params.get("detail", "")),
        )
    )


def _update_installer() -> HubUpdateInstaller:
    """The installer the routes use; a test replaces this.

    Returns:
        An installer over the real releases and the real state file.
    """
    return HubUpdateInstaller(checker=HubReleaseChecker(), state=HubUpdateStateFile())


def _listen_port(runtime: PanelRuntime) -> int:
    """The port the panel answers on, for the unit's gate."""
    return int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))


def _stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _conflict(code: str, **params) -> HTTPException:
    """One 409 the panel turns into a sentence of its own.

    Args:
        code: The name the panel switches on.
        params: The values that sentence names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "params": params},
    )


def _unreachable() -> HTTPException:
    """The 502 for a GitHub that did not answer with a release."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": UPDATE_ERROR_UNREACHABLE, "params": {}},
    )


# What the hub package itself carries, credited with the exact tag each
# binary was built from. The agent and the client carry RustDesk and
# cc-switch and credit those in their own packages.
CARRIED_COMPONENTS = (
    (
        "Xray-core",
        XRAY_VERSION,
        "MPL-2.0",
        "https://github.com/XTLS/Xray-core/tree/v{}",
    ),
    (
        "CLIProxyAPI",
        CLIPROXYAPI_VERSION,
        "MIT",
        "https://github.com/router-for-me/CLIProxyAPI/tree/v{}",
    ),
    (
        "NetBird",
        NETBIRD_VERSION,
        "BSD-3-Clause",
        "https://github.com/netbirdio/netbird/tree/v{}",
    ),
    (
        "EasyTier",
        EASYTIER_VERSION,
        "LGPL-3.0",
        "https://github.com/EasyTier/EasyTier/tree/v{}",
    ),
)


def _acknowledgements() -> list[AcknowledgementView]:
    """Everything this hub conveys that names a license.

    The components the hub package carries come first, with the exact tag
    each binary was built from. Then every module manifest naming a
    ``license``: software whose bytes this hub fetches and hands to a
    machine. A module the person installs themselves names none and is
    credited in its own row and nowhere else.

    Returns:
        The acknowledgements, the carried components first and then the
        modules by title.
    """
    credited = [
        AcknowledgementView(
            name=name,
            version=version,
            license=license_name,
            corresponding_source=source.format(version),
        )
        for name, version, license_name, source in CARRIED_COMPONENTS
    ]
    for name, manifest in sorted(load_module_manifests().items()):
        license_name = str(manifest.get("license", "") or "")
        if not license_name:
            continue
        credited.append(
            AcknowledgementView(
                name=str(manifest.get("title", name)),
                version=str(manifest.get("version", "") or ""),
                license=license_name,
                corresponding_source=str(
                    manifest.get("corresponding_source", "") or ""
                ),
            )
        )
    return credited
