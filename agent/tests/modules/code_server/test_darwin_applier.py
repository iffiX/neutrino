"""code-server on macOS, with launchctl and the account database faked.

What these pin: each instance is a LaunchDaemon that runs the release's
launcher as ``UserName`` on the account's socket with code-server's own
login off, its output in its own log file under the agents' log directory;
an account the Mac does not have is refused; a changed or unloaded job is
booted out and bootstrapped, a loaded unchanged one left alone; and an
instance no longer named is booted out with its plist, its log and its run
directory deleted.
"""

import os
import plistlib

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server.config import CodeServerConfig
from neutrino_agent.modules.code_server.darwin_applier import CodeServerDarwinApplier
from neutrino_agent.modules.subprocess_run import CommandResult

CONFIG = CodeServerConfig.from_dict(
    {"instances": [{"account": "ann", "port": 8443, "secret": "s"}]}
)
LABEL = "com.neutrino.code_server.ann"


class Machine:
    """launchctl, recorded; ``print`` answers for the loaded labels."""

    def __init__(self):
        self.calls: list = []
        self.loaded: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[1] == "print":
            label = command[2].split("/", 1)[1]
            is_loaded = label in self.loaded
            return CommandResult(
                list(command),
                0 if is_loaded else 113,
                "state = running\n" if is_loaded else "",
                "",
            )
        if command[1] == "bootstrap":
            self.loaded.add(os.path.basename(command[3])[: -len(".plist")])
        if command[1] == "bootout":
            self.loaded.discard(command[2].split("/", 1)[1])
        return CommandResult(list(command), 0, "", "")


def lookup(account):
    if account != "ann":
        raise KeyError(account)
    return 501, 20, "/Users/ann", "/bin/zsh"


@pytest.fixture
def machine():
    return Machine()


@pytest.fixture
def applier(tmp_path, machine):
    module_dir = tmp_path / "cs"
    (module_dir / "release" / "bin").mkdir(parents=True)
    (module_dir / "release" / "bin" / "code-server").write_text("#!/bin/sh\n")
    (tmp_path / "daemons").mkdir()
    return CodeServerDarwinApplier(
        module_dir=str(module_dir),
        record_dir=str(tmp_path / "records"),
        run=machine,
        lookup_account=lookup,
        chown=lambda path, uid, gid: None,
        launchd_dir=str(tmp_path / "daemons"),
        log_dir=str(tmp_path / "logs"),
    )


def test_an_instance_is_a_launch_daemon_of_its_account_on_its_socket(
    applier, machine, tmp_path
):
    notes = applier.apply(CONFIG)

    with open(tmp_path / "daemons" / f"{LABEL}.plist", "rb") as stream:
        plist = plistlib.load(stream)
    module_dir = str(tmp_path / "cs")
    assert plist["UserName"] == "ann"
    assert plist["ProgramArguments"] == [
        f"{module_dir}/release/bin/code-server",
        "--socket",
        f"{module_dir}/run/ann/code_server.sock",
        "--auth",
        "none",
        "--socket-mode",
        "600",
        "--disable-telemetry",
        "--disable-update-check",
    ]
    assert plist["EnvironmentVariables"]["HOME"] == "/Users/ann"
    assert plist["StandardOutPath"] == str(tmp_path / "logs" / "code_server_ann.log")
    assert [
        "launchctl",
        "bootstrap",
        "system",
        str(tmp_path / "daemons" / f"{LABEL}.plist"),
    ] in machine.calls
    assert os.path.isdir(tmp_path / "cs" / "run" / "ann")
    assert notes == ["started code-server of ann"]
    assert applier.states(["ann"]) == {"ann": {"is_running": True, "code": ""}}


def test_a_loaded_unchanged_job_is_left_alone(applier, machine):
    applier.apply(CONFIG)
    machine.calls.clear()

    assert applier.apply(CONFIG) == []
    assert all(call[1] == "print" for call in machine.calls)


def test_an_account_the_mac_does_not_have_is_refused(applier, machine):
    config = CodeServerConfig.from_dict(
        {"instances": [{"account": "bob", "port": 8443, "secret": "s"}]}
    )

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(config)

    assert caught.value.code == "account_unknown"
    assert machine.calls == []


def test_an_instance_no_longer_named_is_booted_out_and_its_files_deleted(
    applier, machine, tmp_path
):
    applier.apply(CONFIG)

    applier.apply(CodeServerConfig.from_dict({"instances": []}))

    assert ["launchctl", "bootout", f"system/{LABEL}"] in machine.calls
    assert os.listdir(tmp_path / "daemons") == []
    assert not os.path.exists(tmp_path / "logs" / "code_server_ann.log")
    assert not os.path.exists(tmp_path / "cs" / "run" / "ann")
    assert applier.log_paths(["ann"]) == [
        ("ann", str(tmp_path / "logs" / "code_server_ann.log"))
    ]
