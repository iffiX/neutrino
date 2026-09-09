"""The one route table the socket handler and the window share.

Every request is ``(method, path, body)`` and every answer is a status and
a JSON object. The identity was already judged by the transport: the socket
refuses any peer that is not this person, and the window is this person's
own process.

Every refusal is ``{"code", "params"}``; each surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import urllib.parse

from neutrino_client import CLIENT_VERSION
from neutrino_client.core.enrollment import EnrollmentError
from neutrino_client.platforms.base import PlatformUnsupportedError

SERVICES_PREFIX = "/api/services/"


def state_payload(session) -> dict:
    """Everything the page draws.

    Args:
        session: The running :class:`~neutrino_client.core.session.ClientSession`.

    Returns:
        The state payload; no token and no password is in it.
    """
    state = {
        "version": CLIENT_VERSION,
        "hostname": session.hostname(),
        "platform": session.platform_tuple(),
        "mount_location_shape": session.mount_location_shape(),
        "mount_location_suggestion": session.suggest_mount_location(),
        "home": session.home(),
        "is_connected": session.is_connected(),
        "gateway_url": session.gateway_url(),
        "hub_version": session.hub_version(),
        "is_disabled": session.is_disabled(),
        "last_error": session.last_error(),
        "services": session.service_entries(),
    }
    state.update(session.service_states())
    return state


def dispatch(method: str, path: str, body: "dict | None", session):
    """Answer one request.

    Args:
        method: ``GET`` or ``POST``.
        path: The request path, query included.
        body: The JSON body of a POST, or None.
        session: The running session.

    Returns:
        ``(status, reply)``.
    """
    route, _, query = path.partition("?")
    payload = body if isinstance(body, dict) else {}
    if method == "GET":
        if route == "/api/state":
            return 200, state_payload(session)
        if route == "/api/fs":
            return _list_directories(session, query)
        return 404, {"code": "unknown_request", "params": {}}
    if method == "POST":
        if route == "/api/connect":
            return _connect(session, payload)
        if route == "/api/disconnect":
            session.disconnect()
            return 200, state_payload(session)
        if route.startswith(SERVICES_PREFIX):
            return _service_action(session, route[len(SERVICES_PREFIX) :], payload)
        if route == "/api/fs":
            return _make_directory(session, payload)
        if route == "/api/show":
            session.request_show()
            return 200, {}
        return 404, {"code": "unknown_request", "params": {}}
    return 404, {"code": "unknown_request", "params": {}}


def refusal_status(code: str) -> int:
    """The HTTP status one typed refusal answers with.

    Args:
        code: The refusal code.

    Returns:
        404 for an unknown request, 403 for a refused scope or path, 400
        otherwise.
    """
    if code == "unknown_request":
        return 404
    if code in ("control_peer_refused", "fs_refused", "client_disabled"):
        return 403
    return 400


def _connect(session, body: dict):
    try:
        session.connect(str(body.get("link", "")))
    except EnrollmentError as error:
        state = state_payload(session)
        state["error"] = {"code": error.code, "params": dict(error.params)}
        return 200, state
    return 200, state_payload(session)


def _service_action(session, service_type: str, body: dict):
    outcome = session.service_action(service_type, body)
    if outcome:
        return refusal_status(str(outcome.get("code", ""))), outcome
    return 200, state_payload(session)


def _list_directories(session, query: str):
    values = urllib.parse.parse_qs(query).get("path", [])
    path = values[0] if values else ""
    if not path:
        path = session.home() or "/"
    try:
        names = session.list_directories(path)
    except (OSError, PlatformUnsupportedError):
        return 403, {"code": "fs_refused", "params": {}}
    return 200, {"path": path, "dirs": names}


def _make_directory(session, body: dict):
    path = str(body.get("path", ""))
    if not path.startswith("/") and not _is_drive_path(path):
        return 403, {"code": "fs_refused", "params": {}}
    try:
        session.make_directory(path)
    except (OSError, PlatformUnsupportedError):
        return 403, {"code": "fs_refused", "params": {}}
    return 200, {"path": path}


def _is_drive_path(path: str) -> bool:
    """Whether a path is absolute the Windows way, ``C:\\...``."""
    return len(path) > 2 and path[1] == ":" and path[2] in ("\\", "/")
