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
from neutrino_agent.control import client
from neutrino_agent.core import enrollment
from neutrino_agent.core.loop import Agent
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

STATUS_UNBOUND = "this machine has joined no gateway"

# What each error code says on this surface, and the follow-up line the codes
# that unbind by themselves get.
ERROR_WORDS = {
    "hub_refused": "the hub refused this machine's token",
    "hub_untrusted": "what answers is not the hub this machine pinned",
    "hub_unreachable": "the hub cannot be reached",
    "agent_wire_stale": (
        "this agent's build does not match the hub; it reinstalls itself "
        "from the hub's package"
    ),
    "agent_update_fetch_failed": (
        "self-update failed: the package could not be fetched from the hub"
    ),
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
    "hub_refused": (
        "the hub has let this machine go; the running service unbinds by "
        "itself, or run `sudo nagent disconnect` and join with a fresh link"
    ),
    "hub_untrusted": (
        "what answers there is not the hub this machine pinned. It was "
        "reset or reinstalled; the running service unbinds by itself after "
        "a few of these, and a fresh link from the hub's Devices page rejoins"
    ),
    "agent_newer_than_hub": (
        "the hub turns this agent away; the running service unbinds by "
        "itself after a few of these. Update the hub, then rejoin with a "
        "fresh link from its Devices page"
    ),
}
UNBIND_CAUSE_WORDS = {
    "hub_untrusted": "the hub's identity changed (it was reset or reinstalled)",
    "agent_newer_than_hub": "this agent is newer than the hub",
    "hub_refused": "the hub no longer knows this machine",
}
REJOIN_HINT = "rejoin by pasting a fresh link from the hub's Devices page"


def main() -> int:
    """Report the three things that break independently.

    Returns:
        Process exit status: 0 when bound and the hub answered, 1 otherwise.
    """
    print(f"neutrino-agent {AGENT_VERSION}")
    # The running service is the one that knows. The binding file is only
    # read when there is no service to ask.
    state = _local_state()
    if state is not None:
        return _status_from_service(state)
    gateway_url = enrollment.load_config().get("gateway_url", "")
    if not gateway_url:
        print(f"hub        {STATUS_UNBOUND}")
        print(f"service    {service_state()}")
        return 1
    print(f"hub        {gateway_url}   connected")
    current = service_state()
    if current == "running":
        print(f"service    {current}")
    else:
        hint = _start_hint()
        tail = f"; start it: {hint}" if hint else ""
        print(f"service    {current}. The machine reports only while it runs{tail}")

    agent = Agent(log=_discard)
    started_at = time.monotonic()
    agent.probe()
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    error = agent.last_error()
    if error:
        print(f"heartbeat  {word_error(error)}")
        advice = ERROR_ADVICE.get(error.get("code", ""))
        if advice:
            print(f"           {advice}")
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
    if code == "agent_newer_than_hub":
        return (
            f"this agent ({params.get('agent_version', '')}) is newer than "
            f"the hub ({params.get('hub_version', '')}); update the hub first"
        )
    if code == "hub_unreachable":
        return str(params.get("detail", "")) or ERROR_WORDS[code]
    if code == "self_unbound":
        cause = UNBIND_CAUSE_WORDS.get(
            str(params.get("cause", "")), UNBIND_CAUSE_WORDS["hub_refused"]
        )
        return f"{cause}; {REJOIN_HINT}"
    if code == "agent_package_digest_mismatch":
        target = params.get("target", "")
        return f"self-update to {target} failed: the package did not match its digest"
    if code == "agent_update_launch_failed":
        target = params.get("target", "")
        return f"self-update to {target} could not be launched"
    return ERROR_WORDS.get(code, code)


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
            socket_path=socket_path, method="GET", path="/api/state", timeout_s=2
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
    if not state.get("is_connected"):
        print(f"hub        {STATUS_UNBOUND}")
        print("service    running")
        return 1
    print(f"hub        {state.get('gateway_url', '')}   connected")
    print("service    running")
    error = state.get("last_error")
    if isinstance(error, dict) and error.get("code"):
        print(f"heartbeat  {word_error(error)}")
        return 1
    if not state.get("is_online", True):
        print("heartbeat  connecting. The service is reaching the hub")
        return 1
    print("heartbeat  ok. The service holds its socket to the hub")
    return 0


def _discard(message: str) -> None:
    """Swallow the agent's own log while status does the talking."""
