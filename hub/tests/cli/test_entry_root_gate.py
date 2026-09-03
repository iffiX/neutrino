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
