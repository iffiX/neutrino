"""The Samba block: which devices host a file share, and each one's shares.

Everything but passwords is the device's desired state: a saved group is
checked on the agent, stored under the device's directory and pushed at
once. A password is the one imperative action: it lands in Samba's
credential store on the device and nowhere else.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    SambaDeviceView,
    SambaDiskView,
    SambaPasswordUpdate,
    SambaSessionView,
    SambaShareListUpdate,
    SambaShareView,
    SambaStatusView,
    SambaUserListUpdate,
    SambaUserView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    run_command,
    store_config,
)

MODULE = "samba"
COMMAND_SET_PASSWORD = "set_password"
# The ``testparm -s`` parameters a share's fields are read from.
PARAM_COMMENT = "comment"
PARAM_READ_ONLY = "read only"
PARAM_VALID_USERS = "valid users"
PARAM_YES_VALUES = ("yes", "true", "1")


def device_view(runtime: PanelRuntime, context: DeviceModuleContext) -> SambaDeviceView:
    """One device's file share: the configuration and the live parts.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        Shares as configured; users as configured, each with whether its
        account exists yet and whether it has a password; the live status.
    """
    details = context.details
    surveyed = {
        str(user.get("name", "")): user
        for user in details.get("users") or []
        if isinstance(user, dict)
    }
    return SambaDeviceView(
        **context.fields(),
        shares=[SambaShareView(**share) for share in context.config.get("shares", [])],
        users=[
            SambaUserView(
                name=name,
                is_present=bool(surveyed.get(name, {}).get("is_present")),
                has_password=bool(surveyed.get(name, {}).get("has_password")),
            )
            for name in context.config.get("users", [])
        ],
        is_active=bool(details.get("is_active")),
        sessions=[SambaSessionView(**entry) for entry in details.get("sessions") or []],
        disks=[SambaDiskView(**entry) for entry in details.get("disk_usage") or []],
    )


def import_config(details: dict) -> dict:
    """The configuration the machine's own Samba amounts to.

    Args:
        details: What the agent last reported: ``shares`` as ``testparm``
            prints them, each ``{name, path, params}``, and ``users`` as
            ``pdbedit`` lists them, each ``{name, is_present,
            has_password}``.

    Returns:
        ``{"shares", "users"}`` in the hub's shape. A share without a path
        exports nothing and is left out; a share's ``valid users`` keeps
        only names the user list carries.
    """
    users = [
        str(user.get("name", ""))
        for user in details.get("users") or []
        if isinstance(user, dict) and user.get("name")
    ]
    shares = []
    for share in details.get("shares") or []:
        if not isinstance(share, dict) or not share.get("path"):
            continue
        params = share.get("params") if isinstance(share.get("params"), dict) else {}
        valid_users = [
            name
            for name in str(params.get(PARAM_VALID_USERS, "")).replace(",", " ").split()
            if name in users
        ]
        shares.append(
            {
                "name": str(share.get("name", "")),
                "path": str(share.get("path", "")),
                "comment": str(params.get(PARAM_COMMENT, "")),
                "is_read_only": str(params.get(PARAM_READ_ONLY, "")).lower()
                in PARAM_YES_VALUES,
                "valid_users": valid_users,
            }
        )
    return {"shares": shares, "users": users}


router: APIRouter = module_router(
    MODULE,
    view_model=SambaDeviceView,
    build_view=device_view,
    import_config=import_config,
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
        Live sessions and per-share disk usage.
    """
    view = device_view(runtime, device_context(runtime, MODULE, device_id))
    return SambaStatusView(
        is_active=view.is_active, sessions=view.sessions, disks=view.disks
    )


@router.post("/share/set", response_model=SambaDeviceView)
def update_shares(
    update: SambaShareListUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> SambaDeviceView:
    """Replace the share list.

    Args:
        update: The device, and the new shares.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 409 ``agent_offline``, 400 with the agent's code when
            the configuration does not hold together.
    """
    context = device_context(runtime, MODULE, update.device_id)
    config = dict(context.config)
    config["shares"] = [share.model_dump() for share in update.shares]
    store_config(runtime, context, config)
    return device_view(runtime, context)


@router.post("/user/set", response_model=SambaDeviceView)
def update_users(
    update: SambaUserListUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> SambaDeviceView:
    """Replace the user list.

    Removing a user also drops it from every share that named it: a share
    restricted to accounts that no longer exist would refuse everyone.

    Args:
        update: The device, and the new user names.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.
    """
    context = device_context(runtime, MODULE, update.device_id)
    config = dict(context.config)
    config["users"] = list(update.users)
    config["shares"] = [
        {
            **share,
            "valid_users": [
                user for user in share.get("valid_users", []) if user in update.users
            ],
        }
        for share in config.get("shares", [])
    ]
    store_config(runtime, context, config)
    return device_view(runtime, context)


@router.post("/user/password/set", response_model=SambaUserView)
def set_password(
    update: SambaPasswordUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> SambaUserView:
    """Set one user's share password on the device.

    Args:
        update: The device, a configured user, and the new password.
        runtime: The shared runtime.

    Returns:
        The user's state afterwards.

    Raises:
        HTTPException: 404 ``user_unknown`` for a name not in the
            configuration, 409 ``agent_offline``, 502 with the agent's code
            when Samba refuses.
    """
    name = update.name
    context = device_context(runtime, MODULE, update.device_id)
    if name not in context.config.get("users", []):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "user_unknown", "params": {"user": name}},
        )
    run_command(
        runtime,
        context,
        COMMAND_SET_PASSWORD,
        {"name": name, "password": update.password},
    )
    return SambaUserView(name=name, is_present=True, has_password=True)
