"""The ``nclient`` command: one command for each button of the window.

Most people never see this: the client installs with a desktop entry that
runs ``nclient gui``, which is the resident and its window. The groups
follow the window's pages, with the program itself and ``ssh`` above them:

    nclient gui | quit
    nclient ssh list | open | config show|install|uninstall | proxy
    nclient hub list | join | leave | open
    nclient app list | open | stop | set
    nclient ai show | set
    nclient file list | mount | unmount
    nclient terminal list | open | attach | exec | set | stop
    nclient rdp list | connect
    nclient settings show | set

Every level prints its help with ``-h``, in the client's language. The
client runs as a person and never as root. The exceptions are ``nclient
easytier-daemon`` and ``nclient files-daemon``, the services the package
installs, which no person runs.
"""

import argparse
import os
import sys

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import (
    ai,
    app,
    easytier_daemon,
    file,
    files_daemon,
    gui,
    help_pages,
    hub,
    quit,
    rdp,
    settings,
    ssh,
    terminal,
    wording,
)
from neutrino_client.constants import (
    CLIENT_EASYTIER_DAEMON_VERB,
    CLIENT_FILES_DAEMON_VERB,
)

# What separates a command's own arguments from the command it runs.
COMMAND_SEPARATOR = "--"
# The levels whose words after ``--`` are a command to run.
COMMAND_LEVELS = (("terminal", "exec"), ("ssh", "open"))
# The options of ``nclient terminal``'s verbs that take a value.
TERMINAL_VALUE_OPTIONS = ("--hub", "--account", "--persist", "--share")
# The values a session switch takes.
SWITCH_VALUES = ("on", "off")
# The commands that run whoever holds the machine.
UNHELD_COMMANDS = ("gui", "quit")
# What Launch Services passes a program it opens: a process serial number on
# older macOS, nothing on newer ones.
LAUNCH_SERVICES_ARGUMENT_PREFIX = "-psn_"


class CliHelpAction(argparse.Action):
    """``-h``: print one level's help in the client's language, and exit 0."""

    def __init__(self, option_strings, dest, level: str = "", **kwargs):
        """
        Args:
            option_strings: ``-h`` and ``--help``.
            dest: The name argparse gives the action.
            level: The words of the command the help is for.
            **kwargs: What argparse passes on.
        """
        super().__init__(option_strings, dest, nargs=0, **kwargs)
        self.level = level

    def __call__(self, parser, namespace, values, option_string=None):
        """Print the help and end the process.

        Args:
            parser: The parser the option was given to.
            namespace: What was parsed so far.
            values: Nothing.
            option_string: ``-h`` or ``--help``.
        """
        print(wording.console_text(help_pages.page(self.level)))
        parser.exit(0)


class CliArgumentParser(argparse.ArgumentParser):
    """A parser whose help and whose usage errors are the client's own words."""

    def __init__(self, *args, level: str = "", **kwargs):
        """
        Args:
            *args: What argparse takes.
            level: The words of the command this parser reads.
            **kwargs: What argparse takes.
        """
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self.level = level
        self.add_argument("-h", "--help", action=CliHelpAction, level=level)

    def print_help(self, file=None):
        """Print this level's help in the client's language.

        Args:
            file: Where to print; None is stdout.
        """
        print(wording.console_text(help_pages.page(self.level)), file=file)

    def error(self, message):
        """Print this level's usage line and where its help is, and exit 2.

        Args:
            message: argparse's own words, which are not printed.
        """
        command = f"nclient {self.level}".strip()
        wording.say(help_pages.page(self.level).splitlines()[0], is_error=True)
        wording.say(wording.line("see_help", command=command), is_error=True)
        self.exit(2)


def main() -> int:
    """Dispatch to a command.

    Returns:
        The command's exit status.
    """
    _use_utf8_console()
    parser, levels = _parser()
    argv, command = _split_argv(_argv_without_launch_services())
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
        wording.refuse("root_refused")
        return 2
    if arguments.command not in UNHELD_COMMANDS:
        holder = wording.other_holder()
        if holder:
            wording.refuse("client_held", {"account": holder})
            return 1
    hub_name = (
        getattr(arguments, "hub", "")
        or getattr(arguments, "group_hub", "")
        or arguments.top_hub
    )
    if arguments.command == "gui":
        return gui.main(is_hidden=arguments.hidden)
    if arguments.command == "quit":
        return quit.main(is_upgrade=arguments.upgrade)
    verb = getattr(arguments, "verb", None)
    if not verb:
        levels[arguments.command].print_help()
        return 2
    run = DISPATCH.get((arguments.command, verb))
    if arguments.command == "ssh" and verb == "config":
        run = DISPATCH.get(("ssh config", arguments.config_verb))
        if run is None:
            levels["ssh config"].print_help()
            return 2
    return run(arguments, hub_name, command or [])


def _parser():
    """The whole ``nclient`` tree.

    Returns:
        ``(parser, levels)``: the top parser, and each group's parser by its
        words, for its help on a missing verb.
    """
    parser = CliArgumentParser(prog="nclient", level="")
    parser.add_argument("--version", action="version", version=CLIENT_VERSION)
    parser.add_argument("--hub", dest="top_hub", default="", metavar="<hub>")
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    levels = {}
    gui_parser = commands.add_parser("gui", level="gui")
    gui_parser.add_argument("--hidden", action="store_true")
    quit_parser = commands.add_parser("quit", level="quit")
    quit_parser.add_argument("--upgrade", action="store_true")

    ssh_parser = _group(commands, levels, "ssh")
    verbs = ssh_parser.add_subparsers(dest="verb")
    _leaf(verbs, "ssh", "list")
    _leaf(verbs, "ssh", "open").add_argument("target")
    config_parser = _leaf(verbs, "ssh", "config", has_hub=False)
    levels["ssh config"] = config_parser
    config_verbs = config_parser.add_subparsers(dest="config_verb")
    for config_verb in ("show", "install", "uninstall"):
        _leaf(config_verbs, "ssh config", config_verb, has_hub=False)
    _leaf(verbs, "ssh", "proxy").add_argument("target")

    hub_parser = _group(commands, levels, "hub")
    verbs = hub_parser.add_subparsers(dest="verb")
    _leaf(verbs, "hub", "list", has_hub=False)
    _leaf(verbs, "hub", "join", has_hub=False).add_argument(
        "link", nargs="?", default=""
    )
    leave_parser = _leaf(verbs, "hub", "leave", has_hub=False)
    leave_parser.add_argument("hub_name")
    leave_parser.add_argument("--yes", action="store_true")
    _leaf(verbs, "hub", "open", has_hub=False).add_argument("hub_name")

    app_parser = _group(commands, levels, "app")
    verbs = app_parser.add_subparsers(dest="verb")
    _leaf(verbs, "app", "list")
    _leaf(verbs, "app", "use").add_argument("app")
    _leaf(verbs, "app", "open").add_argument("app")
    _leaf(verbs, "app", "stop").add_argument("app")
    set_parser = _leaf(verbs, "app", "set")
    set_parser.add_argument("app")
    set_parser.add_argument("--port", action="append", default=[])

    ai_parser = _group(commands, levels, "ai")
    verbs = ai_parser.add_subparsers(dest="verb")
    _leaf(verbs, "ai", "show")
    _leaf(verbs, "ai", "set")

    file_parser = _group(commands, levels, "file")
    verbs = file_parser.add_subparsers(dest="verb")
    _leaf(verbs, "file", "list")
    mount_parser = _leaf(verbs, "file", "mount")
    mount_parser.add_argument("share")
    mount_parser.add_argument("--account", default="")
    place = mount_parser.add_mutually_exclusive_group()
    place.add_argument("--path", default="")
    place.add_argument("--drive", default="")
    unmount_parser = _leaf(verbs, "file", "unmount")
    unmount_parser.add_argument("share")
    unmount_parser.add_argument("--account", default="")

    terminal_parser = _group(commands, levels, "terminal")
    verbs = terminal_parser.add_subparsers(dest="verb")
    _leaf(verbs, "terminal", "list").add_argument("machine")
    open_parser = _leaf(verbs, "terminal", "open")
    open_parser.add_argument("machine")
    open_parser.add_argument("--account", default="")
    attach_parser = _leaf(verbs, "terminal", "attach")
    attach_parser.add_argument("machine")
    attach_parser.add_argument("session")
    exec_parser = _leaf(verbs, "terminal", "exec")
    exec_parser.add_argument("machine")
    exec_parser.add_argument("exec_command", nargs="*")
    exec_parser.add_argument("--account", default="")
    exec_parser.add_argument("--tty", action="store_true")
    session_set = _leaf(verbs, "terminal", "set")
    session_set.add_argument("machine")
    session_set.add_argument("session")
    session_set.add_argument("--persist", choices=SWITCH_VALUES, default=None)
    session_set.add_argument("--share", choices=SWITCH_VALUES, default=None)
    stop_parser = _leaf(verbs, "terminal", "stop")
    stop_parser.add_argument("machine")
    stop_parser.add_argument("session")

    rdp_parser = _group(commands, levels, "rdp")
    verbs = rdp_parser.add_subparsers(dest="verb")
    _leaf(verbs, "rdp", "list")
    _leaf(verbs, "rdp", "connect").add_argument("machine")

    settings_parser = _group(commands, levels, "settings")
    verbs = settings_parser.add_subparsers(dest="verb")
    _leaf(verbs, "settings", "show", has_hub=False)
    settings_set = _leaf(verbs, "settings", "set", has_hub=False)
    settings_set.add_argument("name")
    settings_set.add_argument("value")

    daemon_parser = commands.add_parser(CLIENT_EASYTIER_DAEMON_VERB, level="")
    daemon_parser.add_argument("--service", action="store_true")
    files_daemon_parser = commands.add_parser(CLIENT_FILES_DAEMON_VERB, level="")
    files_daemon_parser.add_argument("--service", action="store_true")
    return parser, levels


def _group(commands, levels: dict, name: str):
    """One group's parser, kept by its name for its help."""
    group = commands.add_parser(name, level=name)
    group.add_argument("--hub", dest="group_hub", default="")
    levels[name] = group
    return group


def _leaf(verbs, group: str, verb: str, *, has_hub: bool = True):
    """One verb's parser, with ``--hub`` where the verb names a hub's things."""
    leaf = verbs.add_parser(verb, level=f"{group} {verb}")
    if has_hub:
        leaf.add_argument("--hub", default="")
    return leaf


def _run_ssh_list(arguments, hub_name: str, command: list) -> int:
    return ssh.main_list(hub=hub_name)


def _run_ssh_open(arguments, hub_name: str, command: list) -> int:
    return ssh.main_open(arguments.target, command, hub=hub_name)


def _run_ssh_proxy(arguments, hub_name: str, command: list) -> int:
    return ssh.main_proxy(arguments.target, hub=hub_name)


def _run_ssh_config_show(arguments, hub_name: str, command: list) -> int:
    return ssh.main_config_show()


def _run_ssh_config_install(arguments, hub_name: str, command: list) -> int:
    return ssh.main_config_install(is_installed=True)


def _run_ssh_config_uninstall(arguments, hub_name: str, command: list) -> int:
    return ssh.main_config_install(is_installed=False)


def _run_hub_list(arguments, hub_name: str, command: list) -> int:
    return hub.main_list()


def _run_hub_join(arguments, hub_name: str, command: list) -> int:
    return hub.main_join(arguments.link)


def _run_hub_leave(arguments, hub_name: str, command: list) -> int:
    return hub.main_leave(arguments.hub_name, is_forced=arguments.yes)


def _run_hub_open(arguments, hub_name: str, command: list) -> int:
    return hub.main_open(arguments.hub_name)


def _run_app_list(arguments, hub_name: str, command: list) -> int:
    return app.main_list(hub=hub_name)


def _run_app_use(arguments, hub_name: str, command: list) -> int:
    return app.main_use(arguments.app, hub=hub_name)


def _run_app_open(arguments, hub_name: str, command: list) -> int:
    return app.main_open(arguments.app, hub=hub_name)


def _run_app_stop(arguments, hub_name: str, command: list) -> int:
    return app.main_stop(arguments.app, hub=hub_name)


def _run_app_set(arguments, hub_name: str, command: list) -> int:
    return app.main_set(arguments.app, list(arguments.port), hub=hub_name)


def _run_ai_show(arguments, hub_name: str, command: list) -> int:
    return ai.main_show(hub=hub_name)


def _run_ai_set(arguments, hub_name: str, command: list) -> int:
    return ai.main_set(hub=hub_name)


def _run_file_list(arguments, hub_name: str, command: list) -> int:
    return file.main_list(hub=hub_name)


def _run_file_mount(arguments, hub_name: str, command: list) -> int:
    return file.main_mount(
        arguments.share,
        account=arguments.account,
        path=arguments.path,
        drive=arguments.drive,
        hub=hub_name,
    )


def _run_file_unmount(arguments, hub_name: str, command: list) -> int:
    return file.main_unmount(arguments.share, account=arguments.account, hub=hub_name)


def _run_terminal_list(arguments, hub_name: str, command: list) -> int:
    return terminal.main_list(arguments.machine, hub=hub_name)


def _run_terminal_open(arguments, hub_name: str, command: list) -> int:
    return terminal.main_open(
        arguments.machine, account=arguments.account, hub=hub_name
    )


def _run_terminal_attach(arguments, hub_name: str, command: list) -> int:
    return terminal.main_attach(arguments.machine, arguments.session, hub=hub_name)


def _run_terminal_exec(arguments, hub_name: str, command: list) -> int:
    return terminal.main_exec(
        arguments.machine,
        list(arguments.exec_command) + list(command),
        account=arguments.account,
        hub=hub_name,
        is_tty=arguments.tty,
    )


def _run_terminal_set(arguments, hub_name: str, command: list) -> int:
    return terminal.main_set(
        arguments.machine,
        arguments.session,
        is_persistent=_switch(arguments.persist),
        is_shared=_switch(arguments.share),
        hub=hub_name,
    )


def _run_terminal_stop(arguments, hub_name: str, command: list) -> int:
    return terminal.main_stop(arguments.machine, arguments.session, hub=hub_name)


def _run_rdp_list(arguments, hub_name: str, command: list) -> int:
    return rdp.main_list(hub=hub_name)


def _run_rdp_connect(arguments, hub_name: str, command: list) -> int:
    return rdp.main_connect(arguments.machine, hub=hub_name)


def _run_settings_show(arguments, hub_name: str, command: list) -> int:
    return settings.main_show()


def _run_settings_set(arguments, hub_name: str, command: list) -> int:
    return settings.main_set(arguments.name, arguments.value)


# Each verb's runner, by its group and its verb.
DISPATCH = {
    ("ssh", "list"): _run_ssh_list,
    ("ssh", "open"): _run_ssh_open,
    ("ssh", "proxy"): _run_ssh_proxy,
    ("ssh config", "show"): _run_ssh_config_show,
    ("ssh config", "install"): _run_ssh_config_install,
    ("ssh config", "uninstall"): _run_ssh_config_uninstall,
    ("hub", "list"): _run_hub_list,
    ("hub", "join"): _run_hub_join,
    ("hub", "leave"): _run_hub_leave,
    ("hub", "open"): _run_hub_open,
    ("app", "list"): _run_app_list,
    ("app", "use"): _run_app_use,
    ("app", "open"): _run_app_open,
    ("app", "stop"): _run_app_stop,
    ("app", "set"): _run_app_set,
    ("ai", "show"): _run_ai_show,
    ("ai", "set"): _run_ai_set,
    ("file", "list"): _run_file_list,
    ("file", "mount"): _run_file_mount,
    ("file", "unmount"): _run_file_unmount,
    ("terminal", "list"): _run_terminal_list,
    ("terminal", "open"): _run_terminal_open,
    ("terminal", "attach"): _run_terminal_attach,
    ("terminal", "exec"): _run_terminal_exec,
    ("terminal", "set"): _run_terminal_set,
    ("terminal", "stop"): _run_terminal_stop,
    ("rdp", "list"): _run_rdp_list,
    ("rdp", "connect"): _run_rdp_connect,
    ("settings", "show"): _run_settings_show,
    ("settings", "set"): _run_settings_set,
}


def _switch(value: "str | None") -> "bool | None":
    """``on`` as True, ``off`` as False, nothing as None."""
    if value is None:
        return None
    return value == "on"


def _split_argv(argv: list) -> tuple:
    """The arguments with ``open`` for a bare machine, and a command cut off.

    Args:
        argv: The arguments as given.

    Returns:
        ``(argv, command)``: ``terminal <machine>`` read as ``terminal open
        <machine>``, and the words after ``--`` of ``terminal exec`` and
        ``ssh open`` cut off as the command; ``command`` is None without one.
    """
    position = _first_word(argv)
    if position is None:
        return argv, None
    group = argv[position]
    rest = list(argv[position + 1 :])
    head = list(argv[: position + 1])
    verb_position = _first_word(rest)
    if group == "terminal" and verb_position is not None:
        if rest[verb_position] not in terminal.TERMINAL_VERBS:
            rest.insert(verb_position, terminal.TERMINAL_DEFAULT_VERB)
    if verb_position is None:
        return head + rest, None
    if (group, rest[verb_position]) in COMMAND_LEVELS and COMMAND_SEPARATOR in rest:
        cut = rest.index(COMMAND_SEPARATOR)
        return head + rest[:cut], rest[cut + 1 :]
    return head + rest, None


def _first_word(words: list) -> "int | None":
    """Where the first word that is not an option is, None when there is none."""
    position = 0
    while position < len(words):
        word = words[position]
        if word == COMMAND_SEPARATOR:
            return None
        if word in TERMINAL_VALUE_OPTIONS:
            position += 2
            continue
        if word.startswith("-"):
            position += 1
            continue
        return position
    return None


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

    Another system keeps each stream's encoding and replaces what it cannot
    encode, which under the POSIX locale is every character past ASCII. A
    stream that cannot be reconfigured is left as is.
    """
    settings = {"errors": "replace"}
    if os.name == "nt":
        settings["encoding"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(**settings)
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    sys.exit(main())
