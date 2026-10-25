"""The macOS part of a Podman machine, driven through a recording platform,
a recorded run and a fake installer.

What these pin: Podman's pkg handed to the system's installer and a failure
carried as ``podman_install_failed``; the uninstall deleting what the pkg
put on the computer and forgetting its receipt; the computer's size from
``sysctl``; the disk read from the machine's settings file; the stop and
the resources through ``podman machine``; the account's own ``TMPDIR`` read
once per account and carried by every machine command; and the macOS
platform choosing this applier.
"""

import json
import os
import subprocess

import pytest

from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.podman.darwin_applier import PodmanDarwinApplier
from neutrino_agent.modules.podman.machine import PodmanMachine
from neutrino_agent.modules.podman.machine_runner import (
    PodmanSystemApplier,
    podman_system_applier_for,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

TEMP_DIR = "/var/folders/xy/abc123/T/"
PKG = {"name": "podman", "kind": "pkg", "directory": "podman"}


class RecordingPlatform(AgentPlatform):
    """A Mac whose runs as an account are recorded and answered from a list."""

    os_name = "darwin"

    def __init__(self, home="/Users/me", answers=()):
        self._home = home
        self.calls: list = []
        self.answers = list(answers)

    def account_home(self, account):
        if account != "me":
            raise KeyError(account)
        return self._home

    def run_as_account(
        self, account, argv, *, stdin="", timeout_s=0, password="", environment=None
    ):
        if account != "me":
            raise KeyError(account)
        self.calls.append(
            {"account": account, "argv": list(argv), "environment": environment}
        )
        answer = self.answers.pop(0) if self.answers else (0, TEMP_DIR + "\n")
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
        return CommandResult(list(command), code, stdout, stderr)


class RecordingInstaller:
    """``installers.install_pkg``, recorded, raising what it is given."""

    def __init__(self, error=None):
        self.paths: list = []
        self.error = error

    def __call__(self, path):
        self.paths.append(path)
        if self.error is not None:
            raise self.error


def applier(platform=None, run=None, install_pkg=None, installed_paths=()):
    return PodmanDarwinApplier(
        platform=platform or RecordingPlatform(),
        run=run or RecordingRun(),
        install_pkg=install_pkg or RecordingInstaller(),
        installed_paths=installed_paths,
    )


def machine(platform, home, environment=None) -> PodmanMachine:
    return PodmanMachine(
        platform=platform,
        account="me",
        password="",
        binary="/opt/podman/bin/podman",
        provider="applehv",
        environment=environment,
        run=RecordingRun(),
    )


def write_settings(home, settings) -> None:
    directory = home / ".config/containers/podman/machine/applehv"
    directory.mkdir(parents=True)
    (directory / "podman-machine-default.json").write_text(json.dumps(settings))


def test_the_program_is_podmans_pkg_install_and_the_provider_applehv():
    assert PodmanDarwinApplier.binary == "/opt/podman/bin/podman"
    assert PodmanDarwinApplier.provider == "applehv"
    assert not applier().is_reboot_pending()


def test_the_pkg_goes_to_the_systems_installer():
    install_pkg = RecordingInstaller()

    applier(install_pkg=install_pkg).install_artifact(PKG, "/state/podman.pkg")

    assert install_pkg.paths == ["/state/podman.pkg"]


@pytest.mark.parametrize("exit_code, reported", [(1, 1), (None, 1), (143, 143)])
def test_a_failed_installer_is_podman_install_failed_with_its_exit_code(
    exit_code, reported
):
    error = InstallError("installer failed: no space", exit_code=exit_code)

    with pytest.raises(ModuleApplyError) as refused:
        applier(install_pkg=RecordingInstaller(error)).install_artifact(PKG, "/p.pkg")

    assert refused.value.code == "podman_install_failed"
    assert refused.value.params == {"artifact": "podman", "exit_code": reported}


def test_an_artifact_that_is_not_a_pkg_is_refused_before_any_installer_runs():
    install_pkg = RecordingInstaller()
    artifact = {"name": "podman", "kind": "msi"}

    with pytest.raises(ModuleApplyError) as refused:
        applier(install_pkg=install_pkg).install_artifact(artifact, "/p.msi")

    assert refused.value.code == "install_failed"
    assert install_pkg.paths == []


def test_the_uninstall_deletes_the_pkgs_files_and_forgets_its_receipt(tmp_path):
    program = tmp_path / "opt/podman/bin"
    program.mkdir(parents=True)
    (program / "podman").write_text("")
    paths_file = tmp_path / "paths.d/podman-pkg"
    paths_file.parent.mkdir()
    paths_file.write_text("/opt/podman/bin\n")
    man_link = tmp_path / "podman.man.conf"
    os.symlink(str(tmp_path / "gone"), man_link)
    run = RecordingRun([(1, "", "No receipt for 'com.redhat.podman' found at '/'.")])
    installed = (str(tmp_path / "opt/podman"), str(paths_file), str(man_link))

    applier(run=run, installed_paths=installed).uninstall()

    assert not (tmp_path / "opt/podman").exists()
    assert not paths_file.exists()
    assert not os.path.lexists(man_link)
    assert run.calls == [["pkgutil", "--forget", "com.redhat.podman"]]


def test_an_uninstall_with_nothing_there_still_forgets_the_receipt(tmp_path):
    run = RecordingRun()

    applier(run=run, installed_paths=(str(tmp_path / "opt/podman"),)).uninstall()

    assert run.calls == [["pkgutil", "--forget", "com.redhat.podman"]]


def test_the_computers_size_is_read_from_sysctl():
    run = RecordingRun([(0, "10\n17179869184\n", "")])

    assert applier(run=run).host_facts() == (10, 16)
    assert run.calls == [["/usr/sbin/sysctl", "-n", "hw.logicalcpu", "hw.memsize"]]


@pytest.mark.parametrize(
    "answer", [(1, "", "unknown oid"), (0, "10\n", ""), OSError("no sysctl")]
)
def test_a_sysctl_that_does_not_answer_is_the_bases_reading(answer):
    run = RecordingRun([answer])

    assert applier(run=run).host_facts() == PodmanSystemApplier().host_facts()


def test_the_disk_is_the_size_podman_wrote_in_the_settings_file(tmp_path):
    write_settings(tmp_path, {"Resources": {"CPUs": 2, "DiskSize": 120}})
    platform = RecordingPlatform(home=str(tmp_path))

    assert applier(platform).disk_gib(machine(platform, tmp_path)) == 120


@pytest.mark.parametrize("settings", [None, {}, {"Resources": {"DiskSize": "x"}}])
def test_a_disk_that_cannot_be_read_is_0(tmp_path, settings):
    if settings is not None:
        write_settings(tmp_path, settings)
    platform = RecordingPlatform(home=str(tmp_path))

    assert applier(platform).disk_gib(machine(platform, tmp_path)) == 0


def test_an_account_the_computer_does_not_have_has_no_disk(tmp_path):
    platform = RecordingPlatform(home=str(tmp_path))
    stranger = PodmanMachine(
        platform=platform,
        account="ann",
        password="",
        binary="/opt/podman/bin/podman",
        provider="applehv",
    )

    assert applier(platform).disk_gib(stranger) == 0


def test_halt_resources_and_disk_are_podman_machine_verbs(tmp_path):
    platform = RecordingPlatform(home=str(tmp_path), answers=[(0, "")] * 3)
    system = applier(platform)
    mac = machine(platform, tmp_path, {"TMPDIR": TEMP_DIR})

    system.halt(mac)
    system.write_resources(mac, cpus=4, memory_gib=6)
    system.resize_disk(mac, disk_gib=150)

    assert [call["argv"][1:] for call in platform.calls] == [
        ["machine", "stop", "podman-machine-default"],
        [
            "machine",
            "set",
            "--cpus",
            "4",
            "--memory",
            "6144",
            "podman-machine-default",
        ],
        ["machine", "set", "--disk-size", "150", "podman-machine-default"],
    ]
    for call in platform.calls:
        assert call["environment"] == {
            "TMPDIR": TEMP_DIR,
            "CONTAINERS_MACHINE_PROVIDER": "applehv",
        }


def test_a_smaller_disk_is_refused_with_podmans_words(tmp_path):
    words = "Error: new disk size must be larger than 150 GB"
    platform = RecordingPlatform(home=str(tmp_path), answers=[(125, words)])

    with pytest.raises(ModuleApplyError) as refused:
        applier(platform).resize_disk(machine(platform, tmp_path), disk_gib=100)

    assert refused.value.code == "machine_set_failed"
    assert refused.value.params == {"detail": words}


def test_the_accounts_temporary_directory_is_read_once_as_the_account():
    platform = RecordingPlatform()
    system = applier(platform)

    assert system.machine_environment("me") == {"TMPDIR": TEMP_DIR}
    assert system.machine_environment("me") == {"TMPDIR": TEMP_DIR}
    assert platform.calls == [
        {
            "account": "me",
            "argv": ["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"],
            "environment": None,
        }
    ]


@pytest.mark.parametrize(
    "answer",
    [(1, ""), (0, "\n"), OSError("no getconf"), subprocess.TimeoutExpired("x", 30)],
)
def test_a_directory_that_cannot_be_read_is_no_variable_and_is_asked_again(answer):
    platform = RecordingPlatform(answers=[answer])
    system = applier(platform)

    assert system.machine_environment("me") == {}
    assert system.machine_environment("me") == {"TMPDIR": TEMP_DIR}


def test_an_account_the_computer_does_not_have_gets_no_variable():
    assert applier().machine_environment("ann") == {}


def test_the_mac_platform_chooses_this_applier():
    platform = RecordingPlatform()

    chosen = podman_system_applier_for(platform)

    assert isinstance(chosen, PodmanDarwinApplier)
    assert chosen.machine_environment("me") == {"TMPDIR": TEMP_DIR}
