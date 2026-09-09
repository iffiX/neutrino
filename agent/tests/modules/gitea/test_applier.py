"""The git server's effects, with the system underneath replaced.

The rule with teeth is work-root ownership: gitea runs as the git account
and creates ``.ssh`` under its work root on start, so a root-owned root is
a crashloop. The applier owns the root on every apply.
"""

import os
import stat

import pytest

from neutrino_agent.modules.gitea import applier as applier_module
from neutrino_agent.modules.gitea.applier import (
    GiteaAdminManager,
    GiteaConfigApplier,
    GiteaInstaller,
)
from neutrino_agent.modules.subprocess_run import CommandResult


class FakeCommands:
    def __init__(self, answers=None):
        self.calls: list = []
        self.answers = dict(answers or {})

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        exit_code, stdout = self.answers.get(tuple(command[:2]), (0, ""))
        return CommandResult(list(command), exit_code, stdout, "")


@pytest.fixture
def box(monkeypatch, tmp_path):
    commands = FakeCommands()
    chowns: list = []
    monkeypatch.setattr(applier_module, "run", commands)
    monkeypatch.setattr(applier_module, "GITEA_DIR", str(tmp_path / "gitea"))
    monkeypatch.setattr(applier_module, "GITEA_ETC_DIR", str(tmp_path / "etc"))
    monkeypatch.setattr(
        applier_module, "GITEA_CONF_PATH", str(tmp_path / "etc/app.ini")
    )
    monkeypatch.setattr(
        applier_module, "GITEA_BINARY_PATH", str(tmp_path / "bin/gitea")
    )
    monkeypatch.setattr(applier_module, "GITEA_SYSTEMD_DIR", str(tmp_path / "systemd"))
    (tmp_path / "bin").mkdir()
    (tmp_path / "systemd").mkdir()
    monkeypatch.setattr(
        applier_module.shutil,
        "chown",
        lambda path, user=None, group=None: chowns.append((str(path), user, group)),
    )
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "inactive")
    monkeypatch.setattr(applier_module.pwd, "getpwnam", lambda name: object())
    return commands, chowns, tmp_path


def test_apply_writes_app_ini_group_readable_owns_the_root_and_starts(box):
    commands, chowns, tmp_path = box

    note = GiteaConfigApplier().apply("[server]\n")

    assert note == "started"
    app_ini = tmp_path / "etc/app.ini"
    assert app_ini.read_text() == "[server]\n"
    assert stat.S_IMODE(os.stat(app_ini).st_mode) == 0o640
    assert (tmp_path / "gitea/.ssh").is_dir()
    assert (str(tmp_path / "gitea"), "git", "git") in chowns
    assert (str(tmp_path / "gitea/.ssh"), "git", "git") in chowns
    assert ["systemctl", "enable", "--now", "neutrino_gitea.service"] in commands.calls


def test_apply_restarts_a_running_server(box, monkeypatch):
    commands, _, _ = box
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "active")

    assert GiteaConfigApplier().apply("[server]\n") == "restarted"
    assert ["systemctl", "restart", "neutrino_gitea.service"] in commands.calls


def test_apply_without_the_git_account_leaves_the_work_root_alone(box, monkeypatch):
    _, chowns, tmp_path = box

    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(applier_module.pwd, "getpwnam", missing)

    GiteaConfigApplier().apply("[server]\n")

    assert not (tmp_path / "gitea").exists()


def test_install_copies_the_binary_makes_the_user_and_installs_the_unit(box):
    commands, chowns, tmp_path = box
    commands.answers[("id", "git")] = (1, "")
    downloaded = tmp_path / "download"
    downloaded.write_bytes(b"\x7fELF binary")

    GiteaInstaller().install(str(downloaded))

    binary = tmp_path / "bin/gitea"
    assert binary.read_bytes() == b"\x7fELF binary"
    assert stat.S_IMODE(os.stat(binary).st_mode) == 0o755
    assert any(call[:2] == ["useradd", "--system"] for call in commands.calls)
    unit = tmp_path / "systemd/neutrino_gitea.service"
    assert "ExecStart=/usr/local/bin/gitea web" in unit.read_text()
    assert ["systemctl", "daemon-reload"] in commands.calls
    for name in ("custom", "data", "log", ".ssh"):
        assert (tmp_path / "gitea" / name).is_dir()


def test_the_unit_is_rewritten_only_when_it_differs(box):
    commands, _, tmp_path = box
    installer = GiteaInstaller()
    assert installer.install_unit() is True
    commands.calls.clear()

    assert installer.install_unit() is False
    assert commands.calls == []


def test_uninstall_removes_the_unit_binary_and_config_but_keeps_the_data(box):
    commands, _, tmp_path = box
    (tmp_path / "bin/gitea").write_text("")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/app.ini").write_text("")
    (tmp_path / "gitea/data").mkdir(parents=True)
    (tmp_path / "systemd/neutrino_gitea.service").write_text("")

    GiteaInstaller().uninstall()

    assert not (tmp_path / "bin/gitea").exists()
    assert not (tmp_path / "etc/app.ini").exists()
    assert not (tmp_path / "systemd/neutrino_gitea.service").exists()
    assert (tmp_path / "gitea/data").is_dir()
    assert ["systemctl", "disable", "--now", "neutrino_gitea.service"] in commands.calls


def test_survey_reads_the_version_and_the_admins_as_the_git_user(box):
    commands, _, tmp_path = box
    (tmp_path / "bin/gitea").write_text("")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/app.ini").write_text("")
    commands.answers[(str(tmp_path / "bin/gitea"), "--version")] = (
        0,
        "Gitea version 1.27.3 built\n",
    )
    commands.answers[("runuser", "-u")] = (
        0,
        "ID Username Email IsActive\n1 root root@x true\n2 ann ann@x true\n",
    )

    state = GiteaAdminManager().survey()

    assert state.is_installed and state.version == "1.27.3"
    assert state.admin_usernames == ["root", "ann"]
    assert state.has_admin
    listing = next(call for call in commands.calls if call[0] == "runuser")
    assert listing[:4] == ["runuser", "-u", "git", "--"]
    assert "sudo" not in " ".join(listing)


def test_a_missing_binary_surveys_as_not_installed(box):
    state = GiteaAdminManager().survey()

    assert state == applier_module.GiteaState(False, "", [])


def test_the_admin_verbs_run_as_the_git_user_with_the_config(box):
    commands, _, tmp_path = box

    GiteaAdminManager().create_admin(username="ann", password="pw", email="a@x")
    GiteaAdminManager().change_password(username="ann", password="pw2")

    create, change = [call for call in commands.calls if call[0] == "runuser"]
    assert create[:4] == ["runuser", "-u", "git", "--"]
    assert "--admin" in create and "--password" in create
    assert create[-2:] == ["--config", str(tmp_path / "etc/app.ini")]
    assert "change-password" in change
