"""The ``nagent`` command.

    nagent connect neutrino://enroll/...
    nagent disconnect
    nagent status
    nagent sync
    nagent rdp start [--user <name>] | stop
    nagent run

The shape is settled in ../../../docs/cli.md.
"""

import argparse
import os
import shlex
import sys

from neutrino_agent import AGENT_VERSION
from neutrino_agent.cli import connect, disconnect, rdp, run, status, sync

# Everything the agent does is root's to do, and the control socket it asks
# through is root's to open. Only ``--version`` answers any account.
ROOT_COMMANDS = {
    "connect": "it writes the binding and starts the service",
    "disconnect": "it removes the binding",
    "status": "it asks the agent over its root-only control socket",
    "sync": "it asks the agent over its root-only control socket",
    "rdp": "it configures this machine's desktop share",
    "run": "the agent manages this machine",
}


def main() -> int:
    """Dispatch to a subcommand.

    Returns:
        The subcommand's exit status.
    """
    parser = argparse.ArgumentParser(prog="nagent", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=AGENT_VERSION)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    connect_parser = subparsers.add_parser("connect", help="join the hub a link names")
    connect_parser.add_argument(
        "link",
        nargs="?",
        default="",
        help="the neutrino://enroll link from the hub; omit it to paste at "
        "a prompt instead",
    )
    connect_parser.add_argument(
        "--yes",
        action="store_true",
        help="replace an existing binding without asking",
    )

    subparsers.add_parser("disconnect", help="leave the hub")
    subparsers.add_parser("status", help="what this machine is bound to")
    subparsers.add_parser("sync", help="ask the hub for this machine's state now")
    subparsers.add_parser("run", help="run the agent in the foreground")
    rdp_parser = _add_rdp_parser(subparsers)

    arguments = parser.parse_args()
    if not arguments.command:
        parser.print_help()
        return 2
    reason = ROOT_COMMANDS.get(arguments.command)
    if reason is not None and hasattr(os, "geteuid") and os.geteuid() != 0:
        print(f"nagent {arguments.command} needs root ({reason}):", file=sys.stderr)
        print(f"    sudo nagent {shlex.join(sys.argv[1:])}", file=sys.stderr)
        return 2
    if arguments.command == "connect":
        return connect.main(arguments.link, is_forced=arguments.yes)
    if arguments.command == "disconnect":
        return disconnect.main()
    if arguments.command == "run":
        return run.main()
    if arguments.command == "sync":
        return sync.main()
    if arguments.command == "rdp":
        return _run_rdp(arguments, rdp_parser)
    return status.main()


def _add_rdp_parser(subparsers):
    """The ``nagent rdp`` verb tree.

    Args:
        subparsers: The top-level subparser group.

    Returns:
        The rdp parser, for its help on a missing action.
    """
    rdp_parser = subparsers.add_parser("rdp", help="this machine's desktop share")
    actions = rdp_parser.add_subparsers(dest="rdp_command", metavar="<action>")
    start = actions.add_parser(
        "start", help="share this desktop; the password is asked, never an argument"
    )
    start.add_argument(
        "--user",
        default="",
        help="whose desktop; unnamed, the account that invoked sudo or the "
        "one account at the screen",
    )
    actions.add_parser("stop", help="stop sharing this desktop")
    return rdp_parser


def _run_rdp(arguments, rdp_parser) -> int:
    """Dispatch one ``nagent rdp`` action.

    Args:
        arguments: The parsed arguments.
        rdp_parser: The rdp parser, for its help.

    Returns:
        The action's exit status.
    """
    if arguments.rdp_command == "start":
        return rdp.main_start(user=arguments.user)
    if arguments.rdp_command == "stop":
        return rdp.main_stop()
    rdp_parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
