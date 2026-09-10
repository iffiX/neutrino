"""The ``nclient`` command.

Most people never see this: the client installs with a desktop entry that
runs ``nclient gui``, which is the resident and its window. These commands
do the same things from a terminal.

    nclient connect neutrino://enroll/... [--yes]
    nclient disconnect
    nclient status
    nclient gui [--hidden]
    nclient quit
    nclient service list | <kind> <action>

The client runs as a person and never as root.
"""

import argparse
import os
import sys

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import (
    connect,
    disconnect,
    gui,
    quit,
    service,
    status,
    wording,
)
from neutrino_client.services.ai import AI_REASONING_EFFORTS

AI_PROVIDER_HUB = "hub"
AI_PROVIDER_OFF = "off"


def main() -> int:
    """Dispatch to a subcommand.

    Returns:
        The subcommand's exit status.
    """
    _use_utf8_console()
    parser = argparse.ArgumentParser(
        prog="nclient", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--version", action="version", version=CLIENT_VERSION)
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
        "--yes", action="store_true", help="replace an existing binding without asking"
    )
    subparsers.add_parser("disconnect", help="leave the hub")
    subparsers.add_parser("status", help="what this person is bound to")
    gui_parser = subparsers.add_parser("gui", help="run the client and its window")
    gui_parser.add_argument(
        "--hidden", action="store_true", help="start without showing the window"
    )
    subparsers.add_parser("quit", help="stop the running client")
    service_parser, service_kind_parsers = _add_service_parser(subparsers)

    arguments = parser.parse_args()
    if not arguments.command:
        parser.print_help()
        return 2
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print(wording.word_code("root_refused"), file=sys.stderr)
        return 2
    if arguments.command == "connect":
        return connect.main(arguments.link, is_forced=arguments.yes)
    if arguments.command == "disconnect":
        return disconnect.main()
    if arguments.command == "gui":
        return gui.main(is_hidden=arguments.hidden)
    if arguments.command == "quit":
        return quit.main()
    if arguments.command == "service":
        return _run_service(arguments, service_parser, service_kind_parsers)
    return status.main()


def _use_utf8_console() -> None:
    """Print UTF-8 on Windows, where the console default mangles arrows.

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


def _add_service_parser(subparsers):
    """The ``nclient service`` verb tree, one branch per service type.

    Args:
        subparsers: The top-level subparser group.

    Returns:
        The service parser and each kind's parser, for their help on a
        missing action.
    """
    service_parser = subparsers.add_parser(
        "service", help="what the hub publishes for this person"
    )
    kinds = service_parser.add_subparsers(dest="service_command", metavar="<kind>")
    kinds.add_parser("list", help="every published entry, nested by kind")

    web_parser = kinds.add_parser("web", help="published links")
    web_actions = web_parser.add_subparsers(dest="web_action", metavar="<action>")
    web_open = web_actions.add_parser("open", help="open one link in the browser")
    web_open.add_argument("ref", help="the entry's number in service list, or its id")

    port_parser = kinds.add_parser("port", help="published ports")
    port_actions = port_parser.add_subparsers(dest="port_action", metavar="<action>")
    forward = port_actions.add_parser(
        "forward", help="relay one port to this machine's loopback"
    )
    forward.add_argument("ref", help="the entry's number in service list, or its id")
    forward.add_argument(
        "--local-port", type=int, default=0, help="the loopback port to prefer"
    )
    unforward = port_actions.add_parser("unforward", help="close that relay")
    unforward.add_argument("ref", help="the entry's number in service list, or its id")

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
    ai_actions.add_parser("show", help="where this person's tools point")
    ai_apply = ai_actions.add_parser(
        "apply", help="point the tools at the hub, or put them back"
    )
    ai_apply.add_argument(
        "provider",
        choices=(AI_PROVIDER_HUB, AI_PROVIDER_OFF),
        help="hub points the tools at the gateway; off puts them back",
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

    desktop_parser = kinds.add_parser("desktop", help="desktops the fleet shares")
    desktop_actions = desktop_parser.add_subparsers(
        dest="desktop_action", metavar="<action>"
    )
    desktop_connect = desktop_actions.add_parser(
        "connect", help="open the viewer at one shared desktop"
    )
    desktop_connect.add_argument(
        "ref", help="the entry's number in service list, or its id"
    )

    kind_parsers = {
        "web": web_parser,
        "port": port_parser,
        "file": file_parser,
        "ai": ai_parser,
        "desktop": desktop_parser,
    }
    return service_parser, kind_parsers


def _run_service(arguments, service_parser, kind_parsers) -> int:
    """Dispatch one ``nclient service`` action.

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
    if kind == "port" and arguments.port_action == "forward":
        return service.main_port(
            arguments.ref, is_enabled=True, local_port=arguments.local_port
        )
    if kind == "port" and arguments.port_action == "unforward":
        return service.main_port(arguments.ref, is_enabled=False)
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
            is_enabled=arguments.provider == AI_PROVIDER_HUB,
            claude_default=arguments.claude_default,
            claude_opus=arguments.claude_opus,
            claude_sonnet=arguments.claude_sonnet,
            claude_haiku=arguments.claude_haiku,
            codex_model=arguments.codex_model,
            codex_effort=arguments.codex_effort,
            gemini_model=arguments.gemini_model,
        )
    if kind == "desktop" and arguments.desktop_action == "connect":
        return service.main_desktop_connect(arguments.ref)
    if kind in kind_parsers:
        kind_parsers[kind].print_help()
        return 2
    service_parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
