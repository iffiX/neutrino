"""The ``nhub`` command.

One entry point with a subcommand each. The work itself stays in the module
beside this one; this file only decides which of them runs.

The shape is settled in [../../../../docs/cli.md](../../../../docs/cli.md).
"""

import argparse
import sys

from neutrino_hub import HUB_VERSION

# Each subcommand names the module that does the work. They are imported when
# chosen rather than up front: `nhub unlock` should not pay for the installer's
# imports.
COMMANDS = {
    "setup": ("neutrino_hub.cli.setup", "Set this gateway up, once"),
    "run": ("neutrino_hub.cli.run", "Run the control panel in the foreground"),
    "apply": ("neutrino_hub.cli.apply", "Render every config and make it true"),
    "unlock": ("neutrino_hub.cli.unlock", "Clear the login lockout and SSH bans"),
    "reset": ("neutrino_hub.cli.reset", "Return part of the box to a fresh state"),
    "scan-secrets": (
        "neutrino_hub.cli.scan_secrets",
        "Check what a commit would carry",
    ),
}


def main() -> int:
    """Dispatch to a subcommand.

    Returns:
        The subcommand's exit status.
    """
    parser = argparse.ArgumentParser(prog="nhub", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=HUB_VERSION)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name, (_, summary) in COMMANDS.items():
        subparsers.add_parser(name, help=summary, add_help=False)

    arguments, rest = parser.parse_known_args()
    if not arguments.command:
        parser.print_help()
        return 2

    module_name, _ = COMMANDS[arguments.command]
    module = __import__(module_name, fromlist=["main"])
    sys.argv = [f"nhub {arguments.command}"] + rest
    return module.main()


if __name__ == "__main__":
    sys.exit(main())
