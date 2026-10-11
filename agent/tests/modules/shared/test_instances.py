"""The shared runner of the programs run as an account, driven through fake hooks.

What these pin: an apply refuses an account the machine lacks and software
that is not there before anything is written; it prepares each account,
renders the template from the hooks' answer for ``%i``, writes and starts
one service per instance, restarting a new or changed one and keeping an
unchanged one up, and keeps a root-only record per instance written only
once every service started; an account no longer named loses its service,
its record and its forwarder; one forwarder runs per record and follows
it; a stop closes the forwarders and keeps the records; a restarted agent
starts the forwarders from the records; a row runs only while its service
runs and its forwarder listens; the details carry what the hooks add; the
journal is the units' or the log files', the refusal last; an install and
an uninstall go through the hooks and the module directory; and a record
changed by the hooks is applied again.
"""

import json
import os
import stat
from dataclasses import dataclass

import pytest

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
    ServiceMachine,
)
from neutrino_agent.modules.shared.http_forward import RELAY, refused
from neutrino_agent.modules.shared.instances import (
    InstanceHooks,
    InstancesModuleRunner,
    kept_config,
    machine_for,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

INSTANCE = {"account": "ann", "port": 8443, "secret": "s"}
CONFIG = {"instances": [INSTANCE]}


@dataclass
class DemoInstance:
    account: str
    port: int = 0
    secret: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "DemoInstance":
        return cls(
            account=str(data.get("account", "") or ""),
            port=int(data.get("port", 0) or 0),
            secret=str(data.get("secret", "") or ""),
        )


@dataclass
class DemoConfig:
    instances: list

    @classmethod
    def from_dict(cls, data: dict) -> "DemoConfig":
        return cls(
            instances=[
                DemoInstance.from_dict(entry) for entry in data.get("instances", [])
            ]
        )


class DemoHooks(InstanceHooks):
    """A module that runs ``demo`` as the account on one port behind a forwarder."""

    name = "demo"
    title = "Demo"
    kind = "demo"
    download_failure_code = "demo_download_failed"
    instance_class = DemoInstance
    record_fields = ("account", "port", "secret", "upstream_port")
    forwarder_fields = ("account", "port", "secret")

    def __init__(self, *, platform, log=print):
        super().__init__(platform=platform, log=log)
        self.is_installed = True
        self.prepared: list = []
        self.installed: list = []
        self.prepare_error = None
        self.module_notes: list = []
        self.is_forgotten = False

    def parse(self, config):
        parsed = DemoConfig.from_dict(config)
        for instance in parsed.instances:
            if not instance.secret:
                raise ModuleApplyError("secret_missing", {"account": instance.account})
        return parsed

    def verify(self):
        return self.is_installed

    def install(self, package_path, package_kind):
        self.installed.append((package_path, package_kind))
        os.makedirs(self.machine.module_dir, exist_ok=True)
        with open(os.path.join(self.machine.module_dir, "demo"), "w") as stream:
            stream.write("#!/bin/sh\n")
        self.is_installed = True

    def prepare_module(self):
        return list(self.module_notes)

    def prepare(self, instance, entry):
        self.prepared.append((instance.account, entry.home))
        if self.prepare_error is not None:
            raise self.prepare_error
        return []

    def record(self, parsed, instance, held):
        record = super().record(parsed, instance, held)
        record["upstream_port"] = held.get("upstream_port") or 41000
        return record

    def service(self, instance, entry, record):
        return AccountService(
            name=self.name,
            title=self.title,
            account=instance.account,
            command=(os.path.join(self.machine.module_dir, "demo"), "--serve"),
            environment={"DEMO_PORT": str(record.get("upstream_port") or 0)},
            working_directory="~",
        )

    def admit(self, request, record):
        return RELAY if request.header("cookie") else refused()

    def connect(self, record):
        raise OSError("no page in this test")

    def details_extra(self, record):
        return {"upstream_port": record.get("upstream_port")}

    def module_details(self):
        return {"version": "1.0"}

    def forget_module(self):
        self.is_forgotten = True


class FakeForwarder:
    made: list = []

    def __init__(self, **fields):
        self.fields = fields
        self.record = dict(fields["record"])
        self.is_started = False
        self.is_closed = False
        self.is_listening = False
        self.failure = ("", {})
        FakeForwarder.made.append(self)

    def matches(self, record):
        return all(
            self.record.get(field) == record.get(field)
            for field in self.fields["hooks"].forwarder_fields
        )

    def start(self):
        self.is_started = True

    def close(self):
        self.is_closed = True


class Systemd:
    """systemctl, recorded; every unit the test names active reads active."""

    def __init__(self):
        self.calls: list = []
        self.active: set = set()
        self.error = None

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if self.error is not None and command[1] in ("enable", "restart"):
            raise self.error
        if command[:2] == ["systemctl", "is-active"]:
            word = "active" if command[2] in self.active else "inactive"
            return CommandResult(list(command), 0, word + "\n", "")
        return CommandResult(list(command), 0, "", "")

    def units(self, verb):
        return [call for call in self.calls if call[1] == verb]


class Platform(AgentPlatform):
    def __init__(self, os_name="linux", root="", log_path=""):
        self.os_name = os_name
        self._root = root
        self._log_path = log_path
        self.opened: list = []

    def agent_var_dir(self):
        return self._root + "/state"

    def agent_data_dir(self):
        return self._root + "/config"

    def agent_log_path(self):
        return self._log_path

    def account_home(self, account):
        if account != "ann":
            raise KeyError(account)
        return "C:\\Users\\ann"

    def open_to_accounts(self, directory):
        self.opened.append(directory)


def lookup(account):
    if account not in ("ann", "bob"):
        raise KeyError(account)
    return AccountEntry(1000, 1000, f"/home/{account}", "/bin/bash")


@pytest.fixture
def systemd():
    return Systemd()


@pytest.fixture
def machine(systemd, tmp_path):
    (tmp_path / "systemd").mkdir()
    return ServiceMachine(
        os_name="linux",
        module_dir=str(tmp_path / "state" / "demo"),
        record_dir=str(tmp_path / "config" / "demo"),
        lookup_account=lookup,
        run=systemd,
        chown=lambda path, uid, gid: None,
        systemd_dir=str(tmp_path / "systemd"),
    )


@pytest.fixture
def platform(tmp_path):
    return Platform(root=str(tmp_path))


def make_runner(machine, platform, log=None):
    FakeForwarder.made = []
    return InstancesModuleRunner(
        hooks_class=DemoHooks,
        platform=platform,
        log=log if log is not None else (lambda line: None),
        machine=machine,
        forwarder_factory=FakeForwarder,
    )


@pytest.fixture
def runner(machine, platform):
    return make_runner(machine, platform)


# --- an apply ---


def test_an_apply_prepares_writes_starts_and_records_each_instance(
    runner, systemd, tmp_path
):
    runner.apply(CONFIG)

    assert runner.hooks.prepared == [("ann", "/home/ann")]
    template = (tmp_path / "systemd" / "neutrino_demo@.service").read_text()
    assert "Description=Demo for %i\n" in template
    assert "User=%i\n" in template
    assert f"ExecStart={tmp_path}/state/demo/demo --serve\n" in template
    assert "WorkingDirectory=~\n" in template
    environment = tmp_path / "config" / "demo" / "ann.env"
    assert environment.read_text() == "DEMO_PORT=41000\n"
    assert systemd.calls == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "neutrino_demo@ann.service"],
        ["systemctl", "restart", "neutrino_demo@ann.service"],
    ]
    record = tmp_path / "config" / "demo" / "ann.json"
    assert stat.S_IMODE(os.stat(record).st_mode) == 0o600
    assert json.loads(record.read_text()) == {
        "account": "ann",
        "port": 8443,
        "secret": "s",
        "upstream_port": 41000,
    }


def test_an_unchanged_instance_is_only_kept_up_and_its_record_kept(runner, systemd):
    runner.apply(CONFIG)
    systemd.calls.clear()

    runner.apply(CONFIG)

    assert systemd.calls == [
        ["systemctl", "enable", "--now", "neutrino_demo@ann.service"]
    ]
    assert runner.details({})["instances"][0]["upstream_port"] == 41000


def test_a_changed_environment_restarts_the_instance(runner, systemd, tmp_path):
    runner.apply(CONFIG)
    (tmp_path / "config" / "demo" / "ann.env").write_text("DEMO_PORT=1\n")
    systemd.calls.clear()

    runner.apply(CONFIG)

    assert systemd.units("restart") == [
        ["systemctl", "restart", "neutrino_demo@ann.service"]
    ]


def test_a_changed_template_restarts_every_instance(runner, systemd, tmp_path):
    runner.apply({"instances": [INSTANCE, dict(INSTANCE, account="bob", port=8444)]})
    (tmp_path / "systemd" / "neutrino_demo@.service").write_text("old\n")
    systemd.calls.clear()

    runner.apply({"instances": [INSTANCE, dict(INSTANCE, account="bob", port=8444)]})

    assert systemd.calls[0] == ["systemctl", "daemon-reload"]
    assert [call[2] for call in systemd.units("restart")] == [
        "neutrino_demo@ann.service",
        "neutrino_demo@bob.service",
    ]


def test_an_account_no_longer_named_loses_its_service_record_and_forwarder(
    runner, systemd, tmp_path
):
    runner.apply(CONFIG)

    runner.apply({"instances": []})

    assert ["systemctl", "disable", "--now", "neutrino_demo@ann.service"] in (
        systemd.calls
    )
    assert not (tmp_path / "config" / "demo" / "ann.env").exists()
    assert os.listdir(tmp_path / "config" / "demo") == []
    assert FakeForwarder.made[0].is_closed


def test_an_account_the_machine_lacks_is_refused_before_anything_is_written(
    runner, systemd, tmp_path
):
    with pytest.raises(ModuleApplyError) as caught:
        runner.apply({"instances": [dict(INSTANCE, account="ghost")]})

    assert caught.value.code == "account_unknown"
    assert caught.value.params == {"account": "ghost"}
    assert systemd.calls == [] and runner.hooks.prepared == []
    assert os.listdir(tmp_path / "systemd") == []


def test_software_that_is_not_there_is_the_modules_download_failure(runner, systemd):
    runner.hooks.is_installed = False

    with pytest.raises(ModuleApplyError) as caught:
        runner.apply(CONFIG)

    assert caught.value.code == "demo_download_failed"
    assert systemd.calls == []


def test_a_refused_configuration_reaches_neither_the_machine_nor_a_record(
    runner, systemd, tmp_path
):
    with pytest.raises(ModuleApplyError) as caught:
        runner.apply({"instances": [dict(INSTANCE, secret="")]})

    assert caught.value.code == "secret_missing"
    assert systemd.calls == []
    assert not (tmp_path / "config").exists()
    assert runner.journal_text(5)[-1] == "demo: secret_missing account=ann"


def test_a_failure_of_the_system_is_apply_failed_and_writes_no_record(
    runner, systemd, tmp_path
):
    systemd.error = OSError("systemctl refused")

    with pytest.raises(ModuleApplyError) as caught:
        runner.apply(CONFIG)

    assert caught.value.code == "apply_failed"
    assert "systemctl refused" in caught.value.params["detail"]
    assert not (tmp_path / "config" / "demo" / "ann.json").exists()


def test_a_step_the_hooks_refuse_keeps_its_code(runner, systemd):
    runner.hooks.prepare_error = ModuleApplyError("demo_npm_failed", {"account": "ann"})

    with pytest.raises(ModuleApplyError) as caught:
        runner.apply(CONFIG)

    assert caught.value.code == "demo_npm_failed"
    assert systemd.calls == []


def test_an_install_the_hooks_leave_running_is_pending_and_reads_installing(
    runner, systemd
):
    runner.hooks.prepare_error = ModuleInstallPending("ann")
    runner.hooks.installing = frozenset({"ann"})

    with pytest.raises(ModuleInstallPending):
        runner.apply(CONFIG)

    assert runner.is_installing() is True
    assert runner.observe({})["is_installing"] is True
    assert systemd.calls == []
    assert FakeForwarder.made == []


def test_the_modules_own_notes_and_the_log_line(machine, platform):
    lines = []
    runner = make_runner(machine, platform, log=lines.append)
    runner.hooks.module_notes = ["raised the limits"]

    runner.apply(CONFIG)

    assert lines == ["demo: raised the limits; started the instance of ann"]


# --- the forwarders and the states ---


def test_an_apply_starts_one_forwarder_per_record_with_the_hooks(runner):
    runner.apply(CONFIG)

    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started
    assert forwarder.fields["name"] == "demo"
    assert forwarder.fields["hooks"] is runner.hooks
    assert forwarder.record["secret"] == "s"
    assert forwarder.record["upstream_port"] == 41000


def test_a_changed_instance_gets_a_new_forwarder_and_an_unchanged_one_stays(runner):
    runner.apply(CONFIG)
    runner.apply(CONFIG)
    runner.apply({"instances": [dict(INSTANCE, port=8444)]})

    first, second = FakeForwarder.made
    assert first.is_closed and second.is_started
    assert second.record["port"] == 8444


def test_a_stop_closes_the_forwarders_stops_the_units_and_keeps_the_records(
    runner, systemd, tmp_path
):
    runner.apply(CONFIG)
    systemd.calls.clear()

    runner.stop()

    assert FakeForwarder.made[0].is_closed
    assert systemd.calls == [["systemctl", "stop", "neutrino_demo@ann.service"]]
    assert sorted(os.listdir(tmp_path / "config" / "demo")) == ["ann.env", "ann.json"]
    assert runner.details({})["instances"][0]["is_running"] is False


def test_a_restarted_agent_starts_the_forwarders_from_the_records(
    runner, machine, platform
):
    runner.apply(CONFIG)
    again = make_runner(machine, platform)

    again.details({})

    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started and forwarder.record["account"] == "ann"


def test_a_row_runs_only_while_its_unit_runs_and_its_forwarder_listens(runner, systemd):
    runner.apply(CONFIG)
    systemd.active.add("neutrino_demo@ann.service")
    runner._forget_states()
    assert runner.is_active() is False

    FakeForwarder.made[0].is_listening = True

    assert runner.is_active() is True
    assert runner.details({}) == {
        "version": "1.0",
        "instances": [
            {
                "account": "ann",
                "port": 8443,
                "is_running": True,
                "code": "",
                "upstream_port": 41000,
            }
        ],
    }


def test_a_forwarders_failure_is_the_rows_code(runner):
    runner.apply(CONFIG)
    FakeForwarder.made[0].failure = ("demo_port_taken", {"port": 8443})

    assert runner.details({})["instances"][0]["code"] == "demo_port_taken"


def test_a_module_without_a_forwarder_runs_on_its_unit_alone(machine, platform):
    class BareHooks(DemoHooks):
        is_forwarded = False

    FakeForwarder.made = []
    runner = InstancesModuleRunner(
        hooks_class=BareHooks,
        platform=platform,
        log=lambda line: None,
        machine=machine,
        forwarder_factory=FakeForwarder,
    )
    runner.apply(CONFIG)
    machine.run.active.add("neutrino_demo@ann.service")
    runner._forget_states()

    assert FakeForwarder.made == []
    assert runner.is_active() is True


# --- removing, installing, the journal ---


def test_removing_the_configuration_retires_every_instance_and_forgets(
    runner, systemd, tmp_path
):
    runner.apply(CONFIG)
    systemd.calls.clear()

    runner.remove_configuration()

    assert ["systemctl", "disable", "--now", "neutrino_demo@ann.service"] in (
        systemd.calls
    )
    assert systemd.calls[-1] == ["systemctl", "daemon-reload"]
    assert os.listdir(tmp_path / "systemd") == []
    assert os.listdir(tmp_path / "config" / "demo") == []
    assert runner.hooks.is_forgotten
    assert FakeForwarder.made[0].is_closed
    assert runner.details({})["instances"] == []


def test_an_install_goes_through_the_hooks_and_opens_the_directory(
    runner, platform, tmp_path
):
    runner.hooks.is_installed = False
    assert runner.verify({}) is False

    runner.install({"entry": {"package_kind": "tar"}}, "/tmp/demo.tar.gz")

    assert runner.hooks.installed == [("/tmp/demo.tar.gz", "tar")]
    assert runner.verify({}) is True
    assert platform.opened == [str(tmp_path / "state" / "demo")]
    runner.uninstall({})
    assert not (tmp_path / "state" / "demo").exists()


def test_the_journal_is_the_units_with_the_refusal_last(runner, monkeypatch):
    monkeypatch.setattr(
        "neutrino_agent.modules.shared.base.units_journal",
        lambda units, lines: [f"journal of {units[0]}"],
    )
    runner.apply(CONFIG)
    runner.hooks.prepare_error = ModuleApplyError("demo_npm_failed", {"account": "ann"})
    with pytest.raises(ModuleApplyError):
        runner.apply(CONFIG)

    assert runner.journal_units() == ["neutrino_demo@ann.service"]
    assert runner.journal_text(10) == [
        "journal of neutrino_demo@ann.service",
        "demo: demo_npm_failed account=ann",
    ]
    runner.hooks.prepare_error = None
    runner.apply(CONFIG)
    assert runner.journal_text(10) == ["journal of neutrino_demo@ann.service"]


def test_without_units_the_log_files_come_then_the_agents_lines(tmp_path):
    agent_log = tmp_path / "agent.log"
    agent_log.write_text("10:00 demo: running\n10:01 samba: unchanged\n")

    def write(message):
        with open(agent_log, "a", encoding="utf-8") as stream:
            stream.write(f"10:02 {message}\n")

    platform = Platform("darwin", root=str(tmp_path), log_path=str(agent_log))
    machine = ServiceMachine(
        os_name="darwin",
        module_dir=str(tmp_path / "state" / "demo"),
        record_dir=str(tmp_path / "config" / "demo"),
        lookup_account=lookup,
        run=lambda command, **kwargs: CommandResult(list(command), 113, "", ""),
        chown=lambda path, uid, gid: None,
        launchd_dir=str(tmp_path / "daemons"),
        log_dir=str(tmp_path / "logs"),
    )
    (tmp_path / "daemons").mkdir()
    FakeForwarder.made = []
    runner = InstancesModuleRunner(
        hooks_class=DemoHooks,
        platform=platform,
        log=write,
        machine=machine,
        forwarder_factory=FakeForwarder,
    )
    runner.apply(CONFIG)
    (tmp_path / "logs" / "demo_ann.log").write_text("a1\n")
    runner.hooks.installing = frozenset({"bob"})
    runner.hooks.install_log = lambda account: (
        str(tmp_path / "install_bob.log") if account == "bob" else ""
    )

    first = runner.journal_text(200)

    assert first[:2] == ["ann: a1", "10:00 demo: running"]
    assert first[2].startswith("10:02 demo: started")
    assert any("cannot read the log source" in line for line in first)


# --- a record the hooks change ---


def test_a_record_the_hooks_change_is_applied_again(runner, systemd):
    runner.apply(CONFIG)
    systemd.calls.clear()

    runner.hooks._reapply("ann", upstream_port=42000)

    assert runner._records.read("ann")["upstream_port"] == 42000
    assert systemd.units("restart") == [
        ["systemctl", "restart", "neutrino_demo@ann.service"]
    ]
    assert len(FakeForwarder.made) == 1


def test_after_a_restart_the_kept_state_is_applied_again(machine, platform, tmp_path):
    os.makedirs(platform.agent_data_dir(), exist_ok=True)
    with open(os.path.join(platform.agent_data_dir(), "desired.json"), "w") as stream:
        json.dump({"modules": {"demo": {"want": "running", "config": CONFIG}}}, stream)
    first = make_runner(machine, platform)
    first.apply(CONFIG)
    restarted = make_runner(machine, platform)
    machine.run.calls.clear()

    restarted.hooks._reapply("ann", upstream_port=42000)

    assert machine.run.units("restart") == [
        ["systemctl", "restart", "neutrino_demo@ann.service"]
    ]
    assert restarted.hooks._reapply("ghost") is None


def test_the_kept_configuration_is_read_from_the_state_file(tmp_path):
    path = tmp_path / "desired.json"

    assert kept_config(str(path), "demo") == {}
    path.write_text(json.dumps({"modules": {"demo": {"config": CONFIG}}}))
    assert kept_config(str(path), "demo") == CONFIG
    assert kept_config(str(path), "other") == {}


# --- the machine ---


def test_the_machine_names_the_modules_directories_under_both_roots():
    linux = machine_for(Platform("linux", "/agent"), "demo")
    windows = machine_for(Platform("windows", "C:\\N\\agent"), "demo")

    assert (linux.module_dir, linux.record_dir) == (
        "/agent/state/demo",
        "/agent/config/demo",
    )
    assert windows.module_dir == "C:\\N\\agent/state\\demo"
    assert windows.lookup_account("ann") == AccountEntry(0, 0, "C:\\Users\\ann", "")
    with pytest.raises(KeyError):
        windows.lookup_account("ghost")
