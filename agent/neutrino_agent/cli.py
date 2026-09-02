"""The ``nagent`` command.

Most machines never see this: the agent installs with a desktop entry, and
clicking it opens the agent's own page on http://127.0.0.1:8765, which is where
the enrollment link is pasted. These commands do the same things from a
terminal, for machines with no desktop and for reading what went wrong.

    nagent connect neutrino://enroll/...
    nagent disconnect
    nagent run
    nagent status

The shape is settled in ../../docs/cli.md.
"""

import argparse
import subprocess
import sys
import time

from neutrino_agent import AGENT_VERSION, enrollment
from neutrino_agent.agent import Agent
from neutrino_agent.constants import AGENT_SERVICE_NAME
from neutrino_agent.mini_ui import MiniUiServer

# --- config ---
STATUS_UNBOUND = "this machine has joined no gateway"
STATUS_SERVICE_UNKNOWN = "unknown"


def main() -> int:
    """Dispatch to a subcommand.

    Returns:
        The subcommand's exit status.
    """
    parser = argparse.ArgumentParser(prog="nagent", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=AGENT_VERSION)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    connect = subparsers.add_parser("connect", help="join the hub a link names")
    connect.add_argument(
        "link",
        nargs="?",
        default="",
        help="the neutrino://enroll link from the hub; omit it to paste at "
        "a prompt instead",
    )
    connect.add_argument(
        "--yes",
        action="store_true",
        help="replace an existing binding without asking",
    )

    subparsers.add_parser("disconnect", help="leave the hub")

    run = subparsers.add_parser("run", help="run the agent in the foreground")
    run.add_argument("--no-ui", action="store_true", help="do not serve the local page")

    subparsers.add_parser("status", help="what this machine is bound to")

    arguments = parser.parse_args()
    if not arguments.command:
        parser.print_help()
        return 2
    if arguments.command == "connect":
        return _connect(arguments.link, is_forced=arguments.yes)
    if arguments.command == "disconnect":
        return _disconnect()
    if arguments.command == "run":
        return _run(is_ui_served=not arguments.no_ui)
    return _status()


def _connect(link: str, *, is_forced: bool) -> int:
    """Join the hub the link names.

    Args:
        link: The enrollment link.
        is_forced: Replace an existing binding without asking.

    Returns:
        Process exit status.
    """
    link = link.strip()
    if not link:
        try:
            link = input("paste the enrollment link: ").strip()
        except EOFError:
            link = ""
    if not link:
        print("error: no link was given", file=sys.stderr)
        return 1
    bound_to = enrollment.load_config().get("gateway_url", "")
    if bound_to and not is_forced:
        answer = input(f"this machine is bound to {bound_to}; replace it? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("nothing changed")
            return 1
    try:
        Agent().connect(link)
    except enrollment.EnrollmentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"joined {enrollment.load_config().get('gateway_url', '')}")
    if _service_state() != "running":
        subprocess.run(
            ["systemctl", "enable", "--now", AGENT_SERVICE_NAME],
            capture_output=True,
            timeout=30,
            check=False,
        )
        state = _service_state()
        print(f"service    {state}")
        if state != "running":
            print(
                "start it for heartbeats: "
                f"sudo systemctl enable --now {AGENT_SERVICE_NAME}",
                file=sys.stderr,
            )
    return 0


def _disconnect() -> int:
    """Leave the hub.

    Returns:
        Process exit status.
    """
    if not enrollment.is_configured():
        print(STATUS_UNBOUND)
        return 1
    Agent().disconnect()
    print("left the hub; this machine keeps the agent and can join again")
    return 0


def _run(*, is_ui_served: bool) -> int:
    """Run the agent in the foreground.

    Args:
        is_ui_served: Serve the local page as well.

    Returns:
        Process exit status.
    """
    agent = Agent()
    if is_ui_served:
        MiniUiServer(agent=agent).start()
    agent.run_forever()
    return 0


def _status() -> int:
    """Report the three things that break independently.

    A device missing from the hub's panel looks the same whether the machine
    never joined, the service is not running, or the hub cannot be reached from
    here. This says which.

    Returns:
        Process exit status: 0 when bound and the hub answered, 1 otherwise.
    """
    print(f"neutrino-agent {AGENT_VERSION}")
    gateway_url = enrollment.load_config().get("gateway_url", "")
    if not gateway_url:
        print(f"hub        {STATUS_UNBOUND}")
        print(f"service    {_service_state()}")
        return 1
    print(f"hub        {gateway_url}   connected")
    service_state = _service_state()
    if service_state == "running":
        print(f"service    {service_state}")
    else:
        print(
            f"service    {service_state} — the machine beats only while "
            "status runs; start it: sudo systemctl enable --now "
            f"{AGENT_SERVICE_NAME}"
        )

    agent = Agent(log=_discard)
    started_at = time.monotonic()
    delay = agent.run_once()
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    error = agent.last_error()
    if error:
        print(f"heartbeat  {error}")
        if "refused" in error:
            print(
                "           the hub has let this machine go; the running "
                "service unbinds by itself, or run `sudo nagent disconnect` "
                "and join with a fresh link"
            )
        elif "fingerprint" in error:
            print(
                "           what answers there is not the hub this machine "
                "pinned; if the hub was reinstalled, rejoin with a fresh "
                "link from its Devices page"
            )
        return 1
    print(f"heartbeat  ok, {elapsed_ms} ms — next report in {delay}s")
    return 0


def _service_state() -> str:
    """What the init system says about the agent's own service.

    Returns:
        The state word, or ``unknown`` where nothing answers for it.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", AGENT_SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return STATUS_SERVICE_UNKNOWN
    state = result.stdout.strip()
    return "running" if state == "active" else (state or STATUS_SERVICE_UNKNOWN)


def _discard(message: str) -> None:
    """Swallow the agent's own log while status does the talking."""


if __name__ == "__main__":
    sys.exit(main())
