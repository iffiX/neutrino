"""The file share's status and its folder shares.

The Home shares are the module's enabled accounts, served by the shared
account-layer router. This file holds the live parts of the machine's last
report and the folder shares: a share the person names, at a folder on the
machine, open to the enabled accounts checked for it (file_share.md). Each
add, edit and remove writes ``samba.json`` at once and pushes the state.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.channel.constants import CHANNEL_MODULE_STATE_RUNNING
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.accounts import DeviceAccountStore
from neutrino_hub.modules.devices.constants import (
    DEVICE_PASSWORD_OS,
    DEVICE_SAMBA_MODULE,
)
from neutrino_hub.modules.devices.folder_shares import (
    find_folder_share,
    folder_shares,
    in_file_share_order,
    is_share_name_taken,
    is_share_name_valid,
    with_folder_share,
    without_folder_share,
)
from neutrino_hub.modules.services.file_ids import folder_share_id
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    FolderShareListView,
    FolderShareRemove,
    FolderShareUpdate,
    FolderShareView,
    SambaDiskView,
    SambaSessionView,
    SambaStatusView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    push_state,
    recompose_published,
    require_online,
    validate_config,
    write_module_config,
)
from neutrino_hub.web.routers.agent.module_account import is_machine_path_absolute

MODULE = DEVICE_SAMBA_MODULE
CODE_SHARE_NAME_INVALID = "share_name_invalid"
CODE_SHARE_NAME_TAKEN = "share_name_taken"
CODE_SHARE_ACCOUNT_NOT_ENABLED = "share_account_not_enabled"
CODE_FOLDER_SHARE_UNKNOWN = "folder_share_unknown"
CODE_PATH_INVALID = "path_invalid"
CODE_CONFIG_UNWRITABLE = "config_unwritable"

router = APIRouter(
    prefix=f"/api/agent/module/{MODULE}",
    tags=["module"],
    dependencies=[Depends(require_session)],
)


@router.get("/status", response_model=SambaStatusView)
def read_status(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> SambaStatusView:
    """Read who is connected and how full each share is, as last reported.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime.

    Returns:
        Whether the unit is active, the live sessions and per-share disk
        usage.

    Raises:
        HTTPException: 404 ``device_unknown``.
    """
    details = device_context(runtime, MODULE, device_id).details
    return SambaStatusView(
        is_active=bool(details.get("is_active")),
        sessions=[
            SambaSessionView(**entry)
            for entry in details.get("sessions") or []
            if isinstance(entry, dict)
        ],
        disks=[
            SambaDiskView(**entry)
            for entry in details.get("disk_usage") or []
            if isinstance(entry, dict)
        ],
    )


@router.get("/folder_share", response_model=FolderShareListView)
def read_folder_shares(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> FolderShareListView:
    """Read a machine's folder shares and the accounts one can name.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime.

    Returns:
        The folder shares in the order they were added, and the file
        share's enabled accounts.

    Raises:
        HTTPException: 404 ``device_unknown``.
    """
    context = device_context(runtime, MODULE, device_id)
    return _view(runtime, context)


@router.post("/folder_share/add", response_model=FolderShareListView)
def add_folder_share(
    request: FolderShareUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> FolderShareListView:
    """Add a folder share, want the module running, and push the state.

    Args:
        request: The device, the name, the folder and the accounts checked.
        runtime: The shared runtime.

    Returns:
        The machine's folder shares afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``; 400 ``share_name_invalid
            {name}``, ``share_name_taken {name}``, ``path_invalid {path}``,
            ``share_account_not_enabled {account}``, then the agent's own
            refusals; 409 ``agent_offline``; 500 ``config_unwritable``.
    """
    context = device_context(runtime, MODULE, request.device_id)
    if not is_share_name_valid(request.name):
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_SHARE_NAME_INVALID, name=request.name
        )
    return _save(runtime, context, request, others=folder_shares(context.config))


@router.post("/folder_share/set", response_model=FolderShareListView)
def set_folder_share(
    request: FolderShareUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> FolderShareListView:
    """Replace a folder share's folder and accounts. Its name stays.

    Args:
        request: The device, the share's name, its folder and its accounts.
        runtime: The shared runtime.

    Returns:
        The machine's folder shares afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``, ``folder_share_unknown
            {name}``; the refusals of :func:`add_folder_share`.
    """
    context = device_context(runtime, MODULE, request.device_id)
    if find_folder_share(context.config, request.name) is None:
        raise _refusal(
            status.HTTP_404_NOT_FOUND, CODE_FOLDER_SHARE_UNKNOWN, name=request.name
        )
    others = [
        share
        for share in folder_shares(context.config)
        if share["name"] != request.name
    ]
    return _save(runtime, context, request, others=others)


@router.post("/folder_share/remove", response_model=FolderShareListView)
def remove_folder_share(
    request: FolderShareRemove, runtime: PanelRuntime = Depends(get_runtime)
) -> FolderShareListView:
    """Remove a folder share and its row from every permission, and push the state.

    The agent takes the share and its grants off the machine and leaves the
    folder and its files.

    Args:
        request: The device and the share's name.
        runtime: The shared runtime.

    Returns:
        The machine's folder shares afterwards.

    Raises:
        HTTPException: 404 ``device_unknown``, ``folder_share_unknown
            {name}``; 409 ``agent_offline``; 500 ``config_unwritable``.
    """
    context = device_context(runtime, MODULE, request.device_id)
    if find_folder_share(context.config, request.name) is None:
        raise _refusal(
            status.HTTP_404_NOT_FOUND, CODE_FOLDER_SHARE_UNKNOWN, name=request.name
        )
    require_online(context)
    written = without_folder_share(context.config, request.name)
    write_module_config(runtime, context.key, MODULE, written)
    context.config = written
    try:
        ClientRegistry().forget_permission_rows(
            [folder_share_id(context.key, request.name)]
        )
    except OSError as error:
        raise _config_unwritable(error) from error
    push_state(runtime, context.key)
    recompose_published(runtime, MODULE)
    return _view(runtime, context)


def _save(
    runtime: PanelRuntime,
    context: DeviceModuleContext,
    request: FolderShareUpdate,
    *,
    others: list,
) -> FolderShareListView:
    """Check a folder share, have the agent check the module's section, and store it.

    Raises:
        HTTPException: As :func:`add_folder_share` says.
    """
    enabled = runtime.desired_states.enabled_accounts(context.key, MODULE)
    available = [
        account.account
        for account in DeviceAccountStore(runtime.desired_states).accounts(context.key)
    ]
    if is_share_name_taken(
        request.name,
        request.accounts,
        device_id=context.key,
        available=available,
        shares=others,
    ):
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_SHARE_NAME_TAKEN, name=request.name
        )
    platform = runtime.device_platform.get(context.key, {})
    is_windows = platform.get("os") == DEVICE_PASSWORD_OS
    if not is_machine_path_absolute(request.path, is_windows):
        raise _refusal(
            status.HTTP_400_BAD_REQUEST, CODE_PATH_INVALID, path=request.path
        )
    for account in request.accounts:
        if account not in enabled:
            raise _refusal(
                status.HTTP_400_BAD_REQUEST,
                CODE_SHARE_ACCOUNT_NOT_ENABLED,
                account=account,
            )
    written = with_folder_share(
        context.config,
        {
            "name": request.name,
            "path": request.path,
            "accounts": in_file_share_order(request.accounts, enabled),
        },
    )
    validate_config(runtime, context, written)
    write_module_config(runtime, context.key, MODULE, written)
    context.config = written
    try:
        runtime.desired_states.set_want(
            context.key, MODULE, CHANNEL_MODULE_STATE_RUNNING
        )
    except OSError as error:
        raise _config_unwritable(error) from error
    push_state(runtime, context.key)
    recompose_published(runtime, MODULE)
    return _view(runtime, context)


def _view(runtime: PanelRuntime, context: DeviceModuleContext) -> FolderShareListView:
    """The machine's folder shares as the File share tab reads them."""
    return FolderShareListView(
        shares=[FolderShareView(**share) for share in folder_shares(context.config)],
        accounts=runtime.desired_states.enabled_accounts(context.key, MODULE),
    )


def _config_unwritable(error: OSError) -> HTTPException:
    return _refusal(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        CODE_CONFIG_UNWRITABLE,
        detail=str(error)[:200],
    )


def _refusal(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": dict(params)}
    )
