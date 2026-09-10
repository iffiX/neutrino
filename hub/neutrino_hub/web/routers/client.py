"""HTTP endpoints a person's client program talks to.

Served on the agent channel's TLS port beside the agent's own routes, with
no session: a client authenticates with the token its enroll reply handed
it. Joining and leaving are HTTP; everything live rides the one socket in
``client_ws``.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_ENROLLMENT_UNKNOWN,
    CLIENT_CODE_NEWER_THAN_HUB,
    CLIENT_CODE_UNKNOWN,
    CLIENT_ENROLLMENT_KIND,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.constants import AGENT_WS_CLOSE_UNKNOWN_TOKEN
from neutrino_hub.web.constants import WEB_EVENT_CLIENTS
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import ClientEnroll, ClientEnrollReply, ClientLeave
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent import version_refusal

router = APIRouter(prefix="/api/client", tags=["client"])


def client_version_refusal(client_version: str) -> "dict | None":
    """Judge whether a client may talk to this hub at all.

    Args:
        client_version: What the client reported itself as.

    Returns:
        ``{"code", "params"}`` for a client newer than this hub, else None.
    """
    return version_refusal(
        client_version,
        None,
        code=CLIENT_CODE_NEWER_THAN_HUB,
        version_field="client_version",
    )


@router.post("/enroll", response_model=ClientEnrollReply)
def enroll(
    request: ClientEnroll, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientEnrollReply:
    """Let a client join with the ticket its link carries.

    Args:
        request: The ticket and what the program says it is.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The channel token and the client's id.

    Raises:
        HTTPException: 409 when the client is a later release than this hub,
            judged before the ticket is spent; 401 with
            ``enrollment_unknown`` when the ticket is unknown, expired, or
            for a record that is gone.
    """
    refusal = client_version_refusal(request.client_version)
    if refusal is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)
    ticket = runtime.enrollments.pop(request.enrollment_token, None)
    if (
        ticket is None
        or ticket.get("kind") != CLIENT_ENROLLMENT_KIND
        or ticket["expires_at"] < time.time()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": CLIENT_CODE_ENROLLMENT_UNKNOWN, "params": {}},
        )
    registry = ClientRegistry()
    client_id = str(ticket.get("client_id", ""))
    if registry.get(client_id) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": CLIENT_CODE_ENROLLMENT_UNKNOWN, "params": {}},
        )
    registry.record_seen(
        client_id,
        hostname=request.hostname,
        platform=request.platform,
        version=request.client_version,
    )
    token = registry.issue_token(client_id)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return ClientEnrollReply(token=token, client_id=client_id, hub_version=HUB_VERSION)


@router.post("/leave")
def leave(request: ClientLeave, runtime: PanelRuntime = Depends(get_runtime)) -> dict:
    """Take a client's token back on its own word; the row stays.

    Args:
        request: Carries the leaving client's token.
        runtime: The shared runtime, which holds the live sockets.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 401 with ``client_unknown`` when the token matches no
            client.
    """
    registry = ClientRegistry()
    client = registry.find_by_token(request.token)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": CLIENT_CODE_UNKNOWN, "params": {}},
        )
    registry.drop_token(client.id)
    runtime.client_sessions.close_from_thread(
        client.id, AGENT_WS_CLOSE_UNKNOWN_TOKEN, "unknown_token"
    )
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return {}
