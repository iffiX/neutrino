"""``nclient`` entry: the verb tree, the version, and root refused.

The client runs as a person; root is refused with a typed line before any
command runs. The Windows console is switched to UTF-8.
"""

import pytest

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import entry, wording


class FakeStream:
    """A stream that only remembers how it was reconfigured."""

    def __init__(self):
        self.reconfigured = None

    def reconfigure(self, *, encoding, errors):
        self.reconfigured = (encoding, errors)


def test_the_version_answers_any_caller(monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "argv", ["nclient", "--version"])

    with pytest.raises(SystemExit) as refusal:
        entry.main()

    assert refusal.value.code == 0
    assert CLIENT_VERSION in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["connect", "neutrino://enroll/x"],
        ["disconnect"],
        ["status"],
        ["gui"],
        ["quit"],
        ["service", "list"],
    ],
)
def test_root_is_refused_with_a_typed_line(monkeypatch, capsys, argv):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nclient"] + argv)

    assert entry.main() == 2

    assert wording.word_code("root_refused") in capsys.readouterr().err


def test_no_command_prints_the_help(monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "argv", ["nclient"])

    assert entry.main() == 2

    assert "connect" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv, target, expected",
    [
        (["connect", "L", "--yes"], "connect", ("L", {"is_forced": True})),
        (["disconnect"], "disconnect", ((), {})),
        (["status"], "status", ((), {})),
        (["gui", "--hidden"], "gui", ((), {"is_hidden": True})),
        (["quit"], "quit", ((), {})),
    ],
)
def test_each_verb_reaches_its_command(monkeypatch, argv, target, expected):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nclient"] + argv)
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(getattr(entry, target), "main", record)

    assert entry.main() == 0

    args, kwargs = calls[0]
    if target == "connect":
        assert (args[0], kwargs) == expected
    else:
        assert (args, kwargs) == expected


@pytest.mark.parametrize(
    "argv, function, expected",
    [
        (["service", "list"], "main_list", ((), {})),
        (["service", "web", "open", "1"], "main_web_open", (("1",), {})),
        (
            ["service", "port", "forward", "1", "--local-port", "9000"],
            "main_port",
            (("1",), {"is_enabled": True, "local_port": 9000}),
        ),
        (
            ["service", "port", "unforward", "svc_tcp"],
            "main_port",
            (("svc_tcp",), {"is_enabled": False}),
        ),
        (
            ["service", "file", "config", "1", "--path", "/p", "--username", "u"],
            "main_file_config",
            (("1",), {"path": "/p", "username": "u"}),
        ),
        (["service", "file", "mount", "1"], "main_file_mount", (("1",), {})),
        (["service", "file", "unmount", "1"], "main_file_unmount", (("1",), {})),
        (["service", "ai", "show"], "main_ai_show", ((), {})),
        (["service", "desktop", "connect", "2"], "main_desktop_connect", (("2",), {})),
    ],
)
def test_each_service_verb_reaches_its_function(monkeypatch, argv, function, expected):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nclient"] + argv)
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(entry.service, function, record)

    assert entry.main() == 0
    assert calls == [expected]


def test_ai_apply_names_the_provider_and_the_knobs(monkeypatch):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        entry.sys,
        "argv",
        ["nclient", "service", "ai", "apply", "hub", "--claude-default", "m2"],
    )
    calls = []

    def record(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(entry.service, "main_ai_apply", record)

    assert entry.main() == 0
    assert calls[0]["is_enabled"] is True
    assert calls[0]["claude_default"] == "m2"
    assert calls[0]["codex_effort"] is None

    monkeypatch.setattr(entry.sys, "argv", ["nclient", "service", "ai", "apply", "off"])
    entry.main()
    assert calls[1]["is_enabled"] is False


def test_the_removed_verbs_are_gone(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    for argv in (
        ["run"],
        ["module", "list"],
        ["operation"],
        ["service", "rdp", "share"],
    ):
        monkeypatch.setattr(entry.sys, "argv", ["nclient"] + argv)
        with pytest.raises(SystemExit) as refusal:
            entry.main()
        assert refusal.value.code == 2
    assert "--account" not in capsys.readouterr().err


def test_a_kind_without_an_action_prints_its_help(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nclient", "service", "web"])

    assert entry.main() == 2
    assert "open" in capsys.readouterr().out


def test_the_windows_console_is_switched_to_utf8(monkeypatch):
    out, err = FakeStream(), FakeStream()
    monkeypatch.setattr(entry.os, "name", "nt")
    monkeypatch.setattr(entry.sys, "stdout", out)
    monkeypatch.setattr(entry.sys, "stderr", err)

    entry._use_utf8_console()

    assert out.reconfigured == ("utf-8", "replace")
    assert err.reconfigured == ("utf-8", "replace")


def test_other_platforms_leave_the_console_alone(monkeypatch):
    out = FakeStream()
    monkeypatch.setattr(entry.os, "name", "posix")
    monkeypatch.setattr(entry.sys, "stdout", out)

    entry._use_utf8_console()

    assert out.reconfigured is None
