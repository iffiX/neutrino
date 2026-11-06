"""The file share runner: validate, apply, stop, verbs, and what it observes.

What these pin beside the verbs: the runner's own check is the binary, and
read with the unit and the details as the engine reads them, the details
are what Samba itself says, ``testparm -s`` parsed into the global section
and each share and ``pdbedit -L`` into the accounts. Each apply sets the
passwords of the hub's map whose digest differs from the root-only record,
which keeps digests and never a password; a user that is no account of the
machine's lacks, the account a share writes as, is refused ``account_unknown``;
the SMB users are made before the file is written; a share a share of the
person's names is left off with ``share_name_taken`` and the rest served,
the row naming the first share left off in the configuration's order;
``configure`` and
``uninstall`` take ``system_accounts``; the ``set_password`` verb is gone.
On Windows and macOS the apply sets each account's password the same way,
after the server has made the account, and a removal forgets the digests.
A ``configure`` under ``stopped`` starts no server on any system and serves
no share on Windows and macOS. On Linux a ``configure`` that serves a share
turns the SELinux boolean on and the record stores the mark; a boolean on
before the module stays unmarked; a refusal logs a line and the apply goes on;
a **Stop** leaves it on; an uninstall turns it off only with the mark. On a Samba
the module installed a **Stop** takes the NetBIOS name server down, and the next
**Start** starts it. A Samba the install step did
not record as its own is the person's: its units and its package stay as they
are at an uninstall, the row reads the module's own mark and the unit, a **Start**
starts the server and the name server, share or no share, and a **Stop** stops
both, on either kind of Samba; the first **Start** keeps what both units were and an
uninstall puts them back, a later share or the last one going moves no unit, and
the module reads absent after its uninstall and installs again with no
package manager. An uninstall on either kind deletes every ``neutrino_`` user
before any package goes.
"""

import hashlib
import json
import os
import stat
import subprocess
import threading

import pytest

from neutrino_agent.core import engine as engine_module
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.core.tasks import run_step
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared import system_package as system_package_module
from neutrino_agent.modules.samba import applier as applier_module
from neutrino_agent.modules.samba import runner as runner_module
from neutrino_agent.modules.samba.applier import SambaUserState, password_digest
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_CONF_MARKER,
    SAMBA_NATIVE_STATUS_TTL_S,
    samba_name_unit,
)
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.samba.runner import (
    SambaModuleRunner,
    SambaNativeServerRunner,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
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
PDBEDIT_OUTPUT = "neutrino_ann:1001:\nneutrino_bob:1002:\nperson:1003:A Person\n"

CONFIG = {
    "shares": [
        {"name": "share", "path": "/srv/share", "valid_users": ["neutrino_ann"]}
    ],
    "users": ["neutrino_ann"],
    "passwords": {"neutrino_ann": "generated"},
}


class RecordingPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self, var_dir="/nonexistent/neutrino_test"):
        self.installed: list = []
        self.var_dir = str(var_dir)

    def agent_var_dir(self):
        return self.var_dir

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return ""


class FakeApplier:
    applied: list = []
    started: list = []
    stops = 0
    starts = 0
    removals = 0
    withdrawals = 0
    earlier_sweeps = 0
    # What the shares of 0.5 in smb.conf are, as :meth:`sweep_earlier` gives them.
    earlier: list = []
    earlier_users: list = []
    earlier_kept: set = set()
    served: list = []
    user_files: dict = {}
    # Whether the unit is active as the applier reads it.
    is_unit_active = True
    # The share folders the machine does not have, and those that are links.
    missing: set = set()
    links: set = set()

    def __init__(self, *, unit):
        self.unit = unit

    @staticmethod
    def read_folder(path, *, platform=None):
        if path in FakeApplier.missing:
            return "missing"
        return "link" if path in FakeApplier.links else "folder"

    def plan(self, *, is_served):
        FakeApplier.served.append(is_served)
        return b"[global]\n   include = /etc/samba/neutrino.conf\n", ""

    def apply(self, rendered, *, config, user_files=None, is_reloaded=True):
        FakeApplier.applied.append((self.unit, rendered, config))
        FakeApplier.user_files = dict(user_files or {})
        FakeApplier.started.append(is_reloaded)
        return "reloaded" if is_reloaded else "written"

    def remove(self):
        FakeApplier.removals += 1

    def sweep_earlier(self):
        FakeApplier.earlier_sweeps += 1
        return (
            list(FakeApplier.earlier),
            list(FakeApplier.earlier_users),
            set(FakeApplier.earlier_kept),
        )

    def withdraw(self):
        FakeApplier.withdrawals += 1
        return "took the module's shares off"

    def stop(self):
        FakeApplier.stops += 1
        FakeApplier.is_unit_active = False

    def start(self):
        FakeApplier.starts += 1
        FakeApplier.is_unit_active = True


class FakeSelinux:
    """The SELinux boolean, its value in :attr:`value`, every change in :attr:`changes`."""

    value = "off"
    changes: list = []
    refusal: "BaseException | None" = None

    def turn_on(self):
        return self._change("off", "on")

    def turn_off(self):
        return self._change("on", "off")

    def _change(self, before, after):
        if FakeSelinux.refusal is not None:
            raise FakeSelinux.refusal
        if FakeSelinux.value != before:
            return False
        FakeSelinux.value = after
        FakeSelinux.changes.append(after)
        return True


class FakeUnits:
    """Samba's units by name, what each is in :attr:`states`, every change in :attr:`calls`."""

    states: dict = {}
    calls: list = []

    def __init__(self, *, unit):
        self.unit = unit

    def read(self):
        return dict(FakeUnits.states.get(self.unit, {}))

    def start(self):
        FakeUnits.calls.append((self.unit, "start"))
        FakeUnits.states[self.unit] = {"is_enabled": True, "is_active": True}

    def stop(self):
        FakeUnits.calls.append((self.unit, "stop"))
        FakeUnits.states[self.unit] = {}

    def put_back(self, found):
        FakeUnits.calls.append((self.unit, "put_back", dict(found)))
        FakeUnits.states[self.unit] = dict(found)


NAME_UNIT = "nmb.service"
SERVER_UNIT = "smb.service"


class FakeReader:
    persons: tuple = ({}, [])
    judged = b""

    def read(self):
        return {}, []

    def read_persons(self, data):
        FakeReader.judged = data
        return FakeReader.persons


class FakeUsers:
    converged: list = []
    made: list = []
    sweeps = 0
    earlier: list = []

    def sweep(self):
        FakeUsers.sweeps += 1
        return ["swept the account neutrino_old"]

    def sweep_earlier(self, named, *, kept=frozenset()):
        FakeUsers.earlier.append((list(named), set(kept)))
        return [f"swept the 0.5 credential of {name}" for name in named]

    def check_accounts(self, accounts):
        for name in accounts:
            if name == "ghost":
                raise ModuleApplyError("account_unknown", {"account": name})

    def converge_accounts(self, config):
        FakeUsers.made.append(list(config.users))
        return []

    def converge(self, config, held):
        FakeUsers.converged.append(dict(held))
        kept = {name: password_digest(config.passwords[name]) for name in config.users}
        return [f"set the password of {name}" for name in config.users], kept

    def survey(self, users):
        return [SambaUserState(name, True, False) for name in users]

    def credentialed_users(self):
        return []


@pytest.fixture
def runner(monkeypatch, tmp_path):
    FakeApplier.applied = []
    FakeApplier.started = []
    FakeApplier.missing = set()
    FakeApplier.links = set()
    FakeApplier.stops = 0
    FakeApplier.starts = 0
    FakeApplier.removals = 0
    FakeApplier.withdrawals = 0
    FakeApplier.earlier_sweeps = 0
    FakeApplier.earlier = []
    FakeApplier.earlier_users = []
    FakeApplier.earlier_kept = set()
    FakeApplier.served = []
    FakeApplier.is_unit_active = True
    FakeUsers.converged = []
    FakeUsers.made = []
    FakeUsers.sweeps = 0
    FakeUsers.earlier = []
    FakeReader.persons = ({}, [])
    FakeSelinux.value = "off"
    FakeSelinux.changes = []
    FakeSelinux.refusal = None
    FakeUnits.states = {}
    FakeUnits.calls = []
    (tmp_path / "configured").mkdir()
    (tmp_path / "configured" / "samba").write_text("")
    (tmp_path / "samba.json").write_text('{"is_swept": true}')
    monkeypatch.setattr(runner_module, "SambaConfigApplier", FakeApplier)
    monkeypatch.setattr(runner_module, "read_posix_folder", FakeApplier.read_folder)
    monkeypatch.setattr(runner_module, "SambaUserManager", FakeUsers)
    monkeypatch.setattr(runner_module, "testparm", lambda smb_conf, rendered: None)
    monkeypatch.setattr(
        runner_module,
        "unit_state",
        lambda unit: "active" if FakeApplier.is_unit_active else "inactive",
    )
    monkeypatch.setattr(runner_module, "SambaConfigReader", FakeReader)
    monkeypatch.setattr(runner_module, "SambaSelinuxApplier", FakeSelinux)
    monkeypatch.setattr(runner_module, "SambaUnitApplier", FakeUnits)
    held = SambaModuleRunner(
        platform=RecordingPlatform(tmp_path), log=lambda m: None, family="rhel"
    )
    held.record_path = tmp_path / "samba.json"
    return held


TWO_SHARES = {
    "shares": [
        {"name": "share", "path": "/srv/share", "valid_users": ["neutrino_ann"]},
        {"name": "gone", "path": "/srv/gone", "valid_users": ["neutrino_ann"]},
    ],
    "users": ["neutrino_ann"],
    "passwords": {"neutrino_ann": "generated"},
}


def test_a_share_whose_folder_is_missing_is_left_off_and_named_on_the_row(runner):
    """No folder is made: the person makes it and applies again."""
    FakeApplier.missing = {"/srv/gone"}
    lines: list = []
    runner._log = lines.append

    runner.apply(TWO_SHARES)

    _unit, rendered, config = FakeApplier.applied[-1]
    assert [share.name for share in config.shares] == ["share"]
    assert "[gone]" not in rendered
    assert "[share]" in rendered
    assert runner.notice() == {
        "code": "share_path_missing",
        "params": {"name": "gone", "path": "/srv/gone"},
    }
    assert any(
        "left share gone off the server: share_path_missing" in line for line in lines
    )
    FakeApplier.missing = set()
    runner.apply(TWO_SHARES)
    assert runner.notice() == {}


def test_a_share_whose_folder_is_a_link_is_left_off_and_the_rest_served(runner):
    FakeApplier.links = {"/srv/gone"}

    runner.apply(TWO_SHARES)

    _unit, rendered, config = FakeApplier.applied[-1]
    assert [share.name for share in config.shares] == ["share"]
    assert "[share]" in rendered
    assert runner.notice() == {
        "code": "share_path_link",
        "params": {"name": "gone", "path": "/srv/gone"},
    }


@pytest.mark.parametrize(
    ("path", "outcome"),
    [
        ("/srv/share", {"exit_code": 0, "code": "", "params": {}}),
        (
            "/srv/gone",
            {
                "exit_code": 1,
                "code": "share_path_missing",
                "params": {"path": "/srv/gone"},
            },
        ),
        (
            "/srv/link",
            {
                "exit_code": 1,
                "code": "share_path_link",
                "params": {"path": "/srv/link"},
            },
        ),
        (
            "srv/share",
            {"exit_code": 1, "code": "path_invalid", "params": {"path": "srv/share"}},
        ),
    ],
)
def test_the_folder_verb_reads_a_path_at_once(runner, path, outcome):
    FakeApplier.missing = {"/srv/gone"}
    FakeApplier.links = {"/srv/link"}

    answer = runner.command("folder", {"path": path})

    assert {name: answer[name] for name in ("exit_code", "code", "params")} == outcome
    assert FakeApplier.applied == []


def test_a_folder_gone_and_made_again_asks_for_a_task_each_time_and_is_served_again(
    runner, monkeypatch
):
    asked: list = []
    runner.bind_configure_asker(lambda: asked.append("samba"))
    runner.take_config(TWO_SHARES)
    runner.apply(TWO_SHARES)
    samba_commands(monkeypatch)
    now = [1e12]
    runner._folders._clock = lambda: now[0]
    FakeApplier.missing = {"/srv/gone"}

    observed(runner)
    observed(runner)
    runner.apply(TWO_SHARES)
    gone = runner.notice()
    FakeApplier.missing = set()
    now[0] += 31
    observed(runner)
    runner.apply(TWO_SHARES)

    assert asked == ["samba", "samba"]
    assert gone == {
        "code": "share_path_missing",
        "params": {"name": "gone", "path": "/srv/gone"},
    }
    assert runner.notice() == {}
    assert "[gone]" in FakeApplier.applied[-1][1]


def test_the_first_report_after_a_restart_asks_for_one_configure_task(
    runner, monkeypatch
):
    """The agent keeps neither the last apply's reads nor the shares it left
    off; a running task's ``configure`` answers the ask."""
    asked: list = []
    runner.bind_configure_asker(lambda **kwargs: asked.append(kwargs))
    runner.take_config(TWO_SHARES)
    samba_commands(monkeypatch)

    observed(runner)
    observed(runner)

    assert asked == [{"is_answered_by_task": True}]


def test_a_share_with_no_account_is_named_before_a_missing_folder(runner):
    FakeApplier.missing = {"/srv/gone"}
    config = {
        **TWO_SHARES,
        "shares": TWO_SHARES["shares"]
        + [{"name": "nobody", "path": "/srv/nobody", "valid_users": []}],
    }

    runner.apply(config)

    assert runner.notice() == {
        "code": "share_users_unknown",
        "params": {"shares": "nobody"},
    }


def test_the_unit_follows_the_family(runner):
    assert runner.unit == "smb.service"
    assert SambaModuleRunner(platform=RecordingPlatform(), family="debian").unit == (
        "smbd.service"
    )


def test_is_active_before_any_configure_is_the_units_word(runner, monkeypatch):
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


def test_install_puts_the_package_alone(runner, monkeypatch):
    monkeypatch.setattr(system_package_module.shutil, "which", lambda name: None)

    runner.install({"params": {"packages": ["samba"]}})

    assert runner._platform.installed == [["samba"]]


def test_an_account_a_share_writes_as_that_the_machine_lacks_is_refused(runner):
    bad = {
        **CONFIG,
        "shares": [{"name": "ghost", "path": "/home/ghost", "force_user": "ghost"}],
    }

    for step in (runner.validate, runner.apply):
        with pytest.raises(ModuleApplyError) as refused:
            step(bad)
        assert refused.value.params == {"account": "ghost"}
    assert FakeApplier.applied == []
    assert FakeUsers.made == []


def test_apply_makes_the_smb_users_before_the_file_is_written(runner):
    runner.apply(CONFIG)

    assert FakeUsers.made == [["neutrino_ann"]]


def test_apply_keeps_the_digest_of_each_password_root_only(runner):
    runner.apply(CONFIG)
    runner.apply(CONFIG)

    record = json.loads(runner.record_path.read_text())
    assert record["passwords"] == {"neutrino_ann": password_digest("generated")}
    assert "generated" not in runner.record_path.read_text()
    assert stat.S_IMODE(os.stat(runner.record_path).st_mode) == 0o600
    assert FakeUsers.converged == [{}, {"neutrino_ann": password_digest("generated")}]


def test_removing_the_configuration_forgets_the_digests(runner):
    runner.apply(CONFIG)

    runner.remove_configuration()

    assert not runner.record_path.exists()
    assert FakeApplier.withdrawals == 1


def test_validate_refuses_a_bad_configuration_typed(runner):
    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({**CONFIG, "shares": [{"name": "global", "path": "/x"}]})

    assert refused.value.code == "share_name_reserved"


def test_validate_has_samba_check_the_render_with_the_planned_smb_conf(
    runner, monkeypatch
):
    checked: list = []
    monkeypatch.setattr(
        runner_module,
        "testparm",
        lambda smb_conf, rendered: checked.append((smb_conf, rendered)),
    )

    runner.validate(CONFIG)

    assert checked[0][0] == b"[global]\n   include = /etc/samba/neutrino.conf\n"
    assert "[share]" in checked[0][1]
    assert checked[0][1].endswith("[global]\n")


def test_the_persons_own_samba_refuses_before_anything_is_applied(runner):
    FakeReader.persons = ({"hosts allow": "10.0.0.0/8"}, [])

    for step in (runner.validate, runner.apply):
        with pytest.raises(ModuleApplyError) as refused:
            step(CONFIG)
        assert refused.value.code == "samba_hosts_allow_no_loopback"
    assert FakeApplier.applied == []
    assert FakeUsers.made == []
    assert FakeReader.judged == b"[global]\n   include = /etc/samba/neutrino.conf\n"


def test_a_share_named_like_one_of_the_persons_is_left_off_and_the_rest_served(
    runner, monkeypatch
):
    """One share never stops the others: the person's share keeps its name."""
    FakeReader.persons = ({}, [{"name": "SHARE", "path": "/p", "params": {}}])
    checked: list = []
    monkeypatch.setattr(
        runner_module,
        "testparm",
        lambda smb_conf, rendered: checked.append(rendered),
    )
    lines: list = []
    runner._log = lines.append

    runner.validate(TWO_SHARES)
    runner.apply(TWO_SHARES)

    assert "[share]" not in checked[0]
    assert "[gone]" in checked[0]
    _unit, rendered, config = FakeApplier.applied[-1]
    assert [share.name for share in config.shares] == ["gone"]
    assert "[share]" not in rendered
    assert "[gone]" in rendered
    assert runner.notice() == {"code": "share_name_taken", "params": {"name": "share"}}
    assert any(
        "left share share off the server: share_name_taken" in line for line in lines
    )


def test_the_row_names_the_first_share_left_off_in_the_configurations_order(runner):
    FakeReader.persons = ({}, [{"name": "share", "path": "/p", "params": {}}])
    FakeApplier.missing = {"/srv/gone"}

    runner.apply(TWO_SHARES)

    assert runner.notice() == {"code": "share_name_taken", "params": {"name": "share"}}
    assert FakeApplier.applied[-1][2].shares == []


def logged_runner(tmp_path) -> tuple:
    lines: list = []
    return (
        SambaModuleRunner(
            platform=RecordingPlatform(tmp_path), log=lines.append, family="rhel"
        ),
        lines,
    )


def test_a_configure_serving_a_share_turns_the_boolean_on_and_marks_it(
    runner, tmp_path
):
    held, lines = logged_runner(tmp_path)

    held.apply(CONFIG)

    assert FakeSelinux.changes == ["on"]
    assert json.loads(runner.record_path.read_text())["is_selinux_boolean_ours"] is True
    assert "samba: turned on the SELinux boolean samba_export_all_rw" in lines


def test_an_apply_that_changes_nothing_changes_no_boolean_and_keeps_the_mark(runner):
    runner.apply(CONFIG)
    written = runner.record_path.read_text()

    runner.apply(CONFIG)

    assert FakeSelinux.changes == ["on"]
    assert runner.record_path.read_text() == written


def test_a_new_password_keeps_the_mark(runner):
    runner.apply(CONFIG)

    runner.apply(dict(CONFIG, passwords={"neutrino_ann": "another"}))

    record = json.loads(runner.record_path.read_text())
    assert record["passwords"] == {"neutrino_ann": password_digest("another")}
    assert record["is_selinux_boolean_ours"] is True


def test_a_boolean_on_before_the_module_stays_on_after_the_uninstall(runner):
    FakeSelinux.value = "on"

    runner.apply(CONFIG)

    assert "is_selinux_boolean_ours" not in json.loads(runner.record_path.read_text())
    runner.remove_configuration()
    assert FakeSelinux.changes == []
    assert FakeSelinux.value == "on"


def test_an_uninstall_turns_the_marked_boolean_off(runner, tmp_path):
    held, lines = logged_runner(tmp_path)
    held.apply(CONFIG)

    held.remove_configuration()

    assert FakeSelinux.changes == ["on", "off"]
    assert not runner.record_path.exists()
    assert "samba: turned off the SELinux boolean samba_export_all_rw" in lines


def test_stop_leaves_the_boolean_on(runner):
    runner.apply(CONFIG)

    runner.stop()

    assert FakeSelinux.value == "on"
    assert FakeSelinux.changes == ["on"]


def test_a_configure_under_stopped_leaves_the_boolean_alone(runner):
    runner.apply_stopped(CONFIG)

    assert FakeSelinux.changes == []


def test_a_configure_serving_no_share_leaves_the_boolean_alone(runner):
    runner.apply({"shares": [], "users": [], "passwords": {}})

    assert FakeSelinux.changes == []


def test_a_configure_serving_no_share_keeps_the_boolean_on(runner):
    runner.apply(CONFIG)

    runner.apply({"shares": [], "users": [], "passwords": {}})

    assert FakeSelinux.value == "on"
    assert json.loads(runner.record_path.read_text())["is_selinux_boolean_ours"] is True


@pytest.mark.parametrize(
    "refusal",
    [
        FileNotFoundError("getsebool"),
        subprocess.CalledProcessError(1, ["setsebool"], stderr="permission denied"),
    ],
)
def test_a_refused_boolean_logs_a_line_and_the_share_goes_on(runner, tmp_path, refusal):
    FakeSelinux.refusal = refusal
    held, lines = logged_runner(tmp_path)

    held.apply(CONFIG)

    assert FakeApplier.started == [True]
    assert any(
        line.startswith("samba: could not turn on the SELinux boolean")
        for line in lines
    )
    assert "is_selinux_boolean_ours" not in json.loads(runner.record_path.read_text())


def test_a_refused_turn_off_logs_a_line_and_the_uninstall_goes_on(runner, tmp_path):
    held, lines = logged_runner(tmp_path)
    held.apply(CONFIG)
    FakeSelinux.refusal = subprocess.CalledProcessError(
        1, ["setsebool"], stderr="permission denied"
    )

    held.remove_configuration()

    assert not runner.record_path.exists()
    assert any(
        line.startswith("samba: could not turn off the SELinux boolean")
        for line in lines
    )


def test_apply_renders_applies_and_keeps_the_configuration(runner):
    runner.apply(CONFIG)

    unit, rendered, config = FakeApplier.applied[0]
    assert unit == "smb.service"
    assert "[share]" in rendered
    assert config.users == ["neutrino_ann"]
    assert runner.details({})["users"] == [
        {"name": "neutrino_ann", "is_present": True, "has_password": False}
    ]


def test_a_refused_apply_is_typed(runner, monkeypatch):
    def refuse(self, rendered, *, config, user_files=None, is_reloaded=True):
        raise subprocess.CalledProcessError(1, ["systemctl"], stderr="no unit")

    monkeypatch.setattr(FakeApplier, "apply", refuse)

    with pytest.raises(ModuleApplyError) as refused:
        runner.apply(CONFIG)

    assert refused.value.code == "apply_failed"
    assert "no unit" in refused.value.params["detail"]


def mark_package_ours(runner) -> None:
    """A Samba the install step found missing and installed."""
    runner_module.write_record(str(runner.record_path), {"is_package_ours": True})


def test_stop_takes_the_unit_of_a_samba_the_module_installed_down(runner):
    mark_package_ours(runner)

    runner.stop()

    assert FakeApplier.stops == 1


NAME_SERVER_UP = {"is_enabled": True, "is_active": True}


@pytest.mark.parametrize(
    "family, unit",
    [("debian", "nmbd.service"), ("rhel", "nmb.service"), ("arch", "nmb.service")],
)
def test_the_name_server_unit_follows_the_family(family, unit):
    assert samba_name_unit(family) == unit


def test_a_stop_takes_both_units_down_on_a_samba_the_module_installed(runner):
    mark_package_ours(runner)
    runner.apply(CONFIG)

    runner.stop()

    assert FakeApplier.stops == 1
    assert FakeUnits.calls == [(NAME_UNIT, "stop")]
    record = json.loads(runner.record_path.read_text())
    assert list(record["passwords"]) == ["neutrino_ann"]
    assert "found_units" not in record


def test_a_start_starts_both_units_on_a_samba_the_module_installed(runner):
    mark_package_ours(runner)
    runner.apply(CONFIG)
    runner.stop()

    runner.apply(CONFIG)
    runner.start()

    assert FakeApplier.starts == 1
    assert FakeUnits.calls == [(NAME_UNIT, "stop"), (NAME_UNIT, "start")]
    assert "found_units" not in json.loads(runner.record_path.read_text())


def test_a_configure_under_stopped_keeps_both_units_down(runner):
    mark_package_ours(runner)
    runner.stop()
    FakeUnits.calls = []

    runner.apply_stopped(CONFIG)

    assert FakeUnits.calls == []
    assert FakeApplier.starts == 0


def test_a_start_with_no_share_brings_up_a_samba_the_module_installed(runner):
    mark_package_ours(runner)
    runner.apply({})
    runner.stop()
    assert runner.is_active() is False

    runner.apply({})
    runner.start()

    assert FakeApplier.starts == 1
    assert runner.is_active() is True
    assert FakeUnits.calls == [(NAME_UNIT, "stop"), (NAME_UNIT, "start")]


def test_a_configure_under_stopped_writes_the_files_and_starts_no_server(runner):
    mark_package_ours(runner)
    planned = [
        ModuleStep(name="configure", run=lambda context: None),
        ModuleStep(name="stop", run=lambda context: None),
    ]

    steps = runner.configure_steps(CONFIG, "stopped", planned)
    steps[0].run(None)

    assert [step.name for step in steps] == ["configure", "stop"]
    assert steps[1] is planned[1]
    assert FakeApplier.started == [False]
    assert FakeUsers.made
    assert runner.configure_steps(CONFIG, "running", planned) == planned


@pytest.mark.parametrize("step", ["configure", "uninstall"])
def test_the_steps_that_make_or_remove_accounts_take_system_accounts(runner, step):
    held = (("system_accounts", "alone"),)

    assert runner.step_locks(step) == held
    assert runner.step_locks("start") == ()
    assert runner_module.account_step_locks(step) == held


def test_details_carry_the_live_reads(runner, monkeypatch):
    class Reader:
        def sessions(self):
            return [{"username": "neutrino_ann"}]

        def disk_usage(self, config):
            return [{"share": share.name} for share in config.shares]

    monkeypatch.setattr(runner_module, "SambaStatusReader", Reader)
    runner.apply(CONFIG)

    details = runner.details({})

    assert details["is_active"] is True
    assert details["sessions"] == [{"username": "neutrino_ann"}]
    assert details["disk_usage"] == [{"share": "share"}]


def test_the_password_verb_is_gone(runner):
    outcome = runner.command("set_password", {"name": "neutrino_ann", "password": "x"})

    assert outcome["code"] == "verb_unknown"


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


def test_apply_hands_the_applier_each_users_file(runner):
    runner.apply(
        {
            **CONFIG,
            "shares": [
                {
                    "name": "ann",
                    "path": "/home/ann",
                    "valid_users": ["neutrino_ann"],
                    "force_user": "ann",
                }
            ],
        }
    )

    assert FakeApplier.user_files == {
        "neutrino_ann.conf": SAMBA_CONF_MARKER + "\n   force user = ann\n"
    }


def test_removing_the_configuration_goes_through_the_applier_each_time(runner):
    runner.remove_configuration()
    runner.remove_configuration()

    assert FakeApplier.withdrawals == 2


# --- a person's Samba and the module's ---


RECIPE = {
    "params": {
        "packages": ["samba"],
        "uninstall": {"packages": ["samba"], "post_uninstall": []},
    }
}


def samba_on_path(monkeypatch, *, is_there: bool) -> None:
    monkeypatch.setattr(
        system_package_module.shutil,
        "which",
        lambda name: "/usr/sbin/smbd" if is_there else None,
    )


class RemovingPlatform(RecordingPlatform):
    """A system whose package manager's runs are recorded."""

    def __init__(self, var_dir):
        super().__init__(var_dir)
        self.removed: list = []
        self.install_refusal = None
        self.on_install = None

    def install_system_packages(self, names):
        self.installed.append(list(names))
        if self.on_install is not None:
            self.on_install()
        if self.install_refusal is not None:
            raise self.install_refusal
        return ""

    def remove_system_packages(self, names):
        self.removed.append(list(names))
        return ""


@pytest.fixture
def packaged(runner, tmp_path):
    runner._platform = RemovingPlatform(tmp_path)
    return runner


def test_an_install_that_finds_no_samba_installs_it_and_records_it_as_the_modules(
    packaged, monkeypatch
):
    samba_on_path(monkeypatch, is_there=False)
    recorded: list = []

    def arrive():
        recorded.append(runner_module.is_package_ours(str(packaged.record_path)))
        samba_on_path(monkeypatch, is_there=True)

    packaged._platform.on_install = arrive

    packaged.install(RECIPE)

    assert packaged._platform.installed == [["samba"]]
    assert recorded == [True]
    assert runner_module.is_package_ours(str(packaged.record_path)) is True
    assert packaged.is_software_kept() is False


def test_an_install_takes_down_both_units_its_package_started(packaged, monkeypatch):
    """Ubuntu's samba starts and enables smbd and nmbd. The module's Samba stays
    down until a Start, across a reboot too."""
    samba_on_path(monkeypatch, is_there=False)
    started: list = []

    def arrive():
        started.extend(FakeUnits.calls)
        samba_on_path(monkeypatch, is_there=True)

    packaged._platform.on_install = arrive

    packaged.install(RECIPE)

    assert started == []
    assert FakeUnits.calls == [(SERVER_UNIT, "stop"), (NAME_UNIT, "stop")]


def test_a_failed_install_that_left_samba_takes_its_units_down(packaged, monkeypatch):
    samba_on_path(monkeypatch, is_there=False)

    def arrive():
        samba_on_path(monkeypatch, is_there=True)

    packaged._platform.on_install = arrive
    packaged._platform.install_refusal = OSError("a later package failed")

    with pytest.raises(OSError):
        packaged.install(RECIPE)

    assert FakeUnits.calls == [(SERVER_UNIT, "stop"), (NAME_UNIT, "stop")]


def test_an_install_that_finds_samba_runs_no_package_manager_and_records_nothing(
    packaged, monkeypatch
):
    samba_on_path(monkeypatch, is_there=True)

    packaged.install(RECIPE)

    assert packaged._platform.installed == []
    assert runner_module._read_record(str(packaged.record_path)) == {"is_swept": True}
    assert packaged.is_software_kept() is True
    assert FakeUnits.calls == []


STOCK_CONF = b"[global]\n   server role = standalone server\n"


@pytest.fixture
def smb_conf(monkeypatch, tmp_path):
    """``smb.conf`` under tmp_path. The fake applier's start writes the stock file
    on a machine with none, as the real one does."""
    path = tmp_path / "smb.conf"
    monkeypatch.setattr(applier_module, "SAMBA_CONF_PATH", str(path))

    def start(self):
        FakeApplier.starts += 1
        if not path.exists():
            path.write_bytes(STOCK_CONF)

    monkeypatch.setattr(FakeApplier, "start", start)
    return path


def test_an_uninstall_removes_the_smb_conf_the_module_made_on_its_own_samba(
    packaged, smb_conf, monkeypatch
):
    samba_on_path(monkeypatch, is_there=True)
    mark_package_ours(packaged)
    packaged.start()
    assert smb_conf.read_bytes() == STOCK_CONF
    samba_on_path(monkeypatch, is_there=False)
    packaged.remove_configuration()

    packaged.uninstall(RECIPE)

    assert not smb_conf.exists()
    assert not packaged.record_path.exists()


def test_an_uninstall_removes_the_smb_conf_the_module_made_on_a_persons_samba(
    packaged, smb_conf, monkeypatch
):
    samba_on_path(monkeypatch, is_there=True)
    packaged.start()
    packaged.remove_configuration()

    packaged.uninstall(RECIPE)

    assert not smb_conf.exists()
    assert packaged._platform.removed == []
    assert not packaged.record_path.exists()


def test_an_uninstall_keeps_an_smb_conf_edited_after_the_module_made_it(
    packaged, smb_conf, monkeypatch
):
    samba_on_path(monkeypatch, is_there=True)
    packaged.start()
    smb_conf.write_bytes(STOCK_CONF + b"   workgroup = HOME\n")
    packaged.remove_configuration()

    packaged.uninstall(RECIPE)

    assert smb_conf.exists()
    assert not packaged.record_path.exists()


def test_an_uninstall_keeps_an_smb_conf_the_module_did_not_make(
    packaged, smb_conf, monkeypatch
):
    samba_on_path(monkeypatch, is_there=True)
    smb_conf.write_bytes(STOCK_CONF)
    packaged.start()
    packaged.remove_configuration()

    packaged.uninstall(RECIPE)

    assert smb_conf.read_bytes() == STOCK_CONF


def test_an_apply_that_makes_the_smb_conf_keeps_its_digest(
    packaged, smb_conf, monkeypatch
):
    def apply(self, rendered, **kw):
        smb_conf.write_bytes(STOCK_CONF + b"   include = /etc/samba/neutrino.conf\n")
        return "written"

    monkeypatch.setattr(FakeApplier, "apply", apply)
    samba_on_path(monkeypatch, is_there=True)

    packaged.apply(CONFIG)

    record = json.loads(packaged.record_path.read_text())
    assert (
        record[runner_module.WRITTEN_CONF_KEY] == hashlib.sha256(STOCK_CONF).hexdigest()
    )


def test_a_failed_install_that_leaves_no_samba_records_nothing(packaged, monkeypatch):
    samba_on_path(monkeypatch, is_there=False)
    packaged._platform.install_refusal = OSError("no network")

    with pytest.raises(OSError):
        packaged.install(RECIPE)

    assert runner_module._read_record(str(packaged.record_path)) == {"is_swept": True}


def test_a_failed_install_that_left_samba_stays_the_modules_and_runs_again(
    packaged, monkeypatch
):
    samba_on_path(monkeypatch, is_there=False)

    def arrive():
        samba_on_path(monkeypatch, is_there=True)

    packaged._platform.on_install = arrive
    packaged._platform.install_refusal = OSError("post-install failed")
    with pytest.raises(OSError):
        packaged.install(RECIPE)
    assert runner_module.is_package_ours(str(packaged.record_path)) is True

    packaged._platform.install_refusal = None
    packaged.install(RECIPE)

    assert packaged._platform.installed == [["samba"], ["samba"]]


def test_an_uninstall_with_no_samba_on_the_machine_leaves_no_uninstalled_mark(
    linux, monkeypatch, tmp_path
):
    """A failed install left nothing: a Samba a person installs later reads installed."""
    engine, platform = linux
    samba_on_path(monkeypatch, is_there=False)
    absent = linux_entry("absent")
    engine.take_state({"samba": absent})
    engine.keep_install_mark("samba")

    run_steps(engine.uninstall_steps("samba", absent))

    assert not (tmp_path / "uninstalled").exists()
    assert platform.removed == []


def test_a_first_apply_under_stopped_on_a_person_s_samba_withdraws_once(
    runner, tmp_path
):
    (tmp_path / "samba.json").unlink()

    runner.apply_stopped(CONFIG)

    assert FakeUsers.sweeps == 1
    assert FakeApplier.removals == 0
    assert FakeApplier.withdrawals == 1


def test_a_later_apply_keeps_the_mark_that_the_module_installed_samba(runner):
    mark_package_ours(runner)

    runner.apply(CONFIG)
    runner.apply(dict(CONFIG, passwords={"neutrino_ann": "another"}))
    runner.apply_stopped(CONFIG)

    assert runner_module.is_package_ours(str(runner.record_path)) is True


def test_an_uninstall_of_a_person_s_samba_removes_no_package(packaged):
    packaged.uninstall(RECIPE)

    assert packaged._platform.removed == []


def test_an_uninstall_of_the_module_s_samba_removes_the_package_and_forgets_it(
    packaged,
):
    mark_package_ours(packaged)
    packaged.remove_configuration()

    packaged.uninstall(RECIPE)

    assert packaged._platform.removed == [["samba"]]
    assert not packaged.record_path.exists()


@pytest.mark.parametrize("is_ours", [False, True], ids=["persons", "modules"])
def test_an_uninstall_deletes_the_neutrino_users_before_any_package_goes(
    packaged, is_ours
):
    if is_ours:
        mark_package_ours(packaged)
    swept_before_the_package: list = []
    platform = packaged._platform

    def removed(names):
        swept_before_the_package.append(FakeUsers.sweeps)
        return ""

    platform.remove_system_packages = removed

    packaged.uninstall(RECIPE)

    assert FakeUsers.sweeps == 1
    assert swept_before_the_package == ([1] if is_ours else [])


def test_a_refused_sweep_leaves_the_package_and_the_mark_for_the_next_press(
    packaged, monkeypatch
):
    def refuse(self):
        raise subprocess.CalledProcessError(8, ["userdel"], stderr="in use")

    monkeypatch.setattr(FakeUsers, "sweep", refuse)
    mark_package_ours(packaged)

    with pytest.raises(subprocess.CalledProcessError):
        packaged.uninstall(RECIPE)

    assert packaged._platform.removed == []
    assert runner_module.is_package_ours(str(packaged.record_path)) is True


FOUND_OFF = {"server": {}, "name_server": {}}


def test_a_stop_on_a_person_s_samba_stops_both_units_and_withdraws_the_shares(runner):
    FakeUnits.states[SERVER_UNIT] = dict(NAME_SERVER_UP)
    runner.apply(CONFIG)
    runner.start()
    assert runner.is_active() is True

    runner.apply_stopped(CONFIG)
    runner.stop()

    assert FakeApplier.withdrawals == 1
    assert FakeApplier.started == [True]
    assert FakeApplier.stops == 1
    assert FakeApplier.is_unit_active is False
    assert (NAME_UNIT, "stop") in FakeUnits.calls
    assert runner.is_active() is False
    assert runner.details({})["is_active"] is False


def test_a_start_on_a_person_s_samba_starts_both_units_with_a_share(runner):
    FakeApplier.is_unit_active = False
    runner.apply_stopped(CONFIG)
    runner.stop()

    runner.apply(CONFIG)
    runner.start()

    assert FakeApplier.starts == 1
    assert FakeApplier.is_unit_active is True
    assert FakeUnits.calls[-1] == (NAME_UNIT, "start")
    assert runner.is_active() is True


def test_a_start_turns_on_a_person_s_samba_that_is_off_with_no_share(runner):
    FakeApplier.is_unit_active = False

    runner.apply({"shares": [], "users": [], "passwords": {}})

    assert FakeApplier.is_unit_active is False
    assert runner.is_active() is False

    runner.start()

    assert FakeApplier.is_unit_active is True
    assert FakeUnits.calls == [(NAME_UNIT, "start")]
    assert runner.is_active() is True


def test_a_person_s_samba_with_no_share_stops_and_reads_stopped(runner):
    empty = {"shares": [], "users": [], "passwords": {}}
    runner.apply(empty)
    runner.start()
    assert runner.is_active() is True

    runner.apply_stopped(empty)
    runner.stop()

    assert FakeApplier.is_unit_active is False
    assert runner.is_active() is False


@pytest.mark.parametrize(
    "config", [CONFIG, {"shares": [], "users": [], "passwords": {}}], ids=["one", "no"]
)
def test_a_person_s_smbd_stopped_by_hand_reads_stopped_with_any_share(runner, config):
    runner.apply(config)
    runner.start()

    FakeApplier.is_unit_active = False

    assert runner.is_active() is False


def test_a_smbd_the_person_starts_after_a_stop_leaves_the_module_stopped(runner):
    runner.apply_stopped(CONFIG)
    runner.stop()

    FakeApplier.is_unit_active = True

    assert runner.is_active() is False


def test_an_apply_starts_no_unit(runner):
    FakeApplier.is_unit_active = False

    runner.apply(CONFIG)

    assert FakeApplier.is_unit_active is False
    assert FakeApplier.starts == 0
    assert FakeUnits.calls == []
    assert "found_units" not in json.loads(runner.record_path.read_text())


def test_the_first_start_keeps_what_both_units_were_and_a_second_keeps_that(runner):
    FakeUnits.states[SERVER_UNIT] = {"is_enabled": True, "is_active": False}
    FakeUnits.states[NAME_UNIT] = {"is_enabled": False, "is_active": False}
    FakeApplier.is_unit_active = False
    runner.apply(CONFIG)

    runner.start()
    runner.stop()
    runner.apply(CONFIG)
    runner.start()

    assert json.loads(runner.record_path.read_text())["found_units"] == {
        "server": {"is_enabled": True, "is_active": False},
        "name_server": {"is_enabled": False, "is_active": False},
    }


def test_a_stop_on_a_machine_with_no_first_start_keeps_what_both_units_are(runner):
    FakeUnits.states[SERVER_UNIT] = dict(NAME_SERVER_UP)
    runner.apply_stopped(CONFIG)

    runner.stop()

    record = json.loads(runner.record_path.read_text())
    assert record["found_units"]["server"] == NAME_SERVER_UP


def test_a_stop_of_a_person_s_samba_that_does_not_run_leaves_both_units_as_they_are(
    runner,
):
    """The person enabled smbd for the next boot and stopped it; nmbd runs."""
    FakeApplier.is_unit_active = False
    FakeUnits.states[SERVER_UNIT] = {"is_enabled": True, "is_active": False}
    FakeUnits.states[NAME_UNIT] = {"is_enabled": True, "is_active": True}

    runner.apply_stopped({"shares": [], "users": [], "passwords": {}})
    runner.stop()

    assert FakeApplier.stops == 0
    assert FakeUnits.calls == []
    record = json.loads(runner.record_path.read_text())
    assert "found_units" not in record
    assert record["is_served"] is False
    assert runner.is_active() is False


def test_a_share_on_a_running_module_starts_nothing_and_the_last_going_moves_nothing(
    runner,
):
    FakeApplier.is_unit_active = False
    empty = {"shares": [], "users": [], "passwords": {}}
    runner.apply(empty)
    runner.start()
    FakeUnits.calls = []

    runner.apply(CONFIG)
    runner.apply(empty)

    assert FakeApplier.starts == 1
    assert FakeApplier.stops == 0
    assert FakeApplier.is_unit_active is True
    assert FakeUnits.calls == []


def test_a_stop_is_not_refused_by_a_share_of_the_person_s_of_the_same_name(runner):
    FakeReader.persons = ({}, [{"name": "SHARE", "path": "/p", "params": {}}])

    runner.apply_stopped(CONFIG)

    assert FakeApplier.withdrawals == 1


class LinuxPlatform(RemovingPlatform):
    """A Linux machine as the engine builds its runners for it."""

    capabilities = frozenset({"packages"})


def linux_entry(want: str) -> dict:
    """The file share's entry in a state, as the hub composes it on Linux."""
    return {
        "want": want,
        "config": CONFIG,
        "install": {
            "runner": "samba",
            "method": "system",
            "params": {
                "version": "system",
                "packages": ["samba"],
                "verify": "smbd -V",
                "uninstall": {"packages": ["samba"], "post_uninstall": []},
            },
        },
    }


@pytest.fixture
def linux(runner, monkeypatch, tmp_path):
    """An engine on Linux whose verify command runs the runner's own check."""
    platform = LinuxPlatform(tmp_path)
    engine = ModuleEngine(
        platform=platform,
        log=lambda message: None,
        configured_dir=str(tmp_path / "configured"),
    )
    (tmp_path / "configured" / "samba").unlink()
    samba = engine.module_runners["samba"]
    monkeypatch.setattr(
        engine_module,
        "verify_passes",
        lambda command, environment=None: samba.verify({}),
    )
    monkeypatch.setattr(
        runner_module,
        "SambaStatusReader",
        lambda: type(
            "Reader",
            (),
            {
                "sessions": lambda self: [],
                "disk_usage": lambda self, config: [],
            },
        )(),
    )
    return engine, platform


def configure(engine, want: str) -> None:
    entry = linux_entry(want)
    engine.take_state({"samba": entry})
    run_steps(engine.configure_steps("samba", entry, want))
    engine.mark_configured("samba")


def test_a_person_s_samba_stops_starts_uninstalls_and_installs_again_through_the_engine(
    linux, monkeypatch, tmp_path
):
    engine, platform = linux
    samba_on_path(monkeypatch, is_there=True)

    configure(engine, "running")
    assert row_of(engine)["state"] == "running"

    configure(engine, "stopped")
    assert row_of(engine)["state"] == "stopped"
    assert FakeApplier.is_unit_active is False

    configure(engine, "running")
    assert row_of(engine)["state"] == "running"
    assert FakeApplier.is_unit_active is True

    absent = linux_entry("absent")
    engine.take_state({"samba": absent})
    run_steps(engine.uninstall_steps("samba", absent))

    assert platform.removed == []
    row = row_of(engine)
    assert (row["state"], row["code"]) == ("absent", "")
    assert engine.is_installed("samba", absent) is False

    engine.take_state({"terminal": {"want": "running"}})
    assert row_of(engine)["state"] == "absent"
    restarted = ModuleEngine(
        platform=platform,
        log=lambda message: None,
        configured_dir=str(tmp_path / "configured"),
    )
    assert row_of(restarted)["state"] == "absent"

    installed = linux_entry("installed")
    restarted.take_state({"samba": installed})
    assert restarted.is_installed("samba", installed) is False
    run_steps(restarted.install_steps("samba", installed))

    assert platform.installed == []
    assert not (tmp_path / "uninstalled" / "samba").exists()
    assert row_of(restarted)["state"] == "installed"
    assert restarted.module_runners["samba"].is_software_kept() is True


def test_a_join_that_adopts_a_person_s_samba_stopped_changes_no_unit(
    linux, monkeypatch, tmp_path
):
    engine, _ = linux
    samba_on_path(monkeypatch, is_there=True)
    samba = engine.module_runners["samba"]
    FakeApplier.is_unit_active = False
    FakeUnits.states[samba.unit] = {"is_enabled": True, "is_active": False}

    configure(engine, "stopped")

    assert row_of(engine)["state"] == "stopped"
    assert FakeUnits.calls == []
    assert FakeApplier.stops == 0

    configure(engine, "running")

    assert row_of(engine)["state"] == "running"
    record = json.loads((tmp_path / runner_module.SAMBA_RECORD_NAME).read_text())
    assert record["found_units"]["server"] == {
        "is_enabled": True,
        "is_active": False,
    }


def test_an_uninstall_puts_a_person_s_units_back_as_the_first_start_found_them(
    linux, monkeypatch, tmp_path
):
    engine, _ = linux
    samba_on_path(monkeypatch, is_there=True)
    samba = engine.module_runners["samba"]
    FakeApplier.is_unit_active = False
    FakeUnits.states[samba.unit] = {}
    FakeUnits.states[samba_name_unit("")] = {}

    configure(engine, "running")
    assert FakeApplier.is_unit_active is True
    assert FakeUnits.states[samba_name_unit("")]["is_active"] is True

    absent = linux_entry("absent")
    engine.take_state({"samba": absent})
    run_steps(engine.uninstall_steps("samba", absent))

    put_back = [call for call in FakeUnits.calls if call[1] == "put_back"]
    assert [call[2] for call in put_back] == [{}, {}]
    assert not (tmp_path / runner_module.SAMBA_RECORD_NAME).exists()


def test_an_uninstall_with_no_record_leaves_a_person_s_units_as_they_are(
    linux, monkeypatch
):
    engine, _ = linux
    samba_on_path(monkeypatch, is_there=True)
    FakeApplier.is_unit_active = True

    absent = linux_entry("absent")
    engine.take_state({"samba": absent})
    run_steps(engine.uninstall_steps("samba", absent))

    assert FakeUnits.calls == []
    assert FakeApplier.stops == 0
    assert FakeApplier.is_unit_active is True


def test_an_uninstall_of_a_module_with_no_first_start_ends_with_units_as_it_found(
    linux, monkeypatch
):
    """A machine an earlier build configured: the stop the uninstall runs keeps them first."""
    engine, _ = linux
    samba_on_path(monkeypatch, is_there=True)
    samba = engine.module_runners["samba"]
    engine.mark_configured("samba")
    FakeUnits.states[samba.unit] = {"is_enabled": True, "is_active": True}

    absent = linux_entry("absent")
    engine.take_state({"samba": absent})
    run_steps(engine.uninstall_steps("samba", absent))

    assert (samba.unit, "put_back", {"is_enabled": True, "is_active": True}) in (
        FakeUnits.calls
    )


def test_a_samba_the_module_installed_is_taken_off_with_its_package_through_the_engine(
    linux, monkeypatch, tmp_path
):
    engine, platform = linux
    samba_on_path(monkeypatch, is_there=False)

    def arrive():
        samba_on_path(monkeypatch, is_there=True)

    def leave(names):
        platform.removed.append(list(names))
        samba_on_path(monkeypatch, is_there=False)
        return ""

    platform.on_install = arrive
    platform.remove_system_packages = leave
    installed = linux_entry("installed")
    engine.take_state({"samba": installed})
    run_steps(engine.install_steps("samba", installed))
    assert platform.installed == [["samba"]]

    configure(engine, "running")
    configure(engine, "stopped")
    assert FakeApplier.stops == 1
    assert FakeApplier.is_unit_active is False
    assert row_of(engine)["state"] == "stopped"

    configure(engine, "running")
    assert FakeApplier.is_unit_active is True
    assert row_of(engine)["state"] == "running"

    absent = linux_entry("absent")
    engine.take_state({"samba": absent})
    run_steps(engine.uninstall_steps("samba", absent))

    assert platform.removed == [["samba"]]
    assert not (tmp_path / "uninstalled").exists()
    assert not (tmp_path / runner_module.SAMBA_RECORD_NAME).exists()
    assert row_of(engine)["state"] == "absent"

    samba_on_path(monkeypatch, is_there=True)
    assert engine.module_runners["samba"].is_software_kept() is True


def test_samba_a_person_installs_while_the_mark_stands_is_absent_until_an_install(
    linux, monkeypatch
):
    """The press and its verify end the mark, whoever put Samba there."""
    engine, platform = linux
    samba_on_path(monkeypatch, is_there=True)
    absent = linux_entry("absent")
    engine.take_state({"samba": absent})
    run_steps(engine.uninstall_steps("samba", absent))
    samba_on_path(monkeypatch, is_there=False)
    assert row_of(engine)["state"] == "absent"

    def arrive():
        samba_on_path(monkeypatch, is_there=True)

    platform.on_install = arrive
    installed = linux_entry("installed")
    engine.take_state({"samba": installed})
    run_steps(engine.install_steps("samba", installed))

    assert platform.installed == [["samba"]]
    assert engine.module_runners["samba"].is_software_kept() is False
    assert row_of(engine)["state"] == "installed"


# --- what a hand-written file share observes as ---


def observed(runner) -> dict:
    """The runner read as the engine reads a module the state does not name:
    its own check, then its unit and its details while the check passes."""
    is_installed = bool(runner.verify({}))
    return {
        "is_installed": is_installed,
        "is_active": bool(runner.is_active()) if is_installed else False,
        "details": runner.details({}) if is_installed else {},
    }


def samba_commands(monkeypatch, *, accounts=("neutrino_ann",)):
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

    observed_now = observed(runner)

    assert (observed_now["is_installed"], observed_now["is_active"]) == (True, True)
    details = observed_now["details"]
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
    # Every account of the module's prefix Samba holds a credential for,
    # whether or not the hub configured it, with the unix account's presence
    # beside it, and no other.
    assert details["users"] == [
        {"name": "neutrino_ann", "is_present": True, "has_password": True},
        {"name": "neutrino_bob", "is_present": False, "has_password": True},
    ]
    assert details["sessions"] == []
    assert ["testparm", "-s", applier_module.SAMBA_CONF_PATH] in asked
    assert ["pdbedit", "-L"] in asked


def test_observe_lists_the_configured_users_first_then_the_rest(runner, monkeypatch):
    runner.apply(
        {
            **CONFIG,
            "users": ["neutrino_carol", "neutrino_ann"],
            "passwords": {"neutrino_carol": "c", "neutrino_ann": "a"},
        }
    )
    samba_commands(monkeypatch, accounts=("neutrino_ann", "neutrino_carol"))

    users = observed(runner)["details"]["users"]

    assert [user["name"] for user in users] == [
        "neutrino_carol",
        "neutrino_ann",
        "neutrino_bob",
    ]
    assert users[0] == {
        "name": "neutrino_carol",
        "is_present": True,
        "has_password": False,
    }


def test_observe_of_a_machine_without_samba_reads_nothing(runner, monkeypatch):
    samba_commands(monkeypatch)
    monkeypatch.setattr(applier_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_package_module.shutil, "which", lambda name: None)

    observed_now = observed(runner)

    assert observed_now == {"is_installed": False, "is_active": False, "details": {}}


class FakeNativeApplier:
    """The system server's applier, recording each call with its record."""

    def __init__(self):
        self.missing: set = set()
        self.links: set = set()
        # The shares the server refuses to make, by name, with its words.
        self.refusing: dict = {}
        self.calls: list = []
        self.sweeps: list = []
        self.earlier_accounts: list = []
        self.served: list = []
        self.status = {"is_present": True, "is_running": True, "shares": []}
        self.reads = 0
        self.error = None
        self.server = {"start_type": "Automatic", "is_running": True}
        self.dependents: list = []
        self.stop_refusal = None

    def read_folder(self, path):
        if path in self.missing:
            return "missing"
        return "link" if path in self.links else "folder"

    def read_server(self):
        return dict(self.server)

    def read_server_dependents(self):
        return list(self.dependents)

    def stop_server(self):
        self.calls.append(("stop_server",))
        if self.stop_refusal is not None:
            self.dependents = []
            raise self.stop_refusal
        self.status = dict(self.status, is_running=False)
        self.dependents = []

    def put_back_server(self, found, dependents):
        self.calls.append(("put_back_server", found, dependents))
        self.status = dict(self.status, is_running=bool(found.get("is_running")))

    def read_status(self, record):
        self.reads += 1
        return dict(self.status)

    def sweep(self, folders, *, is_served, earlier_accounts=()):
        self.sweeps.append((list(folders), is_served, len(self.calls)))
        self.earlier_accounts.append(list(earlier_accounts))
        return ["swept account neutrino_old"]

    def apply(self, config, record, *, is_served=True, refused=None, sids=None):
        self.calls.append(("apply", config.to_dict(), record))
        self.served.append(is_served)
        if sids is not None:
            sids.update({name: f"S-{name}" for name in config.users})
        if self.error is not None:
            raise self.error
        if is_served:
            self.status = dict(self.status, is_running=True)
        for share in config.served_shares():
            if share.name in self.refusing and refused is not None:
                refused.append(
                    {
                        "code": "share_not_served",
                        "params": {
                            "name": share.name,
                            "detail": self.refusing[share.name],
                        },
                    }
                )
        return ["created share share"]

    def withdraw(self, record, *, is_removed):
        self.calls.append(("withdraw", record, is_removed))

    def set_password(self, name, password):
        self.calls.append(("set_password", name, password))

    def read_server_log(self, lines):
        return ["10:00 1001 A client connected.", "10:05 1002 A client left."]


class NativeServerPlatform(RecordingPlatform):
    """A system that carries its own SMB server, the way Windows does."""

    os_name = "windows"
    capabilities = frozenset({"smb_server"})

    def __init__(self, var_dir):
        super().__init__(var_dir)
        self.applier = FakeNativeApplier()
        self.log_path = ""

    def smb_server_applier(self):
        return self.applier

    def agent_log_path(self):
        return self.log_path


FOUND_SERVER = {"start_type": "Automatic", "is_running": True}
WINDOWS_CONFIG = {
    "shares": [{"name": "share", "path": "D:\\share", "valid_users": ["neutrino_ann"]}],
    "users": ["neutrino_ann"],
    "passwords": {"neutrino_ann": "pw"},
}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def native(tmp_path):
    (tmp_path / "configured").mkdir()
    (tmp_path / "configured" / "samba").write_text("")
    (tmp_path / "samba_native.json").write_text('{"is_swept": true}')
    platform = NativeServerPlatform(tmp_path)
    clock = Clock()
    held = SambaNativeServerRunner(platform=platform, log=lambda m: None, clock=clock)
    held.applier = platform.applier
    held.clock = clock
    assert platform.applier.calls == []
    return held


def record_of(native_runner) -> dict:
    return native_runner._read_record()


def test_a_native_share_whose_folder_is_missing_is_left_off_and_named_on_the_row(
    native,
):
    native.applier.missing = {"D:\\share"}

    native.apply(WINDOWS_CONFIG)

    _name, config, _record = [
        call for call in native.applier.calls if call[0] == "apply"
    ][-1]
    assert config["shares"] == []
    assert config["users"] == ["neutrino_ann"]
    assert native.notice() == {
        "code": "share_path_missing",
        "params": {"name": "share", "path": "D:\\share"},
    }
    assert record_of(native)["shares"] == {}


TWO_WINDOWS_SHARES = {
    "shares": [
        {"name": "share", "path": "D:\\share", "valid_users": ["neutrino_ann"]},
        {"name": "media", "path": "D:\\media", "valid_users": ["neutrino_ann"]},
        {"name": "lab", "path": "D:\\lab", "valid_users": ["neutrino_ann"]},
    ],
    "users": ["neutrino_ann"],
    "passwords": {"neutrino_ann": "pw"},
}


def test_a_native_share_the_server_refuses_is_left_off_and_the_rest_served(native):
    """One share that cannot be served never stops the others (R146 F1)."""
    native.applier.links = {"D:\\lab"}
    native.applier.refusing = {"media": "The path is not a directory."}

    native.apply(TWO_WINDOWS_SHARES)

    _name, config, _record = [
        call for call in native.applier.calls if call[0] == "apply"
    ][-1]
    assert [share["name"] for share in config["shares"]] == ["share", "media"]
    assert native.notice() == {
        "code": "share_not_served",
        "params": {"name": "media", "detail": "The path is not a directory."},
    }
    native.applier.refusing = {}
    native.apply(TWO_WINDOWS_SHARES)
    assert native.notice() == {
        "code": "share_path_link",
        "params": {"name": "lab", "path": "D:\\lab"},
    }


def test_the_native_folder_verb_reads_a_windows_path(native):
    native.applier.missing = {"D:\\gone"}

    found = native.command("folder", {"path": "D:\\gone"})
    real = native.command("folder", {"path": "D:\\share"})
    relative = native.command("folder", {"path": "/srv/share"})

    assert (found["code"], found["params"]) == (
        "share_path_missing",
        {"path": "D:\\gone"},
    )
    assert (real["exit_code"], real["code"]) == (0, "")
    assert relative["code"] == "path_invalid"
    assert [call for call in native.applier.calls if call[0] == "apply"] == []


def test_a_native_folder_gone_and_made_again_asks_for_a_task_each_time(native):
    native.take_config(TWO_WINDOWS_SHARES)
    native.apply(TWO_WINDOWS_SHARES)
    asked: list = []
    native.bind_configure_asker(lambda: asked.append("samba"))
    native.applier.missing = {"D:\\media"}
    native.clock.now += 31

    native.details({})
    native.details({})
    native.apply(TWO_WINDOWS_SHARES)
    gone = native.notice()
    native.applier.missing = set()
    native.clock.now += 31
    native.details({})
    native.apply(TWO_WINDOWS_SHARES)

    assert asked == ["samba", "samba"]
    assert gone == {
        "code": "share_path_missing",
        "params": {"name": "media", "path": "D:\\media"},
    }
    _name, config, _record = [
        call for call in native.applier.calls if call[0] == "apply"
    ][-1]
    assert [share["name"] for share in config["shares"]] == ["share", "media", "lab"]
    assert native.notice() == {}


def test_a_native_folder_turned_into_a_link_asks_for_a_configure_task(native):
    native.take_config(TWO_WINDOWS_SHARES)
    native.apply(TWO_WINDOWS_SHARES)
    asked: list = []
    native.bind_configure_asker(lambda: asked.append("samba"))
    native.applier.links = {"D:\\lab"}
    native.clock.now += 31

    native.details({})
    native.details({})

    assert asked == ["samba"]


def test_the_native_server_s_account_steps_take_system_accounts(native):
    assert native.step_locks("configure") == (("system_accounts", "alone"),)
    assert native.step_locks("uninstall") == (("system_accounts", "alone"),)
    assert native.step_locks("verify") == ()


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

    (verb, config, record), password = native.applier.calls
    assert verb == "apply"
    assert password == ("set_password", "neutrino_ann", "pw")
    assert config == SambaConfig.from_dict(WINDOWS_CONFIG).to_dict()
    assert record["shares"] == {"share": "D:\\share"}
    assert record_of(native) == {
        "shares": {"share": "D:\\share"},
        "accounts": ["neutrino_ann"],
        "passwords": {"neutrino_ann": password_digest("pw")},
        "is_served": True,
        "is_swept": True,
        "sids": {"neutrino_ann": "S-neutrino_ann"},
        "found_server": FOUND_SERVER,
    }
    assert native.is_active() is True


def test_a_native_record_s_name_without_the_prefix_is_no_account_of_the_module(native):
    """An older record can name a person's account: the applier never hears of it."""
    with open(native._record_path, "w", encoding="utf-8") as stream:
        json.dump({"accounts": ["anna", "neutrino_ann"], "shares": {}}, stream)

    assert record_of(native)["accounts"] == ["neutrino_ann"]

    native.remove_configuration()

    assert native.applier.calls[-1][1]["accounts"] == ["neutrino_ann"]
    assert record_of(native)["accounts"] == ["neutrino_ann"]


def test_a_record_write_waits_for_a_read_that_holds_the_record_open(
    native, monkeypatch
):
    native.apply(WINDOWS_CONFIG)
    reading, released = threading.Event(), threading.Event()
    loaded = json.load

    def slow_load(stream):
        reading.set()
        released.wait(5)
        return loaded(stream)

    monkeypatch.setattr(runner_module.json, "load", slow_load)
    reader = threading.Thread(target=native._read_record)
    reader.start()
    assert reading.wait(5)
    writer = threading.Thread(
        target=native._write_record, args=({"shares": {}, "is_served": False},)
    )
    writer.start()
    writer.join(0.2)

    assert writer.is_alive()
    released.set()
    reader.join(5)
    writer.join(5)
    monkeypatch.setattr(runner_module.json, "load", loaded)
    assert record_of(native)["is_served"] is False


def test_a_failed_apply_still_lists_the_shares_it_may_have_made(native):
    native.applier.error = OSError("New-SmbShare : Access is denied.")

    with pytest.raises(ModuleApplyError) as refused:
        native.apply(WINDOWS_CONFIG)

    assert refused.value.code == "apply_failed"
    assert "Access is denied" in refused.value.params["detail"]
    assert record_of(native)["shares"] == {"share": "D:\\share"}
    assert record_of(native)["accounts"] == []


def test_a_refusal_from_the_server_keeps_its_code(native):
    native.applier.error = ModuleApplyError("user_name_taken", {"user": "neutrino_ann"})

    with pytest.raises(ModuleApplyError) as refused:
        native.apply(WINDOWS_CONFIG)

    assert refused.value.code == "user_name_taken"


def test_a_path_is_checked_for_the_system_that_serves_it(native):
    with pytest.raises(ModuleApplyError) as refused:
        native.validate({**WINDOWS_CONFIG, "shares": [{"name": "s", "path": "/srv"}]})

    assert refused.value.code == "share_path_relative"
    assert native.applier.calls == []


def test_stopping_withdraws_the_shares_and_the_row_reads_stopped(native):
    native.apply(WINDOWS_CONFIG)

    native.stop()

    assert native.applier.calls[-2:] == [
        (
            "withdraw",
            {
                "shares": {"share": "D:\\share"},
                "accounts": ["neutrino_ann"],
                "passwords": {"neutrino_ann": password_digest("pw")},
                "is_served": True,
                "is_swept": True,
                "sids": {"neutrino_ann": "S-neutrino_ann"},
                "found_server": FOUND_SERVER,
            },
            False,
        ),
        ("stop_server",),
    ]
    assert record_of(native) == {
        "shares": {"share": "D:\\share"},
        "accounts": ["neutrino_ann"],
        "passwords": {"neutrino_ann": password_digest("pw")},
        "is_served": False,
        "is_swept": True,
        "sids": {"neutrino_ann": "S-neutrino_ann"},
        "found_server": FOUND_SERVER,
    }
    assert native.is_active() is False


def test_a_native_module_with_no_share_reads_running_and_stops_its_server(native):
    empty = {"shares": [], "users": [], "passwords": {}}

    native.apply(empty)
    assert native.is_active() is True

    native.stop()

    assert native.applier.calls[-1] == ("stop_server",)
    assert native.is_active() is False


def test_the_first_native_start_keeps_what_the_server_was_and_a_second_keeps_that(
    native,
):
    native.applier.server = {"start_type": "Manual", "is_running": False}
    native.apply(WINDOWS_CONFIG)
    native.applier.server = {"start_type": "Automatic", "is_running": True}

    native.apply(WINDOWS_CONFIG)

    assert record_of(native)["found_server"] == {
        "start_type": "Manual",
        "is_running": False,
    }


def test_a_native_stop_on_a_machine_with_no_first_start_keeps_what_the_server_is(
    native,
):
    native.stop()

    assert record_of(native)["found_server"] == FOUND_SERVER


EMPTY_NATIVE_CONFIG = {"shares": [], "users": [], "passwords": {}}


def test_a_server_on_with_no_mark_reads_running(native):
    os.unlink(native._record_path)

    assert native.is_active() is True
    assert native.details({})["is_active"] is True


def test_a_server_off_with_no_mark_reads_stopped(native):
    native.applier.status = dict(native.applier.status, is_running=False)

    assert native.is_active() is False


def test_the_first_configure_of_a_server_on_keeps_it_and_reads_running(native):
    native.apply(EMPTY_NATIVE_CONFIG)
    native.start()

    assert record_of(native)["found_server"] == FOUND_SERVER
    assert native.is_active() is True
    assert ("stop_server",) not in native.applier.calls


def test_a_server_on_when_the_module_took_it_comes_back_after_stop_and_uninstall(
    native,
):
    native.apply(EMPTY_NATIVE_CONFIG)
    native.applier.server = {"start_type": "Disabled", "is_running": False}
    native.stop()
    native.remove_configuration()

    native.uninstall({})

    assert native.applier.calls[-1] == ("put_back_server", FOUND_SERVER, [])
    assert "found_server" not in record_of(native)
    assert native.is_active() is True


def test_a_server_off_is_left_alone_by_the_stopped_module_s_first_configure(native):
    off = {"start_type": "Manual", "is_running": False}
    native.applier.status = dict(native.applier.status, is_running=False)
    native.applier.server = dict(off)

    native.apply_stopped(EMPTY_NATIVE_CONFIG)
    native.stop()

    assert ("stop_server",) not in native.applier.calls
    assert not any(call[0] == "withdraw" for call in native.applier.calls)
    assert "found_server" not in record_of(native)
    assert record_of(native)["is_served"] is False
    assert native.is_active() is False


def test_a_server_off_comes_back_off_after_a_start_a_stop_and_an_uninstall(native):
    off = {"start_type": "Manual", "is_running": False}
    native.applier.status = dict(native.applier.status, is_running=False)
    native.applier.server = dict(off)
    native.apply_stopped(EMPTY_NATIVE_CONFIG)
    native.stop()

    native.apply(EMPTY_NATIVE_CONFIG)
    assert record_of(native)["found_server"] == off
    native.stop()
    assert native.applier.calls[-1] == ("stop_server",)
    native.remove_configuration()
    native.uninstall({})

    assert native.applier.calls[-1] == ("put_back_server", off, [])


def test_a_server_the_person_started_by_hand_stays_on_through_a_stopped_configure(
    native,
):
    native.applier.status = dict(native.applier.status, is_running=False)
    native.apply_stopped(EMPTY_NATIVE_CONFIG)
    native.stop()
    native.applier.status = dict(native.applier.status, is_running=True)
    native.clock.now += SAMBA_NATIVE_STATUS_TTL_S + 1

    native.apply_stopped(EMPTY_NATIVE_CONFIG)
    native.stop()

    assert ("stop_server",) not in native.applier.calls
    assert "found_server" not in record_of(native)
    assert native.is_active() is False


def test_a_stop_of_a_server_on_with_no_mark_keeps_what_it_was_and_stops_it(native):
    native.apply_stopped(EMPTY_NATIVE_CONFIG)
    native.stop()

    assert record_of(native)["found_server"] == FOUND_SERVER
    assert native.applier.calls[-1] == ("stop_server",)
    assert native.is_active() is False


def test_an_uninstall_with_no_found_server_drops_the_mark(native):
    native.applier.status = dict(native.applier.status, is_running=False)
    native.apply_stopped(EMPTY_NATIVE_CONFIG)
    native.stop()
    native.remove_configuration()
    native.applier.calls = []

    native.uninstall({})

    assert native.applier.calls == []
    assert "is_served" not in record_of(native)


def test_the_services_a_native_stop_took_down_start_again_with_the_server(native):
    native.applier.dependents = ["Browser"]
    native.apply(WINDOWS_CONFIG)
    native.stop()
    assert record_of(native)["server_dependents"] == ["Browser"]

    native.apply_stopped(WINDOWS_CONFIG)
    assert record_of(native)["server_dependents"] == ["Browser"]

    native.applier.calls = []
    native.apply(WINDOWS_CONFIG)

    assert native.applier.calls[0][2]["server_dependents"] == ["Browser"]
    assert "server_dependents" not in record_of(native)


def test_a_native_stop_that_fails_keeps_the_record_for_a_second_press(native):
    native.apply(WINDOWS_CONFIG)
    native.applier.dependents = ["Browser"]
    native.applier.stop_refusal = OSError("the server will not stop")

    with pytest.raises(OSError):
        native.stop()

    held = record_of(native)
    assert held["is_served"] is True
    assert held["found_server"] == FOUND_SERVER
    assert held["server_dependents"] == ["Browser"]
    assert native.is_active() is True

    native.applier.stop_refusal = None
    native.stop()

    held = record_of(native)
    assert held["is_served"] is False
    assert held["found_server"] == FOUND_SERVER
    assert held["server_dependents"] == ["Browser"]
    assert native.is_active() is False


def test_a_start_after_a_native_stop_that_failed_starts_what_the_stop_took_down(native):
    native.apply(WINDOWS_CONFIG)
    native.applier.dependents = ["Browser"]
    native.applier.stop_refusal = OSError("the server will not stop")
    with pytest.raises(OSError):
        native.stop()
    native.applier.calls = []

    native.apply(WINDOWS_CONFIG)

    assert native.applier.calls[0][2]["server_dependents"] == ["Browser"]
    assert "server_dependents" not in record_of(native)


def test_an_uninstall_after_a_native_stop_that_failed_puts_everything_back(native):
    native.apply(WINDOWS_CONFIG)
    native.applier.dependents = ["Browser"]
    native.applier.stop_refusal = OSError("the server will not stop")
    with pytest.raises(OSError):
        native.stop()
    native.remove_configuration()

    native.uninstall({})

    assert native.applier.calls[-1] == ("put_back_server", FOUND_SERVER, ["Browser"])
    assert "found_server" not in record_of(native)


def test_a_native_uninstall_puts_the_server_back_as_the_first_start_found_it(native):
    native.applier.server = {"start_type": "Manual", "is_running": False}
    native.applier.dependents = ["Browser"]
    native.apply(WINDOWS_CONFIG)
    native.stop()
    native.remove_configuration()

    native.uninstall({})

    assert native.applier.calls[-1] == (
        "put_back_server",
        {"start_type": "Manual", "is_running": False},
        ["Browser"],
    )
    assert "found_server" not in record_of(native)


def test_a_native_uninstall_with_no_record_leaves_the_server_as_it_is(native):
    native.uninstall({})

    assert native.applier.calls == []


def test_a_share_removed_while_stopped_reaches_the_applier_with_its_folder(native):
    native.apply(WINDOWS_CONFIG)
    native.stop()

    native.apply_stopped({**WINDOWS_CONFIG, "shares": []})
    _verb, _config, record = next(
        call for call in reversed(native.applier.calls) if call[0] == "apply"
    )
    assert record["shares"] == {"share": "D:\\share"}
    assert record_of(native)["shares"] == {}


def test_a_share_added_while_stopped_stays_in_the_record_for_its_removal(native):
    native.apply(WINDOWS_CONFIG)
    native.stop()
    probe = {"name": "probe", "path": "D:\\probe", "valid_users": ["neutrino_ann"]}
    added = {**WINDOWS_CONFIG, "shares": [*WINDOWS_CONFIG["shares"], probe]}

    native.apply_stopped(added)
    assert record_of(native)["shares"] == {
        "share": "D:\\share",
        "probe": "D:\\probe",
    }

    native.apply_stopped(WINDOWS_CONFIG)
    _verb, _config, record = next(
        call for call in reversed(native.applier.calls) if call[0] == "apply"
    )
    assert record["shares"]["probe"] == "D:\\probe"
    assert record_of(native)["shares"] == {"share": "D:\\share"}


def test_a_native_configure_under_stopped_serves_no_share_and_reads_stopped(native):
    native.apply(WINDOWS_CONFIG)
    planned = [
        ModuleStep(name="configure", run=lambda context: None),
        ModuleStep(name="stop", run=lambda context: None),
    ]

    steps = native.configure_steps(
        {**WINDOWS_CONFIG, "passwords": {"neutrino_ann": "pw2"}}, "stopped", planned
    )
    steps[0].run(None)

    assert [step.name for step in steps] == ["configure", "stop"]
    assert steps[1] is planned[1]
    assert native.applier.served == [True, False]
    assert native.applier.calls[-2][2]["shares"] == {"share": "D:\\share"}
    assert native.applier.calls[-1] == ("set_password", "neutrino_ann", "pw2")
    assert record_of(native) == {
        "shares": {"share": "D:\\share"},
        "accounts": ["neutrino_ann"],
        "passwords": {"neutrino_ann": password_digest("pw2")},
        "is_served": False,
        "is_swept": True,
        "sids": {"neutrino_ann": "S-neutrino_ann"},
        "found_server": FOUND_SERVER,
    }
    assert native.is_active() is False
    assert native.configure_steps(WINDOWS_CONFIG, "running", planned) == planned


def test_removing_the_configuration_is_a_removal(native):
    native.apply(WINDOWS_CONFIG)

    native.remove_configuration()

    assert native.applier.calls[-1][0] == "withdraw"
    assert native.applier.calls[-1][2] is True
    assert record_of(native)["accounts"] == ["neutrino_ann"]


NATIVE_CONFIGS = {
    "windows": WINDOWS_CONFIG,
    "darwin": {
        "shares": [
            {"name": "share", "path": "/Users/ann", "valid_users": ["neutrino_ann"]}
        ],
        "users": ["neutrino_ann"],
        "passwords": {"neutrino_ann": "pw"},
    },
}


def native_entry(want: str, os_name: str) -> dict:
    """The file share's entry in a state, as the hub composes it on Windows and macOS."""
    return {
        "want": want,
        "config": NATIVE_CONFIGS[os_name],
        "install": {"runner": "samba_native", "method": "builtin", "params": {}},
    }


def native_engine(platform, tmp_path) -> ModuleEngine:
    return ModuleEngine(
        platform=platform,
        log=lambda message: None,
        configured_dir=str(tmp_path / "configured"),
    )


class SilentStepContext:
    """What a step is handed here: its lines go nowhere."""

    def log(self, line):
        pass

    def stop_requiring_modules(self):
        pass


def run_steps(steps) -> None:
    for step in steps:
        assert run_step(step, SilentStepContext()) is None


def row_of(engine) -> dict:
    engine._refresh(is_forced=True)
    return engine.report()["samba"]


@pytest.mark.parametrize("os_name", ["windows", "darwin"])
def test_the_file_share_uninstalls_to_absent_and_installs_again_on_the_system_s_server(
    tmp_path, os_name
):
    platform = NativeServerPlatform(tmp_path)
    platform.os_name = os_name
    engine = native_engine(platform, tmp_path)
    running = native_entry("running", os_name)
    engine.take_state({"samba": running})
    run_steps(engine.configure_steps("samba", running, "running"))
    engine.mark_configured("samba")
    assert row_of(engine)["state"] == "running"

    absent = native_entry("absent", os_name)
    engine.take_state({"samba": absent})
    run_steps(engine.uninstall_steps("samba", absent))

    assert [call[0] for call in platform.applier.calls[-4:]] == [
        "withdraw",
        "stop_server",
        "withdraw",
        "put_back_server",
    ]
    assert platform.applier.status["is_present"] is True
    assert platform.applier.status["is_running"] is True
    row = row_of(engine)
    assert (row["state"], row["code"]) == ("absent", "")

    engine.take_state({"terminal": {"want": "running"}})
    assert row_of(engine)["state"] == "absent"
    restarted = native_engine(platform, tmp_path)
    assert row_of(restarted)["state"] == "absent"

    installed = native_entry("installed", os_name)
    restarted.take_state({"samba": installed})
    run_steps(restarted.install_steps("samba", installed))
    assert row_of(restarted)["state"] == "installed"

    restarted.take_state({"samba": running})
    run_steps(restarted.configure_steps("samba", running, "running"))
    restarted.mark_configured("samba")
    assert row_of(restarted)["state"] == "running"
    # The first configure, the uninstall and the first configure after the
    # install again each sweep, the uninstall on the folder the record kept.
    folder = running["config"]["shares"][0]["path"]
    assert [
        (folders, is_served) for folders, is_served, _ in platform.applier.sweeps
    ] == [
        ([folder], True),
        ([folder], False),
        ([folder], True),
    ]


def password_calls(native) -> list:
    return [call for call in native.applier.calls if call[0] == "set_password"]


def test_a_password_is_set_again_only_when_the_hubs_differs(native):
    native.apply(WINDOWS_CONFIG)
    native.apply(WINDOWS_CONFIG)
    native.apply({**WINDOWS_CONFIG, "passwords": {"neutrino_ann": "pw2"}})

    assert password_calls(native) == [
        ("set_password", "neutrino_ann", "pw"),
        ("set_password", "neutrino_ann", "pw2"),
    ]
    assert "pw2" not in open(native._record_path).read()


def test_a_dropped_user_leaves_the_digests_and_comes_back_with_its_password(native):
    native.apply(WINDOWS_CONFIG)
    native.apply({"shares": [], "users": [], "passwords": {}})

    assert record_of(native)["passwords"] == {}

    native.apply(WINDOWS_CONFIG)
    assert len(password_calls(native)) == 2


def test_a_password_the_server_refused_is_not_recorded(native):
    def refuse(name, password):
        raise OSError("eDSAuthAccountDisabled")

    native.applier.set_password = refuse

    with pytest.raises(ModuleApplyError) as refused:
        native.apply(WINDOWS_CONFIG)

    assert refused.value.code == "apply_failed"
    assert record_of(native)["passwords"] == {}


def test_an_account_the_system_would_not_make_is_passed_over(native):
    native.applier.error = ModuleApplyError(
        "user_create_failed", {"user": "neutrino_ann", "detail": "full name exists"}
    )

    with pytest.raises(ModuleApplyError) as refused:
        native.apply(WINDOWS_CONFIG)

    assert refused.value.code == "user_create_failed"
    assert password_calls(native) == []
    assert record_of(native)["passwords"] == {}


def test_a_removal_forgets_every_password(native):
    native.apply(WINDOWS_CONFIG)

    native.remove_configuration()

    assert record_of(native)["passwords"] == {}


def test_the_password_verb_is_gone_on_the_native_server(native):
    assert native.command("set_password", {"name": "neutrino_ann", "password": "pw"})[
        "code"
    ] == ("verb_unknown")


def test_the_server_is_read_once_per_half_minute_and_after_each_change(native):
    observed(native)
    observed(native)
    assert native.applier.reads == 1

    native.clock.now += 31
    observed(native)
    assert native.applier.reads == 2

    native.apply(WINDOWS_CONFIG)
    observed(native)
    assert native.applier.reads == 3


def test_the_details_have_the_linux_shape_and_no_fence(native):
    native.applier.status = {
        "is_present": True,
        "is_running": True,
        "shares": [{"name": "share", "path": "D:\\share", "params": {}}],
        "users": [{"name": "neutrino_ann", "is_present": True, "has_password": True}],
        "sessions": [],
    }

    details = observed(native)["details"]

    assert set(details) == {
        "is_active",
        "global",
        "shares",
        "users",
        "sessions",
        "disk_usage",
    }
    assert details["global"] == {}


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


@pytest.mark.parametrize("os_name", ["windows", "darwin"])
def test_a_server_log_that_fails_is_warned_of_and_the_agent_s_lines_stay(
    native, tmp_path, os_name
):
    log = tmp_path / "agent.log"
    log.write_text("11:00 samba: unchanged\n", encoding="utf-8")
    native._platform.log_path = str(log)
    native._platform.os_name = os_name

    def fail(lines):
        raise OSError("powershell exited 1")

    def write(message):
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(f"11:01 {message}\n")

    native.applier.read_server_log = fail
    native._log = write

    first = native.command("journal", {"lines": 10})["output"].splitlines()
    second = native.command("journal", {"lines": 10})["output"].splitlines()

    assert first == [
        "11:00 samba: unchanged",
        "11:01 samba: cannot read the log source the SMB server's events: "
        "powershell exited 1",
    ]
    assert second == first


def test_an_account_passed_over_keeps_the_rest_recorded_and_says_why(native):
    """The applier made every other account and share; the record lists
    them so their passwords can be set, and the refusal still surfaces."""
    lines = []
    native._log = lines.append
    native.applier.error = ModuleApplyError(
        "user_record_unusable", {"user": "neutrino_ann", "detail": "eDSPermissionError"}
    )

    with pytest.raises(ModuleApplyError) as refused:
        native.apply(dict(WINDOWS_CONFIG, users=["neutrino_ann", "neutrino_bob"]))

    assert refused.value.code == "user_record_unusable"
    record = record_of(native)
    assert record["accounts"] == ["neutrino_ann", "neutrino_bob"]
    assert record["shares"] == {"share": "D:\\share"}
    assert lines == ["samba: passed over account neutrino_ann"]


def test_a_share_left_out_is_named_on_the_row_until_an_apply_serves_every_share(
    runner,
):
    runner.apply(
        {
            **CONFIG,
            "shares": [
                {
                    "name": "share",
                    "path": "/srv/share",
                    "valid_users": ["neutrino_ann"],
                },
                {"name": "carried", "path": "/srv/c", "valid_users": []},
            ],
        }
    )
    assert runner.notice() == {
        "code": "share_users_unknown",
        "params": {"shares": "carried"},
    }
    assert "[carried]" not in FakeApplier.applied[-1][1]
    assert FakeApplier.served[-1] is True

    runner.apply(CONFIG)

    assert runner.notice() == {}


def test_a_configuration_with_no_served_share_plans_an_unserved_smb_conf(runner):
    runner.apply({"shares": [{"name": "carried", "path": "/srv/c", "valid_users": []}]})

    assert FakeApplier.served == [False]
    assert runner.notice()["params"] == {"shares": "carried"}


def test_a_record_with_a_name_an_earlier_build_gave_sweeps_again(runner, tmp_path):
    """``neutrino-ann`` is old: the first apply with the new names sweeps it
    away and makes ``neutrino_ann``."""
    (tmp_path / "samba.json").write_text(
        '{"is_swept": true, "passwords": {"neutrino-ann": "d"}}'
    )

    runner.apply(CONFIG)
    runner.apply(CONFIG)

    assert FakeUsers.sweeps == 1


def test_a_native_record_with_an_earlier_name_sweeps_it_and_keeps_the_new_sids(
    native,
):
    with open(native._record_path, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "is_swept": True,
                "shares": {"share": "D:\\share"},
                "accounts": ["neutrino-ann"],
                "passwords": {"neutrino-ann": "d"},
            },
            stream,
        )

    native.apply(WINDOWS_CONFIG)
    native.apply(WINDOWS_CONFIG)

    assert native.applier.earlier_accounts == [["neutrino-ann"]]
    assert record_of(native)["sids"] == {"neutrino_ann": "S-neutrino_ann"}


def test_a_fresh_machine_s_task_that_configures_twice_sweeps_once(runner, tmp_path):
    """The R166 Windows machine's first enable ran ``configure`` twice in one
    task, the configured mark not yet written, and the second swept again."""
    (tmp_path / "configured" / "samba").unlink()
    (tmp_path / "samba.json").unlink()

    runner.apply(CONFIG)
    runner.apply(CONFIG)

    assert FakeUsers.sweeps == 1
    assert FakeApplier.earlier_sweeps == 1
    assert FakeApplier.removals == 1
    assert FakeUsers.made == [["neutrino_ann"], ["neutrino_ann"]]
    assert FakeUsers.converged == [{}, {"neutrino_ann": password_digest("generated")}]
    assert runner_module._read_record(str(runner.record_path))["is_swept"] is True


def test_the_first_apply_after_0_5_takes_its_shares_and_logins_away_first(
    runner, tmp_path
):
    """A 0.5 share named like an account would leave the account's Home
    share off as the person's, so the 0.5 shares go before the person's
    shares are read."""
    (tmp_path / "samba.json").unlink()
    FakeApplier.earlier = ["swept the 0.5 share olddocs"]
    FakeApplier.earlier_users = ["smbold", "alice"]
    FakeApplier.earlier_kept = {"handuser"}
    order: list = []
    plan = FakeApplier.plan
    sweep_earlier = FakeApplier.sweep_earlier

    def planned(self, *, is_served):
        order.append("plan")
        return plan(self, is_served=is_served)

    def swept(self):
        order.append("sweep_earlier")
        return sweep_earlier(self)

    FakeApplier.plan = planned
    FakeApplier.sweep_earlier = swept
    try:
        runner.apply(CONFIG)
        runner.apply(CONFIG)
    finally:
        FakeApplier.plan = plan
        FakeApplier.sweep_earlier = sweep_earlier

    assert order[0] == "sweep_earlier" and order.count("sweep_earlier") == 1
    assert FakeUsers.earlier == [(["smbold", "alice"], {"handuser"})]


def test_an_uninstall_sweeps_0_5_s_logins_too_and_forgets_the_mark(packaged):
    FakeApplier.earlier_users = ["smbold"]

    packaged.uninstall(RECIPE)

    assert FakeUsers.sweeps == 1
    assert FakeUsers.earlier == [(["smbold"], set())]
    assert "is_swept" not in runner_module._read_record(str(packaged.record_path))


def test_a_fresh_native_machine_s_task_that_configures_twice_sweeps_once(
    native, tmp_path
):
    (tmp_path / "configured" / "samba").unlink()
    os.unlink(native._record_path)

    native.apply(WINDOWS_CONFIG)
    native.apply(WINDOWS_CONFIG)

    assert [folders for folders, _, _ in native.applier.sweeps] == [["D:\\share"]]
    first, second = [call for call in native.applier.calls if call[0] == "apply"]
    assert first[2]["accounts"] == []
    assert second[2]["accounts"] == ["neutrino_ann"]
    assert record_of(native)["is_swept"] is True


def test_a_native_record_of_0_5_is_swept_with_its_folders_and_starts_empty(native):
    """A record of 0.5 lists its shares and accounts and has no mark."""
    with open(native._record_path, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "shares": {"docs": "C:\\shares\\docs"},
                "accounts": ["labsmb", "neutrino_old"],
                "passworded": ["labsmb"],
                "is_served": True,
            },
            stream,
        )

    native.apply(WINDOWS_CONFIG)

    assert [
        (folders, is_served) for folders, is_served, _ in native.applier.sweeps
    ] == [(["C:\\shares\\docs", "D:\\share"], True)]
    assert native.applier.earlier_accounts == [["labsmb"]]
    (apply_call,) = [call for call in native.applier.calls if call[0] == "apply"]
    assert apply_call[2]["accounts"] == []
    assert apply_call[2]["shares"] == {"share": "D:\\share"}


def test_a_native_uninstall_sweeps_the_folders_the_record_kept_and_forgets_the_mark(
    native,
):
    native.apply(WINDOWS_CONFIG)
    native.stop()
    native.remove_configuration()

    native.uninstall({})

    folders, is_served, at = native.applier.sweeps[-1]
    assert (folders, is_served) == (["D:\\share"], False)
    assert native.applier.calls[at - 1][0] == "put_back_server"
    assert record_of(native) == {
        "shares": {},
        "accounts": [],
        "passwords": {},
        "sids": {},
    }


def test_a_native_share_with_no_user_is_named_on_the_row_and_left_out_of_the_record(
    native,
):
    native.apply(
        {
            **WINDOWS_CONFIG,
            "shares": [
                *WINDOWS_CONFIG["shares"],
                {"name": "lab", "path": "D:\\lab", "valid_users": []},
            ],
        }
    )

    assert native.notice() == {
        "code": "share_users_unknown",
        "params": {"shares": "lab"},
    }
    assert record_of(native)["shares"] == {"share": "D:\\share"}

    native.apply(WINDOWS_CONFIG)

    assert native.notice() == {}
