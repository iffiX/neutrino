"""The hub on Linux: the systemd controller, the browser stepped down, the
journal as the place a log is read."""

import pytest

from neutrino_hub.platforms import linux
from neutrino_hub.platforms.linux import LinuxHubPlatform
from neutrino_hub.system.systemd_ctl import SystemdServiceController

URL = "http://127.0.0.1:8080/?token=t"


def test_the_controller_is_systemds():
    assert isinstance(LinuxHubPlatform().process_controller(), SystemdServiceController)


def test_a_log_is_read_with_journalctl():
    assert LinuxHubPlatform().log_hint("hub_update", "neutrino_hub_update") == (
        "journalctl -u neutrino_hub_update"
    )


def test_root_with_no_signed_in_caller_opens_nothing(monkeypatch):
    monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(linux.os, "geteuid", lambda: 0)
    monkeypatch.delenv("SUDO_USER", raising=False)
    calls = []
    monkeypatch.setattr(linux, "run", lambda *a, **k: calls.append(a))

    assert not LinuxHubPlatform().open_browser(URL)
    assert calls == []


def test_an_unprivileged_run_opens_the_page_directly(monkeypatch):
    monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(linux.os, "geteuid", lambda: 1000)
    calls = []
    monkeypatch.setattr(linux, "run", lambda command, **k: calls.append(command))

    assert LinuxHubPlatform().open_browser(URL)
    assert calls == [["xdg-open", URL]]


def test_sudo_steps_down_with_runuser_never_sudo(monkeypatch, tmp_path):
    monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(linux.os, "geteuid", lambda: 0)
    (tmp_path / "1000").mkdir()
    monkeypatch.setenv("SUDO_USER", "iffi")
    monkeypatch.setenv("SUDO_UID", "1000")

    command = LinuxHubPlatform().browser_command(URL, user_runtime_root=tmp_path)

    assert command[:4] == ["runuser", "-u", "iffi", "--"]
    assert "sudo" not in command


def test_the_agent_is_nagent_on_the_path():
    assert LinuxHubPlatform().agent_command() == "nagent"


def test_elevation_is_euid_zero(monkeypatch):
    monkeypatch.setattr(linux.os, "geteuid", lambda: 0)
    assert LinuxHubPlatform().is_elevated()
    monkeypatch.setattr(linux.os, "geteuid", lambda: 1000)
    assert not LinuxHubPlatform().is_elevated()
    assert LinuxHubPlatform().elevation_hint("setup") == "sudo nhub setup"


def test_the_elevated_step_runs_nhub_through_pkexec(monkeypatch):
    calls = []
    monkeypatch.setattr(linux.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        linux.subprocess,
        "run",
        lambda command, **k: calls.append(command)
        or linux.subprocess.CompletedProcess(command, 0),
    )
    platform = LinuxHubPlatform()

    assert platform.run_elevated(["open", "--start-service"])
    assert calls == [["pkexec", *platform.hub_command("open", "--start-service")]]


def test_a_declined_pkexec_is_not_a_run(monkeypatch):
    monkeypatch.setattr(linux.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        linux.subprocess,
        "run",
        lambda command, **k: linux.subprocess.CompletedProcess(command, 126),
    )

    assert not LinuxHubPlatform().run_elevated(["open"])


def test_without_pkexec_nothing_is_asked(monkeypatch):
    monkeypatch.setattr(linux.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        linux.subprocess, "run", lambda *a, **k: pytest.fail("nothing to ask with")
    )

    assert not LinuxHubPlatform().run_elevated(["open"])
