"""How setup opens the wizard page on the machine it runs on.

Setup runs under sudo, so a bare ``xdg-open`` runs as root and silently opens
nothing: the command must step down to the account that called sudo and reach
that account's session bus.
"""

import neutrino_hub.cli.setup as setup

URL = "http://127.0.0.1:8080/?token=t"


def test_an_unprivileged_run_opens_directly(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(setup.os, "geteuid", lambda: 1000)

    assert setup._browser_command(URL) == ["xdg-open", URL]


def test_a_sudo_run_steps_down_to_the_calling_account(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup, "SETUP_USER_RUNTIME_ROOT", tmp_path)
    (tmp_path / "1000").mkdir()
    monkeypatch.setenv("SUDO_USER", "iffi")
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    command = setup._browser_command(URL)

    assert command[:4] == ["runuser", "-u", "iffi", "--"]
    assert f"XDG_RUNTIME_DIR={tmp_path / '1000'}" in command
    assert f"DBUS_SESSION_BUS_ADDRESS=unix:path={tmp_path / '1000'}/bus" in command
    assert "DISPLAY=:0" in command
    assert command[-2:] == ["xdg-open", URL]


def test_root_without_a_signed_in_caller_opens_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup, "SETUP_USER_RUNTIME_ROOT", tmp_path)
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.delenv("SUDO_UID", raising=False)

    assert setup._browser_command(URL) is None


def test_a_caller_with_no_session_opens_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup, "SETUP_USER_RUNTIME_ROOT", tmp_path)
    monkeypatch.setenv("SUDO_USER", "iffi")
    monkeypatch.setenv("SUDO_UID", "1000")

    assert setup._browser_command(URL) is None


def test_a_machine_without_an_opener_opens_nothing(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)

    assert setup._browser_command(URL) is None
