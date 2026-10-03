"""The CloudCLI runner: Node.js from the hub's bytes, an instance and a forwarder per account.

What these pin: Node.js is there when its interpreter is; an apply hands
the applier each account's loopback port, kept across applies, and keeps a
root-only record per instance; one forwarder runs per record and follows
it; an account no longer named loses its record and its forwarder; a stop
closes every forwarder; a restarted agent starts the forwarders again from
the records; a row runs only while its instance runs and its forwarder
listens; each system gets its own applier; and a failed download is the
module's own code.
"""

import ntpath
import os
import stat

import pytest

import neutrino_agent.modules.cloudcli.runner as runner_module
from neutrino_agent.core.engine import _download_refusal
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.cloudcli.darwin_applier import CloudcliDarwinApplier
from neutrino_agent.modules.cloudcli.linux_applier import CloudcliLinuxApplier
from neutrino_agent.modules.cloudcli.runner import (
    CloudcliModuleRunner,
    cloudcli_applier_for,
)
from neutrino_agent.modules.cloudcli.windows_applier import CloudcliWindowsApplier
from neutrino_agent.platforms.base import AgentPlatform

INSTANCE = {"account": "ann", "port": 3001, "web_password": "p", "token_secret": "s"}
CONFIG = {"gateway_url": "http://10.0.0.1:8317", "instances": [INSTANCE]}


class FakeApplier:
    def __init__(self, tmp_path):
        self.module_dir = str(tmp_path / "cloudcli")
        self.record_dir = str(tmp_path / "records")
        self.node = ""
        self.calls: list = []
        self.running: set = set()
        self.error = None

    def apply(self, config, upstream_ports):
        self.calls.append(("apply", dict(upstream_ports)))
        if self.error is not None:
            raise self.error
        return []

    def stop(self):
        self.calls.append(("stop",))

    def remove(self):
        self.calls.append(("remove",))

    def states(self, accounts):
        return {
            account: {"is_running": account in self.running, "code": ""}
            for account in accounts
        }

    def units(self):
        return []

    def log_paths(self, accounts):
        return []


class FakeForwarder:
    made: list = []

    def __init__(self, **fields):
        self.fields = fields
        self.is_started = False
        self.is_closed = False
        self.is_listening = False
        self.failure = ("", {})
        FakeForwarder.made.append(self)

    def matches(self, record):
        return all(
            self.fields[name] == record[name]
            for name in (
                "account",
                "port",
                "upstream_port",
                "web_password",
                "token_secret",
            )
        )

    def start(self):
        self.is_started = True

    def close(self):
        self.is_closed = True


class Platform(AgentPlatform):
    def __init__(self, os_name, root=""):
        self.os_name = os_name
        self._root = root

    def agent_var_dir(self):
        return self._root + "/state"

    def agent_data_dir(self):
        return self._root + "/config"


@pytest.fixture
def applier(tmp_path):
    return FakeApplier(tmp_path)


@pytest.fixture
def runner(applier):
    FakeForwarder.made = []
    ports = iter([41000, 41001, 41002])
    return CloudcliModuleRunner(
        platform=Platform("linux"),
        log=lambda line: None,
        applier=applier,
        forwarder_factory=FakeForwarder,
        pick_port=lambda: next(ports),
    )


def test_node_is_there_when_its_interpreter_is(runner, applier, tmp_path):
    assert runner.verify({}) is False
    node = tmp_path / "node"
    node.write_text("")
    applier.node = str(node)

    assert runner.verify({}) is True


def test_an_apply_keeps_a_record_and_starts_a_forwarder(runner, applier):
    runner.apply(CONFIG)

    assert applier.calls == [("apply", {"ann": 41000})]
    path = os.path.join(applier.record_dir, "ann.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started
    assert forwarder.fields["upstream_port"] == 41000
    assert forwarder.fields["token_secret"] == "s"


def test_the_loopback_port_and_the_forwarder_are_kept_across_applies(runner, applier):
    runner.apply(CONFIG)
    runner.apply(CONFIG)

    assert applier.calls[-1] == ("apply", {"ann": 41000})
    assert len(FakeForwarder.made) == 1


def test_a_changed_instance_gets_a_new_forwarder(runner):
    runner.apply(CONFIG)
    runner.apply(dict(CONFIG, instances=[dict(INSTANCE, port=3002)]))

    first, second = FakeForwarder.made
    assert first.is_closed and second.is_started
    assert second.fields["port"] == 3002


def test_an_account_no_longer_named_loses_its_record_and_forwarder(runner, applier):
    runner.apply(CONFIG)

    runner.apply({"instances": []})

    assert os.listdir(applier.record_dir) == []
    assert FakeForwarder.made[0].is_closed


def test_a_failed_apply_writes_no_record(runner, applier):
    applier.error = OSError("systemd is gone")

    with pytest.raises(ModuleApplyError) as caught:
        runner.apply(CONFIG)

    assert caught.value.code == "apply_failed"
    assert not os.path.isdir(applier.record_dir)


def test_a_stop_closes_the_forwarders_and_keeps_the_records(runner, applier):
    runner.apply(CONFIG)

    runner.stop()

    assert FakeForwarder.made[0].is_closed
    assert os.listdir(applier.record_dir) == ["ann.json"]
    assert runner.details({}) == {
        "instances": [{"account": "ann", "port": 3001, "is_running": False, "code": ""}]
    }


def test_a_restarted_agent_starts_the_forwarders_from_the_records(runner, applier):
    runner.apply(CONFIG)
    FakeForwarder.made = []
    again = CloudcliModuleRunner(
        platform=Platform("linux"),
        log=lambda line: None,
        applier=applier,
        forwarder_factory=FakeForwarder,
    )

    again.details({})

    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started
    assert forwarder.fields["upstream_port"] == 41000


def test_a_row_runs_only_while_the_instance_runs_and_its_forwarder_listens(
    runner, applier
):
    runner.apply(CONFIG)
    applier.running.add("ann")
    assert runner.is_active() is False

    FakeForwarder.made[0].is_listening = True
    runner._forget_states()

    assert runner.is_active() is True
    FakeForwarder.made[0].failure = ("cloudcli_register_failed", {})
    FakeForwarder.made[0].is_listening = False
    assert runner.details({})["instances"][0]["code"] == "cloudcli_register_failed"


def test_removing_the_configuration_forgets_every_record(runner, applier):
    runner.apply(CONFIG)

    runner.remove_configuration()

    assert applier.calls[-1] == ("remove",)
    assert os.listdir(applier.record_dir) == []
    assert runner.details({}) == {"instances": []}


def test_a_failed_download_is_the_modules_own_code(runner):
    assert _download_refusal(runner, {"code": "module_fetch_failed", "params": {}}) == {
        "code": "cloudcli_node_download_failed",
        "params": {"detail": "module_fetch_failed"},
    }
    assert _download_refusal(runner, {"code": "hub_unreachable", "params": {}}) == {
        "code": "hub_unreachable",
        "params": {},
    }


def test_each_system_gets_its_own_applier(tmp_path):
    linux = cloudcli_applier_for(Platform("linux", "/agent"))
    darwin = cloudcli_applier_for(Platform("darwin", "/Library/N/agent"))
    windows = cloudcli_applier_for(Platform("windows", "C:\\N\\agent"))

    assert isinstance(linux, CloudcliLinuxApplier)
    assert linux.module_dir == "/agent/state/cloudcli"
    assert linux.record_dir == "/agent/config/cloudcli"
    assert isinstance(darwin, CloudcliDarwinApplier)
    assert darwin.module_dir == "/Library/N/agent/state/cloudcli"
    assert darwin.record_dir == "/Library/N/agent/config/cloudcli"
    assert isinstance(windows, CloudcliWindowsApplier)
    assert windows.module_dir == ntpath.join("C:\\N\\agent/state", "cloudcli")
    with pytest.raises(PlatformUnsupportedError):
        cloudcli_applier_for(Platform("plan9"))


def test_an_install_opens_the_node_directory_to_every_account(applier, monkeypatch):
    opened = []

    class OpeningPlatform(Platform):
        def open_to_accounts(self, directory):
            opened.append(directory)

    monkeypatch.setattr(runner_module, "unpack_node", lambda path, **kwargs: path)
    held = CloudcliModuleRunner(
        platform=OpeningPlatform("linux"),
        log=lambda line: None,
        applier=applier,
        forwarder_factory=FakeForwarder,
    )

    held.install({"entry": {"package_kind": "tar"}}, "/tmp/node.tar.gz")

    assert opened == [applier.module_dir]


class LoggedPlatform(Platform):
    """A platform whose agent writes its log to one file, as Windows and macOS do."""

    def __init__(self, os_name, log_path):
        super().__init__(os_name)
        self._log_path = log_path

    def agent_log_path(self):
        return self._log_path


@pytest.mark.parametrize("os_name", ["windows", "darwin"])
def test_without_units_the_log_files_come_then_the_agent_s_lines(os_name, tmp_path):
    agent_log = tmp_path / "agent.log"
    agent_log.write_text(
        "10:00 cloudcli: running\n10:01 samba: unchanged\n", encoding="utf-8"
    )

    def write(message):
        with open(agent_log, "a", encoding="utf-8") as stream:
            stream.write(f"10:02 {message}\n")

    applier = FakeApplier(tmp_path)
    applier.units = lambda: []
    held = CloudcliModuleRunner(
        platform=LoggedPlatform(os_name, str(agent_log)), log=write, applier=applier
    )
    ann = tmp_path / "ann.log"
    ann.write_text("a1\n", encoding="utf-8")
    missing = str(tmp_path / "bob.log")
    applier.log_paths = lambda *args: [("ann", str(ann)), ("bob", missing)]

    first = held.journal_text(200)
    second = held.journal_text(200)
    applier.log_paths = lambda *args: []
    alone = held.journal_text(200)

    assert first[:2] == ["ann: a1", "10:00 cloudcli: running"]
    assert first[2].startswith(f"10:02 cloudcli: cannot read the log source {missing}")
    assert len(first) == 3
    assert second == first
    assert alone == first[1:]
