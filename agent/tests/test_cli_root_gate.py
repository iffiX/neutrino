"""Which nagent commands demand root, and how the refusal reads."""

import neutrino_agent.cli.entry as entry


def test_the_gate_covers_exactly_what_changes_the_machine():
    assert sorted(entry.ROOT_COMMANDS) == ["connect", "disconnect", "run"]


def test_an_unprivileged_disconnect_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "disconnect"])

    assert entry.main() == 2
    output = capsys.readouterr().err
    assert "sudo nagent disconnect" in output


def test_status_is_never_gated():
    assert "status" not in entry.ROOT_COMMANDS
