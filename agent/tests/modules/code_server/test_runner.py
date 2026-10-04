"""The code-server runner: the release from the hub's bytes, an instance and a forwarder per account.

What these pin: the release is there when its launcher is; an install
unpacks a fake release archive, stopping running instances first; an apply
keeps a root-only record per instance and one forwarder per record, on the
account's socket; a changed instance gets a new forwarder; an account no
longer named loses its record and its forwarder; a stop closes every
forwarder and keeps the records; a restarted agent starts the forwarders
again from the records; the details name the version installed and each
instance, running only while its instance runs and its forwarder listens;
each system gets its own applier and Windows none; a failed download is the
module's own code; and a refused apply's code is the journal's last line.
"""

import os
import stat

import pytest

from neutrino_agent.core.engine import _download_refusal
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.code_server.darwin_applier import CodeServerDarwinApplier
from neutrino_agent.modules.code_server.linux_applier import CodeServerLinuxApplier
from neutrino_agent.modules.code_server.runner import (
    CodeServerModuleRunner,
    code_server_applier_for,
)
from neutrino_agent.platforms.base import AgentPlatform
from tests.modules.code_server.test_installer import release_archive

INSTANCE = {"account": "ann", "port": 8443, "secret": "s"}
CONFIG = {"instances": [INSTANCE]}


class FakeApplier:
    def __init__(self, tmp_path):
        self.module_dir = str(tmp_path / "code_server")
        self.record_dir = str(tmp_path / "records")
        self.calls: list = []
        self.running: set = set()
        self.error = None

    def apply(self, config):
        self.calls.append(("apply", [i.account for i in config.instances]))
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
        return ["neutrino_code_server@ann.service"]

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

    def matches(self, record, socket_path):
        return (
            all(self.fields[name] == record[name] for name in ("account", "port"))
            and self.fields["secret"] == record["secret"]
            and self.fields["socket_path"] == socket_path
        )

    def start(self):
        self.is_started = True

    def close(self):
        self.is_closed = True


class Platform(AgentPlatform):
    def __init__(self, os_name, root=""):
        self.os_name = os_name
        self._root = root
        self.opened: list = []

    def agent_var_dir(self):
        return self._root + "/state"

    def agent_data_dir(self):
        return self._root + "/config"

    def open_to_accounts(self, directory):
        self.opened.append(directory)


@pytest.fixture
def applier(tmp_path):
    return FakeApplier(tmp_path)


@pytest.fixture
def platform():
    return Platform("linux")


@pytest.fixture
def runner(applier, platform):
    FakeForwarder.made = []
    return CodeServerModuleRunner(
        platform=platform,
        log=lambda line: None,
        applier=applier,
        forwarder_factory=FakeForwarder,
    )


def test_an_install_unpacks_the_release_and_opens_it_to_every_account(
    runner, applier, platform, tmp_path
):
    assert runner.verify({}) is False

    runner.install(
        {"entry": {"package_kind": "tar"}}, release_archive(tmp_path / "a.tar.gz")
    )

    assert runner.verify({}) is True
    assert platform.opened == [applier.module_dir]
    assert ("stop",) not in applier.calls
    runner.install(
        {"entry": {"package_kind": "tar"}},
        release_archive(tmp_path / "b.tar.gz", "4.141.0"),
    )
    assert ("stop",) in applier.calls
    assert runner.details({})["version"] == "4.141.0"


def test_an_apply_keeps_a_record_and_starts_a_forwarder_on_the_socket(runner, applier):
    runner.apply(CONFIG)

    assert applier.calls == [("apply", ["ann"])]
    path = os.path.join(applier.record_dir, "ann.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started
    assert forwarder.fields["secret"] == "s"
    assert forwarder.fields["socket_path"] == os.path.join(
        applier.module_dir, "run", "ann", "code_server.sock"
    )


def test_a_changed_instance_gets_a_new_forwarder_and_an_unchanged_one_stays(runner):
    runner.apply(CONFIG)
    runner.apply(CONFIG)
    runner.apply({"instances": [dict(INSTANCE, port=8444)]})

    first, second = FakeForwarder.made
    assert first.is_closed and second.is_started
    assert second.fields["port"] == 8444


def test_an_account_no_longer_named_loses_its_record_and_forwarder(runner, applier):
    runner.apply(CONFIG)

    runner.apply({"instances": []})

    assert os.listdir(applier.record_dir) == []
    assert FakeForwarder.made[0].is_closed


def test_a_refused_configuration_reaches_neither_the_applier_nor_a_record(
    runner, applier
):
    with pytest.raises(ModuleApplyError) as caught:
        runner.apply({"instances": [dict(INSTANCE, secret="")]})

    assert caught.value.code == "secret_missing"
    assert applier.calls == []
    assert runner.journal_text(5)[-1] == "code_server: secret_missing account=ann"


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
    assert runner.details({})["instances"] == [
        {"account": "ann", "port": 8443, "is_running": False, "code": ""}
    ]


def test_a_restarted_agent_starts_the_forwarders_from_the_records(
    runner, applier, platform
):
    runner.apply(CONFIG)
    FakeForwarder.made = []

    again = CodeServerModuleRunner(
        platform=platform,
        log=lambda line: None,
        applier=applier,
        forwarder_factory=FakeForwarder,
    )
    again.details({})

    (forwarder,) = FakeForwarder.made
    assert forwarder.is_started and forwarder.fields["account"] == "ann"


def test_an_instance_runs_only_while_code_server_runs_and_its_forwarder_listens(
    runner, applier
):
    runner.apply(CONFIG)
    applier.running.add("ann")
    runner._forget_states()
    assert runner.is_active() is False

    FakeForwarder.made[0].is_listening = True
    FakeForwarder.made[0].failure = ("", {})

    assert runner.is_active() is True
    assert runner.details({})["instances"][0]["is_running"] is True


def test_a_forwarder_s_failure_is_the_instance_s_code(runner, applier):
    runner.apply(CONFIG)
    FakeForwarder.made[0].failure = ("code_server_port_taken", {"port": 8443})

    assert runner.details({})["instances"][0]["code"] == "code_server_port_taken"


def test_an_uninstall_closes_the_forwarders_and_deletes_the_module_directory(
    runner, applier, tmp_path
):
    runner.install(
        {"entry": {"package_kind": "tar"}}, release_archive(tmp_path / "a.tar.gz")
    )
    runner.apply(CONFIG)

    runner.uninstall({})

    assert FakeForwarder.made[0].is_closed
    assert not os.path.exists(applier.module_dir)


def test_each_system_gets_its_own_applier_and_windows_none():
    assert isinstance(
        code_server_applier_for(Platform("linux", "/x")), CodeServerLinuxApplier
    )
    mac = code_server_applier_for(Platform("darwin", "/y"))
    assert isinstance(mac, CodeServerDarwinApplier)
    assert mac.module_dir == "/y/state/code_server"
    assert mac.record_dir == "/y/config/code_server"
    with pytest.raises(PlatformUnsupportedError):
        code_server_applier_for(Platform("windows", "C:"))


def test_a_failed_download_is_the_module_s_own_code(runner):
    refusal = _download_refusal(
        runner, {"code": "module_sha256_mismatch", "params": {}}
    )

    assert refusal == {
        "code": "code_server_download_failed",
        "params": {"detail": "module_sha256_mismatch"},
    }


def test_the_journal_is_the_units_and_the_refusal_last(runner, monkeypatch):
    monkeypatch.setattr(
        "neutrino_agent.modules.base.units_journal",
        lambda units, lines: [f"journal of {units[0]}"],
    )

    assert runner.journal_text(10) == ["journal of neutrino_code_server@ann.service"]
