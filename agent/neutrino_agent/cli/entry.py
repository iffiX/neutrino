"""The ``nagent`` command.

Most machines never see this: the agent installs with a desktop entry that
runs ``nagent ui``, which opens the agent's own page in the clicking
account's scope. These commands do the same things from a terminal, for
machines with no desktop and for reading what went wrong.

    nagent connect neutrino://enroll/...
    nagent disconnect
    nagent run
    nagent status
    nagent ui

The shape is settled in ../../../docs/cli.md.
"""

import argparse
import os
import shlex
import sys

from neutrino_agent import AGENT_VERSION
from neutrino_agent.cli import connect, disconnect, run, status, ui

# The commands that change the machine, and what each one touches. Everything
# else — status, --version — answers to any account.
ROOT_COMMANDS = {
    "connect": "it writes the binding and starts the service",
    "disconnect": "it removes the binding",
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

    run_parser = subparsers.add_parser("run", help="run the agent in the foreground")
    run_parser.add_argument(
        "--no-ui", action="store_true", help="do not serve the local page"
    )

    subparsers.add_parser("status", help="what this machine is bound to")

    subparsers.add_parser("ui", help="open this machine's page in a browser")

    arguments = parser.parse_args()
    if not arguments.command:
        parser.print_help()
        return 2
    reason = ROOT_COMMANDS.get(arguments.command)
    if reason is not None and hasattr(os, "geteuid") and os.geteuid() != 0:
        print(f"nagent {arguments.command} needs root — {reason}:", file=sys.stderr)
        print(f"    sudo nagent {shlex.join(sys.argv[1:])}", file=sys.stderr)
        return 2
    if arguments.command == "connect":
        return connect.main(arguments.link, is_forced=arguments.yes)
    if arguments.command == "disconnect":
        return disconnect.main()
    if arguments.command == "run":
        return run.main(is_ui_served=not arguments.no_ui)
    if arguments.command == "ui":
        return ui.main()
    return status.main()


if __name__ == "__main__":
    sys.exit(main())
