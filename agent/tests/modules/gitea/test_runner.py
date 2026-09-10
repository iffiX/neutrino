"""The git server runner: install from bytes, validate, apply, commands."""

import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.gitea import runner as runner_module
from neutrino_agent.modules.gitea.applier import GiteaState
from neutrino_agent.modules.gitea.runner import GiteaModuleRunner
from neutrino_agent.platforms.base import AgentPlatform

SECRETS = {
    "SECRET_KEY": "sk",
    "INTERNAL_TOKEN": "it",
    "JWT_SECRET": "jw",
    "LFS_JWT_SECRET": "lf",
}
CONFIG = {"listen_port": 3000, "address": "192.168.100.7", "secrets": SECRETS}


class RecordingPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self):
        self.installed: list = []

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return ""


class FakeInstaller:
    installed: list = []
    uninstalls = 0

    def install(self, binary_path):
        FakeInstaller.installed.append(binary_path)

    def uninstall(self):
        FakeInstaller.uninstalls += 1


class FakeApplier:
    applied: list = []
    error = None

    def apply(self, rendered):
        if FakeApplier.error is not None:
            raise FakeApplier.error
        FakeApplier.applied.append(rendered)
        return "started"

    def stop(self):
        FakeApplier.applied.append("stopped")


class FakeAdmins:
    admins: list = []
    created: list = []
    changed: list = []
    error = None

    def survey(self):
        return GiteaState(True, "1.27.3", list(FakeAdmins.admins))

    def create_admin(self, *, username, password, email):
        if FakeAdmins.error is not None:
            raise FakeAdmins.error
        FakeAdmins.created.append(username)
        FakeAdmins.admins.append(username)

    def change_password(self, *, username, password):
        FakeAdmins.changed.append(username)


@pytest.fixture
def runner(monkeypatch):
    for fake in (FakeInstaller, FakeApplier, FakeAdmins):
        for name, value in vars(fake).items():
            if isinstance(value, list):
                setattr(fake, name, [])
    FakeInstaller.uninstalls = 0
    FakeApplier.error = None
    FakeAdmins.error = None
    monkeypatch.setattr(runner_module, "GiteaInstaller", FakeInstaller)
    monkeypatch.setattr(runner_module, "GiteaConfigApplier", FakeApplier)
    monkeypatch.setattr(runner_module, "GiteaAdminManager", FakeAdmins)
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "active")
    return GiteaModuleRunner(platform=RecordingPlatform(), log=lambda m: None)


def test_the_runner_owns_the_gitea_kind(runner):
    assert runner.kind == "gitea"
    assert runner.name == "gitea"


def test_verify_is_the_binary_on_disk(runner, monkeypatch, tmp_path):
    binary = tmp_path / "gitea"
    monkeypatch.setattr(runner_module, "GITEA_BINARY_PATH", str(binary))

    assert runner.verify({}) is False
    binary.write_text("")
    assert runner.verify({}) is True


def test_install_puts_git_first_then_the_bytes(runner):
    runner.install({"entry": {"packages": ["git"]}}, "/tmp/package.binary")

    assert runner._platform.installed == [["git"]]
    assert FakeInstaller.installed == ["/tmp/package.binary"]


def test_uninstall_rides_the_installer(runner):
    runner.uninstall({})

    assert FakeInstaller.uninstalls == 1


def test_validate_refuses_typed(runner):
    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({**CONFIG, "listen_port": 80})

    assert refused.value.code == "port_reserved"


def test_apply_renders_and_keeps_the_url(runner):
    runner.apply(CONFIG)

    assert "HTTP_PORT = 3000" in FakeApplier.applied[0]
    details = runner.details({})
    assert details["url"] == "http://192.168.100.7:3000/"
    assert details["is_running"] is True
    assert details["version"] == "1.27.3"


def test_a_refused_apply_is_typed(runner):
    FakeApplier.error = subprocess.CalledProcessError(
        1, ["systemctl"], stderr="will not start"
    )

    with pytest.raises(ModuleApplyError) as refused:
        runner.apply(CONFIG)

    assert refused.value.code == "apply_failed"


def test_stop_takes_the_server_down(runner):
    runner.stop()

    assert FakeApplier.applied == ["stopped"]


def test_the_first_admin_is_made_and_the_second_refused(runner):
    first = runner.command(
        "gitea_admin", {"username": "ann", "password": "p", "email": "a@x"}
    )
    second = runner.command(
        "gitea_admin", {"username": "bob", "password": "p", "email": "b@x"}
    )

    assert first["exit_code"] == 0
    assert FakeAdmins.created == ["ann"]
    assert (second["exit_code"], second["code"]) == (1, "admin_exists")


def test_an_unusable_username_is_refused_before_gitea_sees_it(runner):
    outcome = runner.command(
        "gitea_admin", {"username": "bad name", "password": "p", "email": "a@x"}
    )

    assert outcome["code"] == "username_invalid"
    assert FakeAdmins.created == []


def test_a_password_reset_lands_only_on_an_administrator(runner):
    FakeAdmins.admins = ["ann"]

    good = runner.command("gitea_password", {"username": "ann", "password": "p"})
    bad = runner.command("gitea_password", {"username": "ghost", "password": "p"})

    assert good["exit_code"] == 0
    assert FakeAdmins.changed == ["ann"]
    assert bad["code"] == "admin_unknown"


def test_a_refused_gitea_verb_is_typed(runner):
    FakeAdmins.error = subprocess.CalledProcessError(1, ["runuser"], stderr="db locked")

    outcome = runner.command(
        "gitea_admin", {"username": "ann", "password": "p", "email": "a@x"}
    )

    assert outcome["code"] == "command_failed"
    assert "db locked" in outcome["params"]["detail"]
