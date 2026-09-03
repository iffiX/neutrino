"""The AI page: the gateway's status, its client keys, and applying changes.

The upstream providers themselves are edited on the Credentials page; a
change there takes effect when this page's apply runs, which re-renders the
YAML and restarts the service.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.ops import (
    CliproxyApiConfigApplier,
    load_config,
    save_config,
)
from neutrino_hub.modules.credentials.registry import AiProviderRegistry
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import (
    CliproxyApiApplyResult,
    CliproxyApiKeyCreate,
    CliproxyApiKeyView,
    CliproxyApiSettingsUpdate,
    CliproxyApiStatusView,
)

router = APIRouter(
    prefix="/api/cliproxyapi",
    tags=["cliproxyapi"],
    dependencies=[Depends(require_session)],
)


@router.get("", response_model=CliproxyApiStatusView)
def read_status() -> CliproxyApiStatusView:
    """Read the AI gateway's state, probing it when it should be up.

    Returns:
        Install state, service state, keys, and what the probe found.
    """
    return _status()


@router.post("/keys", response_model=CliproxyApiStatusView)
def mint_key(request: CliproxyApiKeyCreate) -> CliproxyApiStatusView:
    """Mint a client key and put it into service immediately.

    Args:
        request: What the key is for.

    Returns:
        The state after the change.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        config.client_keys.append(CliproxyApiClientKey.minted(request.name))
        save_config(config)
    _apply_quietly()
    return _status()


@router.delete("/keys/{key_id}", response_model=CliproxyApiStatusView)
def delete_key(key_id: str) -> CliproxyApiStatusView:
    """Revoke a client key; whatever used it stops working now.

    Args:
        key_id: The key to revoke.

    Returns:
        The state after the change.

    Raises:
        HTTPException: 404 for an unknown key.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        remaining = [key for key in config.client_keys if key.id != key_id]
        if len(remaining) == len(config.client_keys):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="unknown key"
            )
        config.client_keys = remaining
        save_config(config)
    _apply_quietly()
    return _status()


@router.put("", response_model=CliproxyApiStatusView)
def update_settings(request: CliproxyApiSettingsUpdate) -> CliproxyApiStatusView:
    """Change the listen port.

    Args:
        request: The new settings.

    Returns:
        The state after the change.

    Raises:
        HTTPException: 400 when the settings do not validate.
    """
    with CONFIG_WRITE_LOCK:
        config = load_config()
        config.listen_port = request.listen_port
        try:
            config.validate()
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        save_config(config)
    _apply_quietly()
    return _status()


@router.post("/apply", response_model=CliproxyApiApplyResult)
def apply() -> CliproxyApiApplyResult:
    """Re-render the YAML from current state and restart the gateway.

    Returns:
        What happened.

    Raises:
        HTTPException: 400 when the stored settings do not validate.
    """
    try:
        message = CliproxyApiConfigApplier().apply()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return CliproxyApiApplyResult(message=message)


def _apply_quietly() -> None:
    """Apply after a key or settings change; the status reflects failures."""
    try:
        CliproxyApiConfigApplier().apply()
    except ValueError:
        return


def _status() -> CliproxyApiStatusView:
    applier = CliproxyApiConfigApplier()
    config = load_config()
    service = SystemdServiceController().status("cliproxyapi")
    is_reachable = False
    probe_message = ""
    if service.is_active:
        first_key = config.client_keys[0].key if config.client_keys else None
        is_reachable, probe_message = applier.probe(
            port=config.listen_port, client_key=first_key
        )
    providers = AiProviderRegistry().list_records()
    return CliproxyApiStatusView(
        is_installed=applier.is_installed,
        is_active=service.is_active,
        listen_port=config.listen_port,
        client_keys=[CliproxyApiKeyView(**key.to_dict()) for key in config.client_keys],
        is_reachable=is_reachable,
        probe_message=probe_message,
        enabled_provider_count=sum(
            1 for p in providers if p.is_enabled and p.secret_id
        ),
    )
