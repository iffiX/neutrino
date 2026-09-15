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

import threading
import time
import urllib.parse

from neutrino_client import CLIENT_VERSION
from neutrino_client.core.resident import end_process
from neutrino_client.exceptions import EnrollmentError, PlatformUnsupportedError

SERVICES_PREFIX = "/api/services/"
# How long the answer is given to reach the caller before the process ends.
QUIT_ANSWER_GRACE_S = 0.3


def state_payload(resident) -> dict:
    """Everything the page draws.

    Args:
        resident: The running :class:`~neutrino_client.core.resident.ClientResident`.

    Returns:
        The state payload: the machine, the hubs joined as ``hubs`` and the
        services they publish as ``services``, each stamped with its
        ``hub_id``, then every handler's state; no token and no password is
        in it.
    """
    state = {
        "version": CLIENT_VERSION,
        "language": resident.language(),
        "theme": resident.theme(),
        "hostname": resident.hostname(),
        "platform": resident.platform_tuple(),
        "mount_location_shape": resident.mount_location_shape(),
        "mount_location_suggestion": resident.suggest_mount_location(),
        "mount_location_choices": resident.mount_location_choices(),
        "home": resident.home(),
        "is_connected": resident.is_connected(),
        "exit_hub_id": resident.exit_hub_id(),
        "hubs": resident.hubs(),
        "services": resident.service_entries(),
    }
    state.update(resident.service_states())
    return state


def dispatch(method: str, path: str, body: "dict | None", resident):
    """Answer one request.

    Args:
        method: ``GET`` or ``POST``.
        path: The request path, query included.
        body: The JSON body of a POST, or None.
        resident: The running resident.

    Returns:
        ``(status, reply)``.
    """
    route, _, query = path.partition("?")
    payload = body if isinstance(body, dict) else {}
    if method == "GET":
        if route == "/api/state":
            return 200, state_payload(resident)
        if route == "/api/fs":
            return _list_directories(resident, query)
        return 404, {"code": "unknown_request", "params": {}}
    if method == "POST":
        if route == "/api/connect":
            return _connect(resident, payload)
        if route == "/api/language":
            resident.set_language(str(payload.get("language", "")))
            return 200, state_payload(resident)
        if route == "/api/theme":
            resident.set_theme(str(payload.get("theme", "")))
            return 200, state_payload(resident)
        if route == "/api/disconnect":
            return _disconnect(resident, payload)
        if route == "/api/session/start":
            return _start_session(resident, payload)
        if route == "/api/exit/set":
            return _set_exit(resident, payload)
        if route.startswith(SERVICES_PREFIX):
            return _service_action(resident, route[len(SERVICES_PREFIX) :], payload)
        if route == "/api/fs":
            return _make_directory(resident, payload)
        if route == "/api/show":
            resident.request_show()
            return 200, {}
        if route == "/api/quit":
            return _quit(resident)
        return 404, {"code": "unknown_request", "params": {}}
    return 404, {"code": "unknown_request", "params": {}}


def refusal_status(code: str) -> int:
    """The HTTP status one typed refusal answers with.

    Args:
        code: The refusal code.

    Returns:
        404 for an unknown request or hub, 403 for a refused scope or path,
        400 otherwise.
    """
    if code in ("unknown_request", "unknown_hub"):
        return 404
    if code in ("control_peer_refused", "fs_refused", "client_disabled"):
        return 403
    return 400


def _quit(resident):
    """Answer, then shut the resident down and end its process.

    Args:
        resident: The running resident.

    Returns:
        ``(200, {})``, sent before the shutdown begins.
    """
    threading.Thread(
        target=_shut_down_and_end, args=(resident,), name="client_quit", daemon=True
    ).start()
    return 200, {}


def _shut_down_and_end(resident) -> None:
    """Let the answer land, then shut down and end the process.

    Args:
        resident: The running resident.
    """
    time.sleep(QUIT_ANSWER_GRACE_S)
    resident.shutdown()
    end_process()


def _connect(resident, body: dict):
    try:
        resident.connect(str(body.get("link", "")))
    except EnrollmentError as error:
        state = state_payload(resident)
        state["error"] = {"code": error.code, "params": dict(error.params)}
        return 200, state
    return 200, state_payload(resident)


def _disconnect(resident, body: dict):
    hub_id = str(body.get("hub_id", ""))
    try:
        resident.disconnect(hub_id)
    except KeyError:
        return _unknown_hub(hub_id)
    return 200, state_payload(resident)


def _start_session(resident, body: dict):
    hub_id = str(body.get("hub_id", ""))
    try:
        resident.reconnect(hub_id)
    except KeyError:
        return _unknown_hub(hub_id)
    return 200, state_payload(resident)


def _set_exit(resident, body: dict):
    outcome = resident.set_exit(str(body.get("hub_id", "")))
    if outcome:
        return refusal_status(str(outcome.get("code", ""))), outcome
    return 200, state_payload(resident)


def _unknown_hub(hub_id: str):
    outcome = {"code": "unknown_hub", "params": {"hub_id": hub_id}}
    return refusal_status(outcome["code"]), outcome


def _service_action(resident, service_type: str, body: dict):
    outcome = resident.service_action(service_type, body)
    if outcome:
        return refusal_status(str(outcome.get("code", ""))), outcome
    return 200, state_payload(resident)


def _list_directories(resident, query: str):
    values = urllib.parse.parse_qs(query).get("path", [])
    path = values[0] if values else ""
    if not path:
        path = resident.home() or "/"
    try:
        names = resident.list_directories(path)
    except (OSError, PlatformUnsupportedError):
        return 403, {"code": "fs_refused", "params": {}}
    return 200, {"path": path, "dirs": names}


def _make_directory(resident, body: dict):
    path = str(body.get("path", ""))
    if not path.startswith("/") and not _is_drive_path(path):
        return 403, {"code": "fs_refused", "params": {}}
    try:
        resident.make_directory(path)
    except (OSError, PlatformUnsupportedError):
        return 403, {"code": "fs_refused", "params": {}}
    return 200, {"path": path}


def _is_drive_path(path: str) -> bool:
    """Whether a path is absolute the Windows way, ``C:\\...``."""
    return len(path) > 2 and path[1] == ":" and path[2] in ("\\", "/")
