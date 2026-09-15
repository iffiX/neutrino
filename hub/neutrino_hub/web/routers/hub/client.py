"""The Clients page: the people's programs enrolled with this hub.

A client is created when its link is minted, so it is a row before it
joins; the panel renames it, switches it off and on, and deletes it. Presence,
hostname, platform and version come from its live session where it has
one, and from what it last reported otherwise.
"""

import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.clients.ai_keys import ensure_client_key, revoke_client_key
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_NAME_REQUIRED,
    CLIENT_CODE_UNKNOWN,
    CLIENT_ENROLLMENT_KIND,
)
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.clients.registry import Client, ClientRegistry
from neutrino_hub.modules.devices.constants import AGENT_WS_CLOSE_UNKNOWN_TOKEN
from neutrino_hub.web import client_channel
from neutrino_hub.web.constants import WEB_EVENT_CLIENTS
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ClientEnrollmentRequest,
    ClientEnrollmentView,
    ClientListView,
    ClientRequest,
    ClientUpdate,
    ClientView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.hub.device import (
    ENROLLMENT_TOKEN_BYTES,
    ENROLLMENT_TTL_S,
    clear_enrollments,
    enrollment_link,
    enrollment_link_parts,
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
    request: ClientEnrollmentRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientEnrollmentView:
    """Create a client and the link its program joins with.

    Args:
        request: The client's name.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The link and when it lapses.

    Raises:
        HTTPException: 400 with ``client_name_required`` when the name is
            blank; the link's own refusals as the device link's.
    """
    name = request.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": CLIENT_CODE_NAME_REQUIRED, "params": {}},
        )
    urls, fingerprint = enrollment_link_parts(runtime)
    client_id = ClientRegistry().create(name)
    clear_enrollments(runtime, kind=CLIENT_ENROLLMENT_KIND)
    token = secrets.token_urlsafe(ENROLLMENT_TOKEN_BYTES)
    expires_at = time.time() + ENROLLMENT_TTL_S
    runtime.enrollments[token] = {
        "kind": CLIENT_ENROLLMENT_KIND,
        "name": name,
        "client_id": client_id,
        "expires_at": expires_at,
    }
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return ClientEnrollmentView(
        link=enrollment_link(urls, token, fingerprint, role=CHANNEL_ROLE_CLIENT),
        expires_at=datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
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
    """Switch a client off: its gateway key is revoked and it is handed an
    empty catalog. Its socket stays.

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
    """Remove a client: its key, its record, and its socket.

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
    registry.forget(client.id)
    runtime.client_catalog_host.pop(client.id, None)
    runtime.client_sessions.close_from_thread(
        client.id, AGENT_WS_CLOSE_UNKNOWN_TOKEN, "unknown_token"
    )
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
    else:
        ensure_client_key(registry, client)
    client_channel.push_client_state(runtime, client.id)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return _list_view(runtime)


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
    views = []
    for client in ClientRegistry().all():
        session = sessions.get(client.id)
        hostname = session.hostname if session is not None else client.hostname
        platform = session.platform if session is not None else client.platform
        version = session.version if session is not None else client.version
        views.append(
            ClientView(
                id=client.id,
                name=client.name,
                hostname=hostname or client.hostname,
                platform_os=str((platform or client.platform).get("os", "") or ""),
                version=version or client.version,
                is_online=session is not None,
                last_seen=sessions.last_seen_at(client.id),
                is_disabled=client.is_disabled,
            )
        )
    return ClientListView(clients=views)
