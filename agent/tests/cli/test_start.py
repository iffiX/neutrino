"""``nagent start``: the agent's service started through each platform's
service manager, asked about first, and refused plainly without root.

The walk runs once per service manager: systemd, the Windows service control
manager and launchd, each faked by the block's ``service_manager``.
"""

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.start as start_cli
from tests.conftest import (
    FakeLaunchd,
    FakeServiceControlManager,
    FakeSystemd,
)

# The command each manager is asked to start the service with.
START_COMMANDS = {
    FakeSystemd: ["systemctl", "enable", "--now", "neutrino_agent.service"],
    FakeServiceControlManager: ["sc", "start", "neutrino_agent"],
    FakeLaunchd: ["launchctl", "kickstart", "system/com.neutrino.agent"],
}


def answer(reply: str):
    """A terminal whose person types ``reply`` to every question."""

    def ask(question: str) -> str:
        return reply

    return ask


def test_a_yes_starts_the_service(service_manager, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", answer("y"))

    assert start_cli.main(is_forced=False) == 0

    assert START_COMMANDS[type(service_manager)] in service_manager.calls
    assert service_manager.is_running
    assert "service    running" in capsys.readouterr().out


def test_yes_on_the_command_line_skips_the_question(service_manager, monkeypatch):
    monkeypatch.setattr("builtins.input", answer("n"))

    assert start_cli.main(is_forced=True) == 0

    assert service_manager.is_running


def test_a_no_changes_nothing(service_manager, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", answer(""))

    assert start_cli.main(is_forced=False) == 1

    assert START_COMMANDS[type(service_manager)] not in service_manager.calls
    assert not service_manager.is_running
    assert "nothing changed" in capsys.readouterr().out


def test_a_running_service_is_left_alone_without_a_question(
    service_manager, monkeypatch, capsys
):
    service_manager.is_running = True
    monkeypatch.setattr("builtins.input", answer("n"))

    assert start_cli.main(is_forced=False) == 0

    assert START_COMMANDS[type(service_manager)] not in service_manager.calls
    assert "service    running" in capsys.readouterr().out


def test_a_service_that_will_not_start_says_so_with_the_command(
    service_manager, capsys
):
    service_manager.is_refusing = True

    assert start_cli.main(is_forced=True) == 1

    captured = capsys.readouterr()
    assert "running" not in captured.out
    assert "the service did not start; try:" in captured.err


def test_start_keeps_the_binding_as_it_is(service_manager, config_path):
    assert start_cli.main(is_forced=True) == 0

    assert not config_path.exists()


def test_an_unprivileged_start_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "start", "--yes"])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert "nagent start needs root (it starts the agent's service)" in err
    assert "sudo nagent start --yes" in err


def test_the_entry_passes_yes_through(monkeypatch):
    called = []
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "start", "--yes"])
    monkeypatch.setattr(
        entry.start, "main", lambda *, is_forced: called.append(is_forced) or 0
    )

    assert entry.main() == 0
    assert called == [True]
