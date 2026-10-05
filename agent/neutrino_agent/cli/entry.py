"""The ``nagent`` command.

    nagent join neutrino://enroll/...
    nagent leave [--yes]
    nagent status
    nagent sync
    nagent start [--yes]
    nagent stop [--yes]
    nagent run
    nagent service run
    nagent service uninstall [--yes]
    nagent answer --prompt <text> --answer <keys> -- <program> [arguments]
    nagent step-down --uid <uid> --gid <gid> -- <program> [arguments]

The shape is settled in ../../../docs/cli.md.
"""

import argparse
import os
import shlex
import subprocess
import sys

from neutrino_agent import AGENT_VERSION
from neutrino_agent.cli import (
    answer,
    join,
    leave,
    run,
    service,
    start,
    status,
    step_down,
    stop,
    sync,
)

# Everything the agent does is root's to do, and the control socket it asks
# through is root's to open. Only ``--version`` answers any account.
ROOT_COMMANDS = {
    "join": "it writes the binding and starts the service",
    "leave": "it removes the binding",
    "status": "it asks the agent over its root-only control socket",
    "sync": "it asks the agent over its root-only control socket",
    "start": "it starts the agent's service",
    "stop": "it stops the agent's service",
    "run": "the agent manages this machine",
    "service": "the agent manages this machine",
}


def main() -> int:
    """Dispatch to a subcommand.

    Returns:
        The subcommand's exit status.
    """
    parser = argparse.ArgumentParser(prog="nagent", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=AGENT_VERSION)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    join_parser = subparsers.add_parser("join", help="join the hub a link names")
    join_parser.add_argument(
        "link",
        nargs="?",
        default="",
        help="the neutrino://enroll link from the hub; omit it to paste at "
        "a prompt instead",
    )
    join_parser.add_argument(
        "--yes",
        action="store_true",
        help="replace an existing binding without asking",
    )

    leave_parser = subparsers.add_parser("leave", help="leave the hub")
    leave_parser.add_argument(
        "--yes", action="store_true", help="leave without asking first"
    )
    subparsers.add_parser("status", help="what this machine is bound to")
    subparsers.add_parser("sync", help="ask the hub for this machine's state now")
    start_parser = subparsers.add_parser("start", help="start the agent's service")
    start_parser.add_argument(
        "--yes", action="store_true", help="start without asking first"
    )
    stop_parser = subparsers.add_parser("stop", help="stop the agent's service")
    stop_parser.add_argument(
        "--yes", action="store_true", help="stop without asking first"
    )
    subparsers.add_parser(
        "run",
        help="run the agent in the foreground, the entry the systemd unit and "
        "the LaunchDaemon start; use start and stop otherwise",
    )
    service_parser = subparsers.add_parser(
        "service",
        help="the entries the service manager and the package's removal run",
    )
    service_actions = service_parser.add_subparsers(
        dest="service_command", metavar="<action>"
    )
    service_actions.add_parser(
        "run",
        help="the foreground entry the service control manager starts; use "
        "start and stop otherwise",
    )
    uninstall_parser = service_actions.add_parser(
        "uninstall",
        help="take away the units, tasks and firewall rules the modules added, "
        "the entry the package's removal runs; on macOS, remove the agent",
    )
    uninstall_parser.add_argument(
        "--yes", action="store_true", help="remove without asking first"
    )
    answer_parser = subparsers.add_parser(
        "answer",
        help="run a program on a terminal of its own and answer one question; "
        "the agent runs it as an account",
    )
    answer_parser.add_argument("--prompt", required=True, help="the question's text")
    answer_parser.add_argument(
        "--answer", required=True, help="what to type before Enter"
    )
    answer_parser.add_argument(
        "program", nargs=argparse.REMAINDER, help="-- then the program"
    )
    step_down_parser = subparsers.add_parser(
        "step-down",
        help="drop to an account and run one program as it; the agent runs it "
        "under launchctl asuser",
    )
    step_down_parser.add_argument("--uid", type=int, required=True)
    step_down_parser.add_argument("--gid", type=int, required=True)
    step_down_parser.add_argument(
        "program", nargs=argparse.REMAINDER, help="-- then the program"
    )

    arguments = parser.parse_args()
    if not arguments.command:
        parser.print_help()
        return 2
    reason = ROOT_COMMANDS.get(arguments.command)
    if reason is not None and not _is_privileged():
        _print_privilege_refusal(arguments.command, reason)
        return 2
    if arguments.command == "join":
        return join.main(arguments.link, is_forced=arguments.yes)
    if arguments.command == "leave":
        return leave.main(is_forced=arguments.yes)
    if arguments.command == "start":
        return start.main(is_forced=arguments.yes)
    if arguments.command == "stop":
        return stop.main(is_forced=arguments.yes)
    if arguments.command == "run":
        return run.main()
    if arguments.command == "sync":
        return sync.main()
    if arguments.command == "answer":
        program = list(arguments.program)
        if program[:1] == ["--"]:
            program = program[1:]
        return answer.main(
            prompt=arguments.prompt, answer=arguments.answer, argv=program
        )
    if arguments.command == "step-down":
        program = list(arguments.program)
        if program[:1] == ["--"]:
            program = program[1:]
        return step_down.main(uid=arguments.uid, gid=arguments.gid, argv=program)
    if arguments.command == "service":
        if arguments.service_command == "run":
            return service.main_run()
        if arguments.service_command == "uninstall":
            return service.main_uninstall(is_forced=arguments.yes)
        service_parser.print_help()
        return 2
    return status.main()


def _is_privileged() -> bool:
    """Whether this process may act for the machine: root, or on Windows an
    elevated administrator."""
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    from neutrino_agent.platforms.windows import WindowsPlatform

    return WindowsPlatform().is_elevated()


def _print_privilege_refusal(command: str, reason: str) -> None:
    """Say who may run a command, and how to run it as them."""
    if hasattr(os, "geteuid"):
        print(f"nagent {command} needs root ({reason}):", file=sys.stderr)
        print(f"    sudo nagent {shlex.join(sys.argv[1:])}", file=sys.stderr)
        return
    print(f"nagent {command} needs an administrator ({reason}):", file=sys.stderr)
    print(
        f"    nagent {subprocess.list2cmdline(sys.argv[1:])} in a terminal "
        "opened as administrator",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
