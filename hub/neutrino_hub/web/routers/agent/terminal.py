"""The Terminals page's shell sessions, beside its socket.

A shell opened on ``/ws/agent/terminal`` is a session its page names by a
generated id, stamped ``owner: hub``. Every online machine's agent reports
the sessions it holds in its ``machine`` section; this lists every one of
them, each saying whether the panel owns it, and ends one with the agent's
``stop_session`` verb, whoever owns it. A session is kept past its socket or
shared by a ``persist`` message on that socket.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_SESSION_UNKNOWN,
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_SHELL_OWNER_HUB,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_VERB_STOP_SESSION,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_MODULE_COMMAND_TIMEOUT_S,
    DEVICE_MODULE_REPORT_WAIT_S,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    TerminalSessionListView,
    TerminalSessionStopRequest,
    TerminalSessionView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.shell_bridge import reported_sessions, viewer_rows

router = APIRouter(
    prefix="/api/agent/terminal",
    tags=["terminal"],
    dependencies=[Depends(require_session)],
)

CODE_AGENT_OFFLINE = "agent_offline"
CODE_DEVICE_UNKNOWN = "device_unknown"


@router.get("/session", response_model=TerminalSessionListView)
def list_sessions(
    runtime: PanelRuntime = Depends(get_runtime),
) -> TerminalSessionListView:
    """Read every shell session the online machines report, oldest first.

    Args:
        runtime: The shared runtime, for the agents' latest reports.

    Returns:
        The sessions, each with the machine holding it and whether the
        panel opened it.
    """
    rows = viewer_rows(
        runtime, CHANNEL_SHELL_OWNER_HUB, reported_sessions(runtime.agent_sessions)
    )
    return TerminalSessionListView(
        sessions=[TerminalSessionView(**row) for row in rows]
    )


@router.post("/session/stop", response_model=TerminalSessionListView)
def stop_session(
    request: TerminalSessionStopRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> TerminalSessionListView:
    """End one shell session on its machine.

    Args:
        request: The machine and the session's id.
        runtime: The shared runtime.

    Returns:
        The sessions once the machine reported after ending it.

    Raises:
        HTTPException: 404 ``device_unknown`` when no managed device has the
            id, 409 ``agent_offline`` when it has no socket, 404
            ``session_unknown`` when the machine holds no such session, 502
            with the agent's code when it refused otherwise.
    """
    device = DeviceRegistry().get(request.device_id)
    if device is None or not device.is_managed:
        raise _refusal(
            status.HTTP_404_NOT_FOUND, CODE_DEVICE_UNKNOWN, device_id=request.device_id
        )
    key = device.id
    sessions = runtime.agent_sessions
    if not sessions.is_online(key):
        raise _refusal(status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=key)
    serial = sessions.report_serial_of(key)
    try:
        info = sessions.run_stream_from_thread(
            key,
            CHANNEL_STREAM_COMMAND,
            {
                "module": CHANNEL_COMMAND_MODULE_AGENT,
                "verb": CHANNEL_VERB_STOP_SESSION,
                "session_id": request.session_id,
            },
            timeout=DEVICE_MODULE_COMMAND_TIMEOUT_S,
        )
    except AgentOfflineError:
        raise _refusal(status.HTTP_409_CONFLICT, CODE_AGENT_OFFLINE, device_id=key)
    except StreamRefusedError as error:
        raise _refusal(status.HTTP_502_BAD_GATEWAY, error.code, **error.params)
    code = str(info.get("code", "") or "")
    if code == CHANNEL_CODE_SESSION_UNKNOWN:
        raise _refusal(
            status.HTTP_404_NOT_FOUND,
            CHANNEL_CODE_SESSION_UNKNOWN,
            session_id=request.session_id,
        )
    if code:
        raise _refusal(status.HTTP_502_BAD_GATEWAY, code, **(info.get("params") or {}))
    sessions.wait_for_report_from_thread(key, serial, DEVICE_MODULE_REPORT_WAIT_S)
    return list_sessions(runtime)


def _refusal(status_code: int, code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "params": dict(params)}
    )
