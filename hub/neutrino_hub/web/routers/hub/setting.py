"""The Settings tab: the panel's own ports, scheme, password, backup and versions."""

import base64
import hashlib
import io
import json
import os
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
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse
from cryptography import x509

from neutrino_hub import edition
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
    unreachable_reason,
)
from neutrino_hub.modules.hub_update.state import HubUpdateRecord, HubUpdateStateFile
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.system.installation import is_packaged
from neutrino_hub.system.machine import machine_id
from neutrino_hub.modules.credentials.vault import (
    unwrap_data_key,
    write_state_key,
)
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR, UTILS_LOG_ROOT
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)
from neutrino_hub.utils.passwords import PASSWORDS_PANEL_RULES, validate
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.platforms.detect import hub_platform, is_linux, process_controller
from neutrino_hub.system.sandbox import outside_sandbox
from neutrino_hub.utils.constants import is_dev_root_set
from neutrino_hub.web.auth import hash_password, verify_password
from neutrino_hub.web.constants import (
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_DEFAULT_HTTPS_LISTEN_PORT,
    WEB_DEFAULT_LANGUAGE,
    WEB_DEFAULT_LISTEN_PORT,
    WEB_DEFAULT_THEME,
    WEB_LANGUAGES,
    WEB_PACKAGE_FAMILY_OF_SUFFIX,
    WEB_PANEL_TLS_AUTHORITY_PATH,
    WEB_PANEL_TLS_MEDIA_TYPE,
    WEB_PANEL_TLS_SERVED_CERT_PATH,
    WEB_PORT_MAX,
    WEB_PORT_MIN,
    WEB_RESTART_DELAY_S,
    WEB_RESTORE_LOCAL_AGENT_PATH,
    WEB_SETTING_HTTPS,
    WEB_SETTING_HTTPS_PORT,
    WEB_THEMES,
)
from neutrino_hub.web.channel_addresses import channel_hosts
from neutrino_hub.web import panel_tls
from neutrino_hub.web.dependencies import get_runtime, require_session, session_cookie
from neutrino_hub.web.identity import hub_name, set_hub_name
from neutrino_hub.web.models import (
    AboutView,
    AcknowledgementView,
    HubReleaseLatestView,
    HubReleaseScanView,
    HubReleaseView,
    HubUpdateRecordView,
    HubUpdateRequest,
    PanelHttpsResetView,
    PanelHttpsView,
    PanelSettings,
    PasswordChange,
    PasswordChangeResult,
    TaskStarted,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub import HUB_PACKAGE_ASSET, HUB_VERSION
from neutrino_hub.platforms.constants import PLATFORM_OS_DARWIN, PLATFORM_OS_WINDOWS
from neutrino_hub.platforms.detect import hub_os
from neutrino_hub.modules.router.constants import (
    ROUTER_MODE_ROUTER,
    ROUTER_MODES_KEYS,
)
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_VERSION
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_SOURCE_URLS,
    EASYTIER_VERSION,
)

router = APIRouter(
    prefix="/api/hub/setting", tags=["setting"], dependencies=[Depends(require_session)]
)
# The routes of this page a browser reaches before it has a session: the
# authority's certificate, which it has to install before it trusts the panel,
# and the probe that says whether it trusts the HTTPS port yet.
authority_router = APIRouter(prefix="/api/hub/setting", tags=["setting"])

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
BACKUP_ERROR_MODE_UNAVAILABLE = "backup_mode_unavailable"
# The member naming the network mode, which a hub restores only when it
# offers that mode.
BACKUP_NETWORK_MEMBER = "config/router/network.json"
# The 422s the page words when it is asked for a language or a theme nobody
# ships.
SETTINGS_ERROR_LANGUAGE_UNKNOWN = "language_unknown"
SETTINGS_ERROR_THEME_UNKNOWN = "theme_unknown"
# The 422 the page words when it is asked to name the hub nothing.
SETTINGS_ERROR_HUB_NAME_REQUIRED = "hub_name_required"
# The 404 for an authority download on a box that has not made one.
HTTPS_ERROR_AUTHORITY_MISSING = "https_authority_missing"
# The 409 for regenerating the authority from a page served over HTTPS.
HTTPS_ERROR_RESET_OVER_HTTPS = "https_reset_over_https"
# The 400 for a panel port another of the hub's listeners already holds.
SETTINGS_ERROR_PORT_TAKEN = "port_already_in_use"
# The 409s and the 502 the update panel words.
UPDATE_ERROR_NOT_PACKAGED = "hub_not_packaged"
UPDATE_ERROR_IN_PROGRESS = "update_in_progress"
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
        The ports the panel answers HTTP and HTTPS on, the language and the
        palette it is drawn in, and the name clients show this hub as.
    """
    return PanelSettings(
        listen_port=int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT)),
        https_listen_port=_https_listen_port(runtime),
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

    A change of either port restarts the panel, and the answer goes out first
    with the restart behind it: the process serving this request is the one
    being restarted, so the browser is told where to look before the socket
    it asked on closes.

    Args:
        request: The HTTP and HTTPS ports to answer on, the language and the
            palette to draw in, and the hub's name. A body leaving one of
            those out leaves it as it is, the HTTP port excepted.
        background: Where the restart is queued.
        runtime: The shared runtime.

    Returns:
        The ports the panel is moving to, the language and the palette it is
        drawn in, and the hub's name.

    Raises:
        HTTPException: 400 with ``port_out_of_range`` when a port is not one
            a listener may take, 400 with ``port_already_in_use`` when the
            two ports are one or either is the agent port, 400 with
            ``language_unknown`` for a language this panel does not ship,
            400 with ``theme_unknown`` for a theme it does not have, and 400
            with ``hub_name_required`` for a blank name.
    """
    https_port = (
        request.https_listen_port
        if "https_listen_port" in request.model_fields_set
        else _https_listen_port(runtime)
    )
    for port in (request.listen_port, https_port):
        if not WEB_PORT_MIN <= port <= WEB_PORT_MAX:
            raise _coded_bad_request(
                "port_out_of_range",
                minimum=WEB_PORT_MIN,
                maximum=WEB_PORT_MAX,
                value=port,
            )
    agent_port = int(
        runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
    )
    if https_port == request.listen_port:
        raise _coded_bad_request(SETTINGS_ERROR_PORT_TAKEN, value=https_port)
    for port in (request.listen_port, https_port):
        if port == agent_port:
            raise _coded_bad_request(SETTINGS_ERROR_PORT_TAKEN, value=port)
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
    stored_port = int(settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT))
    stored_https_port = int(
        settings.get(WEB_SETTING_HTTPS_PORT, WEB_DEFAULT_HTTPS_LISTEN_PORT)
    )
    is_moving = stored_port != request.listen_port or stored_https_port != https_port
    if is_moving or language != stored_language or theme != stored_theme:
        settings["listen_port"] = request.listen_port
        settings[WEB_SETTING_HTTPS_PORT] = https_port
        settings["language"] = language
        settings["theme"] = theme
        write_config(PANEL_SETTINGS_FILE, settings)
        runtime.settings["listen_port"] = request.listen_port
        runtime.settings[WEB_SETTING_HTTPS_PORT] = https_port
        runtime.settings["language"] = language
        runtime.settings["theme"] = theme
    if is_renaming:
        set_hub_name(request.hub_name)
    if is_moving:
        background.add_task(_restart_panel)
    return PanelSettings(
        listen_port=request.listen_port,
        https_listen_port=https_port,
        language=language,
        theme=theme,
        hub_name=hub_name(),
    )


def _restart_panel() -> None:
    """Restart the unit this is running inside.

    ``--no-block`` and a moment's wait, for the same reason everything else
    the hub asks systemd for uses them: the job stops the process making the
    request, and waiting on it would be waiting on itself. On macOS and
    Windows the service exits and its service manager starts it again.
    """
    time.sleep(WEB_RESTART_DELAY_S)
    if not is_linux():
        process_controller().restart("web")
        return
    run(
        ["systemctl", "restart", "--no-block", SYSTEM_CORE_UNITS["web"]],
        is_checked=False,
    )


@router.get("/https", response_model=PanelHttpsView)
def read_https(runtime: PanelRuntime = Depends(get_runtime)) -> PanelHttpsView:
    """Read the panel's scheme, its two ports and the state of its certificates.

    Args:
        runtime: The shared runtime, for the ports.

    Returns:
        Whether the HTTP port sends browsers to the HTTPS port, both ports,
        the authority's fingerprint and when it was made, and the served
        certificate's names, issue and expiry.
    """
    return _https_view(runtime)


@authority_router.get("/https/authority")
def download_authority() -> Response:
    """Download the hub's certificate authority, for a browser to install.

    No session: a browser installs it before it can trust the panel, and a
    certificate is public. The HTTP port serves it while HTTPS is on.

    Returns:
        The authority's DER encoding as ``neutrino-<hub>-ca.crt``.

    Raises:
        HTTPException: 404 with ``https_authority_missing`` when the hub has
            not made one.
    """
    try:
        der = panel_tls.authority_der()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": HTTPS_ERROR_AUTHORITY_MISSING, "params": {}},
        ) from error
    return Response(
        content=der,
        media_type=WEB_PANEL_TLS_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{_authority_file_name()}"'
        },
    )


@authority_router.get("/https/probe", status_code=status.HTTP_204_NO_CONTENT)
def probe_https() -> Response:
    """Answer with nothing, for a page on HTTP to fetch over HTTPS.

    No session: a page fetches it from the HTTPS port, and the fetch
    succeeding is what says this browser trusts the certificate.

    Returns:
        An empty 204.
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/https/enable", response_model=PanelHttpsView)
def enable_https(
    request: Request,
    response: Response,
    runtime: PanelRuntime = Depends(get_runtime),
) -> PanelHttpsView:
    """Send the HTTP port's browsers to the HTTPS port.

    A missing authority is made first. Both ports are already served, so
    nothing restarts: the next request on the HTTP port is redirected, and
    the next session cookie is ``Secure``. The caller's session on the
    scheme it leaves is ended, and the page signs in again on the other.

    Args:
        request: The incoming request, read for its scheme and cookie.
        response: Response the old scheme's cookie is deleted on.
        runtime: The shared runtime, for the names the panel answers on and
            the setting the redirect reads.

    Returns:
        The scheme and certificates, as a read returns them.

    Raises:
        VaultLockedError: If the authority is missing and there is no data
            key to seal its key under.
    """
    panel_tls.ensure_authority()
    _renew_for(runtime)
    _write_https(True, runtime)
    _end_session(runtime, request, response)
    return _https_view(runtime)


@router.post("/https/disable", response_model=PanelHttpsView)
def disable_https(
    request: Request,
    response: Response,
    runtime: PanelRuntime = Depends(get_runtime),
) -> PanelHttpsView:
    """Serve the panel on the HTTP port again; the certificates are kept.

    The caller's session on the HTTPS port is ended and its ``Secure``
    cookie deleted, so the HTTP port's login writes a cookie of its own.

    Args:
        request: The incoming request, read for its scheme and cookie.
        response: Response the old scheme's cookie is deleted on.
        runtime: The shared runtime, for the setting the redirect reads.

    Returns:
        The scheme and certificates, as a read returns them.
    """
    _write_https(False, runtime)
    _end_session(runtime, request, response)
    return _https_view(runtime)


def _end_session(runtime: PanelRuntime, request: Request, response: Response) -> None:
    """End the caller's session on the scheme the request came over."""
    scheme = request.url.scheme
    name = session_cookie(runtime)
    token = request.cookies.get(name)
    if token:
        runtime.sessions.logout(token)
    response.delete_cookie(
        name, httponly=True, samesite="lax", secure=scheme == "https"
    )


@router.post("/https/authority/reset", response_model=PanelHttpsResetView)
def reset_https_authority(
    request: Request, runtime: PanelRuntime = Depends(get_runtime)
) -> PanelHttpsResetView:
    """Replace the certificate authority and the certificate it signed.

    Every browser that installed the old authority has to install this one.
    The panel serves the new certificate from the next connection on.

    Args:
        request: The incoming request, whose scheme is checked.
        runtime: The shared runtime, for the names the panel answers on.

    Returns:
        The scheme and certificates, as a read returns them, and the new
        authority's DER in base64.

    Raises:
        HTTPException: 409 with ``https_reset_over_https`` when the request
            came over HTTPS.
        VaultLockedError: If there is no data key to seal the new key under.
    """
    if request.url.scheme == "https":
        raise _conflict(HTTPS_ERROR_RESET_OVER_HTTPS)
    panel_tls.reset_authority()
    _renew_for(runtime)
    view = _https_view(runtime)
    return PanelHttpsResetView(
        **view.model_dump(),
        authority_der=base64.b64encode(panel_tls.authority_der()).decode("ascii"),
    )


def _renew_for(runtime: PanelRuntime) -> None:
    """Issue the served certificate for the names the panel answers on now."""
    names = panel_tls.leaf_names(channel_hosts(runtime.network()))
    panel_tls.renew_served_leaf(names)


def _write_https(is_enabled: bool, runtime: PanelRuntime) -> None:
    """Store the scheme, in the file and in the settings the redirect reads."""
    with CONFIG_WRITE_LOCK:
        settings = read_config(PANEL_SETTINGS_FILE)
        if bool(settings.get(WEB_SETTING_HTTPS, False)) != is_enabled:
            settings[WEB_SETTING_HTTPS] = is_enabled
            write_config(PANEL_SETTINGS_FILE, settings)
    runtime.settings[WEB_SETTING_HTTPS] = is_enabled


def _https_listen_port(runtime: PanelRuntime) -> int:
    """The port the panel serves HTTPS on."""
    return int(
        runtime.settings.get(WEB_SETTING_HTTPS_PORT, WEB_DEFAULT_HTTPS_LISTEN_PORT)
    )


def _https_view(runtime: PanelRuntime) -> PanelHttpsView:
    """The scheme, the two ports and what the certificates on disk say."""
    view = PanelHttpsView(
        is_https_enabled=panel_tls.is_https_enabled(),
        listen_port=int(runtime.settings.get("listen_port", WEB_DEFAULT_LISTEN_PORT)),
        https_listen_port=_https_listen_port(runtime),
        has_authority=False,
        authority_file_name=_authority_file_name(),
    )
    try:
        authority = x509.load_pem_x509_certificate(
            WEB_PANEL_TLS_AUTHORITY_PATH.read_bytes()
        )
    except (OSError, ValueError):
        return view
    view.has_authority = True
    view.authority_fingerprint = panel_tls.authority_fingerprint()
    view.authority_created_at = authority.not_valid_before_utc.isoformat()
    try:
        leaf = x509.load_pem_x509_certificate(
            WEB_PANEL_TLS_SERVED_CERT_PATH.read_bytes()
        )
    except (OSError, ValueError):
        return view
    view.leaf_names = panel_tls.certificate_names(leaf)
    view.leaf_issued_at = leaf.not_valid_before_utc.isoformat()
    view.leaf_expires_at = leaf.not_valid_after_utc.isoformat()
    renewed = panel_tls.last_renewed_at()
    view.renewed_at = renewed.isoformat() if renewed else None
    return view


def _authority_file_name() -> str:
    """What the downloaded authority is called, after this hub's name."""
    try:
        name = hub_name()
    except (OSError, ValueError):
        name = ""
    return panel_tls.authority_file_name(name)


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
        A streaming ``.tar.gz`` download: the manifest, naming this machine's
        id, the digest list, then the ``config/`` tree.
    """
    with CONFIG_WRITE_LOCK:
        directories, files = _config_snapshot()
    manifest = json.dumps(
        {
            "kind": BACKUP_KIND,
            "version": BACKUP_FORMAT_VERSION,
            "hub_machine_id": machine_id(),
        },
        indent=2,
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
        relative = path.relative_to(UTILS_CONFIG_DIR).as_posix()
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
            holds a member that would land outside ``config/``, sets the
            hub up in a network mode this hub does not offer, or the
            passphrase is missing or wrong. The files of a feature this
            tree leaves out are restored and read by nothing. This endpoint unpacks as root, so
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
    _check_mode(contents)
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
    _mark_local_agent_join(contents)
    # The restored decisions are made true without another command: apply
    # runs as a streamed task the modal shows, and the panel restarts itself
    # last, because the password hash and settings it holds are the old
    # box's until it does.
    stream = runtime.tasks.start(
        label="apply the restored configuration", source=_restore_apply_source()
    )
    return {"is_restored": True, "task_id": stream.id}


def _mark_local_agent_join(contents: dict[str, bytes]) -> None:
    """Leave the restarted panel the restored row this machine's agent joins.

    The row is the one with this machine's id, else the one of the machine
    the backup was made on; with neither, the join makes a new row.

    Args:
        contents: The archive's regular members, the manifest among them.

    Raises:
        OSError: When the mark cannot be written.
    """
    try:
        manifest = json.loads(contents[BACKUP_MANIFEST_MEMBER])
    except (KeyError, ValueError):
        manifest = {}
    row = DeviceRegistry().hub_row_after_restore(
        own_machine_id=machine_id(),
        backup_machine_id=str(manifest.get("hub_machine_id", "") or ""),
    )
    WEB_RESTORE_LOCAL_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_RESTORE_LOCAL_AGENT_PATH.write_text(
        json.dumps({"device_id": row.id if row is not None else ""}),
        encoding="utf-8",
    )


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
    if is_linux():
        command = outside_sandbox(["env", "PYTHONUNBUFFERED=1", "nhub", "apply"])
        environment = None
    else:
        command = hub_platform().hub_command("apply")
        environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=environment,
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
    if not is_linux():
        process_controller().restart("web")
        return
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
        Member name, in POSIX form, to bytes, in archive order.

    Raises:
        HTTPException: 400 ``backup_unrecognized`` when it does not open as a
            tar.gz at all.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            return {
                _posix_name(member.name): archive.extractfile(member).read()
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
        listed[_posix_name(path)] = digest
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


def _check_mode(contents: dict[str, bytes]) -> None:
    """Confirm the backup's network mode is one this hub offers.

    A backup made on a hub with the proxy may set the box up as a side
    gateway, a mode a hub without the proxy does not offer.

    Args:
        contents: The archive's regular members.

    Raises:
        HTTPException: 400 ``backup_mode_unavailable {mode}`` when the
            stored mode is not one of :data:`ROUTER_MODES_KEYS`.
    """
    stored = contents.get(BACKUP_NETWORK_MEMBER)
    if stored is None:
        return
    try:
        mode = json.loads(stored).get("mode", ROUTER_MODE_ROUTER)
    except (ValueError, AttributeError) as error:
        raise _coded_bad_request(BACKUP_ERROR_CORRUPT) from error
    if mode not in ROUTER_MODES_KEYS:
        raise _coded_bad_request(BACKUP_ERROR_MODE_UNAVAILABLE, mode=str(mode))


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
    root, _, rest = _posix_name(member.name).partition("/")
    if root != "config":
        raise _coded_bad_request(BACKUP_ERROR_UNEXPECTED_PATH, path=member.name)
    member.name = UTILS_CONFIG_DIR.name + (f"/{rest}" if rest else "")
    return member


def _posix_name(name: str) -> str:
    """An archive path with a Windows hub's backslashes read as separators."""
    return name.replace("\\", "/")


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


@router.get("/about", response_model=AboutView)
def about() -> AboutView:
    """Read the version of every carried component, and host uptime.

    Returns:
        A version string per carried component, the acknowledgements the
        licenses of what this hub conveys oblige, plus the system, its
        version, the kernel and uptime. xray's and the geodata's versions
        are empty in a tree without the proxy.
    """
    versions = {}
    for about_versions in edition.hooks("about_versions"):
        versions.update(about_versions())
    system = hub_os()
    return AboutView(
        **versions,
        gateway_version=GATEWAY_VERSION,
        cliproxyapi_version=CLIPROXYAPI_VERSION,
        python_version=sys.version.split()[0],
        kernel=platform.release(),
        os=system,
        os_version=_os_version(system),
        uptime_s=int(time.time() - psutil.boot_time()),
        acknowledgements=_acknowledgements(),
    )


def _os_version(system: str) -> str:
    """The version of the system the hub runs on.

    Args:
        system: What :func:`hub_os` named.

    Returns:
        The macOS release, the Windows build, or the kernel release on Linux.
    """
    if system == PLATFORM_OS_DARWIN:
        return platform.mac_ver()[0]
    if system == PLATFORM_OS_WINDOWS:
        return platform.version()
    return platform.release()


def _package_family(asset: str) -> str:
    """The kind of package the hub was installed from.

    Args:
        asset: The release file name the build stamped.

    Returns:
        ``deb``, ``rpm``, ``arch``, ``msi`` or ``pkg``; empty in a checkout.
    """
    for suffix, family in WEB_PACKAGE_FAMILY_OF_SUFFIX:
        if asset.endswith(suffix):
            return family
    return ""


@router.get("/release", response_model=HubReleaseView)
def read_release(runtime: PanelRuntime = Depends(get_runtime)) -> HubReleaseView:
    """The hub's own version and where its last update stands.

    Args:
        runtime: The shared runtime, for the staging task if one runs.

    Returns:
        The version, whether this hub can update itself and from which kind
        of package, where it writes its logs, the last update's
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
        package_family=_package_family(HUB_PACKAGE_ASSET),
        log_root=str(UTILS_LOG_ROOT),
        update=None if record is None else HubUpdateRecordView(**asdict(record)),
        task_id=None if running is None else running.id,
    )


@router.post("/release/scan", response_model=HubReleaseScanView)
async def scan_release() -> HubReleaseScanView:
    """Read the newest release and how it stands to this hub.

    Returns:
        The newest release, or none published; whether it carries a package
        of this hub's family, whether it is newer, a new major, and whether
        a rollback package can be had; the room the update needs and has.

    Raises:
        HTTPException: 409 ``hub_not_packaged`` from a checkout; 502 naming
            why GitHub gave no release: ``release_dns_failed``,
            ``release_timed_out``, ``release_refused``, ``release_http_error``
            or ``release_unreachable``.
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
        raise _unreachable(error) from error
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
        has_package=found.has_package,
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
            ``disk_space_short``; 502 naming why GitHub gave no release, as
            a scan does.
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
        raise _unreachable(error) from error
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
        source=_update_source(
            installer,
            found,
            port=_listen_port(runtime),
            https_port=_https_listen_port(runtime),
        ),
    )
    return TaskStarted(task_id=stream.id)


async def _update_source(
    installer: HubUpdateInstaller, found: HubRelease, *, port: int, https_port: int
):
    """Stage the release in a thread, relaying its progress, then hand over.

    Args:
        installer: What stages and launches.
        found: The release to install.
        port: The panel's HTTP port, for the unit's gate.
        https_port: The panel's HTTPS port, for the unit's gate.

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
            installer.prepare,
            found,
            current=HUB_VERSION,
            port=port,
            https_port=https_port,
            on_progress=say,
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


def _unreachable(error: Exception) -> HTTPException:
    """The 502 for a GitHub that gave no release, naming why."""
    code, params = unreachable_reason(error)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": code, "params": params},
    )


# What the hub package itself carries, credited with the exact tag each
# binary was built from, and the systems whose package carries it: None for
# every system. The agent and the client carry RustDesk and cc-switch and
# credit those in their own packages. What the proxy and NetBird carry comes
# from the edition table, and EasyTier's source is read where the hub's
# edition reads it.
CARRIED_COMPONENTS = (
    (
        "CLIProxyAPI",
        CLIPROXYAPI_VERSION,
        "MIT",
        "https://github.com/router-for-me/CLIProxyAPI/tree/v{}",
        None,
    ),
    (
        "EasyTier",
        EASYTIER_VERSION,
        "LGPL-3.0",
        EASYTIER_SOURCE_URLS,
        None,
    ),
    (
        "Wintun",
        "",
        "Wintun Prebuilt Binaries License",
        "https://git.zx2c4.com/wintun/",
        (PLATFORM_OS_WINDOWS,),
    ),
)


def _source_of(source) -> str:
    """One component's source address, the hub's edition's where it names one.

    Args:
        source: The address, or edition to address.

    Returns:
        The address, with ``{}`` open for the version.
    """
    return source[edition.EDITION] if isinstance(source, dict) else source


def _acknowledgements() -> list[AcknowledgementView]:
    """Every component this hub's package carries on this system.

    Returns:
        The acknowledgements, in the order of :data:`CARRIED_COMPONENTS`
        and then the edition table's, each with the exact tag it was built
        from.
    """
    components = CARRIED_COMPONENTS + tuple(
        component
        for components in edition.hooks("about_components")
        for component in components
    )
    system = hub_os()
    return [
        AcknowledgementView(
            name=name,
            version=version,
            license=license_name,
            corresponding_source=_source_of(source).format(version),
        )
        for name, version, license_name, source, systems in components
        if systems is None or system in systems
    ]
