"""The Podman machine's command lines, run as the account through a recording
platform, and the reads the agent makes itself through the ssh port."""

import json
import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.podman.machine import PodmanMachine
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

WINDOWS_BINARY = "C:\\Program Files\\Podman\\podman.exe"
INSPECT = json.dumps(
    [{"Name": "podman-machine-default", "State": "stopped", "Rootful": False}]
)


class RecordingPlatform(AgentPlatform):
    """Runs nothing: each run as an account is recorded and answered from a list."""

    def __init__(self, os_name="windows", home="C:\\Users\\lab", answers=()):
        self.os_name = os_name
        self._home = home
        self.calls: list = []
        self.answers = list(answers)

    def account_home(self, account):
        if account not in ("lab", "me"):
            raise KeyError(account)
        return self._home

    def run_as_account(
        self, account, argv, *, stdin="", timeout_s=0, password="", environment=None
    ):
        self.calls.append(
            {
                "account": account,
                "argv": list(argv),
                "stdin": stdin,
                "timeout_s": timeout_s,
                "password": password,
                "environment": dict(environment or {}),
            }
        )
        answer = self.answers.pop(0) if self.answers else (0, "")
        if isinstance(answer, BaseException):
            raise answer
        code, output = answer
        return subprocess.CompletedProcess(list(argv), code, output, "")


class RecordingRun:
    """The agent's own commands, recorded and answered from a list."""

    def __init__(self, answers=()):
        self.calls: list = []
        self.answers = list(answers)

    def __call__(self, command, *, is_checked=True, timeout_s=0, **_):
        self.calls.append(list(command))
        answer = self.answers.pop(0) if self.answers else (0, "", "")
        if isinstance(answer, BaseException):
            raise answer
        code, stdout, stderr = answer
        if is_checked and code:
            raise subprocess.CalledProcessError(code, command, stdout, stderr)
        return CommandResult(list(command), code, stdout, stderr)


def windows_machine(platform=None, run=None) -> PodmanMachine:
    return PodmanMachine(
        platform=platform or RecordingPlatform(),
        account="lab",
        password="pw",
        binary=WINDOWS_BINARY,
        provider="wsl",
        run=run or RecordingRun(),
    )


def mac_machine(tmp_path, platform=None, run=None) -> PodmanMachine:
    return PodmanMachine(
        platform=platform or RecordingPlatform("darwin", str(tmp_path / "me")),
        account="me",
        password="",
        binary="/opt/podman/bin/podman",
        provider="applehv",
        run=run or RecordingRun(),
    )


def write_settings(tmp_path, port=50743) -> None:
    directory = tmp_path / "me/.config/containers/podman/machine/applehv"
    directory.mkdir(parents=True)
    (directory / "podman-machine-default.json").write_text(
        json.dumps({"Name": "podman-machine-default", "SSH": {"Port": port}})
    )


def test_every_machine_command_runs_as_the_account_with_its_login_and_provider():
    platform = RecordingPlatform(answers=[(0, INSPECT)])

    state = windows_machine(platform).inspect()

    assert state.state == "stopped"
    assert not state.is_rootful
    assert not state.is_running
    assert platform.calls == [
        {
            "account": "lab",
            "argv": [WINDOWS_BINARY, "machine", "inspect", "podman-machine-default"],
            "stdin": "",
            "timeout_s": 300,
            "password": "pw",
            "environment": {"CONTAINERS_MACHINE_PROVIDER": "wsl"},
        }
    ]


def test_a_wsl_init_names_the_kept_image_and_no_size():
    platform = RecordingPlatform()
    machine = windows_machine(platform)

    machine.init(
        "C:\\state\\podman\\image\\image.tar.zst", cpus=2, memory_gib=4, disk_gib=120
    )

    assert not machine.is_sized_at_init
    assert platform.calls[0]["argv"] == [
        WINDOWS_BINARY,
        "machine",
        "init",
        "--rootful",
        "--image",
        "C:\\state\\podman\\image\\image.tar.zst",
        "podman-machine-default",
    ]
    assert platform.calls[0]["timeout_s"] == 900


def test_an_applehv_init_takes_its_size(tmp_path):
    platform = RecordingPlatform("darwin", str(tmp_path / "me"))
    machine = mac_machine(tmp_path, platform)

    machine.init("/state/image/image.raw.zst", cpus=4, memory_gib=3, disk_gib=100)

    assert machine.is_sized_at_init
    assert platform.calls[0]["argv"] == [
        "/opt/podman/bin/podman",
        "machine",
        "init",
        "--rootful",
        "--image",
        "/state/image/image.raw.zst",
        "--cpus",
        "4",
        "--memory",
        "3072",
        "--disk-size",
        "100",
        "podman-machine-default",
    ]
    assert platform.calls[0]["environment"] == {
        "CONTAINERS_MACHINE_PROVIDER": "applehv"
    }
    assert platform.calls[0]["password"] == ""


def test_the_machines_variables_go_with_every_command_and_the_provider_wins(
    tmp_path,
):
    platform = RecordingPlatform("darwin", str(tmp_path / "me"))
    machine = PodmanMachine(
        platform=platform,
        account="me",
        password="",
        binary="/opt/podman/bin/podman",
        provider="applehv",
        environment={
            "TMPDIR": "/var/folders/xy/abc/T/",
            "CONTAINERS_MACHINE_PROVIDER": "libkrun",
        },
        run=RecordingRun(),
    )

    machine.stop()
    machine.shell("true\n")

    for call in platform.calls:
        assert call["environment"] == {
            "TMPDIR": "/var/folders/xy/abc/T/",
            "CONTAINERS_MACHINE_PROVIDER": "applehv",
        }


def test_rootful_resources_start_and_stop_are_podman_machine_verbs(tmp_path):
    platform = RecordingPlatform("darwin", str(tmp_path / "me"))
    machine = mac_machine(tmp_path, platform)

    machine.set_rootful()
    machine.set_resources(cpus=2, disk_gib=150)
    machine.set_resources()
    machine.start()
    machine.stop()

    assert [call["argv"][2:] for call in platform.calls] == [
        ["set", "--rootful", "podman-machine-default"],
        ["set", "--cpus", "2", "--disk-size", "150", "podman-machine-default"],
        ["start", "podman-machine-default"],
        ["stop", "podman-machine-default"],
    ]


@pytest.mark.parametrize(
    "step, code",
    [
        (
            lambda machine: machine.init("i", cpus=0, memory_gib=0, disk_gib=0),
            "machine_init_failed",
        ),
        (lambda machine: machine.set_rootful(), "machine_set_failed"),
        (lambda machine: machine.start(), "machine_unreachable"),
        (lambda machine: machine.inspect(), "machine_unreachable"),
    ],
)
def test_a_refused_step_carries_podmans_own_words(step, code):
    platform = RecordingPlatform(answers=[(125, "Error: VM does not exist\n")])

    with pytest.raises(ModuleApplyError) as refused:
        step(windows_machine(platform))

    assert refused.value.code == code
    assert refused.value.params == {"detail": "Error: VM does not exist"}


def test_a_refused_login_is_not_renamed():
    error = ModuleApplyError("credential_invalid", {"account": "lab"})
    platform = RecordingPlatform(answers=[error])

    with pytest.raises(ModuleApplyError) as refused:
        windows_machine(platform).start()

    assert refused.value.code == "credential_invalid"


def test_the_root_script_goes_in_on_standard_input_through_podman_machine_ssh():
    platform = RecordingPlatform(answers=[(0, "changed: x\n")])

    done = windows_machine(platform).shell("echo hi\n")

    assert done.stdout == "changed: x\n"
    assert platform.calls[0]["argv"] == [
        WINDOWS_BINARY,
        "machine",
        "ssh",
        "--username",
        "root",
        "podman-machine-default",
        "sh",
        "-s",
    ]
    assert platform.calls[0]["stdin"] == "echo hi\n"
    assert platform.calls[0]["timeout_s"] == 1800


def test_the_windows_paths_are_in_the_accounts_profile():
    machine = windows_machine()

    assert machine.settings_path() == (
        "C:\\Users\\lab\\.config\\containers\\podman\\machine\\wsl"
        "\\podman-machine-default.json"
    )
    assert machine.identity_path() == (
        "C:\\Users\\lab\\.local\\share\\containers\\podman\\machine\\machine"
    )


def test_the_read_names_the_port_from_the_settings_file_and_the_key_in_place(
    tmp_path,
):
    write_settings(tmp_path, port=50743)
    machine = mac_machine(tmp_path)

    assert machine.is_present()
    assert machine.read_command() == (
        "/opt/podman/bin/podman",
        "--url",
        "ssh://root@127.0.0.1:50743/run/podman/podman.sock",
        "--identity",
        f"{tmp_path}/me/.local/share/containers/podman/machine/machine",
    )


def test_the_port_is_read_again_at_every_read(tmp_path):
    write_settings(tmp_path, port=49759)
    machine = mac_machine(tmp_path)
    first = machine.read_command()
    settings = tmp_path / "me/.config/containers/podman/machine/applehv"
    (settings / "podman-machine-default.json").write_text(
        json.dumps({"SSH": {"Port": 50743}})
    )

    assert "127.0.0.1:49759" in first[2]
    assert "127.0.0.1:50743" in machine.read_command()[2]


def test_no_settings_file_is_no_machine_and_names_no_port(tmp_path):
    machine = mac_machine(tmp_path)

    assert not machine.is_present()
    with pytest.raises(ModuleApplyError) as refused:
        machine.read_command()
    assert refused.value.code == "machine_unreachable"


def test_info_is_read_by_the_agent_itself_through_the_ssh_url(tmp_path):
    write_settings(tmp_path)
    run = RecordingRun([(0, json.dumps({"host": {"cpus": 2}}), "")])
    machine = mac_machine(tmp_path, run=run)

    assert machine.info() == {"host": {"cpus": 2}}
    assert run.calls[0][-3:] == ["info", "--format", "json"]
    assert run.calls[0][1:3] == [
        "--url",
        "ssh://root@127.0.0.1:50743/run/podman/podman.sock",
    ]


def test_info_from_a_machine_that_does_not_answer_is_unreachable(tmp_path):
    write_settings(tmp_path)
    run = RecordingRun([(125, "", "Error: unable to connect to Podman socket")])

    with pytest.raises(ModuleApplyError) as refused:
        mac_machine(tmp_path, run=run).info()

    assert refused.value.code == "machine_unreachable"
    assert refused.value.params == {
        "detail": "Error: unable to connect to Podman socket"
    }


def test_a_hand_started_container_is_driven_through_the_read(tmp_path):
    write_settings(tmp_path)
    run = RecordingRun()

    mac_machine(tmp_path, run=run).control("adhoc", "restart")

    assert run.calls[0][0] == "/opt/podman/bin/podman"
    assert run.calls[0][-2:] == ["restart", "adhoc"]
