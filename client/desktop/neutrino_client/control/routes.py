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

import base64
import binascii
import threading
import time
import urllib.parse

from neutrino_client import CLIENT_CARRIED_VERSIONS, CLIENT_VERSION
from neutrino_client.control import page
from neutrino_client.core.resident import end_process
from neutrino_client.exceptions import EnrollmentError, PlatformUnsupportedError

SERVICES_PREFIX = "/api/services/"
# The two routes that answer 101 and hand their connection to a terminal:
# the one that carries what is typed, and the one that carries the output.
TERMINAL_ATTACH_ROUTE = "/api/terminal/attach"
TERMINAL_OUTPUT_ROUTE = "/api/terminal/output"
# The header a 101 names the terminal in.
TERMINAL_HEADER = "X-Neutrino-Terminal"
# How long the answer is given to reach the caller before the process ends.
QUIT_ANSWER_GRACE_S = 0.3


def state_payload(resident) -> dict:
    """Everything the page draws.

    Args:
        resident: The running :class:`~neutrino_client.core.resident.ClientResident`.

    Returns:
        The state document: the machine, the versions of the programs the
        package carries as ``carried_versions``, empty in a checkout, the
        hubs joined as ``hubs``, each with its connection, its virtual
        network and its jobs, the services they publish as ``services``,
        each with its job, the machines they offer a terminal on and the
        sessions they list as ``terminals`` ``{machines, sessions}``, each
        stamped with its ``hub_id``, the notices above the hubs, then every
        handler's state; no token, password or network secret is in it.
    """
    state = {
        "version": CLIENT_VERSION,
        "carried_versions": dict(CLIENT_CARRIED_VERSIONS),
        "language": resident.language(),
        "theme": resident.theme(),
        "terminal_font_size": resident.terminal_font_size(),
        "hostname": resident.hostname(),
        "platform": resident.platform_tuple(),
        "mount_location_shape": resident.mount_location_shape(),
        "mount_location_suggestion": resident.suggest_mount_location(),
        "mount_location_choices": resident.mount_location_choices(),
        "home": resident.home(),
        "is_connected": resident.is_connected(),
        "exit_hub_id": resident.exit_hub_id(),
        "hubs": resident.hubs(),
        "notices": resident.notices(),
        "services": resident.entry_rows(),
        "terminals": {
            "machines": resident.terminal_entries(),
            "sessions": resident.terminal_sessions(),
        },
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
        if route == "/api/font":
            return _font_piece(query)
        if route == "/api/clipboard":
            outcome = resident.read_clipboard()
            if outcome.get("code"):
                return refusal_status(str(outcome["code"])), outcome
            return 200, outcome
        return 404, {"code": "unknown_request", "params": {}}
    if method == "POST":
        if route == "/api/join":
            return _join(resident, payload)
        if route == "/api/language":
            resident.set_language(str(payload.get("language", "")))
            return 200, state_payload(resident)
        if route == "/api/theme":
            resident.set_theme(str(payload.get("theme", "")))
            return 200, state_payload(resident)
        if route == "/api/terminal/font":
            resident.set_terminal_font_size(_size(payload, "size"))
            return 200, state_payload(resident)
        if route == "/api/leave":
            return _leave(resident, payload)
        if route == "/api/session/start":
            return _start_session(resident, payload)
        if route == "/api/refresh":
            resident.refresh()
            return 200, state_payload(resident)
        if route == "/api/notice/close":
            resident.close_notice(str(payload.get("id", "") or ""))
            return 200, state_payload(resident)
        if route == "/api/exit/set":
            return _set_exit(resident, payload)
        if route == TERMINAL_ATTACH_ROUTE:
            return _attach_terminal(resident, payload)
        if route == TERMINAL_OUTPUT_ROUTE:
            return _terminal_output(resident, payload)
        if route == "/api/terminal/resize":
            return _answer(
                resident,
                resident.resize_terminal(
                    _terminal_id(payload),
                    _size(payload, "cols"),
                    _size(payload, "rows"),
                ),
            )
        if route == "/api/terminal/result":
            outcome = resident.terminal_result(_terminal_id(payload))
            if outcome.get("code") == "unknown_terminal":
                return refusal_status("unknown_terminal"), outcome
            return 200, outcome
        if route == "/api/terminal/open":
            return _open_window_terminal(resident, payload)
        if route == "/api/terminal/input":
            return _terminal_input(resident, payload)
        if route == "/api/terminal/persist":
            return _answer_empty(
                resident.persist_terminal(
                    _terminal_id(payload),
                    payload.get("is_persistent") is True,
                    payload.get("is_shared") is True,
                )
            )
        if route == "/api/terminal/stop":
            return _answer_empty(
                resident.stop_terminal_session(
                    _hub_id(payload), str(payload.get("session_id", "") or "")
                )
            )
        if route == "/api/terminal/close":
            outcome = resident.close_terminal(_terminal_id(payload))
            if outcome.get("code"):
                return refusal_status(outcome["code"]), outcome
            return 200, {}
        if route == "/api/overlay/connect":
            return _answer(resident, resident.connect_overlay(_hub_id(payload)))
        if route == "/api/overlay/cancel":
            return _answer(resident, resident.cancel_overlay(_hub_id(payload)))
        if route == "/api/overlay/disconnect":
            return _answer(resident, resident.disconnect_overlay(_hub_id(payload)))
        if route == "/api/clipboard":
            return _answer_empty(
                resident.write_clipboard(str(payload.get("text", "") or ""))
            )
        if route == "/api/overlay/pick":
            return _answer(
                resident,
                resident.pick_overlay(
                    _hub_id(payload), str(payload.get("provider", "") or "")
                ),
            )
        if route == "/api/forward/configure":
            return _answer(
                resident,
                resident.configure_forward(
                    _hub_id(payload),
                    str(payload.get("id", "") or ""),
                    payload.get("local_port"),
                ),
            )
        if route.startswith(SERVICES_PREFIX):
            return _service_action(resident, route[len(SERVICES_PREFIX) :], payload)
        if route == "/api/fs":
            return _make_directory(resident, payload)
        if route == "/api/show":
            resident.request_show()
            return 200, {}
        if route == "/api/open_link":
            return _open_link(resident, payload)
        if route == "/api/quit":
            return _quit(resident)
        return 404, {"code": "unknown_request", "params": {}}
    return 404, {"code": "unknown_request", "params": {}}


def serve_upgrade(route: str, reply: dict, resident, *, read, write) -> None:
    """Hand a connection a 101 answered to its terminal, until the terminal ends.

    Args:
        route: The route that answered 101.
        reply: What it answered, naming ``terminal_id``.
        resident: The running resident.
        read: ``read(size)`` reads the connection, empty at its end.
        write: ``write(data)`` writes the connection.
    """
    terminal_id = str(reply.get("terminal_id", ""))
    if route == TERMINAL_ATTACH_ROUTE:
        resident.attach_terminal(terminal_id, read)
    elif route == TERMINAL_OUTPUT_ROUTE:
        resident.terminal_output(terminal_id, write)


def refusal_status(code: str) -> int:
    """The HTTP status one typed refusal answers with.

    Args:
        code: The refusal code.

    Returns:
        404 for an unknown request or hub, 403 for a refused scope, path or
        authorization, 400 otherwise.
    """
    if code in ("unknown_request", "unknown_hub", "unknown_terminal"):
        return 404
    if code in (
        "control_peer_refused",
        "fs_refused",
        "client_disabled",
        "overlay_not_authorized",
    ):
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


def _join(resident, body: dict):
    try:
        resident.connect(str(body.get("link", "")))
    except EnrollmentError as error:
        state = state_payload(resident)
        state["error"] = {"code": error.code, "params": dict(error.params)}
        return 200, state
    return 200, state_payload(resident)


def _leave(resident, body: dict):
    hub_id = str(body.get("hub_id", ""))
    try:
        resident.leave(hub_id)
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


def _hub_id(body: dict) -> str:
    return str(body.get("hub_id", "") or "")


def _terminal_id(body: dict) -> str:
    return str(body.get("terminal_id", "") or "")


def _size(body: dict, name: str) -> int:
    """A terminal dimension from a body; anything unreadable reads as 0."""
    try:
        return max(int(body.get(name) or 0), 0)
    except (TypeError, ValueError):
        return 0


def _attach_terminal(resident, body: dict):
    """Open the shell and answer 101 naming it, or the refusal."""
    outcome = resident.open_terminal(
        _hub_id(body),
        str(body.get("device_id", "") or ""),
        _size(body, "cols"),
        _size(body, "rows"),
        str(body.get("session_id", "") or ""),
    )
    if "code" in outcome:
        return refusal_status(str(outcome["code"])), outcome
    return 101, outcome


def _terminal_output(resident, body: dict):
    """Answer 101 for a terminal that is open, 404 otherwise."""
    terminal_id = _terminal_id(body)
    if not resident.has_terminal(terminal_id):
        outcome = {"code": "unknown_terminal", "params": {}}
        return refusal_status(outcome["code"]), outcome
    return 101, {"terminal_id": terminal_id}


def _open_window_terminal(resident, body: dict):
    """Open a shell for the window's terminal: its id, or the refusal."""
    outcome = resident.open_window_terminal(
        _hub_id(body),
        str(body.get("device_id", "") or ""),
        _size(body, "cols"),
        _size(body, "rows"),
        str(body.get("session_id", "") or ""),
    )
    if "code" in outcome:
        return refusal_status(str(outcome["code"])), outcome
    return 200, outcome


def _terminal_input(resident, body: dict):
    """Hand keys the window's terminal sent as base64 to its shell."""
    try:
        data = base64.b64decode(str(body.get("data", "") or ""), validate=True)
    except binascii.Error:
        outcome = {"code": "unknown_request", "params": {}}
        return refusal_status(outcome["code"]), outcome
    outcome = resident.terminal_input(_terminal_id(body), data)
    if outcome.get("code"):
        return refusal_status(str(outcome["code"])), outcome
    return 200, {}


def _answer(resident, outcome: dict):
    """The whole state on success, the refusal and its status otherwise."""
    if outcome:
        return refusal_status(str(outcome.get("code", ""))), outcome
    return 200, state_payload(resident)


def _answer_empty(outcome: dict):
    """Empty on success, the refusal and its status otherwise."""
    if outcome.get("code"):
        return refusal_status(str(outcome["code"])), outcome
    return 200, {}


def _unknown_hub(hub_id: str):
    outcome = {"code": "unknown_hub", "params": {"hub_id": hub_id}}
    return refusal_status(outcome["code"]), outcome


def _service_action(resident, service_type: str, body: dict):
    outcome = resident.service_action(service_type, body)
    if outcome:
        return refusal_status(str(outcome.get("code", ""))), outcome
    return 200, state_payload(resident)


def _open_link(resident, body: dict):
    """Open an ``https`` link in the person's browser; any other is unknown."""
    url = str(body.get("url", "") or "")
    if urllib.parse.urlsplit(url).scheme != "https":
        return 404, {"code": "unknown_request", "params": {}}
    resident.platform.open_url(url)
    return 200, {}


def _font_piece(query: str):
    """One piece of a face of the terminal's font, by ``name`` and ``offset``."""
    values = urllib.parse.parse_qs(query)
    name = (values.get("name") or [""])[0]
    try:
        offset = int((values.get("offset") or ["0"])[0])
        return 200, page.terminal_font_piece(name, offset)
    except (KeyError, ValueError, OSError):
        return 404, {"code": "unknown_request", "params": {}}


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
