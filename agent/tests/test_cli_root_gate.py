"""Which nagent commands demand root, and how the refusal reads."""

import neutrino_agent.cli as cli


def test_the_gate_covers_exactly_what_changes_the_machine():
    assert sorted(cli.ROOT_COMMANDS) == ["connect", "disconnect", "run"]


def test_an_unprivileged_disconnect_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(cli.sys, "argv", ["nagent", "disconnect"])

    assert cli.main() == 2
    output = capsys.readouterr().err
    assert "sudo nagent disconnect" in output


def test_status_is_never_gated():
    assert "status" not in cli.ROOT_COMMANDS
