"""The git server's effects, with the system underneath replaced.

The rule with teeth is work-root ownership: gitea runs as the git account
and creates ``.ssh`` under its work root on start, so a root-owned root is
a crashloop. The applier owns the root on every apply. A handover is owed
while another uid owns one of Gitea's own parts, and gives each directory
after what it holds.
"""

import os
import stat
import types

import pytest

from neutrino_agent.modules.gitea import applier as applier_module
from neutrino_agent.modules.gitea.applier import (
    GiteaAdminManager,
    GiteaConfigApplier,
    GiteaInstaller,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult


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
    monkeypatch.setattr(applier_module.pwd, "getpwnam", account_of(os.getuid()))
    return commands, chowns, tmp_path


def account_of(uid: int):
    """A ``getpwnam`` that finds every name with one uid and gid."""

    def getpwnam(name):
        return types.SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=uid + 1)

    return getpwnam


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


def test_apply_leaves_a_running_server_alone_when_the_file_is_the_same(
    box, monkeypatch
):
    commands, _, tmp_path = box
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "active")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/app.ini").write_text("[server]\n")

    assert GiteaConfigApplier().apply("[server]\n") == "unchanged"
    assert ["systemctl", "restart", "neutrino_gitea.service"] not in commands.calls


def test_apply_starts_a_stopped_server_on_an_unchanged_file(box):
    commands, _, tmp_path = box
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/app.ini").write_text("[server]\n")

    assert GiteaConfigApplier().apply("[server]\n") == "started"
    assert ["systemctl", "enable", "--now", "neutrino_gitea.service"] in commands.calls


@pytest.mark.parametrize("state", ["active", "inactive"])
def test_apply_under_stopped_writes_app_ini_and_runs_no_systemctl(
    box, monkeypatch, state
):
    commands, _, tmp_path = box
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: state)

    note = GiteaConfigApplier().apply("[server]\n", is_started=False)

    assert note == "written"
    assert (tmp_path / "etc/app.ini").read_text() == "[server]\n"
    assert not [call for call in commands.calls if call[0] == "systemctl"]
    assert GiteaConfigApplier().apply("[server]\n", is_started=False) == "unchanged"


def test_an_app_ini_listening_on_every_address_moves_to_loopback(box, monkeypatch):
    """A server an earlier build left on every address is restarted on the
    loopback file at the next apply."""
    commands, _, tmp_path = box
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "active")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/app.ini").write_text(
        "[server]\nHTTP_ADDR = 0.0.0.0\nHTTP_PORT = 3000\n"
    )

    note = GiteaConfigApplier().apply(
        "[server]\nHTTP_ADDR = 127.0.0.1\nHTTP_PORT = 3000\n"
    )

    assert note == "restarted"
    assert "HTTP_ADDR = 127.0.0.1" in (tmp_path / "etc/app.ini").read_text()
    assert ["systemctl", "restart", "neutrino_gitea.service"] in commands.calls


def test_apply_without_the_git_account_leaves_the_work_root_alone(box, monkeypatch):
    _, chowns, tmp_path = box

    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(applier_module.pwd, "getpwnam", missing)

    GiteaConfigApplier().apply("[server]\n")

    assert not (tmp_path / "gitea").exists()


def test_install_copies_the_binary_and_installs_the_unit_and_makes_no_user(box):
    commands, chowns, tmp_path = box
    commands.answers[("id", "git")] = (1, "")
    downloaded = tmp_path / "download"
    downloaded.write_bytes(b"\x7fELF binary")

    GiteaInstaller().install(str(downloaded))

    binary = tmp_path / "bin/gitea"
    assert binary.read_bytes() == b"\x7fELF binary"
    assert stat.S_IMODE(os.stat(binary).st_mode) == 0o755
    assert not any(call[0] in ("id", "useradd") for call in commands.calls)
    unit = tmp_path / "systemd/neutrino_gitea.service"
    assert "ExecStart=/usr/local/bin/gitea web" in unit.read_text()
    assert ["systemctl", "daemon-reload"] in commands.calls


def test_the_account_step_makes_the_user_and_its_directories(box):
    commands, chowns, tmp_path = box
    commands.answers[("id", "git")] = (1, "")

    GiteaInstaller().ensure_account()

    assert any(call[:2] == ["useradd", "--system"] for call in commands.calls)
    for name in ("custom", "data", "log", ".ssh"):
        assert (tmp_path / "gitea" / name).is_dir()


def test_the_account_step_gives_a_work_root_another_uid_owns_to_the_account(
    box, monkeypatch
):
    commands, chowns, tmp_path = box
    data = tmp_path / "gitea" / "data"
    (data / "gitea-repositories" / "ann").mkdir(parents=True)
    (data / "gitea.db").write_text("")
    (data / "link").symlink_to(data / "gitea.db")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/app.ini").write_text("[server]\n")
    given: list = []
    monkeypatch.setattr(
        applier_module.os, "chown", lambda path, uid, gid: given.append((path, uid))
    )
    monkeypatch.setattr(applier_module.pwd, "getpwnam", account_of(os.getuid() + 7))

    assert GiteaInstaller().ensure_account() is True

    paths = {path for path, uid in given if uid == os.getuid() + 7}
    assert str(data / "gitea.db") in paths
    assert str(data / "gitea-repositories" / "ann") in paths
    assert str(data / "link") not in paths
    assert (str(tmp_path / "etc/app.ini"), None, "git") in chowns


def test_a_handover_cut_short_runs_again_by_gitea_s_own_parts(box, monkeypatch):
    _, chowns, tmp_path = box
    root = tmp_path / "gitea"
    for part in ("custom/conf", "data", "log"):
        (root / part).mkdir(parents=True)
    (root / "log" / "gitea.log").write_text("")
    real_lstat = os.lstat

    def lstat(path):
        found = real_lstat(path)
        if os.fspath(path) != str(root / "log"):
            return found
        fields = list(found)
        fields[4] = os.getuid() + 9
        return os.stat_result(fields)

    given: list = []
    monkeypatch.setattr(applier_module.os, "lstat", lstat)
    monkeypatch.setattr(
        applier_module.os, "chown", lambda path, uid, gid: given.append(path)
    )

    assert GiteaInstaller().ensure_account() is True

    assert given[-1] == str(root)
    assert given.index(str(root / "log" / "gitea.log")) < given.index(str(root / "log"))
    assert given.index(str(root / "custom" / "conf")) < given.index(
        str(root / "custom")
    )


def test_the_account_step_leaves_a_work_root_the_account_owns(box, monkeypatch):
    _, chowns, tmp_path = box
    (tmp_path / "gitea" / "data").mkdir(parents=True)
    (tmp_path / "gitea" / "data" / "gitea.db").write_text("")
    given: list = []
    monkeypatch.setattr(
        applier_module.os, "chown", lambda path, uid, gid: given.append(path)
    )

    assert GiteaInstaller().ensure_account() is False
    assert given == []


def test_the_unit_is_rewritten_only_when_it_differs(box):
    commands, _, tmp_path = box
    installer = GiteaInstaller()
    assert installer.install_unit() is True
    commands.calls.clear()

    assert installer.install_unit() is False
    assert commands.calls == []


def test_stop_stops_the_unit_and_disables_it(box):
    commands, _, _ = box

    GiteaConfigApplier().stop()

    assert commands.calls == [
        ["systemctl", "disable", "--now", "neutrino_gitea.service"]
    ]


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
        "gitea version 1.27.3 built with go1.26.7-X:jsonv2 : bindata\n",
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


def test_the_listen_port_is_read_from_the_installed_app_ini(monkeypatch, tmp_path):
    from neutrino_agent.modules.gitea import applier as applier_module

    conf = tmp_path / "app.ini"
    monkeypatch.setattr(applier_module, "GITEA_CONF_PATH", str(conf))
    assert applier_module.read_listen_port() == 0

    conf.write_text("[server]\nPROTOCOL = http\nHTTP_PORT = 3300\n")
    assert applier_module.read_listen_port() == 3300

    conf.write_text("[server]\nHTTP_PORT = many\n")
    assert applier_module.read_listen_port() == 0


def test_the_root_url_is_read_from_the_installed_file(tmp_path):
    path = tmp_path / "app.ini"
    path.write_text("[server]\nHTTP_PORT = 3000\nROOT_URL = http://box:3000/\n")

    assert applier_module.read_root_url(str(path)) == "http://box:3000/"
    assert applier_module.read_root_url(str(tmp_path / "missing.ini")) == ""
