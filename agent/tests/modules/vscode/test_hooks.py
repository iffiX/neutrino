"""VS Code's hooks: where the CLI is, each server's service, the inotify floors.

What these pin: the CLI artifact, which names no directory, lands through
the shared unpack directly in the module's directory beside the token
files, runnable by every account and writable by none; the CLI is there
when its file is, and its version is what it prints, read once per CLI
file;
a configuration is checked for this system; each server's service runs the
CLI as the account with its token in a file of the account's own, reading
its address, port and token file from the environment on Linux and from
the command line elsewhere, and names no forwarder; the record carries the
address the servers listen on and the details name each server's url; and
on Linux low inotify limits are raised to the floors and the drop-in goes
with the configuration.
"""

import io
import os
import stat
import tarfile
import zipfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.instances import InstancesModuleRunner
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.shared.package import unpack_artifact
from neutrino_agent.modules.vscode.hooks import VscodeHooks
from neutrino_agent.platforms.base import AgentPlatform

CONFIG = {"address": "", "instances": [{"account": "ann", "token": "t"}]}
ANN = AccountEntry(1000, 1000, "/home/ann", "/bin/bash")


class Platform(AgentPlatform):
    def __init__(self, os_name="linux", root=""):
        self.os_name = os_name
        self._root = root
        self.opened: list = []

    def agent_var_dir(self):
        return self._root + "/state"

    def agent_data_dir(self):
        return self._root + "/config"

    def open_to_accounts(self, directory):
        self.opened.append(directory)


class Systemd:
    def __init__(self):
        self.calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        return CommandResult(list(command), 0, "", "")


def tarball(path, members: dict) -> str:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return str(path)


def hooks_for(os_name, tmp_path, **kwargs) -> VscodeHooks:
    hooks = VscodeHooks(platform=Platform(os_name), log=lambda line: None, **kwargs)
    machine = ServiceMachine(
        os_name=os_name,
        module_dir=str(tmp_path / "state" / "vscode"),
        record_dir=str(tmp_path / "config" / "vscode"),
        lookup_account=lambda account: ANN,
        run=Systemd(),
    )
    hooks.bind(machine, None)
    return hooks


def parsed_instance(hooks, **changes):
    config = hooks.parse({"instances": [dict(CONFIG["instances"][0], **changes)]})
    return config, config.instances[0]


# --- the CLI ---


CLI = {"name": "cli", "kind": "tar_gz"}


def test_the_cli_lands_in_the_modules_directory_beside_the_tokens(tmp_path):
    hooks = hooks_for("linux", tmp_path)
    tokens = tmp_path / "state" / "vscode" / "tokens"
    tokens.mkdir(parents=True)
    (tokens / "ann.token").write_text("t")
    assert hooks.verify() is False

    unpack_artifact(
        CLI,
        tarball(tmp_path / "cli.tar.gz", {"code": b"\x7fELF"}),
        module_dir=hooks.machine.module_dir,
        join=os.path.join,
    )

    assert hooks.verify() is True
    assert hooks.cli_path == str(tmp_path / "state" / "vscode" / "code")
    assert open(hooks.cli_path, "rb").read() == b"\x7fELF"
    assert stat.S_IMODE(os.stat(hooks.cli_path).st_mode) & 0o222 == 0
    assert (tokens / "ann.token").read_text() == "t"
    assert hooks_for("windows", tmp_path).cli_path.endswith("vscode\\code.exe")


def test_the_cli_comes_out_of_a_zip_with_its_one_top_directory_dropped(tmp_path):
    archive = tmp_path / "cli.zip"
    with zipfile.ZipFile(archive, "w") as packed:
        packed.writestr("bin/code.exe", b"MZ")

    unpack_artifact(
        {"name": "cli", "kind": "zip"},
        str(archive),
        module_dir=str(tmp_path / "v"),
        join=os.path.join,
    )

    assert (tmp_path / "v" / "code.exe").read_bytes() == b"MZ"


# --- the configuration and the service ---


class VersionRun:
    """``code --version``, answered and counted."""

    def __init__(self):
        self.calls: list = []
        self.printed = "code 1.144.0 (commit 3b0d6c1)\n"

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        return CommandResult(list(command), 0, self.printed, "")


def test_the_version_is_what_the_cli_prints_read_once_per_cli_file(tmp_path):
    hooks = VscodeHooks(platform=Platform("darwin"), log=lambda line: None)
    run = VersionRun()
    hooks.bind(
        ServiceMachine(
            os_name="darwin",
            module_dir=str(tmp_path / "state" / "vscode"),
            record_dir=str(tmp_path / "config" / "vscode"),
            lookup_account=lambda account: ANN,
            run=run,
        ),
        None,
    )
    assert hooks.module_details() == {"version": ""}

    os.makedirs(os.path.dirname(hooks.cli_path))
    with open(hooks.cli_path, "w", encoding="utf-8") as stream:
        stream.write("1")

    assert hooks.module_details() == {"version": "1.144.0"}
    assert hooks.module_details() == {"version": "1.144.0"}
    assert run.calls == [[hooks.cli_path, "--version"]]
    with open(hooks.cli_path, "a", encoding="utf-8") as stream:
        stream.write("1")
    run.printed = "unexpected words\n"
    assert hooks.module_details() == {"version": ""}
    assert len(run.calls) == 2


def test_a_configuration_is_checked_for_this_system(tmp_path):
    hooks_for("linux", tmp_path).parse(CONFIG)

    with pytest.raises(ModuleApplyError) as refused:
        hooks_for("windows", tmp_path).parse(CONFIG)

    assert refused.value.code == "credential_missing"


def test_the_linux_service_reads_its_address_port_and_token_from_the_environment(
    tmp_path,
):
    hooks = hooks_for("linux", tmp_path)
    config, instance = parsed_instance(hooks)
    record = hooks.record(config, instance, {"port": 8000})

    service = hooks.service(instance, ANN, record)

    token_dir = str(tmp_path / "state" / "vscode" / "tokens")
    assert record == {"account": "ann", "port": 8000, "host": "127.0.0.1"}
    assert service.command == (
        hooks.cli_path,
        "serve-web",
        "--accept-server-license-terms",
        "--host",
        "${VSCODE_HOST}",
        "--port",
        "${VSCODE_PORT}",
        "--connection-token-file",
        "${VSCODE_TOKEN_FILE}",
    )
    assert service.environment == {
        "VSCODE_HOST": "127.0.0.1",
        "VSCODE_PORT": "8000",
        "VSCODE_TOKEN_FILE": token_dir + "/ann.token",
    }
    assert service.environment_dir == token_dir
    assert service.files == ((token_dir + "/ann.token", "t"),)
    assert service.is_environment_secret is False
    assert service.listen_port == 8000
    assert VscodeHooks.is_forwarded is False


@pytest.mark.parametrize("os_name", ["darwin", "windows"])
def test_elsewhere_the_command_line_carries_the_address_port_and_token_file(
    tmp_path, os_name
):
    hooks = hooks_for(os_name, tmp_path)
    config, instance = parsed_instance(hooks, password="pw")
    addressed = hooks.parse(
        {"address": "192.168.1.5", "instances": [dict(instance.__dict__)]}
    )
    record = hooks.record(addressed, instance, {"port": 8000})

    service = hooks.service(instance, ANN, record)

    assert service.command[3:] == (
        "--host",
        "192.168.1.5",
        "--port",
        "8000",
        "--connection-token-file",
        service.files[0][0],
    )
    assert service.environment == {}
    assert service.password == "pw"
    assert hooks.details_extra(record) == {"url": "http://192.168.1.5:8000/"}


def test_a_record_without_an_address_names_loopback(tmp_path):
    hooks = hooks_for("linux", tmp_path)

    assert hooks.details_extra({"account": "ann", "port": 8000}) == {
        "url": "http://127.0.0.1:8000/"
    }


# --- the inotify limits ---


def limits(tmp_path, watches, instances):
    """What the kernel reports for the two inotify limits."""
    inotify = tmp_path / "proc" / "fs" / "inotify"
    inotify.mkdir(parents=True, exist_ok=True)
    (inotify / "max_user_watches").write_text(f"{watches}\n")
    (inotify / "max_user_instances").write_text(f"{instances}\n")


def limited_hooks(tmp_path, os_name="linux") -> VscodeHooks:
    (tmp_path / "sysctl.d").mkdir(exist_ok=True)
    return hooks_for(
        os_name,
        tmp_path,
        sysctl_path=str(tmp_path / "sysctl.d" / "90-neutrino-vscode.conf"),
        proc_dir=str(tmp_path / "proc"),
    )


def test_low_inotify_limits_are_raised_to_the_floors(tmp_path):
    limits(tmp_path, 65536, 128)
    hooks = limited_hooks(tmp_path)

    notes = hooks.prepare_module()

    drop_in = (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").read_text()
    assert drop_in == (
        "fs.inotify.max_user_watches = 524288\nfs.inotify.max_user_instances = 512\n"
    )
    assert ["sysctl", "-p", str(tmp_path / "sysctl.d" / "90-neutrino-vscode.conf")] in (
        hooks.machine.run.calls
    )
    assert notes == ["raised the inotify limits"]
    assert hooks.prepare_module() == []


def test_limits_already_high_enough_are_left_alone(tmp_path):
    limits(tmp_path, 1048576, 1024)
    hooks = limited_hooks(tmp_path)

    assert hooks.prepare_module() == []
    assert not (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").exists()


def test_only_the_limit_below_its_floor_is_raised(tmp_path):
    limits(tmp_path, 1048576, 128)
    hooks = limited_hooks(tmp_path)

    hooks.prepare_module()

    drop_in = (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").read_text()
    assert drop_in == "fs.inotify.max_user_instances = 512\n"


def test_forgetting_the_module_deletes_the_drop_in_and_a_mac_touches_none(tmp_path):
    limits(tmp_path, 65536, 128)
    hooks = limited_hooks(tmp_path)
    hooks.prepare_module()

    hooks.forget_module()

    assert not (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").exists()
    assert limited_hooks(tmp_path, "darwin").prepare_module() == []


# --- through the shared runner ---


def test_the_runner_writes_the_token_the_environment_and_the_unit(tmp_path):
    systemd = Systemd()
    (tmp_path / "systemd").mkdir()
    platform = Platform("linux", str(tmp_path))
    machine = ServiceMachine(
        os_name="linux",
        module_dir=str(tmp_path / "state" / "vscode"),
        record_dir=str(tmp_path / "config" / "vscode"),
        lookup_account=lambda account: ANN,
        run=systemd,
        chown=lambda path, uid, gid: None,
        systemd_dir=str(tmp_path / "systemd"),
    )
    runner = InstancesModuleRunner(
        hooks_class=VscodeHooks,
        platform=platform,
        log=lambda line: None,
        machine=machine,
        is_port_free=lambda port: True,
    )
    runner.install_artifact({}, CLI, tarball(tmp_path / "cli.tar.gz", {"code": b"hi"}))

    runner.apply(CONFIG)

    tokens = tmp_path / "state" / "vscode" / "tokens"
    assert (tokens / "ann.token").read_text() == "t"
    assert stat.S_IMODE(os.stat(tokens / "ann.token").st_mode) == 0o600
    assert (tokens / "ann.env").read_text() == (
        f"VSCODE_HOST=127.0.0.1\nVSCODE_PORT=8000\nVSCODE_TOKEN_FILE={tokens}/ann.token\n"
    )
    unit = (tmp_path / "systemd" / "neutrino_vscode@.service").read_text()
    assert f"EnvironmentFile={tokens}/%i.env\n" in unit
    assert systemd.calls[-2:] == [
        ["systemctl", "enable", "neutrino_vscode@ann.service"],
        ["systemctl", "restart", "neutrino_vscode@ann.service"],
    ]
    assert runner.details({}) == {
        "version": "",
        "instances": [
            {
                "account": "ann",
                "port": 8000,
                "is_running": False,
                "code": "",
                "url": "http://127.0.0.1:8000/",
            }
        ],
    }
    assert runner.journal_units() == ["neutrino_vscode@ann.service"]
