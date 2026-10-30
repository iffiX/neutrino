"""The git server runner: install from bytes, validate, apply, verbs, details.

What these pin beside the verbs: the runner's own check is the binary on
disk, the system packages a recipe names install before the binary, the
server's account is a step of its own before ``configure`` taking
``system_accounts`` as the uninstall does, none where the server runs as
LocalSystem, and the details name the port the server answers on, from the
held configuration or the installed ``app.ini``.
"""

import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.gitea import runner as runner_module
from neutrino_agent.modules.gitea.applier import GiteaState
from neutrino_agent.modules.gitea.runner import GiteaModuleRunner
from neutrino_agent.modules.shared.base import ModuleStep
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
    accounts: list = []
    uninstalls = 0

    def install(self, binary_path):
        FakeInstaller.installed.append(binary_path)

    def ensure_account(self):
        FakeInstaller.accounts.append("git")

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
    surveys: list = []
    error = None

    def survey(self):
        FakeAdmins.surveys.append(list(FakeAdmins.admins))
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


def test_the_runner_is_chosen_by_its_name(runner):
    assert runner.runner == "gitea"
    assert runner.name == "gitea"


def test_is_active_is_the_units_word(runner, monkeypatch):
    asked: list = []
    monkeypatch.setattr(
        runner_module, "unit_state", lambda unit: asked.append(unit) or "active"
    )
    assert runner.is_active() is True
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "failed")
    assert runner.is_active() is False
    assert asked == ["neutrino_gitea.service"]


def test_verify_is_the_binary_on_disk(runner, monkeypatch, tmp_path):
    binary = tmp_path / "gitea"
    monkeypatch.setattr(runner_module, "GITEA_BINARY_PATH", str(binary))

    assert runner.verify({}) is False
    binary.write_text("")
    assert runner.verify({}) is True


BINARY = {"name": "gitea", "kind": "binary", "digest": "sha256:aa"}


def test_install_puts_git_first_then_the_bytes(runner):
    recipe = {"runner": "gitea", "method": "hub", "params": {"packages": ["git"]}}

    runner.install(recipe)
    runner.install_artifact(recipe, BINARY, "/tmp/package.binary")

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
    assert "HTTP_ADDR = 127.0.0.1\n" in FakeApplier.applied[0]
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


def configure_and_start():
    return [
        ModuleStep(name="configure", run=lambda context: None),
        ModuleStep(name="start", run=lambda context: None),
    ]


def test_the_account_step_comes_before_the_core_s_and_makes_the_account(runner):
    steps = runner.configure_steps({}, "running", configure_and_start())
    steps[0].run(None)

    assert [(step.name, step.params) for step in steps] == [
        ("account", {"account": "git"}),
        ("configure", {}),
        ("start", {}),
    ]
    assert FakeInstaller.accounts == ["git"]


def test_a_server_run_as_localsystem_plans_no_account_step(tmp_path):
    runner = GiteaModuleRunner(
        platform=MacPlatform(),
        log=lambda m: None,
        applier=SystemApplier(tmp_path),
        record_dir=str(tmp_path / "record"),
    )

    steps = runner.configure_steps({}, "running", configure_and_start())

    assert [step.name for step in steps] == ["configure", "start"]


def test_the_account_and_the_uninstall_take_system_accounts(runner):
    assert runner.step_locks("account") == (("system_accounts", "alone"),)
    assert runner.step_locks("uninstall") == (("system_accounts", "alone"),)
    assert runner.step_locks("configure") == ()


def test_stop_takes_the_server_down(runner):
    runner.stop()

    assert FakeApplier.applied == ["stopped"]


def test_the_first_admin_is_made_and_the_second_refused(runner):
    first = runner.command(
        "admin", {"username": "ann", "password": "p", "email": "a@x"}
    )
    second = runner.command(
        "admin", {"username": "bob", "password": "p", "email": "b@x"}
    )

    assert first["exit_code"] == 0
    assert FakeAdmins.created == ["ann"]
    assert (second["exit_code"], second["code"]) == (1, "admin_exists")


def test_an_unusable_username_is_refused_before_gitea_sees_it(runner):
    outcome = runner.command(
        "admin", {"username": "bad name", "password": "p", "email": "a@x"}
    )

    assert outcome["code"] == "username_invalid"
    assert FakeAdmins.created == []


def test_a_password_reset_lands_only_on_an_administrator(runner):
    FakeAdmins.admins = ["ann"]

    good = runner.command("password", {"username": "ann", "password": "p"})
    bad = runner.command("password", {"username": "ghost", "password": "p"})

    assert good["exit_code"] == 0
    assert FakeAdmins.changed == ["ann"]
    assert bad["code"] == "admin_unknown"


def test_a_verb_the_module_does_not_have_is_refused(runner):
    outcome = runner.command("set_password", {"name": "ann"})

    assert outcome["code"] == "verb_unknown"
    assert outcome["params"] == {"module": "gitea", "verb": "set_password"}


def test_validate_is_a_verb_every_module_answers(runner):
    good = runner.command("validate", {"config": CONFIG})
    bad = runner.command("validate", {"config": {**CONFIG, "listen_port": 80}})

    assert (good["exit_code"], good["code"]) == (0, "")
    assert (bad["exit_code"], bad["code"]) == (1, "port_reserved")


def test_the_details_read_the_unit_and_the_port(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "active")
    monkeypatch.setattr(runner_module, "read_listen_port", lambda: 3300)

    details = runner.details({})

    assert runner.is_active() is True
    # A hand-installed instance reports as running on its port; the hub
    # imports nothing of it.
    assert details["port"] == 3300
    assert details["is_running"] is True
    assert details["admins"] == []
    runner.apply(CONFIG)
    assert runner.details({})["port"] == 3000


def test_the_details_read_the_url_from_the_installed_file_before_an_apply(
    runner, monkeypatch
):
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "active")
    monkeypatch.setattr(runner_module, "read_listen_port", lambda: 3300)
    monkeypatch.setattr(
        runner_module, "read_root_url", lambda: "http://192.168.100.7:3300/"
    )

    assert runner.details({})["url"] == "http://192.168.100.7:3300/"
    runner.apply(CONFIG)
    assert runner.details({})["url"] == "http://192.168.100.7:3000/"


def test_the_survey_stands_for_a_minute(runner, monkeypatch, tmp_path):
    (tmp_path / "gitea").write_text("")
    monkeypatch.setattr(runner_module, "GITEA_BINARY_PATH", str(tmp_path / "gitea"))
    clock = [1000.0]
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: clock[0])

    runner.details({})
    runner.details({})
    clock[0] += 61.0
    runner.details({})

    assert len(FakeAdmins.surveys) == 2


def test_a_new_administrator_is_surveyed_at_once(runner, monkeypatch, tmp_path):
    (tmp_path / "gitea").write_text("")
    monkeypatch.setattr(runner_module, "GITEA_BINARY_PATH", str(tmp_path / "gitea"))
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: 1000.0)
    runner.details({})

    runner.command("admin", {"username": "ann", "password": "pw", "email": "a@b"})

    # The verb reads once for itself; the details after it read again
    # rather than answering from the survey taken before the account existed.
    assert runner.details({})["admins"] == ["ann"]
    assert FakeAdmins.surveys == [[], [], ["ann"]]


def test_a_refused_gitea_verb_is_typed(runner):
    FakeAdmins.error = subprocess.CalledProcessError(1, ["runuser"], stderr="db locked")

    outcome = runner.command(
        "admin", {"username": "ann", "password": "p", "email": "a@x"}
    )

    assert outcome["code"] == "command_failed"
    assert "db locked" in outcome["params"]["detail"]


def test_journal_reads_the_servers_unit(runner, monkeypatch):
    asked: list = []

    def journal(units, lines):
        asked.append((list(units), lines))
        return ["2026-09-19T10:00:00-0500 box gitea[1]: Starting"]

    monkeypatch.setattr("neutrino_agent.modules.shared.base.units_journal", journal)

    outcome = runner.command("journal", {"lines": 50})

    assert outcome["exit_code"] == 0
    assert outcome["output"].endswith("Starting")
    assert asked == [(["neutrino_gitea.service"], 50)]


class SystemApplier:
    """A macOS or Windows applier as the runner sees it."""

    is_git_required = True
    account = ""

    def __init__(self, tmp_path, git=""):
        self.git = git
        self.binary_path = str(tmp_path / "gitea")
        self.applied: list = []
        self.installed: list = []
        self.log = tmp_path / "gitea.log"

    def find_git(self):
        return self.git

    def layout(self, git_path):
        from neutrino_agent.modules.gitea.renderer import GiteaLayout

        return GiteaLayout(
            run_user="neutrino_gitea",
            work_path="/state/gitea_data",
            git_path=git_path,
        )

    def install(self, binary_path):
        self.installed.append(binary_path)

    def apply(self, rendered, *, git_path):
        self.applied.append((rendered, git_path))
        return "started"

    def is_active(self):
        return True

    def survey(self):
        return GiteaState(True, "1.27.3", [])

    def read_listen_port(self):
        return 0

    def read_root_url(self):
        return ""

    def journal_units(self):
        return []

    def log_path(self):
        return str(self.log)


class MacPlatform(AgentPlatform):
    os_name = "darwin"


def test_without_git_an_install_and_an_apply_are_refused(tmp_path):
    applier = SystemApplier(tmp_path)
    runner = GiteaModuleRunner(
        platform=MacPlatform(), log=lambda m: None, applier=applier
    )

    for step in (
        lambda: runner.install_artifact({}, BINARY, "/tmp/gitea"),
        lambda: runner.apply(CONFIG),
    ):
        with pytest.raises(ModuleApplyError) as refused:
            step()
        assert refused.value.code == "gitea_git_missing"
    assert applier.installed == []
    assert applier.applied == []


def test_the_git_found_is_named_in_app_ini_with_gitea_s_own_ssh(tmp_path):
    applier = SystemApplier(tmp_path, git="/opt/homebrew/bin/git")
    runner = GiteaModuleRunner(
        platform=MacPlatform(), log=lambda m: None, applier=applier
    )

    runner.install_artifact({}, BINARY, "/tmp/gitea")
    runner.apply(CONFIG)

    ((rendered, git_path),) = applier.applied
    assert git_path == "/opt/homebrew/bin/git"
    assert "RUN_USER = neutrino_gitea" in rendered
    assert "HTTP_ADDR = 127.0.0.1\n" in rendered
    assert "START_SSH_SERVER = true" in rendered
    assert "PATH = /state/gitea_data/data/gitea.db" in rendered
    assert "[git]\nPATH = /opt/homebrew/bin/git\n" in rendered
    assert applier.installed == ["/tmp/gitea"]


def test_the_journal_on_macos_and_windows_is_the_servers_own_log(tmp_path):
    applier = SystemApplier(tmp_path, git="/opt/homebrew/bin/git")
    applier.log.write_text(
        "2026/10/05 10:00:00 ...s/web.go:87:serveInstalled() Listen\n"
    )
    runner = GiteaModuleRunner(
        platform=MacPlatform(), log=lambda m: None, applier=applier
    )

    outcome = runner.command("journal", {"lines": 20})

    assert outcome["output"].endswith("Listen")


def test_a_log_gitea_has_not_written_yet_reads_empty_and_logs_nothing(tmp_path):
    applier = SystemApplier(tmp_path, git="/opt/homebrew/bin/git")
    lines: list = []
    runner = GiteaModuleRunner(
        platform=MacPlatform(), log=lines.append, applier=applier
    )

    outcome = runner.command("journal", {"lines": 20})

    assert outcome["exit_code"] == 0
    assert outcome["output"] == ""
    assert lines == []


@pytest.mark.parametrize(
    "os_name, kind",
    [("darwin", "GiteaDarwinApplier"), ("windows", "GiteaWindowsApplier")],
)
def test_each_system_gets_its_own_applier(os_name, kind, tmp_path):
    class Platform(AgentPlatform):
        pass

    Platform.os_name = os_name
    platform = Platform()
    platform.agent_var_dir = lambda: str(tmp_path)

    applier = runner_module.gitea_applier_for(platform)

    assert type(applier).__name__ == kind
    assert applier.is_git_required is True


@pytest.mark.parametrize("os_name", ["darwin", "windows"])
def test_each_system_applier_has_every_member_of_the_linux_one(os_name, tmp_path):
    class Platform(AgentPlatform):
        pass

    Platform.os_name = os_name
    platform = Platform()
    platform.agent_var_dir = lambda: str(tmp_path)
    applier = runner_module.gitea_applier_for(platform)

    members = [
        name
        for name in vars(runner_module.GiteaLinuxApplier)
        if not name.startswith("_")
    ]
    assert [name for name in members if not hasattr(applier, name)] == []


def test_its_ssh_server_takes_the_first_free_port_from_2222_and_keeps_it(tmp_path):
    held = {2222}
    applier = SystemApplier(tmp_path, git="/opt/homebrew/bin/git")
    runner = GiteaModuleRunner(
        platform=MacPlatform(),
        log=lambda m: None,
        applier=applier,
        record_dir=str(tmp_path / "record"),
        is_port_free=lambda port: port not in held,
    )
    assert runner.details({})["ssh_listen_port"] == 0

    runner.apply(CONFIG)
    held.add(2223)
    runner.apply(dict(CONFIG, ssh_port=27654))
    again = GiteaModuleRunner(
        platform=MacPlatform(),
        log=lambda m: None,
        applier=applier,
        record_dir=str(tmp_path / "record"),
        is_port_free=lambda port: True,
    )

    first, second = (rendered for rendered, _git in applier.applied)
    assert "SSH_LISTEN_PORT = 2223\n" in first and "SSH_PORT = 2223\n" in first
    assert "SSH_LISTEN_PORT = 2223\n" in second and "SSH_PORT = 27654\n" in second
    assert runner.details({})["ssh_listen_port"] == 2223
    assert again.details({})["ssh_listen_port"] == 2223
