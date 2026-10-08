"""The ``nclient`` command.

Most people never see this: the client installs with a desktop entry that
runs ``nclient gui``, which is the resident and its window. These commands
do the same things from a terminal.

    nclient join neutrino://enroll/...
    nclient leave [--hub <name>] [--yes]
    nclient status [--json]
    nclient gui [--hidden]
    nclient quit
    nclient service list | <kind> <action> [--hub <name>]
    nclient terminal list | open | attach | exec | persist | share | stop

The client runs as a person and never as root. The exceptions are
``nclient easytier-daemon``, which the system starts as root, or as SYSTEM
with ``--service`` on Windows, and ``nclient files-daemon``, which Windows
starts as SYSTEM with ``--service``; no person runs either.
"""

import argparse
import os
import sys

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import (
    easytier_daemon,
    files_daemon,
    gui,
    join,
    leave,
    quit,
    service,
    status,
    terminal,
    wording,
)
from neutrino_client.constants import (
    CLIENT_EASYTIER_DAEMON_VERB,
    CLIENT_FILES_DAEMON_VERB,
)
from neutrino_client.services.ai import AI_REASONING_EFFORTS

AI_PROVIDER_HUB = "hub"
AI_PROVIDER_OFF = "off"
# The one option of ``nclient terminal``'s verbs that takes a value.
TERMINAL_VALUE_OPTIONS = ("--hub",)
# What separates ``exec``'s own arguments from the command.
TERMINAL_COMMAND_SEPARATOR = "--"


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

    join_parser = subparsers.add_parser("join", help="join the hub a link names")
    join_parser.add_argument(
        "link",
        nargs="?",
        default="",
        help="the neutrino://enroll link from the hub; omit it to paste at "
        "a prompt instead",
    )
    leave_parser = subparsers.add_parser("leave", help="leave one hub")
    _add_hub_argument(leave_parser)
    leave_parser.add_argument("--yes", action="store_true", help="leave without asking")
    status_parser = subparsers.add_parser("status", help="what this person is bound to")
    status_parser.add_argument(
        "--json", action="store_true", help="print one JSON object"
    )
    gui_parser = subparsers.add_parser("gui", help="run the client and its window")
    gui_parser.add_argument(
        "--hidden", action="store_true", help="start without showing the window"
    )
    quit_parser = subparsers.add_parser("quit", help="stop the running client")
    quit_parser.add_argument("--upgrade", action="store_true", help=argparse.SUPPRESS)
    terminal_parser = _add_terminal_parser(subparsers)
    service_parser, service_kind_parsers = _add_service_parser(subparsers)
    daemon_parser = subparsers.add_parser(CLIENT_EASYTIER_DAEMON_VERB)
    daemon_parser.add_argument("--service", action="store_true")
    files_daemon_parser = subparsers.add_parser(CLIENT_FILES_DAEMON_VERB)
    files_daemon_parser.add_argument("--service", action="store_true")

    argv, command = _split_terminal_argv(_argv_without_launch_services())
    arguments = parser.parse_args(argv)
    if not arguments.command:
        if _is_opened_as_app():
            return gui.main(is_hidden=False)
        parser.print_help()
        return 2
    if arguments.command == CLIENT_EASYTIER_DAEMON_VERB:
        return easytier_daemon.main(is_service=arguments.service)
    if arguments.command == CLIENT_FILES_DAEMON_VERB:
        return files_daemon.main(is_service=arguments.service)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print(wording.word_code("root_refused"), file=sys.stderr)
        return 2
    if arguments.command not in ("gui", "quit"):
        holder = wording.other_holder()
        if holder:
            print(
                wording.word_code("client_held", {"account": holder}),
                file=sys.stderr,
            )
            return 1
    if arguments.command == "join":
        return join.main(arguments.link)
    if arguments.command == "leave":
        return leave.main(arguments.hub, is_forced=arguments.yes)
    if arguments.command == "gui":
        return gui.main(is_hidden=arguments.hidden)
    if arguments.command == "quit":
        return quit.main(is_upgrade=arguments.upgrade)
    if arguments.command == "terminal":
        return _run_terminal(arguments, terminal_parser, command)
    if arguments.command == "service":
        return _run_service(arguments, service_parser, service_kind_parsers)
    return status.main(is_json=arguments.json)


# What Launch Services passes a program it opens: a process serial number on
# older macOS, nothing on newer ones.
LAUNCH_SERVICES_ARGUMENT_PREFIX = "-psn_"


def _is_opened_as_app() -> bool:
    """Whether this process was opened as a macOS app bundle.

    Returns:
        True when the program runs from ``Contents/MacOS`` of a bundle, which
        is what a click on the icon starts and what carries no verb.
    """
    return sys.platform == "darwin" and "/Contents/MacOS/" in os.path.realpath(
        sys.argv[0]
    )


def _argv_without_launch_services() -> list:
    """The arguments as given, less what Launch Services added.

    Returns:
        ``sys.argv[1:]`` without a process serial number.
    """
    return [
        argument
        for argument in sys.argv[1:]
        if not argument.startswith(LAUNCH_SERVICES_ARGUMENT_PREFIX)
    ]


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


def _add_hub_argument(parser) -> None:
    """Name the hub a command acts on, on one parser.

    Args:
        parser: The parser the flag belongs to.
    """
    parser.add_argument(
        "--hub",
        default="",
        metavar="<name>",
        help="the hub, by name or id; omit it with one hub joined",
    )


def _split_terminal_argv(argv: list) -> tuple:
    """The arguments with ``open`` for a bare machine, and exec's command cut off.

    Args:
        argv: The arguments as given.

    Returns:
        ``(argv, command)``: the verb moved to just after ``terminal``, and
        the words after ``exec``'s ``--``; ``command`` is None without one.
    """
    if not argv or argv[0] != "terminal":
        return argv, None
    rest = list(argv[1:])
    position = _terminal_verb_position(rest)
    if position is None:
        return argv, None
    verb = rest.pop(position)
    if verb not in terminal.TERMINAL_VERBS:
        rest.insert(position, verb)
        verb = terminal.TERMINAL_DEFAULT_VERB
    if verb == "exec" and TERMINAL_COMMAND_SEPARATOR in rest:
        cut = rest.index(TERMINAL_COMMAND_SEPARATOR)
        return ["terminal", verb] + rest[:cut], rest[cut + 1 :]
    return ["terminal", verb] + rest, None


def _terminal_verb_position(rest: list) -> "int | None":
    """Where the first word that is not an option is, None when there is none."""
    position = 0
    while position < len(rest):
        word = rest[position]
        if word == TERMINAL_COMMAND_SEPARATOR:
            return None
        if word in TERMINAL_VALUE_OPTIONS:
            position += 2
            continue
        if word.startswith("-"):
            position += 1
            continue
        return position
    return None


def _add_terminal_parser(subparsers):
    """The ``nclient terminal`` verb tree.

    Args:
        subparsers: The top-level subparser group.

    Returns:
        The terminal parser, for its help on a missing verb.
    """
    terminal_parser = subparsers.add_parser(
        "terminal",
        help="shells and commands on the machines a hub offers them on",
        description="A bare machine opens a shell: nclient terminal <machine>.",
    )
    verbs = terminal_parser.add_subparsers(dest="terminal_command", metavar="<verb>")
    list_parser = verbs.add_parser(
        "list", help="every online machine and the sessions it keeps"
    )
    _add_hub_argument(list_parser)
    list_parser.add_argument(
        "--json", action="store_true", help="print one JSON object"
    )
    open_parser = verbs.add_parser("open", help="open a new shell in this terminal")
    _add_machine_argument(open_parser)
    open_parser.add_argument(
        "--persistent",
        action="store_true",
        help="keep the session after its last window closes",
    )
    open_parser.add_argument(
        "--shared",
        action="store_true",
        help="let every client with terminal rights on the machine attach",
    )
    _add_hub_argument(open_parser)
    attach_parser = verbs.add_parser(
        "attach", help="attach this terminal to a session the machine keeps"
    )
    _add_machine_argument(attach_parser)
    _add_session_argument(attach_parser)
    _add_hub_argument(attach_parser)
    exec_parser = verbs.add_parser(
        "exec",
        help="run one command and return its exit code",
        usage="nclient terminal exec <machine> [--tty] [--hub <name>] "
        "-- <command> ...",
    )
    _add_machine_argument(exec_parser)
    exec_parser.add_argument(
        "exec_command", nargs="*", metavar="<command>", help="the command, after --"
    )
    exec_parser.add_argument(
        "--tty",
        action="store_true",
        help="run it on a pseudo-terminal, for programs such as top and vim",
    )
    _add_hub_argument(exec_parser)
    for verb, description, on_help, off_help in (
        (
            "persist",
            "keep a session after its last window closes, or stop keeping it",
            "keep the session",
            "stop keeping it",
        ),
        (
            "share",
            "let other clients attach to a session, or stop letting them",
            "share the session",
            "stop sharing it; the others are cut off at once",
        ),
    ):
        verb_parser = verbs.add_parser(verb, help=description)
        _add_machine_argument(verb_parser)
        _add_session_argument(verb_parser)
        switch = verb_parser.add_mutually_exclusive_group(required=True)
        switch.add_argument("--on", dest="is_on", action="store_true", help=on_help)
        switch.add_argument("--off", dest="is_on", action="store_false", help=off_help)
        _add_hub_argument(verb_parser)
    stop_parser = verbs.add_parser("stop", help="end a session the machine keeps")
    _add_machine_argument(stop_parser)
    _add_session_argument(stop_parser)
    _add_hub_argument(stop_parser)
    return terminal_parser


def _add_machine_argument(parser) -> None:
    """Name the machine a terminal verb acts on, on one parser.

    Args:
        parser: The parser the argument belongs to.
    """
    parser.add_argument("machine", help="the machine, by name or id")


def _add_session_argument(parser) -> None:
    """Name the session a terminal verb acts on, on one parser.

    Args:
        parser: The parser the argument belongs to.
    """
    parser.add_argument(
        "session",
        metavar="session-id",
        help="the session's id, or its first characters as list prints them",
    )


def _run_terminal(arguments, terminal_parser, command) -> int:
    """Dispatch one ``nclient terminal`` verb.

    Args:
        arguments: The parsed arguments.
        terminal_parser: The terminal parser, for its help.
        command: The words after exec's ``--``; None without one.

    Returns:
        The verb's exit status.
    """
    verb = arguments.terminal_command
    if verb == "list":
        return terminal.main_list(hub=arguments.hub, is_json=arguments.json)
    if verb == "open":
        return terminal.main_open(
            arguments.machine,
            hub=arguments.hub,
            is_persistent=arguments.persistent,
            is_shared=arguments.shared,
        )
    if verb == "attach":
        return terminal.main_attach(
            arguments.machine, arguments.session, hub=arguments.hub
        )
    if verb == "exec":
        return terminal.main_exec(
            arguments.machine,
            list(arguments.exec_command) + list(command or []),
            hub=arguments.hub,
            is_tty=arguments.tty,
        )
    if verb == "persist":
        return terminal.main_persist(
            arguments.machine,
            arguments.session,
            is_on=arguments.is_on,
            hub=arguments.hub,
        )
    if verb == "share":
        return terminal.main_share(
            arguments.machine,
            arguments.session,
            is_on=arguments.is_on,
            hub=arguments.hub,
        )
    if verb == "stop":
        return terminal.main_stop(
            arguments.machine, arguments.session, hub=arguments.hub
        )
    terminal_parser.print_help()
    return 2


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
    list_parser = kinds.add_parser(
        "list", help="every published entry, by hub and then by kind"
    )
    _add_hub_argument(list_parser)

    web_parser = kinds.add_parser("web", help="published links")
    web_actions = web_parser.add_subparsers(dest="web_action", metavar="<action>")
    web_open = web_actions.add_parser("open", help="open one link in the browser")
    web_open.add_argument("ref", help="the entry's number in service list, or its id")
    _add_hub_argument(web_open)

    port_parser = kinds.add_parser("port", help="published ports")
    port_actions = port_parser.add_subparsers(dest="port_action", metavar="<action>")
    forward = port_actions.add_parser(
        "forward", help="relay one port to this machine's loopback"
    )
    forward.add_argument("ref", help="the entry's number in service list, or its id")
    forward.add_argument(
        "--local-port", type=int, default=0, help="the loopback port to prefer"
    )
    _add_hub_argument(forward)
    unforward = port_actions.add_parser("unforward", help="close that relay")
    unforward.add_argument("ref", help="the entry's number in service list, or its id")
    _add_hub_argument(unforward)

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
    _add_hub_argument(file_config)
    for verb, description in (
        ("mount", "mount a share again with its saved login"),
        ("unmount", "unmount a share; its saved login stays"),
    ):
        verb_parser = file_actions.add_parser(verb, help=description)
        verb_parser.add_argument(
            "ref", help="the entry's number in service list, or its id"
        )
        _add_hub_argument(verb_parser)

    ai_parser = kinds.add_parser("ai", help="the AI gateway service")
    ai_actions = ai_parser.add_subparsers(dest="ai_action", metavar="<action>")
    ai_show = ai_actions.add_parser("show", help="where this person's tools point")
    _add_hub_argument(ai_show)
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
        "--hub",
        default="",
        metavar="<name>",
        help="make this hub the exit first; omit to keep the exit as it is",
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
    _add_hub_argument(desktop_connect)

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
        return service.main_list(hub=arguments.hub)
    if kind == "web" and arguments.web_action == "open":
        return service.main_web_open(arguments.ref, hub=arguments.hub)
    if kind == "port" and arguments.port_action == "forward":
        return service.main_port(
            arguments.ref,
            is_enabled=True,
            local_port=arguments.local_port,
            hub=arguments.hub,
        )
    if kind == "port" and arguments.port_action == "unforward":
        return service.main_port(arguments.ref, is_enabled=False, hub=arguments.hub)
    if kind == "file" and arguments.file_action == "config":
        return service.main_file_config(
            arguments.ref,
            path=arguments.path,
            username=arguments.username,
            hub=arguments.hub,
        )
    if kind == "file" and arguments.file_action == "mount":
        return service.main_file_mount(arguments.ref, hub=arguments.hub)
    if kind == "file" and arguments.file_action == "unmount":
        return service.main_file_unmount(arguments.ref, hub=arguments.hub)
    if kind == "ai" and arguments.ai_action == "show":
        return service.main_ai_show(hub=arguments.hub)
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
            hub=arguments.hub,
        )
    if kind == "desktop" and arguments.desktop_action == "connect":
        return service.main_desktop_connect(arguments.ref, hub=arguments.hub)
    if kind in kind_parsers:
        kind_parsers[kind].print_help()
        return 2
    service_parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
