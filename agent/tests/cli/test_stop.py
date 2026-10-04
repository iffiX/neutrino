"""``nagent stop``: the agent's service stopped through each platform's
service manager, asked about first, the binding kept.

The walk runs once per service manager: systemd, the Windows service control
manager and launchd, each faked by the block's ``service_manager``.
"""

import io

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.stop as stop_cli
import neutrino_agent.core.enrollment as enrollment
from tests.conftest import (
    FakeLaunchd,
    FakeServiceControlManager,
    FakeSystemd,
    bind,
)

# The command each manager is asked to stop the service with.
STOP_COMMANDS = {
    FakeSystemd: ["systemctl", "stop", "neutrino_agent.service"],
    FakeServiceControlManager: ["sc", "stop", "neutrino_agent"],
    FakeLaunchd: ["launchctl", "bootout", "system/com.neutrino.agent"],
}


def answer(reply: str):
    """A terminal whose person types ``reply`` to every question."""

    def ask(question: str) -> str:
        return reply

    return ask


def test_a_yes_stops_the_service(terminal, service_manager, monkeypatch, capsys):
    service_manager.is_running = True
    monkeypatch.setattr("builtins.input", answer("yes"))

    assert stop_cli.main(is_forced=False) == 0

    assert STOP_COMMANDS[type(service_manager)] in service_manager.calls
    assert not service_manager.is_running
    assert "service    running" not in capsys.readouterr().out


def test_yes_on_the_command_line_skips_the_question(service_manager, monkeypatch):
    service_manager.is_running = True
    monkeypatch.setattr("builtins.input", answer("n"))

    assert stop_cli.main(is_forced=True) == 0

    assert not service_manager.is_running


def test_a_no_changes_nothing(terminal, service_manager, monkeypatch, capsys):
    service_manager.is_running = True
    monkeypatch.setattr("builtins.input", answer("n"))

    assert stop_cli.main(is_forced=False) == 1

    assert STOP_COMMANDS[type(service_manager)] not in service_manager.calls
    assert service_manager.is_running
    assert "nothing changed" in capsys.readouterr().out


def test_with_no_terminal_it_names_yes_and_changes_nothing(
    service_manager, monkeypatch, capsys
):
    service_manager.is_running = True
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("builtins.input", refuse_to_ask)

    assert stop_cli.main(is_forced=False) == 1

    assert service_manager.is_running is True
    printed = capsys.readouterr()
    assert printed.err.strip().count("\n") == 0
    assert "--yes" in printed.err


def refuse_to_ask(prompt):
    raise AssertionError("asked with no terminal")


def test_a_stopped_service_is_left_alone_without_a_question(
    service_manager, monkeypatch
):
    monkeypatch.setattr("builtins.input", answer("n"))

    assert stop_cli.main(is_forced=False) == 0

    assert STOP_COMMANDS[type(service_manager)] not in service_manager.calls


def test_a_service_that_will_not_stop_says_so(service_manager, capsys):
    service_manager.is_running = True
    service_manager.is_refusing = True

    assert stop_cli.main(is_forced=True) == 1

    assert "the service did not stop" in capsys.readouterr().err


def test_stop_keeps_the_binding(service_manager, config_path):
    service_manager.is_running = True
    bind(config_path)

    assert stop_cli.main(is_forced=True) == 0

    assert enrollment.is_bound()


def test_an_unprivileged_stop_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "stop"])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert "nagent stop needs root (it stops the agent's service)" in err
    assert "sudo nagent stop" in err


def test_the_entry_asks_unless_yes_is_given(monkeypatch):
    called = []
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "stop"])
    monkeypatch.setattr(
        entry.stop, "main", lambda *, is_forced: called.append(is_forced) or 0
    )

    assert entry.main() == 0
    assert called == [False]
