"""The Clients page: the people's programs enrolled with this hub.

A client is created with its link and the permission it joins with, so it
is a row that waits to join until the link expires; the panel renames it,
switches it off and on, sets its permission and deletes it. Presence,
hostname, platform and version come from its live session where it has
one, and from what it last reported otherwise.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.clients.ai_keys import ensure_client_key, revoke_client_key
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_NAME_REQUIRED,
    CLIENT_CODE_PERMISSION_DEVICE_UNKNOWN,
    CLIENT_CODE_PERMISSION_KIND_UNKNOWN,
    CLIENT_CODE_UNKNOWN,
    CLIENT_PERMISSION_FILTERED_KINDS,
    CLIENT_PERMISSION_KINDS,
    CLIENT_PERMISSION_OVERLAY,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_CLIENT,
    ENROLLMENT_TTL_S,
)
from neutrino_hub.modules.clients.permissions import (
    ClientPermission,
    client_permission,
    default_permission,
    is_permitted,
)
from neutrino_hub.modules.clients.registry import Client, ClientRegistry
from neutrino_hub.modules.clients.rows import permission_rows
from neutrino_hub.modules.services.constants import SERVICES_TYPE_AI
from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.web import channel_overlay, channel_state
from neutrino_hub.web.client_access import close_lost_access
from neutrino_hub.web.panel_sign_in import (
    SESSION_END_DISABLED,
    SESSION_END_PERMISSION,
    SESSION_END_REMOVED,
)
from neutrino_hub.web.constants import WEB_EVENT_CLIENTS
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ClientDefaultPermissionRequest,
    ClientEnrollmentRequest,
    ClientEnrollmentView,
    ClientListView,
    ClientPermissionRequest,
    ClientRequest,
    ClientUpdate,
    ClientView,
    PermissionRowView,
)
from neutrino_hub.web.channel_addresses import enrollment_link_parts
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.web_share_access import web_share_fields
from neutrino_hub.web.routers.hub.device import (
    enrollment_link,
)

router = APIRouter(
    prefix="/api/hub/client", tags=["client"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=ClientListView)
def list_clients(runtime: PanelRuntime = Depends(get_runtime)) -> ClientListView:
    """Every enrolled client, live state folded in.

    Args:
        runtime: The shared runtime, whose sessions say who is online.

    Returns:
        The list.
    """
    return _list_view(runtime)


@router.post("/enrollment/create", response_model=ClientEnrollmentView)
def create_enrollment(
    request: ClientEnrollmentRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ClientEnrollmentView:
    """Create a client that waits to join with its name and permission, and
    the link its program joins with.

    The link carries the overlays' join material when the client's
    permission allows ``overlay``. A client link still open from before
    stops working, and its waiting row goes.

    Args:
        request: The client's name, and its permission or null to follow
            the default.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The link, the new client's id and when the link lapses.

    Raises:
        HTTPException: 400 with ``client_name_required`` when the name is
            blank; the permission's refusals as ``permission/set``'s; the
            link's own refusals as the device link's.
        OSError: When the ticket file cannot be written.
    """
    name = request.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": CLIENT_CODE_NAME_REQUIRED, "params": {}},
        )
    permission = None
    if request.permission is not None:
        _require_kinds(request.permission.kinds)
        _require_devices(request.permission.devices)
        permission = ClientPermission(
            kinds=frozenset(request.permission.kinds),
            devices=dict(request.permission.devices or {}),
            entries=dict(request.permission.entries or {}),
        )
    urls, key = enrollment_link_parts(runtime)
    registry = ClientRegistry()
    joined_with = permission or default_permission(registry)
    overlays = []
    if is_permitted(joined_with, CLIENT_PERMISSION_OVERLAY):
        overlays = channel_overlay.overlay_materials(runtime)
    replaced = [
        entry["client_id"]
        for entry in runtime.enrollments.entries()
        if entry["kind"] == CHANNEL_ROLE_CLIENT and entry["client_id"]
    ]
    client_id = registry.create(
        name, permission=permission, link_expires_at=time.time() + ENROLLMENT_TTL_S
    )
    try:
        token, expires_at = runtime.enrollments.make(
            kind=CHANNEL_ROLE_CLIENT, name=name, client_id=client_id
        )
    except OSError:
        registry.forget(client_id)
        raise
    for waiting_id in replaced:
        waiting = registry.get(waiting_id)
        if waiting is not None and waiting.is_waiting:
            registry.forget(waiting_id)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return ClientEnrollmentView(
        link=enrollment_link(
            urls, token, key, role=CHANNEL_ROLE_CLIENT, overlays=overlays
        ),
        client_id=client_id,
        expires_at=datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
        expires_in_s=ENROLLMENT_TTL_S,
    )


@router.post("/set", response_model=ClientListView)
def rename_client(
    update: ClientUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientListView:
    """Rename a client.

    Args:
        update: The client and its new name.
        runtime: The shared runtime.

    Returns:
        The list, as a read answers.

    Raises:
        HTTPException: 400 with ``client_name_required`` when the name is
            blank, 404 with ``client_unknown`` when there is no such client.
    """
    if not update.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": CLIENT_CODE_NAME_REQUIRED, "params": {}},
        )
    registry = ClientRegistry()
    client = _require(registry, update.client_id)
    registry.rename(client.id, update.name)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return _list_view(runtime)


@router.post("/enable", response_model=ClientListView)
def enable_client(
    request: ClientRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientListView:
    """Switch a client on: a key is minted again and it is handed everything
    back.

    Args:
        request: The client.
        runtime: The shared runtime.

    Returns:
        The list, as a read answers.

    Raises:
        HTTPException: 404 with ``client_unknown`` when there is no such
            client.
    """
    return _set_disabled(runtime, request.client_id, False)


@router.post("/disable", response_model=ClientListView)
def disable_client(
    request: ClientRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientListView:
    """Switch a client off: its gateway key is revoked and its state is
    pushed with ``is_disabled``. Its socket stays.

    Args:
        request: The client.
        runtime: The shared runtime.

    Returns:
        The list, as a read answers.

    Raises:
        HTTPException: 404 with ``client_unknown`` when there is no such
            client.
    """
    return _set_disabled(runtime, request.client_id, True)


@router.post("/remove", response_model=ClientListView)
def delete_client(
    request: ClientRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientListView:
    """Remove a client: its key, its record, its socket, refused with
    ``binding_unknown``, and the link of a client that waits to join.

    Args:
        request: The client.
        runtime: The shared runtime.

    Returns:
        The list, as a read answers.

    Raises:
        HTTPException: 404 with ``client_unknown`` when there is no such
            client.
    """
    registry = ClientRegistry()
    client = _require(registry, request.client_id)
    revoke_client_key(registry, client)
    runtime.enrollments.withdraw_client(client.id)
    registry.forget(client.id)
    runtime.forget_client(client.id)
    close_lost_access(runtime, why=SESSION_END_REMOVED)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return _list_view(runtime)


@router.post("/default_permission/set", response_model=ClientListView)
def set_default_permission(
    request: ClientDefaultPermissionRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> ClientListView:
    """Store what a client with no permission of its own is allowed, and
    push every client its state.

    Args:
        request: The kinds, their device lists and the rows.
        runtime: The shared runtime.

    Returns:
        The list, as a read answers.

    Raises:
        HTTPException: 400 with ``permission_kind_unknown`` for a kind that
            is not one or takes no device filter, 400 with
            ``permission_device_unknown`` for a device that is not stored.
    """
    _require_kinds(request.kinds)
    _require_devices(request.devices)
    registry = ClientRegistry()
    registry.set_default_permission(request.kinds, request.devices, request.entries)
    for client in registry.all():
        _settle_ai_key(registry, client)
    close_lost_access(runtime, why=SESSION_END_PERMISSION)
    channel_state.push_states(runtime, CHANNEL_ROLE_CLIENT)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return _list_view(runtime)


@router.post("/permission/set", response_model=ClientListView)
def set_permission(
    request: ClientPermissionRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientListView:
    """Give one client a permission of its own, or put it back on the
    default, and push it its state.

    Args:
        request: The client, its kinds, its device lists and its rows;
            ``kinds`` null follows the default.
        runtime: The shared runtime.

    Returns:
        The list, as a read answers.

    Raises:
        HTTPException: 400 with ``permission_kind_unknown`` for a kind that
            is not one or takes no device filter, 400 with
            ``permission_device_unknown`` for a device that is not stored,
            404 with ``client_unknown`` when there is no such client.
    """
    if request.kinds is not None:
        _require_kinds(request.kinds)
        _require_devices(request.devices)
    registry = ClientRegistry()
    client = _require(registry, request.client_id)
    registry.set_permission(client.id, request.kinds, request.devices, request.entries)
    _settle_ai_key(registry, registry.get(client.id))
    close_lost_access(runtime, why=SESSION_END_PERMISSION)
    _push_one(runtime, client.id)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return _list_view(runtime)


def _set_disabled(
    runtime: PanelRuntime, client_id: str, is_disabled: bool
) -> ClientListView:
    """Switch one client off or on and hand it its new state."""
    registry = ClientRegistry()
    client = _require(registry, client_id)
    registry.set_disabled(client.id, is_disabled)
    client = registry.get(client.id)
    if is_disabled:
        revoke_client_key(registry, client)
        close_lost_access(runtime, why=SESSION_END_DISABLED)
    else:
        ensure_client_key(registry, client)
    _push_one(runtime, client.id)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return _list_view(runtime)


def _push_one(runtime: PanelRuntime, client_id: str) -> None:
    """Hand one client its state now; a client with no socket gets it later."""
    try:
        channel_state.push_state(runtime, CHANNEL_ROLE_CLIENT, client_id)
    except (AgentOfflineError, StreamRefusedError):
        pass


def _settle_ai_key(registry: ClientRegistry, client: Client) -> None:
    """Revoke the gateway key of a client no longer allowed the AI entry."""
    if not is_permitted(client_permission(registry, client), SERVICES_TYPE_AI):
        revoke_client_key(registry, client)


def _require_kinds(kinds: list) -> None:
    for kind in kinds:
        if kind not in CLIENT_PERMISSION_KINDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": CLIENT_CODE_PERMISSION_KIND_UNKNOWN,
                    "params": {"kind": kind},
                },
            )


def _require_devices(devices: "dict | None") -> None:
    stored = {device.id for device in DeviceRegistry().all_stored()}
    for kind, device_ids in (devices or {}).items():
        if kind not in CLIENT_PERMISSION_FILTERED_KINDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": CLIENT_CODE_PERMISSION_KIND_UNKNOWN,
                    "params": {"kind": kind},
                },
            )
        for device_id in device_ids:
            if device_id not in stored:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": CLIENT_CODE_PERMISSION_DEVICE_UNKNOWN,
                        "params": {"device_id": device_id},
                    },
                )


def _require(registry: ClientRegistry, client_id: str) -> Client:
    client = registry.get(client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": CLIENT_CODE_UNKNOWN, "params": {"client_id": client_id}},
        )
    return client


def _list_view(runtime: PanelRuntime) -> ClientListView:
    sessions = runtime.client_sessions
    registry = ClientRegistry()
    now = time.time()
    views = []
    for client in registry.all():
        session = sessions.get(client.id)
        version = session.version if session is not None else client.version
        views.append(
            ClientView(
                id=client.id,
                name=client.name,
                hostname=client.hostname,
                platform_os=str(client.platform.get("os", "") or ""),
                version=version or client.version,
                is_online=session is not None,
                last_seen=sessions.last_seen_at(client.id),
                is_disabled=client.is_disabled,
                permission=client.permission,
                permission_devices=client.permission_devices,
                permission_entries=client.permission_entries,
                link_expires_in_s=_link_expires_in_s(client, now),
            )
        )
    return ClientListView(
        clients=views,
        default_permission=registry.default_permission(),
        default_permission_devices=registry.default_permission_devices(),
        default_permission_entries=registry.default_permission_entries(),
        permission_kinds=list(CLIENT_PERMISSION_KINDS),
        permission_rows={
            kind: [PermissionRowView(**row) for row in rows]
            for kind, rows in permission_rows(runtime).items()
        },
        **web_share_fields(runtime),
    )


def _link_expires_in_s(client: Client, now: float) -> "int | None":
    """The seconds a waiting client's link still works; None once it joined."""
    if not client.is_waiting:
        return None
    return max(0, int((client.link_expires_at or now) - now))
