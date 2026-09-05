"""``nagent disconnect``: leaving a hub, refused plainly without root."""

import neutrino_agent.cli.entry as entry


def test_an_unprivileged_disconnect_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "disconnect"])

    assert entry.main() == 2
    output = capsys.readouterr().err
    assert "sudo nagent disconnect" in output
