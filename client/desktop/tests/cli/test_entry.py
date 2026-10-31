"""``nclient``: the command tree, its help at every level, and who may run it.

Each verb reaches its command with what was typed; a bare machine after
``terminal`` is ``open``, and the words after ``--`` of ``terminal exec``
and ``ssh open`` are the command. ``--hub`` is taken before the group,
after it, or after the verb. Every level prints its help with ``-h`` in
the client's language and exits 0; a group with no verb prints its help
and exits 2, and a usage error prints the level's usage line and where its
help is. The levels of 0.5 are gone. Root is refused, and another
account's client holding the machine is named, for every command but
``gui`` and ``quit``.
"""

import pytest

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import entry, help_pages, wording


class FakeStream:
    """A stream that only remembers how it was reconfigured."""

    def __init__(self):
        self.reconfigured = None

    def reconfigure(self, *, errors, encoding=None):
        self.reconfigured = (encoding, errors)


@pytest.fixture
def person(monkeypatch):
    """A person's account, holding the machine, in English."""
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(wording, "other_holder", lambda: "")
    wording.fix_language("en")
    yield
    wording.fix_language("")


def run(monkeypatch, argv):
    monkeypatch.setattr(entry.sys, "argv", ["nclient"] + list(argv))
    return entry.main()


# (argv, module, function, args, kwargs)
DISPATCHED = [
    (["ssh", "list"], "ssh", "main_list", (), {"hub": ""}),
    (["ssh", "open", "lab@gpu"], "ssh", "main_open", ("lab@gpu", []), {"hub": ""}),
    (
        ["ssh", "open", "gpu", "--", "nvidia-smi", "-L"],
        "ssh",
        "main_open",
        ("gpu", ["nvidia-smi", "-L"]),
        {"hub": ""},
    ),
    (["ssh", "config", "show"], "ssh", "main_config_show", (), {}),
    (
        ["ssh", "config", "install"],
        "ssh",
        "main_config_install",
        (),
        {"is_installed": True},
    ),
    (
        ["ssh", "config", "uninstall"],
        "ssh",
        "main_config_install",
        (),
        {"is_installed": False},
    ),
    (["ssh", "proxy", "lab@gpu.nt"], "ssh", "main_proxy", ("lab@gpu.nt",), {"hub": ""}),
    (["hub", "list"], "hub", "main_list", (), {}),
    (
        ["hub", "join", "neutrino://enroll/x"],
        "hub",
        "main_join",
        ("neutrino://enroll/x",),
        {},
    ),
    (["hub", "join"], "hub", "main_join", ("",), {}),
    (["hub", "leave", "home"], "hub", "main_leave", ("home",), {"is_forced": False}),
    (["hub", "leave", "2", "--yes"], "hub", "main_leave", ("2",), {"is_forced": True}),
    (["hub", "open", "home"], "hub", "main_open", ("home",), {}),
    (["app", "list"], "app", "main_list", (), {"hub": ""}),
    (["app", "open", "gitea"], "app", "main_open", ("gitea",), {"hub": ""}),
    (["app", "stop", "gitea"], "app", "main_stop", ("gitea",), {"hub": ""}),
    (
        ["app", "set", "gitea", "--port", "web=8080", "--port", "ssh="],
        "app",
        "main_set",
        ("gitea", ["web=8080", "ssh="]),
        {"hub": ""},
    ),
    (["ai", "show"], "ai", "main_show", (), {"hub": ""}),
    (["ai", "set"], "ai", "main_set", (), {"hub": ""}),
    (["file", "list"], "file", "main_list", (), {"hub": ""}),
    (
        ["file", "mount", "gpu/alice"],
        "file",
        "main_mount",
        ("gpu/alice",),
        {"account": "", "path": "", "drive": "", "hub": ""},
    ),
    (
        ["file", "mount", "gpu", "--path", "/mnt/g"],
        "file",
        "main_mount",
        ("gpu",),
        {"account": "", "path": "/mnt/g", "drive": "", "hub": ""},
    ),
    (
        ["file", "mount", "gpu", "--drive", "Z:"],
        "file",
        "main_mount",
        ("gpu",),
        {"account": "", "path": "", "drive": "Z:", "hub": ""},
    ),
    (
        ["file", "mount", "gpu/lab", "--account", "bob"],
        "file",
        "main_mount",
        ("gpu/lab",),
        {"account": "bob", "path": "", "drive": "", "hub": ""},
    ),
    (
        ["file", "unmount", "gpu"],
        "file",
        "main_unmount",
        ("gpu",),
        {"account": "", "hub": ""},
    ),
    (
        ["file", "unmount", "gpu/lab", "--account", "bob"],
        "file",
        "main_unmount",
        ("gpu/lab",),
        {"account": "bob", "hub": ""},
    ),
    (["terminal", "list", "gpu"], "terminal", "main_list", ("gpu",), {"hub": ""}),
    (
        ["terminal", "open", "gpu", "--account", "lab"],
        "terminal",
        "main_open",
        ("gpu",),
        {"account": "lab", "hub": ""},
    ),
    (
        ["terminal", "gpu"],
        "terminal",
        "main_open",
        ("gpu",),
        {"account": "", "hub": ""},
    ),
    (
        ["terminal", "attach", "gpu", "3f2a"],
        "terminal",
        "main_attach",
        ("gpu", "3f2a"),
        {"hub": ""},
    ),
    (
        ["terminal", "exec", "gpu", "--tty", "--", "htop", "-d", "5"],
        "terminal",
        "main_exec",
        ("gpu", ["htop", "-d", "5"]),
        {"account": "", "hub": "", "is_tty": True},
    ),
    (
        ["terminal", "exec", "gpu", "--account", "ci", "--", "ls", "--", "-x"],
        "terminal",
        "main_exec",
        ("gpu", ["ls", "--", "-x"]),
        {"account": "ci", "hub": "", "is_tty": False},
    ),
    (
        ["terminal", "set", "gpu", "3f2a", "--persist", "on", "--share", "off"],
        "terminal",
        "main_set",
        ("gpu", "3f2a"),
        {"is_persistent": True, "is_shared": False, "hub": ""},
    ),
    (
        ["terminal", "set", "gpu", "3f2a", "--share", "on"],
        "terminal",
        "main_set",
        ("gpu", "3f2a"),
        {"is_persistent": None, "is_shared": True, "hub": ""},
    ),
    (
        ["terminal", "stop", "gpu", "3f2a"],
        "terminal",
        "main_stop",
        ("gpu", "3f2a"),
        {"hub": ""},
    ),
    (["rdp", "list"], "rdp", "main_list", (), {"hub": ""}),
    (["rdp", "connect", "gpu"], "rdp", "main_connect", ("gpu",), {"hub": ""}),
    (["settings", "show"], "settings", "main_show", (), {}),
    (
        ["settings", "set", "language", "zh-CN"],
        "settings",
        "main_set",
        ("language", "zh-CN"),
        {},
    ),
]


@pytest.mark.parametrize("argv, module, function, args, kwargs", DISPATCHED)
def test_each_verb_reaches_its_command(
    person, monkeypatch, argv, module, function, args, kwargs
):
    seen = []

    def record(*given_args, **given_kwargs):
        seen.append((given_args, given_kwargs))
        return 0

    monkeypatch.setattr(getattr(entry, module), function, record)

    assert run(monkeypatch, argv) == 0
    assert seen == [(args, kwargs)]


@pytest.mark.parametrize(
    "argv",
    [
        ["--hub", "office", "app", "open", "gitea"],
        ["app", "--hub", "office", "open", "gitea"],
        ["app", "open", "gitea", "--hub", "office"],
    ],
)
def test_the_hub_is_named_before_the_group_after_it_or_after_the_verb(
    person, monkeypatch, argv
):
    seen = []
    monkeypatch.setattr(
        entry.app, "main_open", lambda name, *, hub: seen.append((name, hub)) or 0
    )

    assert run(monkeypatch, argv) == 0
    assert seen == [("gitea", "office")]


def test_a_bare_machine_with_the_hub_named_first_is_open(person, monkeypatch):
    seen = []
    monkeypatch.setattr(
        entry.terminal,
        "main_open",
        lambda machine, *, account, hub: seen.append((machine, hub)) or 0,
    )

    assert run(monkeypatch, ["terminal", "--hub", "home", "gpu"]) == 0
    assert seen == [("gpu", "home")]


def test_the_gui_and_quit_reach_their_commands(person, monkeypatch):
    seen = []
    monkeypatch.setattr(
        entry.gui, "main", lambda *, is_hidden: seen.append(is_hidden) or 0
    )
    monkeypatch.setattr(
        entry.quit, "main", lambda *, is_upgrade: seen.append(("quit", is_upgrade)) or 0
    )

    assert run(monkeypatch, ["gui", "--hidden"]) == 0
    assert run(monkeypatch, ["quit"]) == 0
    assert run(monkeypatch, ["quit", "--upgrade"]) == 0
    assert seen == [True, ("quit", False), ("quit", True)]


def test_the_version_answers_any_caller(monkeypatch, capsys):
    with pytest.raises(SystemExit) as ended:
        run(monkeypatch, ["--version"])

    assert ended.value.code == 0
    assert CLIENT_VERSION in capsys.readouterr().out


@pytest.mark.parametrize("language, opening", [("en", "Usage: "), ("zh-CN", "用法：")])
@pytest.mark.parametrize("level", help_pages.levels())
def test_every_level_prints_its_help_in_the_clients_language(
    person, monkeypatch, capsys, level, language, opening
):
    wording.fix_language(language)

    with pytest.raises(SystemExit) as ended:
        run(monkeypatch, level.split() + ["-h"])

    assert ended.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith(opening + "nclient")
    assert out.strip() == help_pages.CLIENT_HELP[language][level].strip()


def test_every_level_of_the_tree_has_a_help_in_both_languages():
    tree = {""} | {
        group if verb is None else f"{group} {verb}"
        for group, verb in [(key[0], key[1]) for key in entry.DISPATCH]
    }
    groups = {key[0].split()[0] for key in entry.DISPATCH} | {
        "ssh config",
        "gui",
        "quit",
    }

    for level in tree | groups:
        assert level in help_pages.CLIENT_HELP["en"], level
        assert level in help_pages.CLIENT_HELP["zh-CN"], level
    assert set(help_pages.CLIENT_HELP["en"]) == set(help_pages.CLIENT_HELP["zh-CN"])


def test_each_help_says_what_it_does_under_its_usage_line():
    for language in ("en", "zh-CN"):
        for level, text in help_pages.CLIENT_HELP[language].items():
            lines = text.splitlines()
            assert len(lines) >= 3 and lines[1] == "" and lines[2], (language, level)


def test_the_chinese_help_is_the_help_pages_own_words():
    text = help_pages.CLIENT_HELP["zh-CN"]

    assert (
        text["file mount"].splitlines()[2] == "挂载一个共享。什么都不写就用默认位置："
    )
    assert (
        "  --tty        给命令一个终端：要交互的程序（htop、vim、带进度条的）用它；"
        in (text["terminal exec"])
    )
    assert "--hub <中枢>" in text[""]


@pytest.mark.parametrize(
    "group", ["ssh", "hub", "app", "ai", "file", "terminal", "rdp", "settings"]
)
def test_a_group_with_no_verb_prints_its_help(person, monkeypatch, capsys, group):
    assert run(monkeypatch, [group]) == 2

    assert (
        capsys.readouterr().out.strip() == help_pages.CLIENT_HELP["en"][group].strip()
    )


def test_ssh_config_with_no_verb_prints_its_help(person, monkeypatch, capsys):
    assert run(monkeypatch, ["ssh", "config"]) == 2

    assert (
        capsys.readouterr().out.strip()
        == help_pages.CLIENT_HELP["en"]["ssh config"].strip()
    )


def test_no_command_prints_the_help(monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "platform", "linux")

    assert run(monkeypatch, []) == 2

    assert capsys.readouterr().out.startswith("Usage: nclient <command>")


@pytest.mark.parametrize(
    "argv, level",
    [
        (["app", "open"], "app open"),
        (["terminal", "set", "gpu"], "terminal set"),
        (["terminal", "set", "gpu", "s", "--persist", "maybe"], "terminal set"),
        (["file", "mount", "gpu", "--path", "/x", "--drive", "Z:"], "file mount"),
        (["bogus"], ""),
    ],
)
def test_a_usage_error_prints_the_usage_line_and_where_the_help_is(
    person, monkeypatch, capsys, argv, level
):
    with pytest.raises(SystemExit) as ended:
        run(monkeypatch, argv)

    assert ended.value.code == 2
    err = capsys.readouterr().err.splitlines()
    assert err[0] == help_pages.CLIENT_HELP["en"][level].splitlines()[0]
    assert err[1] == f"see nclient {level} -h".replace("nclient  -h", "nclient -h")


@pytest.mark.parametrize(
    "argv",
    [["service", "list"], ["status"], ["join", "neutrino://enroll/x"], ["leave"]],
)
def test_the_levels_of_0_5_are_gone(person, monkeypatch, argv):
    with pytest.raises(SystemExit) as ended:
        run(monkeypatch, argv)

    assert ended.value.code == 2


@pytest.mark.parametrize(
    "argv", [["hub", "list"], ["gui"], ["quit"], ["ssh", "proxy", "gpu"]]
)
def test_root_is_refused_with_a_typed_line(monkeypatch, capsys, argv):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0, raising=False)
    wording.fix_language("en")

    assert run(monkeypatch, argv) == 2

    assert wording.word_code("root_refused") in capsys.readouterr().err
    wording.fix_language("")


@pytest.mark.parametrize(
    "argv",
    [["hub", "list"], ["app", "open", "x"], ["terminal", "box"], ["ssh", "list"]],
)
def test_another_accounts_client_holding_the_machine_is_named(
    monkeypatch, capsys, argv
):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1001, raising=False)
    monkeypatch.setattr(
        wording, "ask_hold", lambda verb: {"holder": "lab", "is_holder": False}
    )
    wording.fix_language("en")

    assert run(monkeypatch, argv) == 1

    err = capsys.readouterr().err
    assert err.strip() == wording.word_code("client_held", {"account": "lab"})
    assert err.count("\n") == 1
    wording.fix_language("")


def test_gui_and_quit_run_whoever_holds_the_machine(monkeypatch):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1001, raising=False)
    monkeypatch.setattr(
        wording, "ask_hold", lambda verb: {"holder": "lab", "is_holder": False}
    )
    ran = []
    monkeypatch.setattr(entry.gui, "main", lambda *, is_hidden: ran.append("gui") or 0)
    monkeypatch.setattr(
        entry.quit, "main", lambda *, is_upgrade: ran.append("quit") or 0
    )

    assert run(monkeypatch, ["gui"]) == 0
    assert run(monkeypatch, ["quit"]) == 0
    assert ran == ["gui", "quit"]


def test_the_windows_console_is_switched_to_utf8(monkeypatch):
    out, err = FakeStream(), FakeStream()
    monkeypatch.setattr(entry.os, "name", "nt")
    monkeypatch.setattr(entry.sys, "stdout", out)
    monkeypatch.setattr(entry.sys, "stderr", err)

    entry._use_utf8_console()

    assert out.reconfigured == ("utf-8", "replace")
    assert err.reconfigured == ("utf-8", "replace")


def test_other_platforms_keep_the_encoding_and_replace_what_it_cannot_print(
    monkeypatch,
):
    """A person's list under the POSIX locale holds a middle dot."""
    out = FakeStream()
    monkeypatch.setattr(entry.os, "name", "posix")
    monkeypatch.setattr(entry.sys, "stdout", out)

    entry._use_utf8_console()

    assert out.reconfigured == (None, "replace")


def test_a_click_on_the_app_icon_opens_the_window(monkeypatch):
    opened = []
    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(
        entry.sys,
        "argv",
        ["/Applications/Neutrino Client.app/Contents/MacOS/nclient", "-psn_0_12345"],
    )
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        entry.gui, "main", lambda *, is_hidden: opened.append(is_hidden) or 0
    )

    assert entry.main() == 0
    assert opened == [False]


# Each command a person types, and its exit status against a client that
# runs and has joined no hub.
UNBOUND = [
    (["ssh", "list"], 0),
    (["ssh", "open", "gpu"], 1),
    (["ssh", "proxy", "gpu"], 1),
    (["hub", "list"], 0),
    (["hub", "leave", "home", "--yes"], 1),
    (["hub", "open", "home"], 1),
    (["app", "list"], 0),
    (["app", "open", "gitea"], 1),
    (["app", "stop", "gitea"], 1),
    (["app", "set", "gitea", "--port", "web=8080"], 1),
    (["ai", "show"], 0),
    (["ai", "set"], 1),
    (["file", "list"], 0),
    (["file", "mount", "gpu"], 1),
    (["file", "unmount", "gpu"], 1),
    (["terminal", "list", "gpu"], 2),
    (["terminal", "open", "gpu"], 2),
    (["terminal", "attach", "gpu", "3f"], 2),
    (["terminal", "exec", "gpu", "--", "ls"], 126),
    (["terminal", "set", "gpu", "3f", "--share", "on"], 2),
    (["terminal", "stop", "gpu", "3f"], 2),
    (["rdp", "list"], 0),
    (["rdp", "connect", "gpu"], 1),
    (["settings", "show"], 0),
]


@pytest.mark.parametrize("argv, status", UNBOUND)
def test_every_command_against_a_client_bound_to_no_hub(
    person, running, monkeypatch, capsys, argv, status
):
    from tests.cli.conftest import unbound_document

    running.state = unbound_document()

    assert run(monkeypatch, argv) == status
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("argv, status", UNBOUND)
def test_every_command_with_no_running_client_says_so(
    person, running, monkeypatch, capsys, argv, status
):
    running.is_running = False

    expected = 125 if argv[:2] == ["terminal", "exec"] else 1
    assert run(monkeypatch, argv) == expected
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")
