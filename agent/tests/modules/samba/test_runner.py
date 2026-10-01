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
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.runner import (
    SambaModuleRunner,
    SambaNativeServerRunner,
)
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


class FakeNativeApplier:
    """The system server's applier, recording each call with its record."""

    def __init__(self):
        self.calls: list = []
        self.status = {"is_present": True, "is_running": True, "shares": []}
        self.reads = 0
        self.error = None

    def read_status(self, record):
        self.reads += 1
        return dict(self.status)

    def apply(self, config, record):
        self.calls.append(("apply", config.to_dict(), record))
        if self.error is not None:
            raise self.error
        return ["created share share"]

    def withdraw(self, record, *, is_removed):
        self.calls.append(("withdraw", record, is_removed))

    def set_password(self, name, password):
        self.calls.append(("set_password", name, password))

    def reload_fence(self):
        self.calls.append(("reload_fence",))

    def read_server_log(self, lines):
        return ["10:00 1001 A client connected.", "10:05 1002 A client left."]


class NativeServerPlatform(RecordingPlatform):
    """A system that carries its own SMB server, the way Windows does."""

    os_name = "windows"
    capabilities = frozenset({"smb_server"})

    def __init__(self):
        super().__init__()
        self.applier = FakeNativeApplier()
        self.log_path = ""

    def smb_server_applier(self):
        return self.applier

    def agent_log_path(self):
        return self.log_path


WINDOWS_CONFIG = {
    "shares": [{"name": "share", "path": "D:\\share"}],
    "users": ["ann"],
    "allowed_subnets": ["192.168.100.0/24"],
}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def native():
    platform = NativeServerPlatform()
    clock = Clock()
    held = SambaNativeServerRunner(platform=platform, log=lambda m: None, clock=clock)
    held.applier = platform.applier
    held.clock = clock
    assert platform.applier.calls == [("reload_fence",)]
    platform.applier.calls.clear()
    return held


def record_of(native_runner) -> dict:
    return native_runner._read_record()


def test_the_native_server_installs_nothing_and_is_there_when_it_answers(native):
    native.install({})
    native.uninstall({})

    assert native.verify({}) is True
    native.applier.status = {"is_present": False}
    native.clock.now += 31
    assert native.verify({}) is False
    assert native.applier.calls == []


def test_an_apply_keeps_what_it_made_in_the_record(native):
    native.apply(WINDOWS_CONFIG)

    ((verb, config, record),) = native.applier.calls
    assert verb == "apply"
    assert config == SambaConfig.from_dict(WINDOWS_CONFIG).to_dict()
    assert record["shares"] == {"share": "D:\\share"}
    assert record_of(native) == {
        "shares": {"share": "D:\\share"},
        "accounts": ["ann"],
        "is_served": True,
    }
    assert native.is_active() is True


def test_a_failed_apply_still_lists_the_shares_it_may_have_made(native):
    native.applier.error = OSError("New-SmbShare : Access is denied.")

    with pytest.raises(ModuleApplyError) as refused:
        native.apply(WINDOWS_CONFIG)

    assert refused.value.code == "apply_failed"
    assert "Access is denied" in refused.value.params["detail"]
    assert record_of(native)["shares"] == {"share": "D:\\share"}
    assert record_of(native)["accounts"] == []


def test_a_refusal_from_the_server_keeps_its_code(native):
    native.applier.error = ModuleApplyError("share_name_taken", {"name": "share"})

    with pytest.raises(ModuleApplyError) as refused:
        native.apply(WINDOWS_CONFIG)

    assert refused.value.code == "share_name_taken"


def test_a_path_is_checked_for_the_system_that_serves_it(native):
    with pytest.raises(ModuleApplyError) as refused:
        native.validate({**WINDOWS_CONFIG, "shares": [{"name": "s", "path": "/srv"}]})

    assert refused.value.code == "share_path_relative"
    assert native.applier.calls == []


def test_stopping_withdraws_the_shares_and_the_row_reads_stopped(native):
    native.apply(WINDOWS_CONFIG)

    native.stop()

    assert native.applier.calls[-1] == (
        "withdraw",
        {"shares": {"share": "D:\\share"}, "accounts": ["ann"], "is_served": True},
        False,
    )
    assert record_of(native) == {"shares": {}, "accounts": ["ann"], "is_served": False}
    assert native.is_active() is False


def test_removing_the_configuration_is_a_removal(native):
    native.apply(WINDOWS_CONFIG)

    native.remove_configuration()

    assert native.applier.calls[-1][0] == "withdraw"
    assert native.applier.calls[-1][2] is True
    assert record_of(native)["accounts"] == ["ann"]


def test_a_password_is_set_only_for_an_account_the_module_made(native):
    assert native.command("set_password", {"name": "ann", "password": "pw"})[
        "code"
    ] == ("user_unknown")

    native.apply(WINDOWS_CONFIG)
    outcome = native.command("set_password", {"name": "ann", "password": "pw"})

    assert outcome["exit_code"] == 0
    assert native.applier.calls[-1] == ("set_password", "ann", "pw")


def test_the_server_is_read_once_per_half_minute_and_after_each_change(native):
    native.observe({})
    native.observe({})
    assert native.applier.reads == 1

    native.clock.now += 31
    native.observe({})
    assert native.applier.reads == 2

    native.apply(WINDOWS_CONFIG)
    native.observe({})
    assert native.applier.reads == 3


def test_the_details_have_the_linux_shape_and_the_fence(native):
    native.applier.status = {
        "is_present": True,
        "is_running": True,
        "shares": [{"name": "share", "path": "D:\\share", "params": {}}],
        "users": [{"name": "ann", "is_present": True, "has_password": True}],
        "sessions": [],
        "fence": {"is_present": True, "is_enabled": True, "blocked": []},
    }

    details = native.observe({})["details"]

    assert set(details) == {
        "is_active",
        "global",
        "shares",
        "users",
        "sessions",
        "disk_usage",
        "fence",
    }
    assert details["global"] == {}
    assert details["fence"]["is_present"] is True


def test_the_native_log_is_the_server_s_then_the_agent_s_lines(native, tmp_path):
    log = tmp_path / "agent.log"
    log.write_text(
        "11:00 samba: created share media\n11:01 vscode: unchanged\n",
        encoding="utf-8",
    )
    native._platform.log_path = str(log)

    outcome = native.command("journal", {"lines": 10})

    assert outcome["output"].splitlines() == [
        "10:00 1001 A client connected.",
        "10:05 1002 A client left.",
        "11:00 samba: created share media",
    ]
    assert native.command("journal", {"lines": 1})["output"] == (
        "11:00 samba: created share media"
    )
