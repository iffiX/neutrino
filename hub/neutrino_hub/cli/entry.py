"""The ``nhub`` command.

One entry point with a subcommand each. The work itself stays in the module
beside this one; this file only decides which of them runs.

The shape is settled in [../../../../docs/cli.md](../../../../docs/cli.md).
"""

import argparse
import os
import shlex
import sys

from neutrino_hub import HUB_VERSION
from neutrino_hub.cli import dev_root
from neutrino_hub.cli.dev_root import DEV_ROOT_NAME

# Each subcommand names the module that does the work. They are imported when
# chosen rather than up front: `nhub unlock` should not pay for the installer's
# imports.
# What a shell reports for a command somebody interrupted.
STOPPED_STATUS = 130

COMMANDS = {
    "setup": ("neutrino_hub.cli.setup", "Set this gateway up, once"),
    "run": ("neutrino_hub.cli.run", "Run the control panel in the foreground"),
    "stop": ("neutrino_hub.cli.stop", "Stop what the hub runs on this box"),
    "apply": ("neutrino_hub.cli.apply", "Render every config and make it true"),
    "unlock": ("neutrino_hub.cli.unlock", "Clear the login lockout and SSH bans"),
    "reset": ("neutrino_hub.cli.reset", "Return part of the box to a fresh state"),
    "vault": ("neutrino_hub.cli.vault", "Maintain the credential vault"),
    "scan-secrets": (
        "neutrino_hub.cli.scan_secrets",
        "Check what a commit would carry",
    ),
}


def _without_dev(arguments: list) -> list:
    """Take the global --dev out, having acted on it.

    It is handled here rather than by a subcommand because the roots it moves
    are resolved when `utils.constants` is imported, which every subcommand
    module does. Acting before that import is what makes one flag enough.

    Args:
        arguments: The command line, without the program name.

    Returns:
        The same arguments with every ``--dev`` removed.

    Raises:
        SystemExit: When there is no working copy to keep a root beside.
    """
    if "--dev" not in arguments:
        return arguments
    try:
        dev_root.enter()
    except dev_root.NoWorkingCopy as error:
        raise SystemExit(f"error: {error}")
    return [argument for argument in arguments if argument != "--dev"]


def main() -> int:
    """Dispatch to a subcommand.

    Returns:
        The subcommand's exit status.
    """
    parser = argparse.ArgumentParser(prog="nhub", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=HUB_VERSION)
    parser.add_argument(
        "--dev",
        action="store_true",
        help=f"run against {DEV_ROOT_NAME}/ in the working copy",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name, (_, summary) in COMMANDS.items():
        subparsers.add_parser(name, help=summary, add_help=False)

    arguments, rest = parser.parse_known_args(_without_dev(sys.argv[1:]))
    if not arguments.command:
        parser.print_help()
        return 2

    # Imported here, after --dev has moved the roots; at module level it
    # would resolve them first and make the flag a no-op.
    from neutrino_hub.utils.constants import is_dev_root_set

    if (
        arguments.command != "scan-secrets"
        and not is_dev_root_set()
        and hasattr(os, "geteuid")
        and os.geteuid() != 0
    ):
        print(
            f"nhub {arguments.command} acts on the installed hub and needs root:",
            file=sys.stderr,
        )
        print(f"    sudo nhub {shlex.join(sys.argv[1:])}", file=sys.stderr)
        return 2

    module_name, _ = COMMANDS[arguments.command]
    module = __import__(module_name, fromlist=["main"])
    sys.argv = [f"nhub {arguments.command}"] + rest
    try:
        return module.main()
    except KeyboardInterrupt:
        # One line rather than a traceback: nothing here is a crash when the
        # person at the keyboard is the one who stopped it.
        print(f"\nnhub {arguments.command} was stopped", file=sys.stderr)
        return STOPPED_STATUS


if __name__ == "__main__":
    sys.exit(main())
