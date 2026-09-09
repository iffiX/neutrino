"""The shared voice of the ``nagent`` commands.

The agent answers with typed ``{"code", "params"}`` refusals and state
tokens; every surface words them itself, and this file is where the terminal
surface keeps its tables. The completeness test holds them to the codes the
agent's own source emits, so a code the agent can answer with cannot go
silent here. The one way these commands ask the running agent lives here
too: over the control socket, with the honest line when nothing answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import getpass
import re
import sys

from neutrino_agent.constants import AGENT_SERVICE_NAME
from neutrino_agent.control import client
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform
from neutrino_agent.rdp.constants import (
    RDP_STATE_NOT_SHARED,
    RDP_STATE_SHARING,
    RDP_STATE_STARTING,
)

AGENT_NOT_RUNNING = (
    "the agent is not running, so there is nothing to ask; start it: "
    f"sudo systemctl enable --now {AGENT_SERVICE_NAME}"
)
NO_CONTROL_SOCKET = "this platform has no control socket"

# What each typed refusal or failure code says on this surface. The channel's
# own failures are worded by ``status.py``, which is the surface that shows
# them.
CLI_CODE_WORDS = {
    "no_platform_build": "no version of this exists for this machine",
    "install_failed": "the install failed",
    "install_unconfirmed": "the install finished, but the software cannot be found",
    "uninstall_unconfirmed": (
        "the uninstall finished, but the software is still there"
    ),
    "module_digest_mismatch": "what arrived did not match the hub's checksum",
    "module_missing": "install the {module} module first",
    "no_download_named": "the catalog names no download for this machine",
    "order_failed": "the install did not finish",
    "verify_failed": "this machine could not tell whether the software is there",
    "unknown_kind": "the agent does not know this kind of module",
    "unknown_action": "the hub asked for something this agent does not know",
    "stream_unknown": "the hub opened a stream this agent does not know",
    "shell_failed": "the shell could not start: {detail}",
    "path_invalid": "{path} is not a path this agent can act on",
    "path_missing": "{path} is not there",
    "file_exists": "something already stands at {path}",
    "write_failed": "{path} could not be written: {detail}",
    "op_failed": "the file operation failed: {detail}",
    "process_missing": "no process {pid} is running",
    "kill_failed": "process {pid} could not be ended: {detail}",
    "product_unknown": "{product} is not a remote desktop this agent reads",
    "unsupported_action": "the hub asked for a command this agent does not run",
    "state_not_settled": "the machine is still applying its configuration; try again",
    "unsupported_platform": "this machine cannot do this",
    "no_target_user": "that account does not exist on this machine",
    "rdp_no_seat": "say whose desktop to share: nagent rdp start --user <name>",
    "rdp_password_missing": "set an access password to share this desktop",  # scan: allow
    "rdp_no_desktop": "this machine has no desktop session to share",
    "rdp_wrong_seat": "{account} is not signed in at this machine's screen",
    "rdp_configure_failed": "RustDesk could not be configured: {detail}",
    "rdp_nobody_seated": "nobody is signed in at that machine's screen",
    "rdp_screen_not_allowed": "allow screen sharing once at that machine's screen",
    "agent_internal": "the agent hit an unexpected error; check its log",
    "unknown_request": "the agent does not know this request",
    "module_not_orderable": "the {module} module is the agent's own; nothing installs it",
    "unknown_module": "the agent has no {module} module to configure",
    "apply_failed": "the configuration could not be applied: {detail}",
    "validate_failed": "the configuration could not be checked: {detail}",
    "command_failed": "the command failed: {detail}",
    "samba_missing": "Samba is not installed on this machine",
    "samba_config_rejected": "Samba rejected the configuration: {detail}",
    "share_name_invalid": "share name {name} is not usable",
    "share_name_reserved": "{name} is a name Samba reserves for itself",
    "share_name_duplicate": "two shares are both named {name}",
    "share_path_relative": "share {name} needs an absolute path",
    "share_user_unknown": "share {name} names {user}, which is not a configured user",
    "user_name_invalid": "user name {user} is not a unix name",
    "user_name_duplicate": "user {user} is listed twice",
    "user_unknown": "{user} is not a configured user",
    "port_invalid": "{port} is not a port",
    "port_reserved": "port {port} already belongs to the hub",
    "root_url_invalid": "the root URL must start with http:// or https://",
    "secrets_missing": "the hub sent no secrets for the git server",  # scan: allow
    "username_invalid": "username {username} is not usable",
    "admin_exists": "an administrator already exists; add more in Gitea",
    "admin_unknown": "{username} is not an administrator",
    "container_name_invalid": "container name {name} is not usable",
    "container_name_duplicate": "two containers are both named {name}",
    "container_unknown": "{name} is not a container podman knows",
    "image_invalid": "container {name} needs an image reference with no spaces",
    "port_mapping_invalid": "port {port} on {name} is not host:container",
    "volume_invalid": "volume {volume} on {name} is not source:destination",
    "environment_invalid": "environment entry {entry} on {name} is not KEY=value",
    "command_invalid": "the command on {name} cannot span lines",
    "mirror_invalid": "mirror {mirror} is not a registry host",
    "pool_name_invalid": "pool name {name} is not usable",
    "pool_name_reserved": "{name} means something to zpool itself",
    "layout_unknown": "unknown vdev layout {layout}",
    "layout_disk_count": "{layout} needs at least {minimum} disks",
    "dataset_name_invalid": "dataset path {name} is not usable",
    "compression_unknown": "compression {compression} is not offered",
    "recordsize_unknown": "recordsize {recordsize} is not offered",
    "mountpoint_invalid": "the mountpoint must be an absolute path",
    "mountpoint_forbidden": "{mountpoint} would sit over the operating system",
}

# Where a shared desktop stands, plus the word for a machine that has not
# reported.
CLI_STATE_WORDS = {
    RDP_STATE_NOT_SHARED: "not shared",
    RDP_STATE_SHARING: "shared",
    RDP_STATE_STARTING: "starting",
    "unknown": "waiting for the agent",
}


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
    word = CLI_CODE_WORDS.get(code)
    return _fill(word, params or {}) if word else code


def word_state(state: str) -> str:
    """One state token's wording; a token outside the table reads as unknown.

    Args:
        state: The token a row reported.

    Returns:
        The words to print.
    """
    return CLI_STATE_WORDS.get(state, CLI_STATE_WORDS["unknown"])


def word_reinstall(result: dict) -> str:
    """One reinstall record's wording on this surface.

    Args:
        result: What the install's own unit wrote: ``{"exit_code",
            "finished_at", ...}``.

    Returns:
        The words to print.
    """
    exit_code = result.get("exit_code")
    outcome = "ok" if exit_code == 0 else f"failed, exit {exit_code}"
    return f"{outcome} at {result.get('finished_at', '')}"


def read_state() -> "dict | None":
    """The running agent's state.

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


def act(path: str, body: dict) -> "dict | None":
    """One posted action, refusals worded here.

    Args:
        path: The request path.
        body: The action's own fields.

    Returns:
        The fresh state payload, or None after the refusal was printed.
    """
    answer = request("POST", path, body)
    if answer is None:
        return None
    _, reply = answer
    if reply.get("code"):
        print(
            word_code(str(reply.get("code")), reply.get("params")),
            file=sys.stderr,
        )
        return None
    return reply


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


def ask_secret(prompt: str) -> str:
    """A password from the person, never from the command line.

    At a terminal it is asked without echo. From a pipe it is one line of
    stdin, which is what a script has.

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
