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
    nagent module list | install <name> | uninstall <name>
    nagent operation [--follow]
    nagent service list | <kind> <action>

The shape is settled in ../../../docs/cli.md.
"""

import argparse
import os
import shlex
import sys

from neutrino_agent import AGENT_VERSION
from neutrino_agent.cli import (
    connect,
    disconnect,
    module,
    operation,
    run,
    service,
    status,
    ui,
)
from neutrino_agent.services.ai import AI_REASONING_EFFORTS

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
    _use_utf8_console()
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

    module_parser = _add_module_parser(subparsers)
    operation_parser = subparsers.add_parser(
        "operation", help="the current or last operation on this machine"
    )
    operation_parser.add_argument(
        "--follow", action="store_true", help="keep printing until it closes"
    )
    service_parser, service_kind_parsers = _add_service_parser(subparsers)

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
    if arguments.command == "module":
        return _run_module(arguments, module_parser)
    if arguments.command == "operation":
        return operation.main(is_followed=arguments.follow)
    if arguments.command == "service":
        return _run_service(arguments, service_parser, service_kind_parsers)
    return status.main()


def _use_utf8_console() -> None:
    """Print UTF-8 on Windows, where the console default mangles em-dashes.

    A redirected stream, or one that cannot be reconfigured, is left as is.
    """
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _add_module_parser(subparsers):
    """The ``nagent module`` verb tree.

    Args:
        subparsers: The top-level subparser group.

    Returns:
        The module parser, for its help on a missing action.
    """
    module_parser = subparsers.add_parser(
        "module", help="what the hub administers on this machine"
    )
    actions = module_parser.add_subparsers(dest="module_command", metavar="<action>")
    actions.add_parser("list", help="every module row, as the page shows them")
    for verb, description in (
        ("install", "ask the hub to install one module"),
        ("uninstall", "ask the hub to uninstall one module"),
    ):
        verb_parser = actions.add_parser(verb, help=description)
        verb_parser.add_argument("name", help="the module, as module list names it")
        verb_parser.add_argument(
            "--no-wait",
            action="store_true",
            help="post the ask and return instead of following the operation",
        )
        if verb == "uninstall":
            verb_parser.add_argument(
                "--yes",
                action="store_true",
                help="skip the SSH server's confirmation",
            )
    return module_parser


def _add_service_parser(subparsers):
    """The ``nagent service`` verb tree, one branch per service type.

    Args:
        subparsers: The top-level subparser group.

    Returns:
        The service parser and each kind's parser, for their help on a
        missing action.
    """
    service_parser = subparsers.add_parser(
        "service", help="what the hub publishes for this machine"
    )
    kinds = service_parser.add_subparsers(dest="service_command", metavar="<kind>")
    kinds.add_parser("list", help="every published entry, nested by kind")

    web_parser = kinds.add_parser("web", help="published links")
    web_actions = web_parser.add_subparsers(dest="web_action", metavar="<action>")
    web_open = web_actions.add_parser("open", help="open one link in the browser")
    web_open.add_argument("ref", help="the entry's number in service list, or its id")

    port_parser = kinds.add_parser("port", help="published ports")
    port_actions = port_parser.add_subparsers(dest="port_action", metavar="<action>")
    for verb, description in (
        ("forward", "relay one port to this machine's loopback"),
        ("unforward", "close that relay"),
    ):
        verb_parser = port_actions.add_parser(verb, help=description)
        verb_parser.add_argument(
            "ref", help="the entry's number in service list, or its id"
        )

    file_parser = kinds.add_parser("file", help="published shares")
    file_actions = file_parser.add_subparsers(dest="file_action", metavar="<action>")
    file_config = file_actions.add_parser(
        "config", help="save a share's login and path, and mount it"
    )
    file_config.add_argument(
        "ref", help="the entry's number in service list, or its id"
    )
    file_config.add_argument("--path", required=True, help="where to mount the share")
    file_config.add_argument("--username", default="", help="the share's own username")
    for verb, description in (
        ("mount", "mount a share again with its saved login"),
        ("unmount", "unmount a share; its saved login stays"),
    ):
        verb_parser = file_actions.add_parser(verb, help=description)
        verb_parser.add_argument(
            "ref", help="the entry's number in service list, or its id"
        )

    ai_parser = kinds.add_parser("ai", help="the AI gateway service")
    ai_actions = ai_parser.add_subparsers(dest="ai_action", metavar="<action>")
    ai_actions.add_parser("show", help="each account's standing at the gateway")
    ai_apply = ai_actions.add_parser(
        "apply",
        help="make the named accounts the whole enabled set; the rest are put back",
    )
    ai_apply.add_argument(
        "--account",
        action="append",
        default=[],
        dest="accounts",
        metavar="<account>",
        help="an account to switch at the gateway; repeatable, none disables all",
    )
    for flag, description in (
        ("--claude-default", "Claude Code's default model slot"),
        ("--claude-opus", "Claude Code's opus slot"),
        ("--claude-sonnet", "Claude Code's sonnet slot"),
        ("--claude-haiku", "Claude Code's haiku slot"),
        ("--codex-model", "Codex's model"),
        ("--gemini-model", "Gemini's model"),
    ):
        ai_apply.add_argument(
            flag,
            metavar="<model>",
            help=f"{description}; omit to keep, pass '' for the gateway default",
        )
    ai_apply.add_argument(
        "--codex-effort",
        choices=AI_REASONING_EFFORTS + ("",),
        metavar="<effort>",
        help=(
            "Codex's reasoning effort: "
            + ", ".join(AI_REASONING_EFFORTS)
            + "; omit to keep, pass '' for the gateway default"
        ),
    )
    kind_parsers = {
        "web": web_parser,
        "port": port_parser,
        "file": file_parser,
        "ai": ai_parser,
    }
    return service_parser, kind_parsers


def _run_module(arguments, module_parser) -> int:
    """Dispatch one ``nagent module`` action.

    Args:
        arguments: The parsed arguments.
        module_parser: The module parser, for its help.

    Returns:
        The action's exit status.
    """
    if arguments.module_command == "list":
        return module.main_list()
    if arguments.module_command in ("install", "uninstall"):
        return module.main_switch(
            arguments.name,
            is_enabled=arguments.module_command == "install",
            is_waited=not arguments.no_wait,
            is_confirmed=getattr(arguments, "yes", False),
        )
    module_parser.print_help()
    return 2


def _run_service(arguments, service_parser, kind_parsers) -> int:
    """Dispatch one ``nagent service`` action.

    Args:
        arguments: The parsed arguments.
        service_parser: The service parser, for its help.
        kind_parsers: Each kind's parser, for theirs.

    Returns:
        The action's exit status.
    """
    kind = arguments.service_command
    if kind == "list":
        return service.main_list()
    if kind == "web" and arguments.web_action == "open":
        return service.main_web_open(arguments.ref)
    if kind == "port" and arguments.port_action in ("forward", "unforward"):
        return service.main_port(
            arguments.ref, is_enabled=arguments.port_action == "forward"
        )
    if kind == "file" and arguments.file_action == "config":
        return service.main_file_config(
            arguments.ref, path=arguments.path, username=arguments.username
        )
    if kind == "file" and arguments.file_action == "mount":
        return service.main_file_mount(arguments.ref)
    if kind == "file" and arguments.file_action == "unmount":
        return service.main_file_unmount(arguments.ref)
    if kind == "ai" and arguments.ai_action == "show":
        return service.main_ai_show()
    if kind == "ai" and arguments.ai_action == "apply":
        return service.main_ai_apply(
            arguments.accounts,
            claude_default=arguments.claude_default,
            claude_opus=arguments.claude_opus,
            claude_sonnet=arguments.claude_sonnet,
            claude_haiku=arguments.claude_haiku,
            codex_model=arguments.codex_model,
            codex_effort=arguments.codex_effort,
            gemini_model=arguments.gemini_model,
        )
    if kind in kind_parsers:
        kind_parsers[kind].print_help()
        return 2
    service_parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
