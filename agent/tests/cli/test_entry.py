"""``nagent`` entry: the verb set, and the root gate over all of it.

Everything the agent does is root's to do, and the control socket every
verb asks through is root's to open, so the gate covers every command but
``--version``.
"""

import pytest

import neutrino_agent.cli.entry as entry
from neutrino_agent import AGENT_VERSION


def test_the_gate_covers_every_verb():
    assert sorted(entry.ROOT_COMMANDS) == [
        "connect",
        "disconnect",
        "rdp",
        "run",
        "status",
        "sync",
    ]


@pytest.mark.parametrize(
    "argv, reason",
    [
        (["nagent", "status"], "it asks the agent over its root-only control socket"),
        (["nagent", "connect", "neutrino://enroll/x"], "it writes the binding"),
        (["nagent", "disconnect"], "it removes the binding"),
        (["nagent", "rdp", "start"], "it configures this machine's desktop share"),
        (["nagent", "run"], "the agent manages this machine"),
        (["nagent", "sync"], "it asks the agent over its root-only control socket"),
    ],
)
def test_an_unprivileged_caller_is_refused_with_the_command(
    monkeypatch, capsys, argv, reason
):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", argv)

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert f"nagent {argv[1]} needs root" in err
    assert reason in err
    assert f"sudo nagent {' '.join(argv[1:])}" in err


def test_the_version_answers_any_account(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "--version"])

    with pytest.raises(SystemExit) as done:
        entry.main()

    assert done.value.code == 0
    assert capsys.readouterr().out.strip() == AGENT_VERSION


def test_no_command_prints_the_help(monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "argv", ["nagent"])

    assert entry.main() == 2
    assert "usage: nagent" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["nagent", "rdp", "start"], ("start", "")),
        (["nagent", "rdp", "start", "--user", "alice"], ("start", "alice")),
        (["nagent", "rdp", "stop"], ("stop", "")),
    ],
)
def test_the_rdp_verbs_reach_their_own_command(monkeypatch, argv, expected):
    called = {}
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", argv)
    monkeypatch.setattr(
        entry.rdp, "main_start", lambda *, user: called.update(start=user) or 0
    )
    monkeypatch.setattr(entry.rdp, "main_stop", lambda: called.update(stop="") or 0)

    assert entry.main() == 0
    assert called == {expected[0]: expected[1]}


def test_rdp_with_no_action_prints_the_help(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "rdp"])

    assert entry.main() == 2
    assert "usage: nagent rdp" in capsys.readouterr().out


def test_sync_reaches_its_own_command(monkeypatch):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "sync"])
    monkeypatch.setattr(entry.sync, "main", lambda: 0)

    assert entry.main() == 0


def test_the_verbs_that_were_pruned_are_gone(monkeypatch, capsys):
    for verb in ("gui", "module", "operation", "service"):
        monkeypatch.setattr(entry.sys, "argv", ["nagent", verb])

        with pytest.raises(SystemExit) as refused:
            entry.main()

        assert refused.value.code == 2
        assert "invalid choice" in capsys.readouterr().err
