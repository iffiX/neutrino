"""Which nhub commands demand root, and how the refusal reads."""

import sys
import types

import neutrino_hub.cli.entry as entry
import neutrino_hub.utils.constants as constants


def test_an_unprivileged_apply_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(constants, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(entry.sys, "argv", ["nhub", "apply"])

    assert entry.main() == 2
    output = capsys.readouterr().err
    assert "sudo nhub apply" in output


def test_scan_secrets_is_never_gated(monkeypatch):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    assert "scan-secrets" in entry.COMMANDS


def test_run_is_never_gated(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(constants, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(entry.sys, "argv", ["nhub", "run"])
    module = types.ModuleType("fake_run")
    module.main = lambda: 0
    monkeypatch.setitem(sys.modules, "fake_run", module)
    monkeypatch.setitem(entry.COMMANDS, "run", ("fake_run", "run"))

    assert entry.main() == 0
    assert "sudo nhub" not in capsys.readouterr().err


def test_windows_asks_for_an_administrator_powershell(monkeypatch, capsys):
    from neutrino_hub.platforms import windows

    monkeypatch.setattr(entry.sys, "platform", "win32")
    monkeypatch.setattr(windows.WindowsHubPlatform, "is_elevated", lambda self: False)
    monkeypatch.setattr(constants, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(entry.sys, "argv", ["nhub", "setup"])

    assert entry.main() == 2
    output = capsys.readouterr().err
    assert "needs an administrator" in output
    assert "administrator PowerShell" in output
    assert "sudo" not in output


def test_status_is_never_gated(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(constants, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(entry.sys, "argv", ["nhub", "status"])
    module = types.ModuleType("fake_status")
    module.main = lambda: 0
    monkeypatch.setitem(sys.modules, "fake_status", module)
    monkeypatch.setitem(entry.COMMANDS, "status", ("fake_status", "status"))

    assert entry.main() == 0
