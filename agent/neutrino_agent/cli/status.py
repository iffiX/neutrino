"""``nagent status``: what this machine is bound to, and whether it works.

Three things break independently, and a device missing from the hub's panel
looks the same for all three: the machine never joined, the service is not
running, or the hub cannot be reached from here. This says which.

The agent reports errors as ``{"code", "params"}``; the wording lives here.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import time

from neutrino_agent import AGENT_VERSION
from neutrino_agent.cli.wording import word_code, word_reinstall
from neutrino_agent.control import client
from neutrino_agent.core import enrollment, self_update
from neutrino_agent.core.loop import Agent
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

STATUS_UNBOUND = "this machine has joined no gateway"
# How long the running service gets to answer on its control socket; a
# small board under load takes more than a second.
STATUS_CONTROL_TIMEOUT_S = 5

# What the channel's own failures say on this surface; every other code is
# worded by the shared table. The advice lines name the next step.
ERROR_WORDS = {
    "hub_untrusted": "what answers is not the hub this machine pinned",
    "hub_unreachable": "the hub cannot be reached",
    "hub_reply_unreadable": "the hub sent a reply this agent could not read",
    "agent_package_missing": (
        "the hub has no agent package for this machine's platform"
    ),
    "agent_package_fetch_failed": (
        "the hub could not fetch the agent package for this platform"
    ),
    "agent_package_sha256_mismatch": (
        "what the hub fetched is not the package its manifest pins"
    ),
    "agent_package_cache_unwritable": (
        "the hub could not write the agent package to its own disk"
    ),
}
ERROR_ADVICE = {
    "hub_untrusted": (
        "the hub was reset or reinstalled; join again with a fresh link "
        "from its Devices page"
    ),
    "binding_unknown": "join again with a fresh link from the hub's Devices page",
    "replaced": "restart the service, or join again with a fresh link",
    "protocol_too_old": "update this agent from the hub's Devices page",
    "protocol_too_new": "update the hub, then this machine reports again",
}


def main() -> int:
    """Report the three things that break independently.

    Returns:
        Process exit status: 0 when bound and the hub answered, 1 otherwise.
    """
    print(f"neutrino-agent {AGENT_VERSION}")
    _print_reinstall()
    # The running service is the one that knows. The binding file is only
    # read when there is no service to ask.
    state = _local_state()
    if state is not None:
        return _status_from_service(state)
    binding = enrollment.load_binding()
    if not binding:
        print(f"hub        {STATUS_UNBOUND}")
        print(f"service    {service_state()}")
        return 1
    _print_binding(binding)
    current = service_state()
    if current == "running":
        # A hello from here would take the binding from the service: the hub
        # keeps one socket per binding and replaces the one it holds. A
        # service that runs and did not answer on its socket is asked again,
        # never gone around.
        print(f"service    {current}")
        print(
            "heartbeat  unknown. The service holds the binding but did not "
            "answer on its control socket; ask again in a moment"
        )
        return 1
    hint = _start_hint()
    tail = f"; start it: {hint}" if hint else ""
    print(f"service    {current}. The machine reports only while it runs{tail}")

    agent = Agent(log=_discard)
    started_at = time.monotonic()
    agent.probe()
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    error = agent.last_error()
    if error:
        _print_error(error)
        return 1
    print(f"heartbeat  ok, {elapsed_ms} ms. The hub answered this machine's hello")
    return 0


def service_state() -> str:
    """What the platform says about the agent's own service.

    Returns:
        The state word, or ``unknown`` where nothing answers for it.
    """
    try:
        return detect_platform().read_agent_service_state()
    except PlatformUnsupportedError:
        return "unknown"


def word_error(error: dict) -> str:
    """One error's wording on this surface.

    Args:
        error: The agent's ``{"code", "params"}``.

    Returns:
        The sentence to print.
    """
    code = error.get("code", "")
    params = error.get("params", {}) or {}
    if code == "hub_unreachable":
        return str(params.get("detail", "")) or ERROR_WORDS[code]
    if code == "agent_package_digest_mismatch":
        target = params.get("target", "")
        return f"self-update to {target} failed: the package did not match its digest"
    if code == "agent_update_launch_failed":
        target = params.get("target", "")
        return f"self-update to {target} could not be launched"
    if code in ERROR_WORDS:
        return ERROR_WORDS[code]
    return word_code(code, params)


def _print_binding(binding: dict) -> None:
    """The two lines that name the hub and the binding on it."""
    print(f"hub        {binding.get('gateway_url', '')}")
    print(f"binding    {binding.get('id', '')}")


def _print_error(error: dict) -> None:
    """The heartbeat line for one error, and its advice when there is some."""
    print(f"heartbeat  {word_error(error)}")
    advice = ERROR_ADVICE.get(str(error.get("code", "")))
    if advice:
        print(f"           {advice}")


def _print_reinstall() -> None:
    """The line about the reinstall this agent came from, when there is one."""
    try:
        data_dir = detect_platform().agent_data_dir()
    except PlatformUnsupportedError:
        return
    result = self_update.read_reinstall_result(data_dir)
    if result:
        print(f"reinstall  {word_reinstall(result)}")


def _start_hint() -> str:
    """The command this platform starts the agent's own service with.

    Returns:
        The platform's start command, empty where it has no service.
    """
    try:
        return detect_platform().agent_service_start_hint()
    except PlatformUnsupportedError:
        return ""


def _local_state() -> "dict | None":
    """What the running service says about itself, asked over its socket.

    Returns:
        The service's own state, or None when nothing answers on the
        control socket.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError:
        return None
    try:
        status, state = client.request(
            socket_path=socket_path,
            method="GET",
            path="/api/state",
            timeout_s=STATUS_CONTROL_TIMEOUT_S,
        )
    except (OSError, ValueError):
        return None
    return state if status == 200 else None


def _status_from_service(state: dict) -> int:
    """Report from the running service's own account of itself.

    Args:
        state: The local page's state payload.

    Returns:
        Process exit status: 0 when bound and beating cleanly, 1 otherwise.
    """
    error = state.get("last_error")
    if not isinstance(error, dict) or not error.get("code"):
        error = None
    if not state.get("is_connected"):
        print(f"hub        {STATUS_UNBOUND}")
        if error is not None:
            _print_error(error)
        print("service    running")
        return 1
    binding = state.get("binding")
    _print_binding(binding if isinstance(binding, dict) else {})
    print("service    running")
    if error is not None:
        _print_error(error)
        return 1
    if not state.get("is_online", True):
        print("heartbeat  connecting. The service is reaching the hub")
        return 1
    print("heartbeat  ok. The service holds its socket to the hub")
    return 0


def _discard(message: str) -> None:
    """Swallow the agent's own log while status does the talking."""
