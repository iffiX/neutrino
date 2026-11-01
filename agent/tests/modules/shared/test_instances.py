"""The shared runner of the programs run as an account, driven through fake hooks.

What these pin: an apply refuses an account the machine lacks before
anything is written and puts no presence check of its own in front of the
instances; it prepares each account,
renders the template from the hooks' answer for ``%i``, writes and starts
one service per instance, restarting a new or changed one and keeping an
unchanged one up, and keeps a root-only record per instance written once
its service started; an account no longer named loses its service,
its record and its forwarder; one forwarder runs per record and follows
it; a task's steps are ``configure``, then per enabled account the step
the hooks name for its preparation and ``account``, each account step
starting its own instance, with no account step under ``stopped``; a
stop closes the forwarders, keeps the records and marks them stopped; a
restarted agent starts the forwarders of the records no stop marked, on every
system, and an account's step starts its own forwarder at its kept port; the
port of the page behind a forwarder is picked from 15000 up and kept, picked
again when the system refuses it and kept when another program holds it, an
instance that does not run on a refused port asking for one configure task; a row runs only while its service
runs and its forwarder listens, a reading that finds a service stopped just
after an apply read again at the next report; the forwarder ports the relays carry are
those of the forwarders that listen; the details carry what the hooks add; the
journal is the units' or the log files', the module's own log first
where the hooks name one and nothing of a service whose output is
discarded, a log not written yet read as empty, the refusal last; an artifact lands under its directory in
the module's and the hooks tidy after it, a bad directory or archive being
``install_failed``; an uninstall deletes the module directory; and a record
changed by the hooks asks for a configure task.
"""

import dataclasses
import functools
import io
import json
import os
import socket
import stat
import tarfile
from dataclasses import dataclass

import pytest

from neutrino_agent.constants import AGENT_PAGE_PORT_FIELDS
from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.cloudcli.hooks import CloudcliHooks
from neutrino_agent.modules.code_server.hooks import CodeServerHooks
from neutrino_agent.modules.codeg.hooks import CodegHooks
import neutrino_agent.modules.shared.instances as instances_module
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
    ServiceMachine,
)
from neutrino_agent.modules.shared.http_forward import RELAY, refused
from neutrino_agent.modules.shared.instances import (
    InstanceHooks,
    InstancesModuleRunner,
    machine_for,
)
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.shared.loopback_port import is_port_refused
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.siyuan.hooks import SiyuanHooks
from neutrino_agent.modules.ssh_server.hooks import SshServerHooks
from neutrino_agent.modules.vscode.hooks import VscodeHooks
from neutrino_agent.platforms.base import AgentPlatform

INSTANCE = {"account": "ann", "secret": "s"}
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
    runner = "demo"
    instance_class = DemoInstance
    record_fields = ("account", "port", "secret", "upstream_port")
    forwarder_fields = ("account", "port", "secret")
    base_port = 8443

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

    def prepare_module(self):
        return list(self.module_notes)

    def prepare(self, parsed, instance, entry):
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

    @property
    def listen_address(self):
        if not self.is_listening:
            return ("", 0)
        return ("127.0.0.1", self.record["port"])

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
        self.labelled: list = []

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

    def label_programs(self, path):
        self.labelled.append(path)


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


# The loopback ports another program holds in a test.
HELD_PORTS: set = set()


def make_runner(machine, platform, log=None):
    FakeForwarder.made = []
    HELD_PORTS.clear()
    return InstancesModuleRunner(
        hooks_class=DemoHooks,
        platform=platform,
        log=log if log is not None else (lambda line: None),
        machine=machine,
        forwarder_factory=FakeForwarder,
        is_port_free=lambda port: port not in HELD_PORTS,
    )


@pytest.fixture
def runner(machine, platform):
    return make_runner(machine, platform)


def configure_step():
    return ModuleStep(name="configure", run=None)


def start_step():
    return ModuleStep(name="start", run=lambda context: None)


def stop_step():
    return ModuleStep(name="stop", run=lambda context: None)


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


def test_every_apply_labels_each_unpack_before_an_instance_starts(
    runner, systemd, platform, tmp_path, monkeypatch
):
    """A relabel of the whole system puts ``var_lib_t`` back, and the next
    apply undoes it."""
    runner.take_recipe(
        {
            "params": {
                "artifacts": [
                    {"name": "server", "kind": "tar_gz", "directory": "server"},
                    {"name": "cli", "kind": "tar_gz"},
                ]
            }
        }
    )

    def label(path):
        systemd.calls.append(["label", path])

    monkeypatch.setattr(platform, "label_programs", label)

    runner.apply(CONFIG)
    runner.apply(CONFIG)

    module = str(tmp_path / "state" / "demo")
    labels = [call[1] for call in systemd.calls if call[0] == "label"]
    assert labels == [module + "/server", module] * 2
    first_start = systemd.calls.index(
        ["systemctl", "restart", "neutrino_demo@ann.service"]
    )
    assert systemd.calls[:2] == [["label", module + "/server"], ["label", module]]
    assert first_start > 1


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
    assert os.listdir(tmp_path / "config" / "demo") == ["ann.json"]
    assert runner.details({})["instances"] == []
    assert FakeForwarder.made[0].is_closed


def test_an_account_with_no_profile_is_refused_by_name_before_anything_is_written(
    runner, systemd, tmp_path, monkeypatch
):
    monkeypatch.setattr(Platform, "has_account", lambda self, account: True)

    with pytest.raises(ModuleApplyError) as caught:
        runner.apply({"instances": [dict(INSTANCE, account="fresh")]})

    assert caught.value.code == "account_no_profile"
    assert caught.value.params == {"account": "fresh"}
    assert systemd.calls == [] and runner.hooks.prepared == []
    assert os.listdir(tmp_path / "systemd") == []


def test_an_account_the_machine_lacks_is_refused_before_anything_is_written(
    runner, systemd, tmp_path
):
    with pytest.raises(ModuleApplyError) as caught:
        runner.apply({"instances": [dict(INSTANCE, account="ghost")]})

    assert caught.value.code == "account_unknown"
    assert caught.value.params == {"account": "ghost"}
    assert systemd.calls == [] and runner.hooks.prepared == []
    assert os.listdir(tmp_path / "systemd") == []


def test_an_apply_puts_no_check_of_its_own_in_front_of_the_instances(runner, systemd):
    """The presence check is the recipe's, which the engine runs before it
    applies; the runner's own check does not refuse the apply."""
    runner.hooks.is_installed = False

    runner.apply(CONFIG)

    assert ["systemctl", "daemon-reload"] in systemd.calls


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
    runner.apply({"instances": [dict(INSTANCE, secret="t")]})

    first, second = FakeForwarder.made
    assert first.is_closed and second.is_started
    assert second.record["secret"] == "t"


# --- the ports the runner takes ---


def test_each_instance_takes_the_first_free_port_from_the_base_up(runner, tmp_path):
    HELD_PORTS.add(8443)

    runner.apply({"instances": [INSTANCE, {"account": "bob", "secret": "b"}]})

    rows = {row["account"]: row["port"] for row in runner.details({})["instances"]}
    assert rows == {"ann": 8444, "bob": 8445}


def test_a_port_given_in_the_state_is_not_read(runner):
    runner.apply({"instances": [dict(INSTANCE, port=9999)]})

    assert runner.details({})["instances"][0]["port"] == 8443


def test_a_kept_port_stays_while_its_instance_runs_whoever_listens(runner):
    runner.apply(CONFIG)
    HELD_PORTS.add(8443)

    runner.apply(CONFIG)

    assert runner.details({})["instances"][0]["port"] == 8443


def test_a_disabled_account_keeps_its_port_for_when_it_is_enabled_again(
    runner, tmp_path
):
    runner.apply(CONFIG)
    runner.apply({"instances": []})
    retired = json.loads((tmp_path / "config" / "demo" / "ann.json").read_text())

    runner.apply({"instances": [{"account": "bob", "secret": "b"}]})
    runner.apply({"instances": [{"account": "bob", "secret": "b"}, INSTANCE]})

    assert retired == {"account": "ann", "port": 8443, "is_retired": True}
    rows = {row["account"]: row["port"] for row in runner.details({})["instances"]}
    assert rows == {"ann": 8443, "bob": 8444}


def test_a_kept_port_another_program_took_meanwhile_moves_to_the_next_free(
    runner, machine, platform
):
    runner.apply(CONFIG)
    runner.apply({"instances": []})
    HELD_PORTS.add(8443)

    runner.apply(CONFIG)

    assert runner.details({})["instances"][0]["port"] == 8444


def test_a_restarted_agent_moves_a_forwarder_whose_port_another_program_took(
    runner, machine, platform, tmp_path
):
    runner.apply(CONFIG)
    again = make_runner(machine, platform)
    HELD_PORTS.add(8443)

    again.details({})

    (forwarder,) = FakeForwarder.made
    assert forwarder.record["port"] == 8444
    record = json.loads((tmp_path / "config" / "demo" / "ann.json").read_text())
    assert record["port"] == 8444


def test_removing_the_configuration_forgets_the_kept_ports(runner, tmp_path):
    runner.apply(CONFIG)
    runner.apply({"instances": []})

    runner.remove_configuration()

    assert os.listdir(tmp_path / "config" / "demo") == []


def test_a_stop_closes_the_forwarders_stops_the_units_and_keeps_the_records(
    runner, systemd, tmp_path
):
    runner.apply(CONFIG)
    systemd.calls.clear()

    runner.stop()

    assert FakeForwarder.made[0].is_closed
    assert systemd.calls == [
        ["systemctl", "disable", "--now", "neutrino_demo@ann.service"]
    ]
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


def test_a_stop_keeps_the_stopped_mark_in_the_record(runner, tmp_path):
    runner.apply(CONFIG)

    runner.stop()

    path = tmp_path / "config" / "demo" / "ann.json"
    assert json.loads(path.read_text())["is_stopped"] is True


def test_a_restarted_agent_starts_no_forwarder_of_a_stopped_module(
    runner, machine, platform
):
    runner.apply(CONFIG)
    runner.stop()
    again = make_runner(machine, platform)

    details = again.details({})

    assert FakeForwarder.made == []
    assert again.forwarder_ports() == ()
    assert details["instances"][0]["is_running"] is False
    assert details["instances"][0]["port"] == 8443


def test_a_stop_whose_mark_cannot_be_written_still_stops_the_module(
    runner, systemd, monkeypatch
):
    lines: list = []
    runner._log = lines.append
    runner.apply(CONFIG)
    systemd.calls.clear()

    def refused(account):
        raise PermissionError(13, "read-only")

    monkeypatch.setattr(runner._records, "mark_stopped", refused)
    runner.stop()

    assert FakeForwarder.made[0].is_closed
    assert systemd.units("disable")
    assert any("ann" in line and "read-only" in line for line in lines)


def test_a_configure_under_stopped_after_a_restart_starts_no_forwarder(
    runner, machine, platform
):
    runner.apply(CONFIG)
    runner.stop()
    again = make_runner(machine, platform)

    steps = again.configure_steps(CONFIG, "stopped", [configure_step(), stop_step()])
    steps[0].run(None)

    assert FakeForwarder.made == []


def test_a_start_after_a_restart_brings_the_forwarder_back_at_its_kept_port(
    runner, machine, platform, tmp_path
):
    runner.apply(CONFIG)
    runner.stop()
    again = make_runner(machine, platform)
    again.details({})

    for step in again.configure_steps(
        CONFIG, "running", [configure_step(), start_step()]
    ):
        step.run(None)

    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started
    assert forwarder.record["port"] == 8443
    assert forwarder.record["upstream_port"] == 41000
    path = tmp_path / "config" / "demo" / "ann.json"
    assert "is_stopped" not in json.loads(path.read_text())


def test_each_account_s_step_starts_its_own_forwarder_after_a_stop(
    runner, machine, platform
):
    both = {"instances": [INSTANCE, {"account": "bob", "secret": "s"}]}
    runner.apply(both)
    runner.stop()
    again = make_runner(machine, platform)
    steps = {
        (step.name, step.params.get("account")): step
        for step in again.configure_steps(
            both, "running", [configure_step(), start_step()]
        )
    }

    steps[("configure", None)].run(None)
    assert FakeForwarder.made == []

    steps[("account", "ann")].run(None)
    assert [made.record["account"] for made in FakeForwarder.made] == ["ann"]

    steps[("account", "bob")].run(None)
    assert [made.record["account"] for made in FakeForwarder.made] == ["ann", "bob"]
    assert [made.record["port"] for made in FakeForwarder.made] == [8443, 8444]


def test_a_second_stop_after_a_restart_leaves_the_mark(
    runner, machine, platform, tmp_path
):
    runner.apply(CONFIG)
    runner.stop()
    again = make_runner(machine, platform)

    again.stop()

    path = tmp_path / "config" / "demo" / "ann.json"
    assert json.loads(path.read_text())["is_stopped"] is True
    assert FakeForwarder.made == []


class FakeAccountLayer:
    """The account service layer of any system: every service runs once started."""

    def __init__(self):
        self.running: set = set()

    def define(self, service, machine):
        return False

    def write(self, service, machine):
        return False

    def start(self, service, machine, *, is_restart):
        self.running.add(service.account)

    def stop(self, service, machine):
        self.running.discard(service.account)

    def states(self, services, machine):
        return {
            service.account: {"is_running": service.account in self.running}
            for service in services
        }


@pytest.mark.parametrize("os_name", ["linux", "windows", "darwin"])
def test_on_every_system_a_stopped_forwarder_stays_down_until_the_start(
    os_name, tmp_path, monkeypatch
):
    monkeypatch.setattr(instances_module, "account_service", FakeAccountLayer())
    the_machine = ServiceMachine(
        os_name=os_name,
        module_dir=str(tmp_path / "state" / "demo"),
        record_dir=str(tmp_path / "state" / "demo"),
        lookup_account=lookup,
        run=lambda command, **fields: CommandResult(list(command), 0, "", ""),
    )
    the_platform = Platform(os_name=os_name, root=str(tmp_path))
    first = make_runner(the_machine, the_platform)
    first.apply(CONFIG)
    first.stop()

    again = make_runner(the_machine, the_platform)
    again.details({})
    assert FakeForwarder.made == []

    again.apply(CONFIG)
    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started and forwarder.record["port"] == 8443


@pytest.mark.parametrize(
    ("hooks_class", "is_forwarded"),
    [
        (CloudcliHooks, True),
        (CodeServerHooks, True),
        (CodegHooks, True),
        (SiyuanHooks, True),
        (SshServerHooks, False),
        (VscodeHooks, False),
    ],
)
def test_the_stopped_mark_covers_each_module_with_a_forwarder(
    hooks_class, is_forwarded, tmp_path, monkeypatch
):
    monkeypatch.setattr(instances_module, "account_service", FakeAccountLayer())
    FakeForwarder.made = []
    the_machine = ServiceMachine(
        os_name="linux",
        module_dir=str(tmp_path / "state" / "module"),
        record_dir=str(tmp_path / "state" / "module"),
        lookup_account=lookup,
    )
    the_platform = Platform(root=str(tmp_path))

    def made():
        made_runner = InstancesModuleRunner(
            hooks_class=hooks_class,
            platform=the_platform,
            log=lambda line: None,
            machine=the_machine,
            forwarder_factory=FakeForwarder,
            is_port_free=lambda port: True,
        )
        made_runner.hooks.service = lambda instance, entry, record: instance
        return made_runner

    store = made()._records
    store.write({"account": "ann", "port": 3101})
    first = made()
    first.details({})
    assert len(FakeForwarder.made) == int(is_forwarded)
    assert first.hooks.is_forwarded is is_forwarded

    first.stop()
    FakeForwarder.made = []
    made().details({})

    assert FakeForwarder.made == []
    assert bool(store.read_running()) is not is_forwarded


class PagedDemoHooks(DemoHooks):
    """A module whose page listens on a port the shared runner keeps for it."""

    page_port_field = "upstream_port"
    forwarder_fields = ("account", "port", "secret", "upstream_port")

    def record(self, parsed, instance, held):
        record = InstanceHooks.record(self, parsed, instance, held)
        record["upstream_port"] = held.get("upstream_port")
        return record


@pytest.fixture
def paged(systemd, tmp_path):
    """A runner whose records lie under the state root, and the system's refusals."""
    (tmp_path / "systemd").mkdir()
    the_machine = ServiceMachine(
        os_name="linux",
        module_dir=str(tmp_path / "state" / "demo"),
        record_dir=str(tmp_path / "state" / "demo"),
        lookup_account=lookup,
        run=systemd,
        chown=lambda path, uid, gid: None,
        systemd_dir=str(tmp_path / "systemd"),
    )
    refused_ports: set = set()
    lines: list = []
    FakeForwarder.made = []

    def made_runner():
        return InstancesModuleRunner(
            hooks_class=PagedDemoHooks,
            platform=Platform(root=str(tmp_path)),
            log=lines.append,
            machine=the_machine,
            forwarder_factory=FakeForwarder,
            is_port_free=lambda port: True,
            is_port_refused=refused_ports.__contains__,
        )

    return made_runner, refused_ports, lines


def keep_record(tmp_path, **fields):
    """An instance's record as an earlier build left it, under the state root."""
    directory = tmp_path / "state" / "demo"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ann.json").write_text(
        json.dumps({"account": "ann", "port": 8443, "secret": "s", **fields})
    )


def kept_record(tmp_path, account="ann"):
    return json.loads((tmp_path / "state" / "demo" / f"{account}.json").read_text())


def test_a_new_instance_s_page_port_is_picked_from_15000_up_and_kept(paged, tmp_path):
    made_runner, _, _ = paged
    runner = made_runner()

    runner.apply({"instances": [INSTANCE, {"account": "bob", "secret": "s"}]})

    assert kept_record(tmp_path, "ann")["upstream_port"] == 15000
    assert kept_record(tmp_path, "bob")["upstream_port"] == 15001


def test_a_page_port_passes_the_ports_any_module_keeps(paged, tmp_path):
    made_runner, _, _ = paged
    other = tmp_path / "state" / "hermes_webui"
    other.mkdir(parents=True)
    (other / "page_ports.json").write_text(json.dumps({"neutrino_webui": 15000}))

    made_runner().apply(CONFIG)

    assert kept_record(tmp_path)["upstream_port"] == 15001


def test_a_kept_page_port_the_system_accepts_stays_whatever_its_number(
    paged, tmp_path, systemd
):
    made_runner, _, lines = paged
    keep_record(tmp_path, upstream_port=51280)

    made_runner().apply(CONFIG)

    assert kept_record(tmp_path)["upstream_port"] == 51280
    assert FakeForwarder.made[0].record["upstream_port"] == 51280
    assert not any("refuses" in line for line in lines)


def test_a_kept_page_port_another_program_holds_stays(paged, tmp_path):
    made_runner, _, _ = paged
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    in_use = holder.getsockname()[1]
    keep_record(tmp_path, upstream_port=in_use)
    try:
        runner = made_runner()
        runner._is_port_refused = is_port_refused
        runner.apply(CONFIG)
    finally:
        holder.close()

    assert kept_record(tmp_path)["upstream_port"] == in_use


def test_a_kept_page_port_the_system_refuses_is_picked_again_and_restarts_the_page(
    paged, tmp_path, systemd
):
    made_runner, refused_ports, lines = paged
    runner = made_runner()
    keep_record(tmp_path, upstream_port=51280)
    runner.apply(CONFIG)
    (first,) = FakeForwarder.made
    systemd.calls.clear()
    refused_ports.add(51280)

    runner.apply(CONFIG)

    record = kept_record(tmp_path)
    assert record["upstream_port"] == 15000
    assert record["port"] == 8443
    assert first.is_closed
    assert FakeForwarder.made[-1].record["upstream_port"] == 15000
    assert systemd.units("restart")
    assert lines.count("demo: the system refuses port 51280 of ann, 15000 now") == 1


def test_a_stopped_page_on_a_refused_port_moves_at_the_start_with_no_other_press(
    paged, tmp_path
):
    made_runner, refused_ports, _ = paged
    keep_record(tmp_path, upstream_port=51280)
    runner = made_runner()
    runner.apply(CONFIG)
    runner.stop()
    refused_ports.add(51280)

    again = made_runner()
    FakeForwarder.made = []
    again.details({})
    assert FakeForwarder.made == []
    assert kept_record(tmp_path)["upstream_port"] == 51280

    again.apply(CONFIG)

    assert kept_record(tmp_path)["upstream_port"] == 15000
    assert FakeForwarder.made[0].record["upstream_port"] == 15000
    assert FakeForwarder.made[0].record["port"] == 8443


def asking(runner) -> list:
    """The configure tasks a runner asks for, one entry each."""
    asks: list = []
    runner.bind_configure_asker(functools.partial(asks.append, "demo"))
    return asks


def test_an_instance_down_on_a_refused_port_asks_for_one_configure_task(
    paged, tmp_path, systemd
):
    made_runner, refused_ports, lines = paged
    keep_record(tmp_path, upstream_port=51280)
    refused_ports.add(51280)
    runner = made_runner()
    asks = asking(runner)

    assert runner.is_active() is False
    runner._forget_states()
    assert runner.is_active() is False

    assert asks == ["demo"]
    assert "demo: the system refuses port 51280, a start follows" in lines


def test_a_configure_task_of_a_refused_port_brings_the_instance_back(
    paged, tmp_path, systemd
):
    made_runner, refused_ports, _ = paged
    keep_record(tmp_path, upstream_port=51280)
    refused_ports.add(51280)
    runner = made_runner()
    asks = asking(runner)
    assert runner.is_active() is False
    assert asks == ["demo"]

    for step in runner.configure_steps(
        CONFIG, "running", [configure_step(), start_step()]
    ):
        step.run(None)
    FakeForwarder.made[-1].is_listening = True
    systemd.active.add("neutrino_demo@ann.service")
    runner._forget_states()

    assert kept_record(tmp_path)["upstream_port"] == 15000
    assert runner.is_active() is True
    assert asks == ["demo"]


def test_an_instance_that_runs_asks_for_nothing_at_a_refused_port(
    paged, tmp_path, systemd
):
    made_runner, refused_ports, _ = paged
    keep_record(tmp_path, upstream_port=51280)
    runner = made_runner()
    asks = asking(runner)
    runner.apply(CONFIG)
    FakeForwarder.made[-1].is_listening = True
    systemd.active.add("neutrino_demo@ann.service")
    runner._forget_states()
    refused_ports.add(51280)

    assert runner.is_active() is True
    assert asks == []


def test_an_instance_down_at_an_accepted_port_asks_for_nothing(paged, tmp_path):
    made_runner, _, _ = paged
    keep_record(tmp_path, upstream_port=51280)
    runner = made_runner()
    asks = asking(runner)

    assert runner.is_active() is False
    assert asks == []


def test_a_stopped_module_asks_for_nothing_at_a_refused_port(paged, tmp_path):
    made_runner, refused_ports, _ = paged
    keep_record(tmp_path, upstream_port=51280)
    first = made_runner()
    first.apply(CONFIG)
    first.stop()
    refused_ports.add(51280)
    runner = made_runner()
    asks = asking(runner)

    assert runner.is_active() is False
    assert asks == []


def test_a_module_with_no_page_port_asks_for_nothing(runner, tmp_path):
    asks = asking(runner)
    runner.apply(CONFIG)
    runner._is_port_refused = lambda port: True

    assert runner.is_active() is False
    assert asks == []


@pytest.mark.parametrize(
    ("hooks_class", "field"),
    [
        (CloudcliHooks, "upstream_port"),
        (CodegHooks, "upstream_port"),
        (SiyuanHooks, "kernel_port"),
        (CodeServerHooks, ""),
        (SshServerHooks, ""),
        (VscodeHooks, ""),
    ],
)
def test_each_module_names_the_field_of_its_page_port(hooks_class, field):
    assert hooks_class.page_port_field == field
    if field:
        assert field in hooks_class.record_fields
        assert field in AGENT_PAGE_PORT_FIELDS


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


def test_a_service_read_stopped_just_after_its_start_is_read_again(
    machine, platform, systemd
):
    now = [100.0]
    FakeForwarder.made = []
    HELD_PORTS.clear()
    runner = InstancesModuleRunner(
        hooks_class=DemoHooks,
        platform=platform,
        log=lambda line: None,
        machine=machine,
        forwarder_factory=FakeForwarder,
        is_port_free=lambda port: port not in HELD_PORTS,
        clock=lambda: now[0],
    )
    runner.apply(CONFIG)
    FakeForwarder.made[0].is_listening = True
    assert runner.is_active() is False

    systemd.active.add("neutrino_demo@ann.service")
    now[0] += 5

    assert runner.is_active() is True
    systemd.active.clear()
    now[0] += 5
    assert runner.is_active() is True


@pytest.fixture
def clocked(machine, platform, monkeypatch):
    """A running instance, its clock, and the answer of the system's next reading."""
    now = [100.0]
    answers: list = []
    FakeForwarder.made = []
    HELD_PORTS.clear()
    runner = InstancesModuleRunner(
        hooks_class=DemoHooks,
        platform=platform,
        log=lambda line: None,
        machine=machine,
        forwarder_factory=FakeForwarder,
        is_port_free=lambda port: port not in HELD_PORTS,
        clock=lambda: now[0],
    )
    runner.apply(CONFIG)
    FakeForwarder.made[0].is_listening = True
    real_states = instances_module.account_service.states

    def states(services, the_machine):
        if answers:
            raise answers[0]
        return real_states(services, the_machine)

    monkeypatch.setattr(instances_module.account_service, "states", states)
    return runner, now, answers


def test_a_failed_reading_keeps_the_last_one_and_the_next_reads_again(clocked, systemd):
    runner, now, answers = clocked
    systemd.active.add("neutrino_demo@ann.service")
    now[0] += instances_module.STATUS_TTL_S
    assert runner.is_active() is True
    systemd.active.clear()

    answers.append(OSError("the task read failed"))
    now[0] += instances_module.STATUS_TTL_S
    assert runner.is_active() is True

    answers.clear()
    assert runner.is_active() is False


def test_a_reading_that_keeps_failing_is_an_error(clocked, systemd):
    runner, now, answers = clocked
    systemd.active.add("neutrino_demo@ann.service")
    now[0] += instances_module.STATUS_TTL_S
    assert runner.is_active() is True

    answers.append(OSError("the task read failed"))
    now[0] += instances_module.STATUS_KEPT_S

    with pytest.raises(OSError, match="the task read failed"):
        runner.is_active()


def test_a_first_reading_that_fails_is_an_error(clocked):
    runner, _, answers = clocked
    runner._forget_states()
    answers.append(OSError("the task read failed"))

    with pytest.raises(OSError, match="the task read failed"):
        runner.is_active()


def test_the_forwarder_ports_are_the_ones_a_forwarder_listens_on(runner):
    runner.apply(CONFIG)
    assert runner.forwarder_ports() == ()

    FakeForwarder.made[0].is_listening = True

    assert runner.forwarder_ports() == (8443,)


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


def test_an_uninstall_deletes_the_modules_directory(runner, tmp_path):
    (tmp_path / "state" / "demo" / "node").mkdir(parents=True)

    runner.uninstall({})

    assert not (tmp_path / "state" / "demo").exists()


def test_an_uninstall_stops_the_installs_before_the_directory_goes(
    runner, tmp_path, monkeypatch
):
    held = tmp_path / "state" / "demo" / "node"
    held.mkdir(parents=True)
    seen = []
    monkeypatch.setattr(
        runner.hooks, "stop_installs", lambda: seen.append(held.exists())
    )

    runner.uninstall({})

    assert seen == [True]
    assert not held.exists()


def test_an_uninstall_tries_again_while_a_file_of_an_ended_process_stays(
    runner, tmp_path, monkeypatch
):
    """Windows kept node.exe a moment after the install's processes were ended."""
    directory = tmp_path / "state" / "demo"
    directory.mkdir(parents=True)
    removed = instances_module.remove_tree
    tries = []

    def remove_on_third(path):
        tries.append(path)
        if len(tries) == 3:
            removed(path)

    slept = []
    monkeypatch.setattr(instances_module, "remove_tree", remove_on_third)
    monkeypatch.setattr(instances_module.time, "sleep", slept.append)

    runner.uninstall({})

    assert len(tries) == 3
    assert slept == [1.0, 1.0]
    assert not directory.exists()


def test_an_uninstall_gives_up_on_a_directory_that_stays(runner, tmp_path, monkeypatch):
    directory = tmp_path / "state" / "demo"
    directory.mkdir(parents=True)
    tries = []
    slept = []
    monkeypatch.setattr(instances_module, "remove_tree", tries.append)
    monkeypatch.setattr(instances_module.time, "sleep", slept.append)

    runner.uninstall({})

    assert len(tries) == 30
    assert directory.exists()


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


@pytest.mark.parametrize(
    "is_folder", [False, True], ids=["log_not_written_yet", "log_path_no_file"]
)
def test_without_units_the_log_files_come_then_the_agents_lines(tmp_path, is_folder):
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
    if is_folder:
        (tmp_path / "install_bob.log").mkdir()

    first = runner.journal_text(200)

    assert first[:2] == ["ann: a1", "10:00 demo: running"]
    assert first[2].startswith("10:02 demo: started")
    warned = [line for line in first if "cannot read the log source" in line]
    assert len(warned) == (1 if is_folder else 0)


def test_a_modules_own_log_is_read_in_place_of_the_units_journal(
    runner, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "neutrino_agent.modules.shared.base.units_journal",
        lambda units, lines: ["journal of the unit"],
    )
    runner.apply(CONFIG)
    own = tmp_path / "codeg-server.2026-10-11.log"
    own.write_text("l1\nl2\n")

    before = runner.journal_text(10)
    runner.hooks.journal_log = lambda record: (
        str(own) if record["account"] == "ann" else ""
    )
    after = runner.journal_text(10)

    assert before == ["journal of the unit"]
    assert after == ["ann: l1", "ann: l2"]


def test_a_discarded_output_without_an_own_log_reads_no_file(tmp_path):
    agent_log = tmp_path / "agent.log"
    agent_log.write_text("10:00 demo: running\n")
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
        log=lambda line: None,
        machine=machine,
        forwarder_factory=FakeForwarder,
    )
    runner.apply(CONFIG)
    kept_service = runner.hooks.service
    runner.hooks.service = lambda instance, entry, record: dataclasses.replace(
        kept_service(instance, entry, record), is_output_discarded=True
    )

    lines = runner.journal_text(200)

    assert lines == ["10:00 demo: running"]


# --- a record the hooks change ---


def test_a_record_the_hooks_change_asks_for_a_configure_task(runner, systemd):
    runner.apply(CONFIG)
    systemd.calls.clear()
    asked: list = []
    runner.bind_configure_asker(lambda: asked.append("demo"))

    runner.hooks._reapply("ann", upstream_port=42000)

    assert runner._records.read("ann")["upstream_port"] == 42000
    assert asked == ["demo"]
    assert systemd.calls == []
    runner.apply(CONFIG)
    assert systemd.units("restart") == [
        ["systemctl", "restart", "neutrino_demo@ann.service"]
    ]
    assert runner.hooks._reapply("ghost") is None
    assert asked == ["demo"]


# --- the steps of a task ---


def core_steps(want):
    """``configure`` and ``start`` or ``stop`` as the core plans them."""
    second = "start" if want == "running" else "stop"
    return [
        ModuleStep(name="configure", run=lambda context: None),
        ModuleStep(name=second, run=lambda context: None),
    ]


def run_steps(steps):
    for step in steps:
        step.run(None)


TWO = {"instances": [INSTANCE, {"account": "bob", "secret": "b"}]}


def test_a_running_module_s_steps_are_configure_then_each_account_then_start(
    runner,
):
    steps = runner.configure_steps(TWO, "running", core_steps("running"))

    assert [(step.name, step.params) for step in steps] == [
        ("configure", {}),
        ("account", {"account": "ann"}),
        ("account", {"account": "bob"}),
        ("start", {}),
    ]


def test_a_stopped_module_s_steps_are_configure_then_stop(runner):
    steps = runner.configure_steps(TWO, "stopped", core_steps("stopped"))

    assert [step.name for step in steps] == ["configure", "stop"]


def test_a_module_that_installs_per_account_puts_its_step_before_each_account(
    machine, platform
):
    class NpmHooks(DemoHooks):
        prepare_step = "npm"

    runner = InstancesModuleRunner(
        hooks_class=NpmHooks,
        platform=platform,
        log=lambda line: None,
        machine=machine,
        forwarder_factory=FakeForwarder,
    )

    steps = runner.configure_steps(TWO, "running", core_steps("running"))
    run_steps(steps)

    assert [(step.name, step.params) for step in steps] == [
        ("configure", {}),
        ("npm", {"account": "ann"}),
        ("account", {"account": "ann"}),
        ("npm", {"account": "bob"}),
        ("account", {"account": "bob"}),
        ("start", {}),
    ]
    assert runner.hooks.prepared == [("ann", "/home/ann"), ("bob", "/home/bob")]


def test_the_configure_step_starts_no_instance_and_each_account_starts_its_own(
    runner, systemd, tmp_path
):
    configure, ann, bob, _start = runner.configure_steps(
        TWO, "running", core_steps("running")
    )

    configure.run(None)
    after_configure = list(systemd.calls)
    ann.run(None)

    assert after_configure == [["systemctl", "daemon-reload"]]
    assert runner.hooks.prepared == [("ann", "/home/ann")]
    assert systemd.calls[1:] == [
        ["systemctl", "enable", "neutrino_demo@ann.service"],
        ["systemctl", "restart", "neutrino_demo@ann.service"],
    ]
    assert sorted(os.listdir(tmp_path / "config" / "demo")) == ["ann.env", "ann.json"]
    assert [forwarder.record["account"] for forwarder in FakeForwarder.made] == ["ann"]
    bob.run(None)
    assert sorted(os.listdir(tmp_path / "config" / "demo")) == [
        "ann.env",
        "ann.json",
        "bob.env",
        "bob.json",
    ]


def test_the_configure_step_retires_an_account_no_longer_named(
    runner, systemd, tmp_path
):
    runner.apply(TWO)
    systemd.calls.clear()

    configure, _ann, _start = runner.configure_steps(
        CONFIG, "running", core_steps("running")
    )
    configure.run(None)

    assert ["systemctl", "disable", "--now", "neutrino_demo@bob.service"] in (
        systemd.calls
    )
    assert runner._records.read("bob") == {}


def test_a_changed_template_restarts_each_instance_at_its_own_step(
    runner, systemd, tmp_path
):
    runner.apply(TWO)
    (tmp_path / "systemd" / "neutrino_demo@.service").write_text("old\n")
    systemd.calls.clear()

    steps = runner.configure_steps(TWO, "running", core_steps("running"))
    run_steps(steps)
    run_steps(runner.configure_steps(TWO, "running", core_steps("running")))

    assert [call[2] for call in systemd.units("restart")] == [
        "neutrino_demo@ann.service",
        "neutrino_demo@bob.service",
    ]


def test_an_account_whose_install_still_runs_holds_its_step(machine, platform):
    class NpmHooks(DemoHooks):
        prepare_step = "npm"

        def prepare(self, parsed, instance, entry):
            self.installing = frozenset({instance.account})
            return []

    runner = InstancesModuleRunner(
        hooks_class=NpmHooks,
        platform=platform,
        log=lambda line: None,
        machine=machine,
        forwarder_factory=FakeForwarder,
    )
    _configure, npm, _account, _start = runner.configure_steps(
        CONFIG, "running", core_steps("running")
    )

    with pytest.raises(ModuleInstallPending):
        npm.run(None)
    assert runner.is_installing() is True


def test_a_failed_account_step_is_the_journal_s_last_line_until_configure_takes(
    runner, monkeypatch
):
    monkeypatch.setattr(
        "neutrino_agent.modules.shared.base.units_journal",
        lambda units, lines: [],
    )
    configure, ann, _start = runner.configure_steps(
        CONFIG, "running", core_steps("running")
    )
    runner.hooks.prepare_error = ModuleApplyError("demo_npm_failed", {"account": "ann"})

    configure.run(None)
    with pytest.raises(ModuleApplyError):
        ann.run(None)
    refused = runner.journal_text(10)
    configure.run(None)

    assert refused == ["demo: demo_npm_failed account=ann"]
    assert runner.journal_text(10) == []


def test_a_failure_of_the_system_at_an_account_step_is_apply_failed(runner, systemd):
    configure, ann, _start = runner.configure_steps(
        CONFIG, "running", core_steps("running")
    )
    configure.run(None)
    systemd.error = OSError("systemctl refused")

    with pytest.raises(ModuleApplyError) as caught:
        ann.run(None)

    assert caught.value.code == "apply_failed"
    assert caught.value.params["detail"] == "systemctl refused"


# --- the machine ---


def test_the_machine_names_the_modules_directory_under_the_state_root():
    linux = machine_for(Platform("linux", "/agent"), "demo")
    windows = machine_for(Platform("windows", "C:\\N\\agent"), "demo")

    assert (linux.module_dir, linux.record_dir) == (
        "/agent/state/demo",
        "/agent/state/demo",
    )
    assert windows.module_dir == "C:\\N\\agent/state\\demo"
    assert windows.lookup_account("ann") == AccountEntry(0, 0, "C:\\Users\\ann", "")
    with pytest.raises(KeyError):
        windows.lookup_account("ghost")


# --- artifacts ---


def node_archive(path):
    with tarfile.open(path, "w:gz") as packed:
        info = tarfile.TarInfo("node-v22/bin/node")
        info.size = 2
        packed.addfile(info, io.BytesIO(b"hi"))
    return str(path)


def test_an_artifact_lands_under_its_directory_and_the_hooks_tidy_after(
    runner, platform, tmp_path
):
    tidied = []
    runner.hooks.after_install = functools.partial(tidied.append, True)
    artifact = {"name": "node", "kind": "tar_gz", "directory": "node"}

    runner.install_artifact({}, artifact, node_archive(tmp_path / "node.tar.gz"))

    node = tmp_path / "state" / "demo" / "node"
    assert (node / "bin" / "node").read_bytes() == b"hi"
    assert tidied == [True]
    assert platform.opened == [str(tmp_path / "state" / "demo")]
    assert platform.labelled == [str(node)]


def test_an_artifact_directory_that_is_not_a_plain_name_is_refused(runner, tmp_path):
    for directory in ("..", "a/b", "a\\b"):
        artifact = {"name": "x", "kind": "tar_gz", "directory": directory}
        with pytest.raises(ModuleApplyError) as caught:
            runner.install_artifact({}, artifact, str(tmp_path / "none.tar"))
        assert caught.value.code == "install_failed"


def test_an_archive_that_cannot_be_read_is_install_failed(runner, tmp_path):
    junk = tmp_path / "junk.tar"
    junk.write_bytes(b"junk")
    artifact = {"name": "node", "kind": "tar_gz", "directory": "node"}

    with pytest.raises(ModuleApplyError) as caught:
        runner.install_artifact({}, artifact, str(junk))

    assert caught.value.code == "install_failed"
