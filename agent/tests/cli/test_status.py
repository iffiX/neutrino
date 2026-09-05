"""``nagent status``: what the operator reads must never lie about the box."""

from neutrino_agent.cli import status as status_cli
from tests.conftest import bind


def test_status_words_a_version_refusal_distinctly(config_path, monkeypatch, capsys):
    bind(config_path)

    class StuckAgent:
        def __init__(self, *, log):
            del log

        def run_once(self):
            return 5

        def last_error(self):
            return {
                "code": "agent_newer_than_hub",
                "params": {"hub_version": "0.1.0", "agent_version": "0.2.0"},
            }

    monkeypatch.setattr(status_cli, "Agent", StuckAgent)
    monkeypatch.setattr(status_cli, "service_state", lambda: "running")
    monkeypatch.setattr(status_cli, "_local_state", lambda: None)

    assert status_cli.main() == 1
    out = capsys.readouterr().out
    assert "newer than the hub" in out
    assert "unbinds by itself" in out
    assert "fresh link" in out
