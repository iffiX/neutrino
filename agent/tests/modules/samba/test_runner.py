"""The file share runner: validate, apply, stop, details and the command."""

import pytest

from neutrino_agent.modules.base import ModuleApplyError
from neutrino_agent.modules.samba import runner as runner_module
from neutrino_agent.modules.samba.applier import SambaUserState
from neutrino_agent.modules.samba.runner import SambaModuleRunner
from neutrino_agent.modules.subprocess_run import CommandError
from neutrino_agent.platforms.base import AgentPlatform

CONFIG = {
    "shares": [{"name": "share", "path": "/srv/share"}],
    "users": ["ann"],
    "allowed_subnets": ["192.168.100.0/24"],
}


class RecordingPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self):
        self.installed: list = []

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return ""


class FakeApplier:
    applied: list = []
    stops = 0

    def __init__(self, *, unit):
        self.unit = unit

    def apply(self, rendered, *, config):
        FakeApplier.applied.append((self.unit, rendered, config))
        return "started"

    def stop(self):
        FakeApplier.stops += 1


class FakeUsers:
    passwords: list = []
    error = None

    def converge(self, users):
        return []

    def survey(self, users):
        return [SambaUserState(name, True, False) for name in users]

    def set_password(self, name, password):
        if FakeUsers.error is not None:
            raise FakeUsers.error
        FakeUsers.passwords.append((name, password))


@pytest.fixture
def runner(monkeypatch):
    FakeApplier.applied = []
    FakeApplier.stops = 0
    FakeUsers.passwords = []
    FakeUsers.error = None
    groups: list = []
    monkeypatch.setattr(runner_module, "SambaConfigApplier", FakeApplier)
    monkeypatch.setattr(runner_module, "SambaUserManager", FakeUsers)
    monkeypatch.setattr(runner_module, "ensure_share_group", lambda: groups.append(1))
    monkeypatch.setattr(runner_module, "testparm", lambda rendered: None)
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "active")
    held = SambaModuleRunner(
        platform=RecordingPlatform(), log=lambda m: None, family="rhel"
    )
    held.groups = groups
    return held


def test_the_unit_follows_the_family(runner):
    assert runner.unit == "smb.service"
    assert SambaModuleRunner(platform=RecordingPlatform(), family="debian").unit == (
        "smbd.service"
    )


def test_install_puts_the_package_and_the_share_group(runner):
    runner.install({"entry": {"packages": ["samba"]}})

    assert runner._platform.installed == [["samba"]]
    assert runner.groups == [1]


def test_validate_refuses_a_bad_configuration_typed(runner):
    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({**CONFIG, "shares": [{"name": "global", "path": "/x"}]})

    assert refused.value.code == "share_name_reserved"


def test_validate_has_samba_check_the_render(runner, monkeypatch):
    checked: list = []
    monkeypatch.setattr(runner_module, "testparm", checked.append)

    runner.validate(CONFIG)

    assert "[share]" in checked[0]
    assert "hosts allow = 192.168.100.0/24 127.0.0.1" in checked[0]


def test_apply_renders_applies_and_keeps_the_configuration(runner):
    runner.apply(CONFIG)

    unit, rendered, config = FakeApplier.applied[0]
    assert unit == "smb.service"
    assert "[share]" in rendered
    assert config.users == ["ann"]
    assert runner.details({})["users"] == [
        {"name": "ann", "is_present": True, "has_password": False}
    ]


def test_a_refused_apply_is_typed(runner, monkeypatch):
    def refuse(self, rendered, *, config):
        raise CommandError(["systemctl"], "no unit")

    monkeypatch.setattr(FakeApplier, "apply", refuse)

    with pytest.raises(ModuleApplyError) as refused:
        runner.apply(CONFIG)

    assert refused.value.code == "apply_failed"
    assert "no unit" in refused.value.params["detail"]


def test_stop_takes_the_unit_down(runner):
    runner.stop()

    assert FakeApplier.stops == 1


def test_details_carry_the_live_reads(runner, monkeypatch):
    class Reader:
        def sessions(self):
            return [{"username": "ann"}]

        def disk_usage(self, config):
            return [{"share": share.name} for share in config.shares]

    monkeypatch.setattr(runner_module, "SambaStatusReader", Reader)
    runner.apply(CONFIG)

    details = runner.details({})

    assert details["is_active"] is True
    assert details["sessions"] == [{"username": "ann"}]
    assert details["disk_usage"] == [{"share": "share"}]


def test_the_password_command_lands_only_on_a_configured_user(runner):
    runner.apply(CONFIG)

    good = runner.command("samba_set_password", {"name": "ann", "password": "x"})
    bad = runner.command("samba_set_password", {"name": "ghost", "password": "x"})

    assert good["exit_code"] == 0
    assert FakeUsers.passwords == [("ann", "x")]
    assert (bad["exit_code"], bad["code"]) == (1, "user_unknown")


def test_a_refused_password_is_typed(runner):
    runner.apply(CONFIG)
    FakeUsers.error = CommandError(["smbpasswd"], "no such user")

    outcome = runner.command("samba_set_password", {"name": "ann", "password": "x"})

    assert outcome["code"] == "command_failed"
    assert "no such user" in outcome["params"]["detail"]


def test_an_action_the_module_does_not_own_is_refused(runner):
    assert runner.command("gitea_admin", {})["code"] == "unsupported_action"
