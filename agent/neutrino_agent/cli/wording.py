"""The shared voice of the module, operation, service and gui commands.

The agent answers with typed ``{"code", "params"}`` refusals and state
tokens; every surface words them itself, and this file is where the
terminal surface keeps its tables. The completeness test holds them to the
page's own code list, so a code the page words cannot go silent here. The
one way these commands ask the running agent lives here too: over the
control socket, as whoever ran them, with the honest line when nothing
answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
import sys

from neutrino_agent.constants import AGENT_SERVICE_NAME
from neutrino_agent.control import client
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

AGENT_NOT_RUNNING = (
    "the agent is not running, so there is nothing to ask; start it: "
    f"sudo systemctl enable --now {AGENT_SERVICE_NAME}"
)
NO_CONTROL_SOCKET = "this platform has no control socket yet"
NOT_JOINED = "this machine has joined no gateway"

# What each typed refusal or failure code says on this surface.
CLI_CODE_WORDS = {
    "no_platform_build": "no version of this exists for this machine",
    "install_unconfirmed": "the install finished, but the software cannot be found",
    "vendor_served_a_page": (
        "the vendor served a challenge page, not the package; install it "
        "by hand and the row follows"
    ),
    "module_fetch_failed": "the hub could not fetch this from the vendor",
    "module_fetch_unavailable": "the hub cannot fetch downloads gated on a browser",
    "module_fetch_too_large": "the vendor's download is larger than the hub will fetch",
    "module_release_unreadable": "the hub could not read that project's releases",
    "module_cache_unwritable": "the hub could not save the download",
    "module_artifact_missing": "the hub no longer holds that download; ask again",
    "module_digest_mismatch": "what arrived did not match the hub's checksum",
    "module_sha256_mismatch": (
        "the download did not match the checksum this hub pins for it"
    ),
    "rdp_password_missing": "set an access password to share this desktop",  # scan: allow
    "rdp_no_desktop": "this machine has no desktop session to share",
    "rdp_wrong_seat": "{account} is not signed in at this machine's screen",
    "rdp_configure_failed": "RustDesk could not be configured: {detail}",
    "rdp_launch_failed": "the RustDesk client could not be started: {detail}",
    "rdp_no_address": "that machine published no address to connect to",
    "rdp_nobody_seated": "nobody is signed in at that machine's screen",
    "rdp_screen_not_allowed": ("allow screen sharing once at that machine's screen"),
    "agent_never_reported": "this machine never said how the install went",
    "uninstall_unconfirmed": "the uninstall finished, but the software is still there",
    "no_download_named": "the catalog names no download for this machine",
    "unsupported_platform": "this machine cannot do this",
    "unknown_kind": "the agent does not know this kind of module",
    "unknown_action": "the hub asked for something this agent does not know",
    "order_failed": "the install did not finish",
    "verify_failed": "this machine could not tell whether the software is there",
    "install_failed": "the install failed",
    "no_target_user": "that account does not exist on this machine",
    "no_endpoint": "the hub has not granted this account a key yet",
    "module_missing": "install the {module} module first",
    "mountpoint_not_empty": "that folder is not empty",
    "cifs_missing": "the mount tooling is missing on this machine",
    "credentials_missing": (
        "the saved login is gone; enter it again: nagent service file config"
    ),
    "fs_refused": "this account may not use that folder",
    "mountpoint_invalid": "that is not a mount location this machine can use",
    "no_logged_on_session": (
        "sign in as the mount's account on this machine, then try again"
    ),
    "agent_internal": "the agent hit an unexpected error; check its log",
    "control_scope_refused": "this account is not allowed to do that; run it as root",
    "control_identity_unknown": "the agent cannot tell who is asking",
    "control_channel_closed": "the agent stopped answering; run nagent gui again",
    "gui_webkitgtk_missing": (
        "the GUI needs WebKitGTK; install it: sudo apt install {packages}"
    ),
    "gui_webview2_missing": "the GUI needs {runtime}; install it and try again",
    "gui_wkwebview_missing": (
        "this install is missing its WKWebView support; reinstall the agent package"
    ),
    "unknown_request": "the agent does not know this request",
}

# Codes worded through their params' own detail text when they carry one.
CLI_DETAIL_CODES = (
    "install_failed",
    "download_failed",
    "reconcile_failed",
    "mount_failed",
    "unmount_failed",
    "forward_failed",
)

# The closed module-state table, plus the ai rows' switching pair and the
# word for a machine that has not reported.
CLI_STATE_WORDS = {
    "installed": "installed",
    "absent": "not installed",
    "installing": "installing",
    "uninstalling": "uninstalling",
    "activating": "switching",
    "deactivating": "switching back",
    "unsupported": "not available on this machine",
    "failed": "failed",
    "unknown": "waiting for the agent",
    # Where a shared desktop stands, the page's own four words.
    "not_shared": "not shared",
    "sharing": "shared",
    "starting": "starting",
    "waiting_for_approval": "waiting for permission on this machine",
}

CLI_OPERATION_WORDS = {
    "queued": "waiting its turn",
    "fetching": "downloading",
    "running": "running",
    "done": "done",
    "failed": "failed",
}

# A running order is worded by what it was asked to do.
CLI_OPERATION_ACTION_WORDS = {"install": "installing", "uninstall": "uninstalling"}

# Where a mount record stands; failed records are worded by their code.
CLI_MOUNT_STATE_WORDS = {
    "queued": "waiting for the agent",
    "mounting": "mounting",
    "pending": "waiting to mount",
    "mounted": "mounted",
    "detached": "not mounted",
}

# Whether the hub is running an operation on this machine right now —
# whichever surface started it.
OPERATION_RUNNING_STATES = ("queued", "fetching", "installing", "running")

OPERATION_AGENT_TITLE = "agent"


def word_code(code: str, params: "dict | None" = None) -> str:
    """One typed code's wording on this surface.

    Args:
        code: The code the agent or the channel answered with.
        params: The code's own parameters.

    Returns:
        The words to print; a code with no entry prints as itself.
    """
    if not code:
        return ""
    values = params or {}
    if code in CLI_DETAIL_CODES:
        return str(values.get("detail", "")) or CLI_STATE_WORDS["failed"]
    word = CLI_CODE_WORDS.get(code)
    return _fill(word, values) if word else code


def word_state(state: str) -> str:
    """One state token's wording; a token outside the table reads as unknown.

    Args:
        state: The token a row reported.

    Returns:
        The words to print.
    """
    return CLI_STATE_WORDS.get(state, CLI_STATE_WORDS["unknown"])


def word_operation(operation: dict) -> str:
    """One operation's standing, worded.

    Args:
        operation: The hub's ``{"kind", "action", "title", "state",
            "output"}``.

    Returns:
        The words to print.
    """
    state = str(operation.get("state", ""))
    if state == "installing":
        action = str(operation.get("action", ""))
        if action in CLI_OPERATION_ACTION_WORDS:
            return CLI_OPERATION_ACTION_WORDS[action]
        return CLI_OPERATION_WORDS["running"]
    return CLI_OPERATION_WORDS.get(state, state)


def operation_title(operation: dict) -> str:
    """What an operation is called: its title, or the agent's own name.

    Args:
        operation: The hub's operation object.

    Returns:
        The title to print.
    """
    if operation.get("kind") == "bootstrap":
        return OPERATION_AGENT_TITLE
    return str(operation.get("title", ""))


def is_operation_running(operation: "dict | None") -> bool:
    """Whether the hub is mid-operation on this machine.

    Args:
        operation: The state payload's operation object, or None.

    Returns:
        True while an operation is queued, fetching, installing or running.
    """
    return bool(operation) and operation.get("state") in OPERATION_RUNNING_STATES


def read_state() -> "dict | None":
    """The running agent's state, in the scope the kernel says we own.

    Returns:
        The state payload, or None after the honest line was printed.
    """
    answer = request("GET", "/api/state")
    if answer is None:
        return None
    status, state = answer
    if status != 200:
        print(word_code(str(state.get("code", ""))), file=sys.stderr)
        return None
    return state


def request(method: str, path: str, body: "dict | None" = None):
    """One request to the running agent over its control socket.

    Args:
        method: The HTTP method.
        path: The request path.
        body: Sent as JSON when given.

    Returns:
        ``(status, reply)``, or None after the honest line was printed —
        no platform socket, or nothing answering on it.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError:
        print(NO_CONTROL_SOCKET, file=sys.stderr)
        return None
    try:
        return client.request(
            socket_path=socket_path, method=method, path=path, body=body
        )
    except (OSError, ValueError):
        print(AGENT_NOT_RUNNING, file=sys.stderr)
        return None


def stream_output(operation: dict, printed: int) -> int:
    """Print whatever the operation's output grew by since the last look.

    Args:
        operation: The hub's operation object.
        printed: How much of the output was printed already.

    Returns:
        How much has been printed now.
    """
    output = str(operation.get("output") or "")
    if len(output) < printed:
        printed = 0
    if len(output) > printed:
        sys.stdout.write(output[printed:])
        sys.stdout.flush()
    return len(output)


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
