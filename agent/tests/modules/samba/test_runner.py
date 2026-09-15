"""The file share runner: validate, apply, stop, verbs, and what it observes.

What these pin beside the verbs: ``observe()`` reads the binary, the unit
and the details in one go, and the details are what Samba itself says,
``testparm -s`` parsed into the global section and each share and
``pdbedit -L`` into the accounts, so a share somebody set up by hand is
reported the way the hub imports it.
"""

import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules import system_package as system_package_module
from neutrino_agent.modules.samba import applier as applier_module
from neutrino_agent.modules.samba import runner as runner_module
from neutrino_agent.modules.samba.applier import SambaUserState
from neutrino_agent.modules.samba.runner import SambaModuleRunner
from neutrino_agent.modules.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

# What ``testparm -s`` prints for a hand-written file: the global section,
# the two printer sections Ubuntu ships, and two shares.
TESTPARM_OUTPUT = """# Global parameters
[global]
\tmap to guest = Bad User
\tserver role = standalone server
\tserver string = %h server (Samba, Ubuntu)
\tidmap config * : backend = tdb


[printers]
\tbrowseable = No
\tcomment = All Printers
\tpath = /var/spool/samba
\tprintable = Yes


[print$]
\tcomment = Printer Drivers
\tpath = /var/lib/samba/printers


[media]
\tpath = /srv/media
\tread only = No
\tvalid users = ann bob


[backup]
\tguest ok = Yes
\tpath = /srv/backup
"""

# What ``pdbedit -L`` prints: name, uid, full name.
PDBEDIT_OUTPUT = "ann:1001:Ann Example\nbob:1002:\n"

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

    def credentialed_users(self):
        return []

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
    monkeypatch.setattr(
        runner_module,
        "SambaConfigReader",
        lambda: type("Reader", (), {"read": lambda self: ({}, [])})(),
    )
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


def test_is_active_is_the_units_word(runner, monkeypatch):
    asked: list = []
    monkeypatch.setattr(
        runner_module, "unit_state", lambda unit: asked.append(unit) or "active"
    )
    assert runner.is_active() is True
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "inactive")
    assert runner.is_active() is False
    assert asked == ["smb.service"]


def test_the_own_check_is_the_server_binary(monkeypatch):
    monkeypatch.setattr(
        system_package_module.shutil,
        "which",
        lambda name: "/usr/sbin/smbd" if name == "smbd" else None,
    )
    held = SambaModuleRunner(platform=RecordingPlatform(), family="debian")

    assert held.verify({}) is True
    monkeypatch.setattr(system_package_module.shutil, "which", lambda name: None)
    assert held.verify({}) is False


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
        raise subprocess.CalledProcessError(1, ["systemctl"], stderr="no unit")

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

    good = runner.command("set_password", {"name": "ann", "password": "x"})
    bad = runner.command("set_password", {"name": "ghost", "password": "x"})

    assert good["exit_code"] == 0
    assert FakeUsers.passwords == [("ann", "x")]
    assert (bad["exit_code"], bad["code"]) == (1, "user_unknown")


def test_a_refused_password_is_typed(runner):
    runner.apply(CONFIG)
    FakeUsers.error = subprocess.CalledProcessError(
        1, ["smbpasswd"], stderr="no such user"
    )

    outcome = runner.command("set_password", {"name": "ann", "password": "x"})

    assert outcome["code"] == "command_failed"
    assert "no such user" in outcome["params"]["detail"]


def test_a_verb_the_module_does_not_have_is_refused(runner):
    outcome = runner.command("admin", {})

    assert outcome["code"] == "verb_unknown"
    assert outcome["params"] == {"module": "samba", "verb": "admin"}


def test_validate_is_a_verb_every_module_answers(runner):
    good = runner.command("validate", {"config": CONFIG})
    bad = runner.command(
        "validate", {"config": {**CONFIG, "shares": [{"name": "global", "path": "/x"}]}}
    )

    assert (good["exit_code"], good["code"]) == (0, "")
    assert (bad["exit_code"], bad["code"]) == (1, "share_name_reserved")


def test_removing_the_configuration_deletes_the_rendered_file(
    runner, monkeypatch, tmp_path
):
    conf = tmp_path / "smb.conf"
    conf.write_text("[global]")
    monkeypatch.setattr(runner_module, "SAMBA_CONF_PATH", str(conf))

    runner.remove_configuration()
    runner.remove_configuration()

    assert not conf.exists()


# --- what a hand-written file share observes as ---


def samba_commands(monkeypatch, *, accounts=("ann",)):
    """Samba's own tools answered from the fixtures; ``id`` knows ``accounts``."""
    asked: list = []

    def run(command, *, is_checked=True, input_text=None, timeout_s=120):
        asked.append(list(command))
        if command[0] == "testparm":
            return CommandResult(command, 0, TESTPARM_OUTPUT, "")
        if command[0] == "pdbedit":
            return CommandResult(command, 0, PDBEDIT_OUTPUT, "")
        if command[0] == "id":
            return CommandResult(command, 0 if command[-1] in accounts else 1, "", "")
        raise OSError(f"{command[0]} is not here")

    monkeypatch.setattr(applier_module, "run", run)
    monkeypatch.setattr(applier_module.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(applier_module.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(
        runner_module, "SambaUserManager", applier_module.SambaUserManager
    )
    monkeypatch.setattr(
        runner_module, "SambaConfigReader", applier_module.SambaConfigReader
    )
    monkeypatch.setattr(
        system_package_module.shutil, "which", lambda name: "/usr/sbin/" + name
    )
    return asked


def test_observe_reads_what_samba_itself_says_of_the_machine(runner, monkeypatch):
    asked = samba_commands(monkeypatch)

    observed = runner.observe({})

    assert (observed["is_installed"], observed["is_active"]) == (True, True)
    details = observed["details"]
    assert set(details) == {
        "is_active",
        "global",
        "shares",
        "users",
        "sessions",
        "disk_usage",
    }
    assert details["global"] == {
        "map to guest": "Bad User",
        "server role": "standalone server",
        "server string": "%h server (Samba, Ubuntu)",
        "idmap config * : backend": "tdb",
    }
    # The printer sections are not shares; the shares keep their order.
    assert details["shares"] == [
        {
            "name": "media",
            "path": "/srv/media",
            "params": {"read only": "No", "valid users": "ann bob"},
        },
        {"name": "backup", "path": "/srv/backup", "params": {"guest ok": "Yes"}},
    ]
    # Every account Samba holds a credential for, whether or not the hub
    # configured it, with the unix account's presence beside it.
    assert details["users"] == [
        {"name": "ann", "is_present": True, "has_password": True},
        {"name": "bob", "is_present": False, "has_password": True},
    ]
    assert details["sessions"] == []
    assert ["testparm", "-s", runner_module.SAMBA_CONF_PATH] in asked
    assert ["pdbedit", "-L"] in asked


def test_observe_lists_the_configured_users_first_then_the_rest(runner, monkeypatch):
    runner.apply({**CONFIG, "users": ["carol", "ann"]})
    samba_commands(monkeypatch, accounts=("ann", "carol"))

    users = runner.observe({})["details"]["users"]

    assert [user["name"] for user in users] == ["carol", "ann", "bob"]
    assert users[0] == {"name": "carol", "is_present": True, "has_password": False}


def test_observe_of_a_machine_without_samba_reads_nothing(runner, monkeypatch):
    samba_commands(monkeypatch)
    monkeypatch.setattr(applier_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_package_module.shutil, "which", lambda name: None)

    observed = runner.observe({})

    assert observed == {"is_installed": False, "is_active": False, "details": {}}
