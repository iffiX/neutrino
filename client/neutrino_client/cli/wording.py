"""The shared voice of the client's commands.

The resident answers with typed ``{"code", "params"}`` refusals and state
tokens; every surface words them itself, and this file is where the
terminal surface keeps its tables. The completeness test holds them to the
page's own code list. The one way these commands ask the resident lives
here too: over the control socket, as whoever ran them, with the honest
line when nothing answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import getpass
import re
import sys

from neutrino_client.control import client
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform

NOT_JOINED = "this person has joined no hub"

# What each typed refusal or failure code says on this surface.
CLIENT_CODE_WORDS = {
    "resident_not_running": "the client is not running; open it: nclient gui",
    "busy": "the client is still handling the last request",
    "crashed": "the last request failed on this machine",
    "root_refused": "nclient runs as a person, never as root",
    "bundle_missing": "this install carries no {binary}; reinstall the client",
    "mount_not_authorized": "mounting was not authorized on this machine",
    "mount_tooling_missing": "the mount tooling is missing on this machine",
    "control_peer_refused": "the running client belongs to another account",
    "control_socket_unavailable": "this session has no place for the client's socket",
    "control_channel_closed": "the client stopped answering; open it again",
    "client_internal": "the client hit an unexpected error; check its log",
    "client_disabled": "the hub has switched this client off",
    "link_missing": "paste the link from the hub's Clients page",
    "link_unreadable": (
        "that is not an enrollment link; copy the whole line from the hub"
    ),
    "link_incomplete": "that link carries no hub address and token",
    "link_not_for_client": "that link is for a device agent, not for a client",
    "enroll_refused": (
        "the hub refused this link; it may have expired, so generate a fresh one"
    ),
    "enroll_no_token": "the hub sent no token back",
    "hub_refused": "the hub refused this client's token",
    "hub_untrusted": "what answers is not the hub this link pins",
    "hub_unreachable": "the hub cannot be reached",
    "hub_reply_unreadable": "the hub sent a reply this client could not read",
    "client_newer_than_hub": (
        "this client ({client_version}) is newer than the hub ({hub_version}); "
        "update the hub first"
    ),
    "self_unbound": "{cause}; rejoin by pasting a fresh link from the hub",
    "no_endpoint": "the hub has not granted this person a key yet",
    "mountpoint_not_empty": "that folder is not empty",
    "credentials_missing": (
        "the saved login is gone; enter it again: nclient service file config"
    ),
    "fs_refused": "this account may not use that folder",
    "mountpoint_invalid": "give a folder under your home, like ~/nas/share",
    "mountpoint_not_drive_letter": "give an unused drive letter, like N:",
    "rdp_not_shared": "that desktop is not shared any more",
    "rdp_no_desktop": "this session has no screen to open a viewer on",
    "rdp_launch_failed": "the RustDesk viewer could not be started: {detail}",
    "rdp_no_address": "that machine published no address to connect to",
    "unsupported_platform": "this machine cannot do this",
    "gui_webkitgtk_missing": (
        "the window needs WebKitGTK; install it: sudo apt install {packages}"
    ),
    "gui_webview2_missing": "the window needs {runtime}; install it and try again",
    "unknown_request": "the client does not know this request",
}

# Codes worded through their params' own detail text when they carry one.
CLIENT_DETAIL_CODES = (
    "switch_failed",
    "reconcile_failed",
    "mount_failed",
    "unmount_failed",
    "forward_failed",
)

# The ai row's standing, and the word for a row that has not reported.
CLIENT_STATE_WORDS = {
    "installed": "ready",
    "absent": "not installed",
    "failed": "failed",
    "unknown": "waiting for the client",
}

# The ai lane's step while it runs, shown in place of the row's standing.
CLIENT_WORK_WORDS = {
    "switching": "switching the tools",
}

# Where a mount record stands; failed records are worded by their code.
CLIENT_MOUNT_STATE_WORDS = {
    "queued": "waiting for the client",
    "mounting": "mounting",
    "pending": "waiting to mount",
    "mounted": "mounted",
    "detached": "not mounted",
}

# What an unbind names as its cause.
CLIENT_UNBIND_CAUSE_WORDS = {
    "hub_untrusted": "the hub's identity changed (it was reset or reinstalled)",
    "client_newer_than_hub": "this client is newer than the hub",
    "hub_refused": "the hub no longer knows this client",
}


def word_code(code: str, params: "dict | None" = None) -> str:
    """One typed code's wording on this surface.

    Args:
        code: The code the resident or the channel answered with.
        params: The code's own parameters.

    Returns:
        The words to print; a code with no entry prints as itself.
    """
    if not code:
        return ""
    values = dict(params or {})
    if code in CLIENT_DETAIL_CODES:
        return str(values.get("detail", "")) or CLIENT_STATE_WORDS["failed"]
    if code == "hub_unreachable" and values.get("detail"):
        return str(values["detail"])
    if code == "self_unbound":
        cause = str(values.get("cause", ""))
        values["cause"] = CLIENT_UNBIND_CAUSE_WORDS.get(
            cause, CLIENT_UNBIND_CAUSE_WORDS["hub_refused"]
        )
    word = CLIENT_CODE_WORDS.get(code)
    return _fill(word, values) if word else code


def word_state(state: str) -> str:
    """One state token's wording; a token outside the table reads as unknown.

    Args:
        state: The token a row reported.

    Returns:
        The words to print.
    """
    return CLIENT_STATE_WORDS.get(state, CLIENT_STATE_WORDS["unknown"])


def read_state() -> "dict | None":
    """The resident's state, as this person.

    Returns:
        The state payload, or None after the honest line was printed.
    """
    answer = request("GET", "/api/state")
    if answer is None:
        return None
    status, state = answer
    if status != 200:
        print(
            word_code(str(state.get("code", "")), state.get("params")), file=sys.stderr
        )
        return None
    return state


def request(method: str, path: str, body: "dict | None" = None):
    """One request to the resident over its control socket.

    Args:
        method: The HTTP method.
        path: The request path.
        body: Sent as JSON when given.

    Returns:
        ``(status, reply)``, or None after the honest line was printed: no
        platform socket, or nothing answering on it.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError as error:
        print(word_code(error.code), file=sys.stderr)
        return None
    try:
        return client.request(
            socket_path=socket_path, method=method, path=path, body=body
        )
    except (OSError, ValueError):
        print(word_code("resident_not_running"), file=sys.stderr)
        return None


def ask_secret(prompt: str) -> str:
    """A password from the person, never from the command line.

    At a terminal it is asked without echo. From a pipe it is one line of
    stdin.

    Args:
        prompt: What to ask at a terminal.

    Returns:
        The secret, without its line ending.
    """
    stream = sys.stdin
    if stream is None or not stream.isatty():
        return (stream.readline() if stream is not None else "").rstrip("\r\n")
    return getpass.getpass(prompt)


def _fill(template: str, params: dict) -> str:
    """A template with its ``{name}`` holes filled from the params.

    Args:
        template: The wording, with ``{name}`` holes.
        params: The code's parameters; a missing name fills as empty.

    Returns:
        The filled wording.
    """

    def _value(match) -> str:
        return str(params.get(match.group(1), ""))

    return re.sub(r"\{(\w+)\}", _value, template)
