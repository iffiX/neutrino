"""The Podman machine runner, driven through a fake system applier, a fake
machine and a recorded launchd.

What these pin: the artifacts kept as the publisher's files with an msi or
a pkg handed to the system's installer; Podman's msi or pkg installed and
uninstalled only with the package mark, a Podman found before the install
being the person's and left as it is on macOS and Windows, by an install,
another version and an uninstall; an install owed while no machine image is
kept, on either Podman, and the details saying whether the package mark
stands; a restart owed holding the apply as
``reboot_required``; each refusal before anything runs, a Windows disk of 0
among them; a new machine made from the kept image and sized where the
provider takes no size at init, its image opened to the account first,
and removed when that sizing fails; a
memory of 0 as half the computer's at most 4 GiB, in the details too; a
machine taken over made rootful and sized, refused a smaller disk; a change
of size against the last apply, the disk grown and never shrunk; a growth
cut half way finished at the next apply; a new account stopping the old
machine and removing its keeper; the wait for the machine to answer; the one
root script; the reads through the ssh URL with addresses blanked and
folders back in the computer's form; the read's command a container's
shell runs through, empty before any apply; a machine step with no
account failing ``machine_account_missing``; the keeper's log in the
journal; a container module's journal asked while one runs taking that
read's lines; the verbs; stop stopping the containers, the keeper and the
machine, and start bringing them back; a stopped machine woken by its
keeper for a removal or a container module's uninstall; removal and
uninstall keeping the machine; a configure under ``stopped`` keeping the
configuration and starting nothing; with no record, Stop stopping and
disabling the keeper of the configured account and an uninstall removing
it with its plist and its log; one line for a machine retired, stopped or
not stopped, and none where no machine exists; and a restarted agent reading
on from the record.
"""

import functools
import json
import ntpath
import os
import subprocess
import threading

import pytest

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.podman import applier as applier_module
from neutrino_agent.modules.podman import machine_runner as machine_runner_module
from neutrino_agent.modules.podman.config import PodmanConfig
from neutrino_agent.modules.podman.constants import PODMAN_MACHINE_INFO_TTL_S
from neutrino_agent.modules.podman.container_runner import ContainerModuleRunner
from neutrino_agent.modules.podman.darwin_applier import PodmanDarwinApplier
from neutrino_agent.modules.podman.machine import PodmanMachineState
from neutrino_agent.modules.podman.machine_runner import (
    PODMAN_GIB,
    PodmanMachineModuleRunner,
    PodmanSystemApplier,
    default_memory_gib,
)
from neutrino_agent.modules.podman.renderer import (
    PodmanMachineScriptRenderer,
    PodmanRenderContext,
    machine_control_script,
    machine_drop_script,
    machine_journal_script,
    machine_stop_script,
)
from neutrino_agent.modules.podman.windows_applier import PodmanWindowsApplier
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms import base as platforms_base_module
from neutrino_agent.platforms.base import AgentPlatform

CONTAINERS = [
    {
        "name": "web",
        "image": "nginx",
        "ports": ["8080:80"],
        "volumes": ["/Users/me/www:/usr/share/nginx/html"],
    }
]
MACHINE = {"account": "me", "cpus": 2, "memory_gib": 4, "disk_gib": 0}
KNOWN_ACCOUNTS = ("me", "ann")
CONFIG = {"containers": CONTAINERS, "mirrors": [], "machine": MACHINE}

PS_OUTPUT = json.dumps(
    [
        {
            "Id": "0a1b",
            "Names": ["web"],
            "Image": "docker.io/library/nginx:latest",
            "State": "running",
            "Status": "Up 2 minutes",
            "StartedAt": 1791761649,
            "Ports": [
                {
                    "host_ip": "127.0.0.1",
                    "container_port": 80,
                    "host_port": 8080,
                    "protocol": "tcp",
                }
            ],
        },
        {
            "Id": "2c3d",
            "Names": ["adhoc"],
            "Image": "docker.io/library/alpine:3.20",
            "State": "exited",
            "Status": "Exited (0)",
            "Ports": None,
        },
    ]
)
INSPECT_OUTPUT = json.dumps(
    [
        {
            "Name": "web",
            "Config": {"Env": ["PATH=/usr/bin"]},
            "HostConfig": {
                "PortBindings": {
                    "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]
                }
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/mnt/c/www",
                    "Destination": "/usr/share/nginx/html",
                }
            ],
        },
        {"Name": "adhoc", "Config": {"Env": []}, "HostConfig": {}, "Mounts": []},
    ]
)
INFO = {"host": {"cpus": 2, "memTotal": 4 * PODMAN_GIB - 100 * 1024**2}}
PODMAN_PKG = {"name": "podman", "kind": "pkg", "directory": "podman"}
PODMAN_MSI = {"name": "podman", "kind": "msi", "directory": "podman"}
WSL_MSI = {"name": "wsl", "kind": "msi", "directory": "wsl"}
IMAGE_RAW = {"name": "image", "kind": "raw_zst", "directory": "image"}
WSL_CODE = "{2D92E6AF-35B2-4109-893F-59E4A4F2D550}"
PODMAN_CODE = "{E8D285D4-F069-44B9-BF8A-C41ED47B02B8}"
WEB_REFERENCE = "ghcr.io/acme/webui@sha256:" + "a" * 64
AGENT_REFERENCE = "docker.io/acme/agent@sha256:" + "b" * 64
IMAGE_RECIPE = {
    "runner": "container",
    "method": "container",
    "params": {
        "artifacts": [
            {
                "name": "webui",
                "kind": "image",
                "digest": "sha256:" + "a" * 64,
                "sources": ["ghcr.io/acme/webui"],
            },
            {
                "name": "agent",
                "kind": "image",
                "digest": "sha256:" + "b" * 64,
                "sources": ["docker.io/acme/agent"],
            },
        ]
    },
}


class World:
    """Every account's machine as the fake sees it, shared by each fake made."""

    def __init__(self):
        self.calls: list = []
        self.present: set = set()
        self.running: set = set()
        self.rootful: set = set()
        self.user_mode: set = set()
        self.scripts: list = []
        self.shell_answers: list = []
        self.answers_after = 0
        self.is_answering = True
        self.is_account_gone = False
        self.environments: list = []
        self.remove_error = None
        self.stop_error = None
        # Whether the machine answered the read at each root script.
        self.answering_at_shell: list = []


def machine_class_for(world: World):
    class FakeMachine:
        def __init__(
            self, *, platform, account, password, binary, provider, environment
        ):
            self.account = account
            self.password = password
            self.binary = binary
            self.provider = provider
            world.environments.append((account, dict(environment)))

        @property
        def is_sized_at_init(self):
            return self.provider != "wsl"

        def is_present(self):
            return self.account in world.present

        def inspect(self):
            world.calls.append((self.account, "inspect"))
            return PodmanMachineState(
                state="running" if self.account in world.running else "stopped",
                is_rootful=self.account in world.rootful,
                has_user_mode_networking=self.account in world.user_mode,
            )

        def init(self, image_path, *, cpus, memory_gib, disk_gib):
            world.calls.append(
                (self.account, "init", image_path, cpus, memory_gib, disk_gib)
            )
            world.present.add(self.account)
            world.rootful.add(self.account)

        def set_rootful(self):
            world.calls.append((self.account, "set_rootful"))
            world.rootful.add(self.account)

        def set_nat_networking(self):
            world.calls.append((self.account, "set_nat_networking"))
            world.user_mode.discard(self.account)

        def stop(self):
            world.calls.append((self.account, "stop", self.password))
            if world.stop_error is not None:
                raise world.stop_error
            world.running.discard(self.account)

        def remove(self):
            world.calls.append((self.account, "remove"))
            if world.remove_error is not None:
                raise world.remove_error
            for held in (world.present, world.running, world.rootful):
                held.discard(self.account)

        def read_command(self):
            if world.is_account_gone:
                raise KeyError(self.account)
            if not world.is_answering:
                raise ModuleApplyError("machine_unreachable", {"detail": "no port"})
            return (
                self.binary,
                "--url",
                f"ssh://root@127.0.0.1:50743/{self.account}",
                "--identity",
                "key",
            )

        def info(self, command=None):
            world.calls.append((self.account, "info"))
            if world.answers_after:
                world.answers_after -= 1
                raise ModuleApplyError("machine_unreachable", {"detail": "starting"})
            world.running.add(self.account)
            return dict(INFO)

        def shell(self, script):
            world.scripts.append((self.account, self.password, script))
            world.answering_at_shell.append(world.is_answering)
            code, output = (
                world.shell_answers.pop(0) if world.shell_answers else (0, "")
            )
            return subprocess.CompletedProcess([], code, output, "")

        def control(self, name, action):
            world.calls.append((self.account, "control", name, action))

    return FakeMachine


class FakeSystem(PodmanSystemApplier):
    """The system's part, recorded; its program a file in the test's directory,
    which an install of Podman's package writes."""

    provider = "applehv"

    def __init__(self, binary, provider="applehv"):
        self.binary = binary
        self.provider = provider
        self.calls: list = []
        self.opened: list = []
        self.is_pending = False
        self.disk = 0
        self.file_system = 0
        self.disk_error = None
        self.facts = (8, 16)
        self.install_error = None
        self.is_program_installed = True

    def install_artifact(self, artifact, path):
        self.calls.append(("install", artifact["name"], os.path.basename(path)))
        if self.install_error is not None:
            raise self.install_error
        if artifact["name"] != "wsl" and self.is_program_installed:
            with open(self.binary, "w", encoding="utf-8"):
                pass

    def open_image(self, path, account):
        self.opened.append((path, account))

    def is_reboot_pending(self):
        return self.is_pending

    def uninstall(self):
        self.calls.append(("uninstall",))

    def host_facts(self):
        return self.facts

    def disk_gib(self, machine):
        return self.disk

    def file_system_gib(self, machine):
        return self.file_system

    def halt(self, machine):
        self.calls.append(("halt", machine.account))

    def terminate(self, machine):
        self.calls.append(("terminate", machine.account))

    def write_resources(self, machine, *, cpus, memory_gib):
        self.calls.append(("resources", machine.account, cpus, memory_gib))

    def resize_disk(self, machine, *, disk_gib):
        self.calls.append(("disk", machine.account, disk_gib))
        self.disk = disk_gib
        if self.disk_error is not None:
            raise self.disk_error
        self.file_system = disk_gib

    def machine_environment(self, account):
        return {"TMPDIR": f"/var/folders/{account}/T/"}


class Launchctl:
    """launchctl, recorded: a job loaded by ``bootstrap`` until ``bootout``."""

    def __init__(self):
        self.calls: list = []
        self.loaded: set = set()
        # Called at each bootstrap, as the keeper starting the machine.
        self.on_bootstrap = None

    def __call__(self, command, *, is_checked=True, **_):
        self.calls.append(list(command))
        verb = command[1]
        if verb == "print":
            label = command[2].split("/", 1)[1]
            code = 0 if label in self.loaded else 113
            return CommandResult(list(command), code, "state = running\n", "")
        if verb == "bootstrap":
            self.loaded.add(os.path.basename(command[3])[: -len(".plist")])
            if self.on_bootstrap is not None:
                self.on_bootstrap()
        if verb == "bootout":
            self.loaded.discard(command[2].split("/", 1)[1])
        return CommandResult(list(command), 0, "", "")

    def verbs(self):
        return [call[1] for call in self.calls if call[1] != "print"]


class Platform(AgentPlatform):
    def __init__(self, root, os_name="darwin"):
        self.os_name = os_name
        self._root = root
        self.opened: list = []
        # Accounts the computer has with no profile yet.
        self.with_no_home: set = set()

    def agent_log_path(self):
        return os.path.join(self._root, "agent.log")

    def account_home(self, account):
        if account in self.with_no_home:
            raise KeyError(account)
        return f"/Users/{account}"

    def has_account(self, account):
        return account in KNOWN_ACCOUNTS

    def open_to_accounts(self, directory):
        self.opened.append(directory)


class FakeProbe:
    """Answers ``http`` for every port it is asked about, and records them."""

    asked: list = []

    def detected(self, targets):
        FakeProbe.asked.append(list(targets))
        return {key: "http" for key, _, _ in targets}


def lookup(platform, account):
    home = platform.account_home(account)
    if account not in KNOWN_ACCOUNTS:
        raise KeyError(account)
    return AccountEntry(501, 20, home, "/bin/zsh")


class Rig:
    """One runner on a fake Mac, with everything it drives recorded."""

    def __init__(self, tmp_path, *, os_name="darwin", provider="applehv"):
        binary = tmp_path / "podman"
        binary.write_text("")
        self.tmp_path = tmp_path
        self.world = World()
        self.system = FakeSystem(str(binary), provider)
        self.launchctl = Launchctl()
        self.platform = Platform(str(tmp_path), os_name)
        self.lines: list = []
        self.now = [0.0]
        self.service_machine = ServiceMachine(
            os_name="darwin",
            module_dir=str(tmp_path / "state" / "podman"),
            record_dir=str(tmp_path / "config" / "podman"),
            lookup_account=functools.partial(lookup, self.platform),
            run=self.launchctl,
            chown=lambda path, uid, gid: None,
            launchd_dir=str(tmp_path / "LaunchDaemons"),
            log_dir=str(tmp_path / "Logs"),
        )
        os.makedirs(self.service_machine.launchd_dir)
        self.runner = self.make_runner()

    def make_runner(self):
        return PodmanMachineModuleRunner(
            platform=self.platform,
            log=self.lines.append,
            system=self.system,
            service_machine=self.service_machine,
            machine_class=machine_class_for(self.world),
            clock=lambda: self.now[0],
            sleep=self.advance,
        )

    def advance(self, seconds):
        self.now[0] += seconds

    def keep_image(self, name="image.raw.zst"):
        directory = self.tmp_path / "state" / "podman" / "image"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text("zstd")
        return str(directory / name)

    def install_podman(self):
        """Podman's pkg installed by the module on a computer with no Podman."""
        os.unlink(self.system.binary)
        self.runner.install_artifact({}, dict(PODMAN_PKG), download(self.tmp_path))
        self.system.calls.clear()

    def package_mark(self):
        return self.tmp_path / "state" / "podman" / "package_mark"

    def record(self):
        path = self.tmp_path / "config" / "podman"
        found = sorted(path.glob("*.json")) if path.is_dir() else []
        return [json.loads(item.read_text()) for item in found]

    def plist(self, account="me"):
        return self.tmp_path / "LaunchDaemons" / f"com.neutrino.podman.{account}.plist"


@pytest.fixture(autouse=True)
def _reads(monkeypatch):
    """The reader's podman answers ps and inspect; the probe dials nothing."""
    asked = []

    def run(command, *, is_checked=True, timeout_s=0, **_):
        asked.append(list(command))
        if "--version" in command:
            return CommandResult(list(command), 0, "podman version 6.1.4\n", "")
        if "ps" in command:
            return CommandResult(list(command), 0, PS_OUTPUT, "")
        if "inspect" in command:
            return CommandResult(list(command), 0, INSPECT_OUTPUT, "")
        return CommandResult(list(command), 1, "", "unexpected")

    FakeProbe.asked = []
    monkeypatch.setattr(applier_module, "run", run)
    monkeypatch.setattr(machine_runner_module, "PodmanServiceProbe", FakeProbe)
    return asked


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def refusal(step) -> ModuleApplyError:
    with pytest.raises(ModuleApplyError) as refused:
        step()
    return refused.value


def download(tmp_path, name="podman") -> str:
    """One artifact as the stream lands it, before the runner keeps it."""
    path = tmp_path / f"{name}.download"
    path.write_text(f"{name} bytes")
    return str(path)


# --- the install ---


def test_an_msi_or_a_pkg_is_kept_and_handed_to_the_systems_installer(rig, tmp_path):
    os.unlink(rig.system.binary)
    package = tmp_path / "download"
    package.write_text("pkg bytes")
    artifact = {"name": "podman", "kind": "pkg", "directory": "podman"}

    rig.runner.install_artifact({}, artifact, str(package))

    kept = tmp_path / "state" / "podman" / "podman" / "podman.pkg"
    assert kept.read_text() == "pkg bytes"
    assert not package.exists()
    assert rig.system.calls == [("install", "podman", "podman.pkg")]
    assert rig.platform.opened == [str(tmp_path / "state" / "podman")]


def test_a_computer_with_no_podman_gets_the_installer_and_the_package_mark(
    rig, tmp_path
):
    os.unlink(rig.system.binary)

    rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))

    assert rig.system.calls == [("install", "podman", "podman.pkg")]
    assert rig.package_mark().is_file()
    assert oct(rig.package_mark().stat().st_mode & 0o777) == oct(0o600)
    assert not rig.runner.is_software_kept()


def test_a_podman_found_before_the_first_install_gets_no_installer_and_no_mark(
    rig, tmp_path
):
    rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))

    assert rig.system.calls == []
    assert (tmp_path / "state" / "podman" / "podman" / "podman.pkg").is_file()
    assert not rig.package_mark().exists()
    assert "podman: found the computer's own Podman, installed nothing" in rig.lines
    assert rig.runner.is_software_kept()


def test_the_module_s_podman_goes_to_the_installer_again_with_its_mark(rig, tmp_path):
    rig.install_podman()

    rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))

    assert rig.system.calls == [("install", "podman", "podman.pkg")]
    assert rig.package_mark().is_file()


@pytest.mark.parametrize("is_failed", [True, False])
def test_an_installer_that_leaves_no_podman_leaves_no_mark(rig, tmp_path, is_failed):
    os.unlink(rig.system.binary)
    rig.system.is_program_installed = False
    if is_failed:
        rig.system.install_error = ModuleApplyError(
            "podman_install_failed", {"artifact": "podman", "exit_code": 1}
        )

    try:
        rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))
    except ModuleApplyError as error:
        assert is_failed and error.code == "podman_install_failed"

    assert rig.system.calls == [("install", "podman", "podman.pkg")]
    assert not rig.package_mark().exists()
    assert not rig.runner.is_software_kept()


def test_wsl_goes_to_the_installer_beside_a_persons_podman_and_writes_no_mark(
    tmp_path,
):
    rig = Rig(tmp_path, os_name="windows", provider="wsl")

    rig.runner.install_artifact({}, dict(WSL_MSI), download(tmp_path, "wsl"))
    rig.runner.install_artifact({}, dict(PODMAN_MSI), download(tmp_path))

    assert [call[:2] for call in rig.system.calls] == [("install", "wsl")]
    assert rig.runner.is_software_kept()


def test_an_install_is_owed_while_no_image_is_kept_on_a_persons_podman(rig, tmp_path):
    recipe = {"params": {"artifacts": [dict(PODMAN_PKG), dict(IMAGE_RAW)]}}
    assert rig.runner.is_software_kept()
    assert rig.runner.is_install_owed(recipe) is True

    rig.runner.install_artifact(recipe, dict(PODMAN_PKG), download(tmp_path))
    rig.runner.install_artifact(recipe, dict(IMAGE_RAW), download(tmp_path, "image"))

    assert rig.system.calls == []
    assert rig.runner.is_install_owed(recipe) is False
    assert (tmp_path / "state" / "podman" / "image" / "image.raw.zst").is_file()
    assert not rig.package_mark().exists()


def test_an_install_is_owed_on_the_module_s_podman_with_no_image_kept(rig):
    recipe = {"params": {"artifacts": [dict(PODMAN_PKG), dict(IMAGE_RAW)]}}
    rig.install_podman()

    assert rig.runner.is_install_owed(recipe) is True
    rig.keep_image()
    assert rig.runner.is_install_owed(recipe) is False


def test_a_recipe_that_names_no_image_owes_no_install(rig):
    assert (
        rig.runner.is_install_owed({"params": {"artifacts": [dict(PODMAN_PKG)]}})
        is False
    )
    assert rig.runner.is_install_owed({}) is False


def test_the_details_say_whether_the_package_mark_stands(rig):
    assert rig.runner.details({})["has_package_mark"] is False

    rig.install_podman()

    assert rig.runner.details({})["has_package_mark"] is True


def test_the_image_is_kept_as_one_file_and_replaces_the_last(rig, tmp_path):
    old = rig.keep_image("image.tar.zst")
    package = tmp_path / "download"
    package.write_text("new image")
    artifact = {"name": "image", "kind": "raw_zst", "directory": "image"}

    rig.runner.install_artifact({}, artifact, str(package))

    assert not os.path.exists(old)
    kept = tmp_path / "state" / "podman" / "image" / "image.raw.zst"
    assert kept.read_text() == "new image"
    assert rig.system.calls == []


@pytest.mark.parametrize(
    "artifact",
    [
        {"name": "image", "kind": "zip", "directory": "image"},
        {"name": "image", "kind": "tar_zst", "directory": "../up"},
        {"name": "", "kind": "msi"},
    ],
)
def test_an_artifact_the_module_does_not_keep_is_refused(rig, tmp_path, artifact):
    package = tmp_path / "download"
    package.write_text("x")

    assert (
        refusal(lambda: rig.runner.install_artifact({}, artifact, str(package))).code
        == "install_failed"
    )


def test_podman_is_there_while_the_systems_program_is(rig, tmp_path):
    assert rig.runner.verify({})

    os.unlink(rig.system.binary)

    assert not rig.runner.verify({})


# --- the restart owed ---


def test_a_restart_owed_holds_the_apply_and_names_itself(rig):
    rig.system.is_pending = True

    with pytest.raises(ModuleInstallPending):
        rig.runner.apply(CONFIG)

    assert rig.runner.is_installing()
    assert rig.runner.install_wait() == {"code": "reboot_required", "params": {}}
    assert rig.world.calls == []
    rig.system.is_pending = False
    assert not rig.runner.is_installing()
    assert rig.runner.install_wait() == {}


# --- the steps of the module's task ---


def plain_step(name):
    return ModuleStep(name=name, run=None)


class FeaturesSystem(FakeSystem):
    """The system's part with Windows features, recorded."""

    has_windows_features = True

    def enable_features(self):
        self.calls.append(("features",))


def test_on_windows_the_install_turns_the_features_on_then_waits_for_the_restart(
    tmp_path,
):
    rig = Rig(tmp_path, provider="wsl")
    rig.system = FeaturesSystem(rig.system.binary, "wsl")
    rig.runner = rig.make_runner()
    planned = [plain_step("artifact"), plain_step("verify")]

    steps = rig.runner.install_steps({}, planned)
    steps[0].run(None)
    rig.system.is_pending = True

    assert [step.name for step in steps] == [
        "windows_features",
        "restart",
        "artifact",
        "verify",
    ]
    assert steps[0].locks == (("package_manager", "alone"),)
    assert [step.failed_state for step in steps[:2]] == ["install_failed"] * 2
    assert rig.system.calls == [("features",)]
    with pytest.raises(ModuleInstallPending):
        steps[1].run(None)
    rig.system.is_pending = False
    steps[1].run(None)


def test_a_system_with_no_windows_features_plans_the_method_s_install(rig):
    planned = [plain_step("artifact"), plain_step("verify")]

    assert rig.runner.install_steps({}, planned) is planned


def test_every_step_takes_containers_alone_and_the_restart_none(rig):
    assert rig.runner.step_locks("machine") == (("containers", "alone"),)
    assert rig.runner.step_locks("windows_features") == (("containers", "alone"),)
    assert rig.runner.step_locks("restart") == ()


def test_under_running_the_apply_is_the_machine_then_the_containers(rig):
    rig.keep_image()
    steps = rig.runner.configure_steps(
        CONFIG, "running", [plain_step("configure"), plain_step("start")]
    )

    assert [step.name for step in steps] == ["machine", "configure", "start"]
    steps[0].run(None)
    assert rig.world.scripts == []
    assert rig.record()[0]["cpus"] == 2
    steps[1].run(None)
    assert len(rig.world.scripts) == 1
    assert rig.record()[0]["names"] == ["web"]


def test_under_stopped_the_configure_keeps_the_configuration_and_starts_nothing(rig):
    rig.keep_image()
    planned = [plain_step("configure"), plain_step("stop")]

    steps = rig.runner.configure_steps(CONFIG, "stopped", planned)
    steps[0].run(None)

    assert [step.name for step in steps] == ["configure", "stop"]
    assert steps[1] is planned[1]
    assert rig.world.calls == []
    assert rig.world.scripts == []
    assert rig.launchctl.calls == []
    assert not rig.plist().exists()
    assert rig.lines[-1] == "podman: kept the configuration for the next Start"


def test_under_stopped_a_refused_container_still_fails_the_configure(rig):
    config = dict(CONFIG, containers=[dict(CONTAINERS[0], image="")])
    steps = rig.runner.configure_steps(config, "stopped", [plain_step("configure")])

    found = refusal(lambda: steps[0].run(None))

    assert (found.code, found.params) == ("image_invalid", {"name": "web", "image": ""})
    assert rig.world.calls == []


def test_a_machine_step_run_again_after_a_new_size_sizes_nothing_again(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.system.calls.clear()
    resized = dict(CONFIG, machine=dict(MACHINE, cpus=4))

    rig.runner.prepare_machine(resized)
    rig.runner.prepare_machine(resized)

    assert rig.system.calls == [("halt", "me"), ("resources", "me", 4, 4)]
    assert rig.record()[0]["names"] == ["web"]


def test_a_machine_step_with_no_account_fails_machine_account_missing(rig):
    config = {"containers": [], "mirrors": [], "machine": dict(MACHINE, account="")}
    steps = rig.runner.configure_steps(
        config, "running", [plain_step("configure"), plain_step("start")]
    )

    found = refusal(lambda: steps[0].run(None))

    assert (found.code, found.params) == ("machine_account_missing", {})
    assert rig.world.calls == []
    assert rig.launchctl.calls == []


def test_the_machine_step_waits_while_a_restart_is_owed(rig):
    rig.system.is_pending = True

    with pytest.raises(ModuleInstallPending):
        rig.runner.prepare_machine(CONFIG)

    assert rig.world.calls == []


# --- the read of a new machine ---


def test_a_new_machine_reads_the_defaults_and_nothing_of_an_account(rig):
    rig.system.facts = (8, 16)

    closed = rig.runner.command("machine_read", {"account": ""})

    assert (closed["exit_code"], closed["code"]) == (0, "")
    assert closed["result"] == {
        "cpus": 4,
        "memory_gib": 4,
        "disk_gib": 100,
        "disk_gib_now": 0,
    }


def test_a_new_machine_reads_the_disk_the_account_already_has(rig):
    rig.system.disk = 1024

    closed = rig.runner.command("machine_read", {"account": "ann"})

    assert closed["result"]["disk_gib"] == 1024
    assert closed["result"]["disk_gib_now"] == 1024


def test_a_new_machine_of_an_account_the_computer_lacks_is_refused(rig):
    closed = rig.runner.command("machine_read", {"account": "ghost"})

    assert (closed["exit_code"], closed["code"]) == (1, "account_unknown")
    assert closed["params"] == {"account": "ghost"}


def test_a_new_machine_of_an_account_with_no_profile_reads_no_disk(tmp_path):
    rig = Rig(tmp_path, os_name="windows", provider="wsl")
    rig.platform.with_no_home.add("ann")

    closed = rig.runner.command("machine_read", {"account": "ann"})

    assert (closed["exit_code"], closed["code"]) == (0, "")
    assert closed["result"]["disk_gib"] == 100
    assert closed["result"]["disk_gib_now"] == 0


# --- refusals ---


def test_an_account_with_no_profile_is_not_unknown(tmp_path):
    rig = Rig(tmp_path, os_name="windows", provider="wsl")
    rig.platform.with_no_home.add("ann")
    machine = dict(MACHINE, account="ann", password="pw", disk_gib=100)

    rig.runner.validate(dict(CONFIG, containers=[], machine=machine))


def test_an_account_the_computer_does_not_have_is_unknown(rig):
    config = dict(CONFIG, machine=dict(MACHINE, account="ghost"))

    found = refusal(lambda: rig.runner.validate(config))

    assert (found.code, found.params) == ("account_unknown", {"account": "ghost"})


def test_the_run_settings_are_checked_against_the_computer(rig):
    rig.system.facts = (4, 8)

    assert refusal(
        lambda: rig.runner.validate(dict(CONFIG, machine=dict(MACHINE, cpus=6)))
    ).params == {"cpus": 6, "max": 4}
    assert (
        refusal(
            lambda: rig.runner.validate(
                dict(CONFIG, machine=dict(MACHINE, memory_gib=9))
            )
        ).code
        == "machine_memory_invalid"
    )


def test_a_disk_smaller_than_the_machines_now_is_refused(rig):
    rig.system.disk = 120

    found = refusal(
        lambda: rig.runner.validate(dict(CONFIG, machine=dict(MACHINE, disk_gib=110)))
    )

    assert (found.code, found.params) == (
        "machine_disk_shrink",
        {"disk_gib": 110, "current_gib": 120},
    )


def test_a_folder_the_machine_cannot_reach_leaves_its_container_out(rig):
    rig.keep_image()
    far = dict(CONTAINERS[0], name="far", volumes=["/opt/www:/srv"])
    config = dict(CONFIG, containers=[*CONTAINERS, far])

    found = refusal(lambda: rig.runner.apply(config))

    assert (found.code, found.params) == (
        "volume_not_shared",
        {"name": "far", "volume": "/opt/www:/srv"},
    )
    expected = PodmanMachineScriptRenderer(
        config=PodmanConfig.from_dict(CONFIG), os_name="darwin"
    ).render()
    assert rig.world.scripts == [("me", "", expected)]
    assert rig.record()[0]["names"] == ["web"]
    assert rig.lines[-1] == "podman: left out far"


def test_validate_refuses_a_folder_the_machine_cannot_reach(rig):
    config = dict(CONFIG, containers=[dict(CONTAINERS[0], volumes=["/opt/www:/srv"])])

    assert refusal(lambda: rig.runner.validate(config)).code == "volume_not_shared"
    assert rig.world.calls == []


def test_with_no_account_a_left_out_container_is_still_refused(rig):
    config = {"containers": [dict(CONTAINERS[0], image="")], "mirrors": []}

    found = refusal(lambda: rig.runner.apply(config))

    assert (found.code, found.params) == ("image_invalid", {"name": "web", "image": ""})
    assert rig.world.calls == []


def test_containers_with_no_account_are_refused(rig):
    assert (
        refusal(lambda: rig.runner.validate({"containers": CONTAINERS})).code
        == "machine_account_missing"
    )


def test_windows_needs_the_accounts_login(tmp_path):
    rig = Rig(tmp_path, os_name="windows", provider="wsl")
    machine = dict(MACHINE, account="ann", disk_gib=100)
    config = dict(CONFIG, containers=[], machine=machine)

    found = refusal(lambda: rig.runner.validate(config))

    assert (found.code, found.params) == ("credential_missing", {"account": "ann"})
    rig.runner.validate(dict(config, machine=dict(machine, password="pw")))


def test_windows_refuses_a_disk_limit_of_0(tmp_path):
    rig = Rig(tmp_path, os_name="windows", provider="wsl")
    machine = dict(MACHINE, account="ann", password="pw")

    found = refusal(
        lambda: rig.runner.validate(dict(CONFIG, containers=[], machine=machine))
    )

    assert (found.code, found.params) == ("machine_disk_invalid", {"disk_gib": 0})


def test_windows_refuses_to_shrink_a_machine_taken_over(tmp_path):
    rig = Rig(tmp_path, os_name="windows", provider="wsl")
    rig.world.present.add("ann")
    rig.system.disk = 130
    machine = dict(MACHINE, account="ann", password="pw")

    found = refusal(
        lambda: rig.runner.validate(
            dict(CONFIG, containers=[], machine=dict(machine, disk_gib=100))
        )
    )

    assert (found.code, found.params) == (
        "machine_disk_shrink",
        {"disk_gib": 100, "current_gib": 130},
    )
    rig.runner.validate(
        dict(CONFIG, containers=[], machine=dict(machine, disk_gib=150))
    )


def test_a_wsl_machine_taken_over_below_the_limit_is_grown_and_kept(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.world.present.add("me")
    rig.world.rootful.add("me")
    rig.system.disk = 130

    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, disk_gib=150)))

    assert ("disk", "me", 150) in rig.system.calls
    assert not any(call[1] in ("init", "remove") for call in rig.world.calls)


def test_validate_answers_through_the_verb(rig):
    outcome = rig.runner.command(
        "validate", {"config": dict(CONFIG, machine=dict(MACHINE, account="ghost"))}
    )

    assert outcome["code"] == "account_unknown"


# --- a new machine ---


def test_a_new_machine_is_made_from_the_kept_image_and_runs_the_containers(rig):
    image = rig.keep_image()

    rig.runner.apply(CONFIG)

    assert rig.world.calls[0] == ("me", "init", image, 2, 4, 100)
    assert rig.system.calls == []
    assert rig.system.opened == [(image, "me")]
    assert rig.plist().is_file()
    assert rig.launchctl.verbs() == ["enable", "bootout", "bootstrap"]
    keeper = rig.tmp_path / "state" / "podman" / "keeper.sh"
    assert "podman machine start podman-machine-default" in keeper.read_text()
    expected = PodmanMachineScriptRenderer(
        config=PodmanConfig.from_dict(CONFIG), os_name="darwin"
    ).render()
    assert rig.world.scripts == [("me", "", expected)]
    assert rig.record() == [
        {
            "account": "me",
            "password": "",
            "cpus": 2,
            "memory_gib": 4,
            "disk_gib": 100,
            "names": ["web"],
            "hub_names": {},
            "images": None,
            "is_stopped": None,
        }
    ]
    assert rig.lines[-2:] == [
        "podman: made the machine of me",
        "podman: containers unchanged",
    ]


def test_every_machine_carries_the_systems_variables_for_its_account(rig):
    rig.keep_image()

    rig.runner.apply(CONFIG)

    assert rig.world.environments
    for made in rig.world.environments:
        assert made == ("me", {"TMPDIR": "/var/folders/me/T/"})


def test_a_wsl_machine_is_sized_after_the_init_and_before_its_first_start(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.keep_image("image.tar.zst")
    rig.system.facts = (8, 16)

    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, cpus=0, memory_gib=0)))

    assert rig.system.calls == [("resources", "me", 4, 4), ("disk", "me", 100)]
    assert rig.world.calls[0][1] == "init"
    assert ("me", "info") in rig.world.calls


@pytest.mark.parametrize(
    "host_memory_gib, memory_gib", [(32, 4), (6, 3), (3, 1), (1, 1), (0, 2)]
)
def test_a_memory_of_0_is_half_the_computers_at_most_4_gib(host_memory_gib, memory_gib):
    assert default_memory_gib(host_memory_gib) == memory_gib


def test_a_new_machine_on_a_small_computer_takes_half_its_memory(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.keep_image("image.tar.zst")
    rig.system.facts = (4, 6)

    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, cpus=0, memory_gib=0)))
    details = rig.runner.details({})

    assert rig.system.calls[0] == ("resources", "me", 2, 3)
    assert details["machine"]["default_memory_gib"] == 3


def test_a_made_machine_keeps_its_size_while_the_run_settings_stay(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.keep_image("image.tar.zst")
    config = dict(CONFIG, machine=dict(MACHINE, memory_gib=0))
    rig.system.facts = (8, 4)
    rig.runner.apply(config)
    rig.system.calls.clear()
    rig.system.facts = (8, 16)

    rig.runner.apply(config)

    assert not [call for call in rig.system.calls if call[0] == "resources"]


def test_a_failed_sizing_after_the_init_removes_the_new_machine(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    image = rig.keep_image("image.tar.zst")
    rig.system.disk_error = ModuleApplyError("machine_set_failed", {"detail": "busy"})

    found = refusal(lambda: rig.runner.apply(CONFIG))

    assert (found.code, found.params) == ("machine_set_failed", {"detail": "busy"})
    assert [call[1] for call in rig.world.calls[:2]] == ["init", "remove"]
    assert "me" not in rig.world.present
    assert rig.record() == []
    rig.system.disk_error = None
    rig.world.calls.clear()
    rig.system.calls.clear()

    rig.runner.apply(CONFIG)

    assert rig.world.calls[0] == ("me", "init", image, 2, 4, 100)
    assert rig.system.calls == [("resources", "me", 2, 4), ("disk", "me", 100)]


def test_a_new_machine_that_cannot_be_removed_keeps_the_sizings_code(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.keep_image("image.tar.zst")
    rig.system.disk_error = ModuleApplyError("machine_set_failed", {"detail": "busy"})
    rig.world.remove_error = ModuleApplyError("machine_set_failed", {"detail": "held"})

    found = refusal(lambda: rig.runner.apply(CONFIG))

    assert found.params == {"detail": "busy"}
    assert "the new machine of me was not removed" in rig.lines[-1]


def test_no_kept_image_is_machine_image_missing(rig):
    assert refusal(lambda: rig.runner.apply(CONFIG)).code == "machine_image_missing"


def test_the_root_scripts_changed_lines_are_logged(rig):
    rig.keep_image()
    rig.world.shell_answers = [(0, "changed: /etc/systemd/system/web.service\n")]

    rig.runner.apply(CONFIG)

    assert rig.lines[-1].endswith("containers: /etc/systemd/system/web.service")


def test_a_refused_script_fails_the_apply_with_systemds_words(rig):
    rig.keep_image()
    rig.world.shell_answers = [(1, "Job for web.service failed.\n")]

    found = refusal(lambda: rig.runner.apply(CONFIG))

    assert (found.code, found.params) == (
        "apply_failed",
        {"detail": "Job for web.service failed."},
    )


def test_a_container_the_script_names_failed_fails_alone(rig, _reads):
    """In the lab a declared container whose image did not exist failed the
    whole apply with systemd's words while the other container ran."""
    rig.keep_image()
    config = {
        **CONFIG,
        "containers": [*CONTAINERS, {"name": "ghost", "image": "acme/ghost:9"}],
    }
    rig.world.shell_answers = [
        (0, "changed: /etc/systemd/system/ghost.service\nfailed: ghost\n")
    ]

    rig.runner.apply(config)
    details = rig.runner.details({})

    by_name = {state["name"]: state for state in details["containers"]}
    assert by_name["ghost"]["code"] == "image_pull_failed"
    assert by_name["ghost"]["params"] == {
        "name": "ghost",
        "image": "docker.io/acme/ghost:9",
    }
    assert by_name["web"]["code"] == ""
    asked = [command for command in _reads if "exists" in command]
    assert asked[0][-3:] == ["image", "exists", "docker.io/acme/ghost:9"]
    assert asked[0][1] == "--url"
    assert any("ghost did not start" in line for line in rig.lines)


def test_the_script_names_each_refused_unit_and_exits_0():
    script = PodmanMachineScriptRenderer(
        config=PodmanConfig.from_dict(CONFIG), os_name="darwin"
    ).render()

    assert 'systemctl restart "$name.service" || echo "failed: $name"' in script
    assert 'systemctl start "$name.service" || echo "failed: $name"' in script
    assert "status=1" not in script


# --- waiting for the machine ---


def test_the_apply_waits_until_the_machine_answers(rig):
    rig.keep_image()
    rig.world.answers_after = 3

    rig.runner.apply(CONFIG)

    assert rig.now[0] == 6.0
    assert len(rig.world.scripts) == 1


def test_a_machine_that_never_answers_is_unreachable_and_nothing_is_written(rig):
    rig.keep_image()
    rig.world.answers_after = 10**6

    found = refusal(lambda: rig.runner.apply(CONFIG))

    assert (found.code, found.params) == ("machine_unreachable", {"detail": "starting"})
    assert rig.now[0] >= 180
    assert rig.world.scripts == []


# --- a machine taken over, and a change of size ---


def test_a_machine_taken_over_is_made_rootful_and_sized_with_the_keeper_stopped(rig):
    rig.world.present.add("me")
    rig.world.running.add("me")
    rig.system.disk = 300

    rig.runner.apply(CONFIG)

    assert rig.world.calls[:3] == [
        ("me", "inspect"),
        ("me", "stop", ""),
        ("me", "set_rootful"),
    ]
    assert rig.system.calls == [("halt", "me"), ("resources", "me", 2, 4)]
    assert rig.launchctl.verbs() == [
        "disable",
        "bootout",
        "enable",
        "bootout",
        "bootstrap",
    ]
    assert rig.record()[0]["disk_gib"] == 300


def test_a_wsl_machine_on_user_mode_networking_is_set_back_to_nat_and_ended(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.world.present.add("me")
    rig.world.rootful.add("me")
    rig.world.running.add("me")
    rig.world.user_mode.add("me")
    rig.system.disk = 100

    rig.runner.apply(CONFIG)

    assert rig.world.calls[:3] == [
        ("me", "inspect"),
        ("me", "stop", ""),
        ("me", "set_nat_networking"),
    ]
    assert rig.system.calls[0] == ("terminate", "me")
    assert rig.launchctl.verbs()[:2] == ["disable", "bootout"]
    assert "set the machine back to WSL's NAT networking" in rig.lines[-2]
    assert rig.world.user_mode == set()


def test_an_unchanged_apply_sizes_nothing_and_leaves_the_keeper_running(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.system.calls.clear()
    rig.launchctl.calls.clear()
    rig.world.calls.clear()

    rig.runner.apply(CONFIG)

    assert rig.world.calls[0] == ("me", "inspect")
    assert rig.system.calls == []
    assert rig.launchctl.verbs() == ["enable"]
    assert len(rig.world.scripts) == 2


def test_a_new_size_halts_the_machine_and_grows_the_disk_alone(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.system.calls.clear()

    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, cpus=4, disk_gib=150)))

    assert rig.system.calls == [
        ("halt", "me"),
        ("resources", "me", 4, 4),
        ("disk", "me", 150),
    ]
    assert rig.record()[0]["disk_gib"] == 150
    rig.system.calls.clear()

    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, cpus=4, disk_gib=0)))

    assert rig.system.calls == []


def test_a_growth_cut_half_way_finishes_at_the_next_apply(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.keep_image()
    machine = dict(MACHINE, disk_gib=100)
    rig.system.disk = rig.system.file_system = 100
    rig.world.present.add("me")
    rig.world.rootful.add("me")
    rig.runner.apply(dict(CONFIG, machine=machine))
    grown = dict(CONFIG, machine=dict(machine, disk_gib=120))
    rig.system.disk_error = ModuleApplyError("machine_set_failed", {"detail": "e2fsck"})

    found = refusal(lambda: rig.runner.apply(grown))

    assert found.code == "machine_set_failed"
    assert (rig.system.disk, rig.system.file_system) == (120, 100)
    rig.system.disk_error = None
    rig.system.calls.clear()

    rig.runner.apply(grown)

    assert rig.system.calls == [
        ("halt", "me"),
        ("resources", "me", 2, 4),
        ("disk", "me", 120),
    ]
    assert rig.system.file_system == 120
    assert rig.record()[0]["disk_gib"] == 120
    rig.system.calls.clear()

    rig.runner.apply(grown)

    assert rig.system.calls == []


def test_a_cut_growth_and_a_larger_limit_resize_once_to_the_limit(tmp_path):
    rig = Rig(tmp_path, provider="wsl")
    rig.keep_image()
    rig.system.disk = 120
    rig.system.file_system = 100
    rig.world.present.add("me")
    rig.world.rootful.add("me")

    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, disk_gib=150)))

    assert [call for call in rig.system.calls if call[0] == "disk"] == [
        ("disk", "me", 150)
    ]


@pytest.mark.parametrize("file_system", [0, 120])
def test_a_file_system_unread_or_as_big_as_the_disk_resizes_nothing(
    tmp_path, file_system
):
    rig = Rig(tmp_path, provider="wsl")
    rig.keep_image()
    rig.system.disk = 120
    rig.system.file_system = file_system
    rig.world.present.add("me")
    rig.world.rootful.add("me")
    config = dict(CONFIG, machine=dict(MACHINE, disk_gib=120))
    rig.runner.apply(config)
    rig.system.calls.clear()

    rig.runner.apply(config)

    assert rig.system.calls == []


# --- a new account ---


def test_a_new_account_stops_the_old_machine_and_removes_its_keeper(rig):
    rig.keep_image()
    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, password="old")))
    old_log = rig.tmp_path / "Logs" / "podman_me.log"
    assert old_log.exists()

    rig.runner.apply(dict(CONFIG, machine=dict(MACHINE, account="ann")))

    assert ("me", "stop", "old") in rig.world.calls
    assert not rig.plist("me").exists()
    assert not old_log.exists()
    assert rig.plist("ann").is_file()
    assert [record["account"] for record in rig.record()] == ["ann"]
    assert "me" in rig.world.present
    stop_at = rig.world.calls.index(("me", "stop", "old"))
    init_at = next(
        i for i, call in enumerate(rig.world.calls) if call[:2] == ("ann", "init")
    )
    assert stop_at < init_at


def test_no_account_and_no_containers_runs_no_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)

    rig.runner.apply({"containers": [], "machine": {"account": ""}})

    assert rig.record() == []
    assert not rig.plist().exists()
    assert ("me", "stop", "") in rig.world.calls


# --- reads ---


def test_details_read_the_machine_through_the_ssh_url(tmp_path, _reads):
    rig = Rig(tmp_path, os_name="windows", provider="wsl")
    os.makedirs(rig.service_machine.record_dir)
    with open(os.path.join(rig.service_machine.record_dir, "ann.json"), "w") as stream:
        json.dump(
            {
                "account": "ann",
                "password": "pw",
                "cpus": 2,
                "memory_gib": 4,
                "disk_gib": 120,
                "names": ["web"],
            },
            stream,
        )
    rig.world.running.add("ann")

    details = rig.runner.details({})

    by_name = {container["name"]: container for container in details["containers"]}
    assert by_name["web"]["source"] == "declared"
    assert by_name["web"]["has_unit"] is True
    assert by_name["web"]["volumes"] == ["C:\\www:/usr/share/nginx/html"]
    assert by_name["web"]["host_bindings"] == [
        {"address": "", "port": 8080, "protocol": "tcp", "detected": "http"}
    ]
    assert FakeProbe.asked[0][0][1:] == ("127.0.0.1", 8080)
    assert by_name["adhoc"]["source"] == "manual"
    assert by_name["adhoc"]["has_unit"] is False
    assert details["machine"] == {
        "account": "ann",
        "is_running": True,
        "cpus": 2,
        "memory_gib": 4,
        "disk_gib": 120,
        "default_memory_gib": 4,
    }
    assert details["is_active"] is True
    assert details["version"] == "6.1.4"
    reads = [command for command in _reads if "ps" in command]
    assert reads[0][:3] == [
        rig.system.binary,
        "--url",
        "ssh://root@127.0.0.1:50743/ann",
    ]


def test_one_reading_serves_the_rows_activity_and_its_details(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.now[0] += 60
    rig.world.calls.clear()

    is_active = rig.runner.is_active()
    details = rig.runner.details({})

    assert is_active is True
    assert details["machine"]["is_running"] is True
    assert rig.world.calls.count(("me", "info")) == 1


def test_a_machine_that_does_not_answer_is_not_active(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.now[0] += 60
    rig.world.is_answering = False

    details = rig.runner.details({})

    assert not rig.runner.is_active()
    assert details["is_active"] is False
    assert details["containers"] == []
    assert details["machine"]["account"] == "me"
    assert details["machine"]["is_running"] is False
    assert details["machine"]["disk_gib"] == 100


def test_a_containers_shell_takes_the_read_command_of_the_applied_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.calls.clear()

    command = rig.runner.read_command()

    assert command == (
        rig.system.binary,
        "--url",
        "ssh://root@127.0.0.1:50743/me",
        "--identity",
        "key",
    )
    assert rig.world.calls == []


def test_before_any_apply_a_containers_shell_has_no_command(rig):
    assert rig.runner.read_command() == ()


def test_a_machine_with_no_port_or_no_account_refuses_the_shells_command(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.is_answering = False

    unreachable = refusal(rig.runner.read_command)
    rig.world.is_account_gone = True
    gone = refusal(rig.runner.read_command)

    assert unreachable.code == "machine_unreachable"
    assert (gone.code, gone.params) == ("account_unknown", {"account": "me"})


def test_before_any_apply_nothing_runs_as_an_account(rig):
    assert not rig.runner.is_active()
    assert rig.runner.details({})["machine"] == {
        "account": "",
        "is_running": False,
        "cpus": 0,
        "memory_gib": 0,
        "disk_gib": 0,
        "default_memory_gib": 4,
    }
    assert rig.world.calls == []


# --- the journal ---


def test_the_journal_is_the_keepers_log_then_the_agents_lines(rig, tmp_path):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    (tmp_path / "Logs" / "podman_me.log").write_text('the machine is "stopped"\n')
    (tmp_path / "agent.log").write_text("podman: made the machine of me\nother\n")

    outcome = rig.runner.command("journal", {"lines": 10})

    assert outcome["output"].splitlines() == [
        'the machine is "stopped"',
        "podman: made the machine of me",
    ]


# --- verbs ---


def test_a_declared_container_is_driven_through_systemd_in_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)

    outcome = rig.runner.command("control", {"name": "web", "action": "restart"})

    assert outcome["exit_code"] == 0
    assert rig.world.scripts[-1][2] == machine_control_script("web", "restart")


def test_a_hand_started_container_is_driven_through_the_read(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)

    outcome = rig.runner.command("control", {"name": "adhoc", "action": "start"})

    assert outcome["exit_code"] == 0
    assert ("me", "control", "adhoc", "start") in rig.world.calls


def test_a_container_nobody_knows_and_an_unknown_action_are_refused(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)

    assert rig.runner.command("control", {"name": "ghost", "action": "start"})[
        "code"
    ] == ("container_unknown")
    assert rig.runner.command("control", {"name": "web", "action": "kill"})["code"] == (
        "verb_unknown"
    )
    assert rig.runner.command("control", {"name": "Bad Name", "action": "start"})[
        "code"
    ] == ("container_name_invalid")


def test_a_declared_container_s_refused_start_closes_with_its_code(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.shell_answers = [(1, "Job for web.service failed.\n")]

    outcome = rig.runner.command("control", {"name": "web", "action": "start"})

    assert outcome["code"] == "image_pull_failed"
    assert outcome["params"] == {"name": "web", "image": "docker.io/library/nginx"}


def test_a_hub_container_s_refused_start_names_the_first_one_down(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner._config = PodmanConfig.from_dict(HUB_CONFIG)
    rig.world.shell_answers = [(1, "Job for neutrino_late.service failed.\n")]

    found = refusal(
        lambda: rig.runner.drive_hub_containers(
            ["neutrino_demo", "neutrino_late"], "start"
        )
    )

    assert found.code == "image_pull_failed"
    assert found.params["name"] == "neutrino_demo"


def test_a_containers_journal_is_read_in_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.shell_answers = [(0, "line one\nline two\n")]
    seen = []

    outcome = rig.runner.command("journal", {"name": "web"}, seen.append)

    assert outcome["output"] == "line one\nline two"
    assert seen == ["line one", "line two"]
    assert rig.world.scripts[-1][2] == machine_journal_script("web", 200)


def test_a_containers_line_written_in_pieces_reads_as_one_line(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    pieces = [
        {"MESSAGE": "+", "CONTAINER_PARTIAL_MESSAGE": "true"},
        {"MESSAGE": " cffi", "CONTAINER_PARTIAL_MESSAGE": "true"},
        {"MESSAGE": "\n"},
    ]
    rig.world.shell_answers = [
        (
            0,
            "".join(
                json.dumps(
                    {"MESSAGE": "", "SYSLOG_IDENTIFIER": "conmon", "_PID": "9", **one}
                )
                + "\n"
                for one in pieces
            ),
        )
    ]

    outcome = rig.runner.command("journal", {"name": "web"})

    assert outcome["output"] == "conmon[9]: + cffi"


def test_a_verb_before_any_apply_knows_no_container(rig):
    assert rig.runner.command("control", {"name": "web", "action": "stop"})["code"] == (
        "container_unknown"
    )


# --- stop, removal, uninstall ---


def test_stop_stops_the_containers_then_the_keeper_then_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    assert rig.runner.is_active()
    rig.world.calls.clear()
    rig.launchctl.calls.clear()

    rig.runner.stop()
    rig.world.is_answering = False

    assert rig.world.scripts[-1][2] == machine_stop_script()
    assert rig.launchctl.verbs() == ["disable", "bootout"]
    assert "com.neutrino.podman.me" not in rig.launchctl.loaded
    assert rig.world.calls == [("me", "stop", "")]
    assert "me" not in rig.world.running
    assert rig.plist().is_file()
    assert not rig.runner.is_active()


def test_start_after_a_stop_brings_the_keeper_and_the_machine_back(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.stop()
    rig.launchctl.calls.clear()

    rig.runner.apply(CONFIG)
    rig.runner.start()

    assert rig.launchctl.verbs() == ["enable", "bootout", "bootstrap"]
    assert "com.neutrino.podman.me" in rig.launchctl.loaded
    assert "me" in rig.world.running
    assert rig.runner.is_active()


def unanswered_machine(rig):
    """A machine step whose machine never answered: the keeper runs, and no record is kept."""
    rig.keep_image()
    rig.world.answers_after = 10**6
    rig.runner.take_config(CONFIG)
    steps = rig.runner.configure_steps(CONFIG, "running", [plain_step("configure")])
    assert refusal(lambda: steps[0].run(None)).code == "machine_unreachable"
    assert rig.record() == []
    assert "com.neutrino.podman.me" in rig.launchctl.loaded
    (rig.tmp_path / "Logs" / "podman_me.log").write_text("vfkit exited\n")
    rig.world.calls.clear()
    rig.launchctl.calls.clear()


def test_stop_with_no_record_stops_and_disables_the_configured_keeper(rig):
    unanswered_machine(rig)

    rig.runner.stop()

    assert rig.launchctl.verbs() == ["disable", "bootout"]
    assert "com.neutrino.podman.me" not in rig.launchctl.loaded
    assert rig.world.calls == [("me", "stop", "")]
    assert rig.world.scripts == []
    assert rig.plist().is_file()
    assert rig.lines[-1] == "podman: stopped the keeper of me"


def test_the_journal_with_no_record_reads_the_configured_keeper_s_log(rig):
    unanswered_machine(rig)

    outcome = rig.runner.command("journal", {"lines": 10})

    assert outcome["output"].splitlines() == ["vfkit exited"]


def test_the_journal_with_no_record_and_no_account_reads_the_agent_s_lines(
    rig, tmp_path
):
    (tmp_path / "agent.log").write_text("podman: no account is named\n")

    outcome = rig.runner.command("journal", {"lines": 10})

    assert outcome["output"].splitlines() == ["podman: no account is named"]


def test_uninstall_with_no_record_removes_the_keeper_its_plist_and_its_log(rig):
    rig.install_podman()
    unanswered_machine(rig)

    rig.runner.uninstall({})

    assert "com.neutrino.podman.me" not in rig.launchctl.loaded
    assert not rig.plist().exists()
    assert not (rig.tmp_path / "Logs" / "podman_me.log").exists()
    assert not (rig.tmp_path / "state" / "podman").exists()
    assert ("me", "stop", "") in rig.world.calls
    assert rig.world.scripts == []
    assert rig.system.calls == [("uninstall",)]


def test_an_uninstall_before_the_machine_exists_stops_nothing_and_says_nothing_of_it(
    rig,
):
    rig.install_podman()
    rig.runner.take_config(CONFIG)

    rig.runner.uninstall({})

    assert ("me", "stop", "") not in rig.world.calls
    assert not any("the machine of me" in line for line in rig.lines)
    assert rig.system.calls == [("uninstall",)]


def test_a_machine_that_does_not_stop_is_logged_as_not_stopped_alone(rig):
    unanswered_machine(rig)
    rig.world.stop_error = ModuleApplyError("machine_set_failed", {"detail": "busy"})

    rig.runner.uninstall({})

    assert "podman: the machine of me was not stopped: machine_set_failed" in rig.lines
    assert "podman: stopped the machine of me" not in rig.lines


def test_a_machine_that_stops_is_logged_as_stopped_alone(rig):
    unanswered_machine(rig)

    rig.runner.uninstall({})

    assert rig.lines.count("podman: stopped the machine of me") == 1
    assert not any("was not stopped" in line for line in rig.lines)


def test_stop_and_uninstall_with_no_record_and_no_account_touch_no_keeper(rig):
    rig.install_podman()
    rig.runner.take_config({"containers": [], "machine": {"account": ""}})

    rig.runner.stop()
    rig.runner.uninstall({})

    assert rig.launchctl.calls == []
    assert rig.world.calls == []
    assert rig.system.calls == [("uninstall",)]


def test_removal_empties_the_machine_removes_the_keeper_and_stops_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)

    rig.runner.remove_configuration()

    assert (
        rig.world.scripts[-1][2]
        == PodmanMachineScriptRenderer(config=PodmanConfig(), os_name="darwin").render()
    )
    assert not rig.plist().exists()
    assert ("me", "stop", "") in rig.world.calls
    assert "me" in rig.world.present
    assert rig.record() == []


def test_removal_of_a_stopped_module_wakes_the_machine_for_its_script(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.stop()
    rig.world.is_answering = False
    rig.launchctl.on_bootstrap = functools.partial(
        setattr, rig.world, "is_answering", True
    )
    rig.launchctl.calls.clear()

    rig.runner.remove_configuration()

    assert rig.launchctl.verbs()[:3] == ["enable", "bootout", "bootstrap"]
    assert (
        rig.world.scripts[-1][2]
        == PodmanMachineScriptRenderer(config=PodmanConfig(), os_name="darwin").render()
    )
    assert rig.world.answering_at_shell[-1] is True
    assert not rig.plist().exists()
    assert rig.world.calls[-1] == ("me", "stop", "")
    assert rig.record() == []


def test_a_stopped_machine_is_held_awake_for_a_container_module_s_uninstall(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.stop()
    rig.world.is_answering = False
    rig.launchctl.on_bootstrap = functools.partial(
        setattr, rig.world, "is_answering", True
    )
    rig.launchctl.calls.clear()
    rig.world.calls.clear()
    seen = []

    with rig.runner.engine_awake():
        seen.append(rig.world.is_answering)
        seen.append(rig.launchctl.verbs())

    assert seen == [True, ["enable", "bootout", "bootstrap"]]
    assert rig.launchctl.verbs() == [
        "enable",
        "bootout",
        "bootstrap",
        "disable",
        "bootout",
    ]
    assert rig.world.calls[-1] == ("me", "stop", "")
    assert rig.plist().is_file()


def _stopped_by_stop(rig):
    """Apply, press Stop, and leave the machine silent; the scripts run so far."""
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.stop()
    rig.world.is_answering = False
    rig.advance(PODMAN_MACHINE_INFO_TTL_S + 1)
    rig.launchctl.on_bootstrap = functools.partial(
        setattr, rig.world, "is_answering", True
    )
    rig.launchctl.calls.clear()
    rig.world.calls.clear()
    rig.system.calls.clear()
    return len(rig.world.scripts)


CHANGED_RUN = {**CONFIG, "machine": {**MACHINE, "cpus": 3}}


def test_an_apply_during_stop_keeps_the_configuration_and_wakes_nothing(rig):
    scripts = _stopped_by_stop(rig)

    rig.runner.apply(CHANGED_RUN)
    rig.runner.stop()

    assert rig.launchctl.verbs() == ["disable", "bootout"]
    assert len(rig.world.scripts) == scripts
    assert rig.world.calls == []
    assert rig.system.calls == []
    assert rig.record()[0]["cpus"] == 2
    assert rig.world.is_answering is False


def test_start_after_an_apply_during_stop_wakes_the_machine_once_and_writes_it(rig):
    scripts = _stopped_by_stop(rig)
    rig.runner.apply(CHANGED_RUN)
    rig.runner.stop()

    rig.runner.apply(CHANGED_RUN)
    rig.runner.start()

    assert rig.launchctl.verbs().count("bootstrap") == 1
    assert ("me", "stop", "") not in rig.world.calls
    assert len(rig.world.scripts) == scripts + 1
    assert rig.world.answering_at_shell[-1] is True
    assert rig.record()[0]["cpus"] == 3
    assert rig.record()[0]["is_stopped"] is None
    assert rig.runner.is_active()


def test_an_uninstall_during_stop_wakes_the_machine_once(rig):
    _stopped_by_stop(rig)

    rig.runner.apply(CONFIG)
    rig.runner.stop()
    with rig.runner.engine_awake():
        pass

    assert rig.launchctl.verbs() == [
        "disable",
        "bootout",
        "enable",
        "bootout",
        "bootstrap",
        "disable",
        "bootout",
    ]
    assert rig.world.calls.count(("me", "stop", "")) == 1
    assert rig.record()[0]["is_stopped"] is True


def test_a_failed_start_after_a_stop_clears_the_mark_and_a_stop_stops_the_keeper(rig):
    _stopped_by_stop(rig)
    rig.launchctl.on_bootstrap = None
    rig.world.answers_after = 10**6

    steps = rig.runner.configure_steps(CONFIG, "running", [plain_step("configure")])
    assert refusal(lambda: steps[0].run(None)).code == "machine_unreachable"
    assert "com.neutrino.podman.me" in rig.launchctl.loaded
    assert not rig.record()[0]["is_stopped"]
    rig.launchctl.calls.clear()

    rig.runner.stop()

    assert "com.neutrino.podman.me" not in rig.launchctl.loaded
    assert rig.launchctl.verbs() == ["disable", "bootout"]
    assert rig.world.calls[-1] == ("me", "stop", "")
    assert rig.record()[0]["is_stopped"] is True


def test_a_stop_of_a_stopped_machine_stops_a_keeper_left_on(rig):
    _stopped_by_stop(rig)
    rig.launchctl.on_bootstrap = None
    rig.launchctl.loaded.add("com.neutrino.podman.me")
    scripts = len(rig.world.scripts)

    rig.runner.stop()

    assert "com.neutrino.podman.me" not in rig.launchctl.loaded
    assert rig.launchctl.verbs() == ["disable", "bootout"]
    assert len(rig.world.scripts) == scripts
    assert rig.world.calls == []


def test_stop_stops_a_machine_its_keeper_started_again_after_a_stop(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.stop()
    rig.advance(PODMAN_MACHINE_INFO_TTL_S + 1)
    rig.world.calls.clear()

    rig.runner.apply(CONFIG)
    rig.runner.stop()

    assert rig.world.scripts[-1][2] == machine_stop_script()
    assert rig.world.calls[-1] == ("me", "stop", "")


def test_a_running_machine_is_left_as_it_is_around_an_uninstall(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.launchctl.calls.clear()
    rig.world.calls.clear()

    with rig.runner.engine_awake():
        pass

    assert rig.launchctl.verbs() == []
    assert ("me", "stop", "") not in rig.world.calls


def test_stop_saves_the_store_s_images_for_a_container_module_s_presence_check(
    rig, monkeypatch
):
    store = {WEB_REFERENCE, AGENT_REFERENCE}
    monkeypatch.setattr(
        machine_runner_module, "read_image_references", lambda *, podman: set(store)
    )
    rig.keep_image()
    rig.runner.apply(CONFIG)
    module = ContainerModuleRunner(
        platform=rig.platform, name="demo", containers=rig.runner, log=rig.lines.append
    )

    rig.runner.stop()
    rig.world.is_answering = False
    store.clear()

    assert rig.record()[0]["images"] == [AGENT_REFERENCE, WEB_REFERENCE]
    assert rig.runner.image_references() == {WEB_REFERENCE, AGENT_REFERENCE}
    assert module.verify(IMAGE_RECIPE) is True
    assert module.is_active() is False

    rig.world.is_answering = True
    rig.advance(PODMAN_MACHINE_INFO_TTL_S + 1)
    store.add(WEB_REFERENCE)
    assert rig.runner.image_references() == {WEB_REFERENCE}
    assert module.verify(IMAGE_RECIPE) is False


def test_the_halt_after_a_container_module_s_uninstall_saves_the_store_without_its_images(
    rig, monkeypatch
):
    store = {WEB_REFERENCE, AGENT_REFERENCE}
    monkeypatch.setattr(
        machine_runner_module, "read_image_references", lambda *, podman: set(store)
    )
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.stop()
    rig.world.is_answering = False
    rig.launchctl.on_bootstrap = functools.partial(
        setattr, rig.world, "is_answering", True
    )
    module = ContainerModuleRunner(
        platform=rig.platform, name="demo", containers=rig.runner, log=rig.lines.append
    )
    is_present_before = module.verify(IMAGE_RECIPE)

    with rig.runner.engine_awake():
        store.clear()
    rig.world.is_answering = False

    assert is_present_before is True
    assert rig.record()[0]["images"] == []
    assert module.verify(IMAGE_RECIPE) is False
    assert rig.world.calls[-1] == ("me", "stop", "")


def test_a_running_machine_s_missed_read_reads_the_images_of_the_last_read(
    rig, monkeypatch
):
    store = {WEB_REFERENCE}
    monkeypatch.setattr(
        machine_runner_module, "read_image_references", lambda *, podman: set(store)
    )
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.stop()
    rig.runner.apply(CONFIG)
    rig.advance(PODMAN_MACHINE_INFO_TTL_S + 1)
    store.add(AGENT_REFERENCE)
    module = ContainerModuleRunner(
        platform=rig.platform, name="demo", containers=rig.runner, log=rig.lines.append
    )
    is_present_while_answering = module.verify(IMAGE_RECIPE)

    rig.world.is_answering = False
    rig.advance(PODMAN_MACHINE_INFO_TTL_S + 1)

    assert is_present_while_answering is True
    assert rig.record()[0]["images"] == [AGENT_REFERENCE, WEB_REFERENCE]
    assert rig.runner.image_references() == {WEB_REFERENCE, AGENT_REFERENCE}
    assert module.verify(IMAGE_RECIPE) is True


def test_an_image_list_that_does_not_answer_reads_the_saved_list_and_keeps_it(
    rig, monkeypatch
):
    answers = [{WEB_REFERENCE, AGENT_REFERENCE}, None]
    monkeypatch.setattr(
        machine_runner_module,
        "read_image_references",
        lambda *, podman: answers.pop(0),
    )
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.image_references()

    seen = rig.runner.image_references()

    assert seen == {WEB_REFERENCE, AGENT_REFERENCE}
    assert rig.record()[0]["images"] == [AGENT_REFERENCE, WEB_REFERENCE]


def test_an_apply_keeps_the_saved_images(rig, monkeypatch):
    monkeypatch.setattr(
        machine_runner_module,
        "read_image_references",
        lambda *, podman: {WEB_REFERENCE},
    )
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner.image_references()

    rig.runner.apply(CONFIG)

    assert rig.record()[0]["images"] == [WEB_REFERENCE]


def test_a_machine_not_stopped_by_the_agent_has_no_saved_images(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.is_answering = False
    rig.advance(PODMAN_MACHINE_INFO_TTL_S + 1)

    assert rig.record()[0]["images"] is None
    assert rig.runner.image_references() == set()


def test_a_machine_that_cannot_take_the_script_still_loses_its_keeper(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.shell_answers = [(255, "ssh: connect refused\n")]

    rig.runner.remove_configuration()

    assert not rig.plist().exists()
    assert any("script failed" in line for line in rig.lines)


def test_uninstall_removes_podman_and_the_kept_files_and_keeps_the_machine(rig):
    rig.install_podman()
    rig.keep_image()
    rig.runner.apply(CONFIG)

    rig.runner.uninstall({})

    assert rig.system.calls[-1] == ("uninstall",)
    assert not (rig.tmp_path / "state" / "podman").exists()
    assert not rig.plist().exists()
    assert rig.record() == []
    assert "me" in rig.world.present


def test_an_uninstall_of_a_persons_podman_removes_the_module_s_own_and_keeps_podman(
    rig,
):
    rig.keep_image()
    rig.runner.apply(CONFIG)

    rig.runner.uninstall({})

    assert ("uninstall",) not in rig.system.calls
    assert "podman: removed no package" in rig.lines
    assert rig.runner.verify({})
    assert not (rig.tmp_path / "state" / "podman").exists()
    assert not rig.plist().exists()
    assert rig.record() == []
    assert "me" in rig.world.present
    assert ("me", "stop", "") in rig.world.calls


def test_another_version_uninstalls_the_podman_package_first_and_keeps_wsl(rig):
    rig.install_podman()
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.system.calls.clear()

    rig.runner.uninstall_package({}, {"name": "wsl", "kind": "msi"})
    rig.runner.uninstall_package({}, {"name": "podman", "kind": "msi"})

    assert rig.system.calls == [("uninstall",)]
    assert "me" in rig.world.present
    assert rig.plist().exists()


def test_another_version_leaves_a_persons_podman_as_it_is(rig, tmp_path):
    rig.runner.uninstall_package({}, dict(PODMAN_PKG))
    rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))

    assert rig.system.calls == []
    assert "podman: the computer's own Podman stays for another version" in rig.lines
    assert not rig.package_mark().exists()


class PkgComputer:
    """A Mac in the test's folder: what Podman's pkg and its scripts put on
    it, its receipt, and the installer that puts them there."""

    def __init__(self, tmp_path):
        opt = tmp_path / "opt" / "podman"
        self.program = opt / "bin" / "podman"
        self.paths = (
            opt,
            tmp_path / "etc" / "paths.d" / "podman-pkg",
            tmp_path / "usr" / "local" / "etc" / "man.d" / "podman.man.conf",
        )
        self.receipts: set = set()
        self.installed: list = []
        self.rig = Rig(tmp_path)
        system = PodmanDarwinApplier(
            platform=self.rig.platform,
            run=self.pkgutil,
            install_pkg=self.install_pkg,
            installed_paths=tuple(str(path) for path in self.paths),
        )
        system.binary = str(self.program)
        self.rig.system = system
        self.rig.runner = self.rig.make_runner()

    def lay_down(self):
        """Podman as the pkg leaves it: the program, the two files and the receipt."""
        self.program.parent.mkdir(parents=True, exist_ok=True)
        self.program.write_text("podman")
        for path in self.paths[1:]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("/opt/podman/bin\n")
        self.receipts.add("com.redhat.podman")

    def install_pkg(self, path):
        self.installed.append(os.path.basename(path))
        self.lay_down()

    def pkgutil(self, command, *, is_checked=True, timeout_s=0, **_):
        if command[:2] == ["pkgutil", "--forget"]:
            self.receipts.discard(command[2])
        return CommandResult(list(command), 0, "", "")

    def state(self):
        """Which of the pkg's paths are there, and the receipts."""
        return [os.path.lexists(path) for path in self.paths], sorted(self.receipts)


def test_a_mac_s_own_podman_gets_no_installer_and_no_mark(tmp_path):
    mac = PkgComputer(tmp_path)
    mac.lay_down()
    before = mac.state()

    mac.rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))

    assert mac.installed == []
    assert not mac.rig.package_mark().exists()
    assert mac.state() == before
    assert mac.rig.runner.is_software_kept()


def test_an_uninstall_with_no_mark_leaves_every_pkg_path_and_the_receipt(tmp_path):
    mac = PkgComputer(tmp_path)
    mac.lay_down()
    mac.rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))

    mac.rig.runner.uninstall({})

    assert mac.state() == ([True, True, True], ["com.redhat.podman"])
    assert mac.rig.runner.verify({})
    assert not (tmp_path / "state" / "podman").exists()


def test_an_uninstall_with_the_mark_removes_every_pkg_path_and_the_receipt(tmp_path):
    mac = PkgComputer(tmp_path)
    mac.rig.runner.install_artifact({}, dict(PODMAN_PKG), download(tmp_path))
    assert mac.installed == ["podman.pkg"]
    assert mac.rig.package_mark().is_file()
    assert not mac.rig.runner.is_software_kept()

    mac.rig.runner.uninstall({})

    assert mac.state() == ([False, False, False], [])
    assert not (tmp_path / "state" / "podman").exists()
    assert not mac.rig.runner.verify({})


class WindowsStateRoot(Platform):
    """The rig's Windows computer, its state root a folder of the test."""

    def agent_var_dir(self):
        return os.path.join(self._root, "state")


class MsiComputer:
    """A Windows computer in the test's folder: Podman's program, the
    products Windows Installer lists, and msiexec."""

    def __init__(self, tmp_path):
        self.program = tmp_path / "Program Files" / "Podman" / "podman.exe"
        self.products: list = []
        self.installed: list = []
        self.uninstalled: list = []
        self.rig = Rig(tmp_path, os_name="windows", provider="wsl")
        system = PodmanWindowsApplier(
            platform=WindowsStateRoot(str(tmp_path), "windows"),
            log=self.rig.lines.append,
            install_msi=self.install_msi,
            uninstall_msi=self.uninstall_msi,
            read_products=self.read_products,
            has_restart_key=self.has_restart_key,
            join=os.path.join,
        )
        system.binary = str(self.program)
        self.rig.system = system
        self.rig.runner = self.rig.make_runner()

    def put_podman_on(self):
        """Podman as its msi leaves it: the program and the product."""
        self.program.parent.mkdir(parents=True, exist_ok=True)
        self.program.write_text("podman")
        self.products.append(
            {"code": PODMAN_CODE, "name": "Podman CLI", "version": "6.1.4"}
        )

    def read_products(self):
        return [dict(product) for product in self.products]

    def has_restart_key(self):
        return False

    def install_msi(self, path, *, log_path, properties=()):
        name = ntpath.basename(path)
        self.installed.append(name)
        if name == "wsl.msi":
            self.products.append(
                {
                    "code": WSL_CODE,
                    "name": "Windows Subsystem for Linux",
                    "version": "3.0.3",
                }
            )
        else:
            self.put_podman_on()
        return False

    def uninstall_msi(self, product_code, *, log_path):
        self.uninstalled.append(product_code)
        return False


def test_on_windows_a_persons_podman_gets_no_msi_and_stays_at_the_uninstall(tmp_path):
    win = MsiComputer(tmp_path)
    win.put_podman_on()

    win.rig.runner.install_artifact({}, dict(WSL_MSI), download(tmp_path, "wsl"))
    win.rig.runner.install_artifact({}, dict(PODMAN_MSI), download(tmp_path))
    assert win.rig.runner.is_software_kept()
    win.rig.runner.uninstall({})

    assert win.installed == ["wsl.msi"]
    assert win.uninstalled == []
    assert win.program.is_file()


def test_on_windows_the_modules_podman_msi_is_uninstalled_and_wsl_stays(tmp_path):
    win = MsiComputer(tmp_path)

    win.rig.runner.install_artifact({}, dict(WSL_MSI), download(tmp_path, "wsl"))
    win.rig.runner.install_artifact({}, dict(PODMAN_MSI), download(tmp_path))
    assert not win.rig.runner.is_software_kept()
    win.rig.runner.uninstall({})

    assert win.installed == ["wsl.msi", "podman.msi"]
    assert win.uninstalled == [PODMAN_CODE]


# --- a restarted agent ---


def test_a_restarted_agent_reads_on_from_the_record(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.calls.clear()

    restarted = rig.make_runner()
    details = restarted.details({})
    outcome = restarted.command("control", {"name": "web", "action": "stop"})

    assert details["machine"]["account"] == "me"
    by_name = {container["name"]: container for container in details["containers"]}
    assert by_name["web"]["source"] == "declared"
    assert outcome["exit_code"] == 0
    assert rig.world.scripts[-1][2] == machine_control_script("web", "stop")


# --- hub containers in the machine ---

HUB_DIGEST = "sha256:" + "9" * 64

HUB_CONFIG = {
    **CONFIG,
    "hub_containers": [
        {
            "module": "demo",
            "name": "neutrino_demo",
            "image": {"digest": HUB_DIGEST, "sources": ["ghcr.io/acme/demo"]},
            "page_port": 8787,
            "source_sets": ["pypi"],
        },
        {
            "module": "late",
            "name": "neutrino_late",
            "image": {
                "digest": HUB_DIGEST.replace("9", "8"),
                "sources": ["ghcr.io/a/l"],
            },
        },
    ],
}


def test_the_machine_gets_the_hub_containers_whose_images_its_store_holds(
    rig, monkeypatch
):
    made: list = []
    monkeypatch.setattr(
        machine_runner_module,
        "image_references",
        lambda *, podman: {"ghcr.io/acme/demo@" + HUB_DIGEST},
    )
    monkeypatch.setattr(
        machine_runner_module,
        "ensure_network",
        lambda name, *, podman: made.append((name, podman[0])) or True,
    )
    monkeypatch.setattr(
        machine_runner_module,
        "fastest_sources",
        lambda names, sets: (
            {"pypi": "https://p.example"},
            {"pypi": ["PIP_INDEX_URL"]},
        ),
    )
    rig.runner._page_ports._pick = lambda taken: 40999
    rig.keep_image()

    rig.runner.apply(HUB_CONFIG)

    script = rig.world.scripts[-1][2]
    rendered = PodmanConfig.from_dict(HUB_CONFIG)
    expected = PodmanMachineScriptRenderer(
        config=rendered.with_hub_containers(rendered.hub_containers[:1]),
        os_name="darwin",
        context=PodmanRenderContext(
            images={"neutrino_demo": "ghcr.io/acme/demo@" + HUB_DIGEST},
            page_ports={"neutrino_demo": 40999},
            sources={"pypi": "https://p.example"},
            variables={"pypi": ["PIP_INDEX_URL"]},
        ),
    ).render()
    assert script == expected
    assert made == [("neutrino_demo", rig.system.binary)]
    assert rig.record()[0]["hub_names"] == {"demo": ["neutrino_demo"]}
    assert rig.runner.hub_names() == {"demo": ["neutrino_demo"]}
    assert rig.make_runner().hub_names() == {"demo": ["neutrino_demo"]}


def test_a_render_after_a_boot_that_reserved_a_page_port_publishes_a_new_port(
    rig, monkeypatch
):
    monkeypatch.setattr(
        machine_runner_module,
        "image_references",
        lambda *, podman: {"ghcr.io/acme/demo@" + HUB_DIGEST},
    )
    monkeypatch.setattr(
        machine_runner_module, "ensure_network", lambda name, *, podman: False
    )
    monkeypatch.setattr(
        machine_runner_module, "fastest_sources", lambda names, sets: ({}, {})
    )
    rendered = PodmanConfig.from_dict(HUB_CONFIG)

    def script_at(port: int) -> str:
        return PodmanMachineScriptRenderer(
            config=rendered.with_hub_containers(rendered.hub_containers[:1]),
            os_name="darwin",
            context=PodmanRenderContext(
                images={"neutrino_demo": "ghcr.io/acme/demo@" + HUB_DIGEST},
                page_ports={"neutrino_demo": port},
            ),
        ).render()

    rig.runner._page_ports._pick = lambda taken: 64586
    rig.runner._page_ports._is_refused = lambda port: False
    rig.keep_image()
    rig.runner.apply(HUB_CONFIG)
    assert rig.world.scripts[-1][2] == script_at(64586)

    rig.runner._page_ports._is_refused = {64586}.__contains__
    rig.runner._page_ports._pick = lambda taken: 15000
    assert rig.runner.refused_page_ports("demo") == [64586]

    rig.runner.apply(HUB_CONFIG)

    assert rig.world.scripts[-1][2] == script_at(15000)
    assert rig.runner.page_port("demo", "neutrino_demo") == 15000
    assert rig.runner.page_ports("demo") == {"neutrino_demo": 15000}
    assert rig.runner.refused_page_ports("demo") == []


def test_a_module_s_containers_are_applied_once_the_root_script_wrote_them(
    rig, monkeypatch
):
    monkeypatch.setattr(
        machine_runner_module,
        "image_references",
        lambda *, podman: {"ghcr.io/acme/demo@" + HUB_DIGEST},
    )
    monkeypatch.setattr(
        machine_runner_module, "ensure_network", lambda name, *, podman: False
    )
    monkeypatch.setattr(
        machine_runner_module, "fastest_sources", lambda names, sets: ({}, {})
    )
    rig.runner._page_ports._pick = lambda taken: 40999
    rig.keep_image()
    changed = json.loads(json.dumps(HUB_CONFIG))
    changed["hub_containers"][0]["environment"] = ["COOKIE_NAME=new"]

    assert rig.runner.is_applied("demo") is True
    rig.runner.take_config(HUB_CONFIG)
    rig.runner.apply(HUB_CONFIG)
    applied = rig.runner.is_applied("demo")
    rig.runner.take_config(changed)
    rig.world.shell_answers = [(1, "Job for neutrino_demo.service failed.\n")]
    refusal(lambda: rig.runner.apply(changed))

    assert applied is True
    assert rig.runner.is_applied("demo") is False
    assert rig.runner.is_applied("late") is False


def test_the_page_ports_are_under_the_state_root(rig, monkeypatch, tmp_path):
    config_root = tmp_path / "config_root"
    state_root = tmp_path / "state_root"
    monkeypatch.setattr(platforms_base_module, "AGENT_DATA_DIR_POSIX", str(config_root))
    monkeypatch.setattr(platforms_base_module, "AGENT_VAR_DIR", str(state_root))

    rig.make_runner().page_port("demo", "neutrino_demo")

    assert (state_root / "demo" / "page_ports.json").is_file()
    assert not config_root.exists()


def test_a_restarted_agent_counts_a_module_s_containers_written_until_its_first_apply(
    rig,
):
    rig.keep_image()
    rig.runner.apply(HUB_CONFIG)
    restarted = rig.make_runner()
    restarted.take_config(HUB_CONFIG)

    before = restarted.is_applied("demo")
    rig.world.shell_answers = [(1, "Job for web.service failed.\n")]
    refusal(lambda: restarted.apply(HUB_CONFIG))

    assert before is True
    assert restarted.is_applied("demo") is False


def test_a_container_module_drives_and_drops_its_containers_in_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner._config = PodmanConfig.from_dict(HUB_CONFIG)

    rig.runner.drive_hub_containers(["neutrino_demo", "neutrino_late"], "restart")
    rig.runner.drop_hub_containers("demo")

    assert (
        rig.world.scripts[-2][2]
        == "systemctl restart neutrino_demo.service neutrino_late.service\n"
    )
    assert rig.world.scripts[-1][2] == machine_drop_script(["neutrino_demo"])
    assert rig.runner.hub_names() == {"late": ["neutrino_late"]}


def test_a_container_module_s_journal_asked_during_a_read_takes_that_read(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    entered, release = threading.Event(), threading.Event()
    machine_class = rig.runner._machine_class
    asked_by = []

    class SlowMachine(machine_class):
        def shell(self, script):
            entered.set()
            release.wait(5)
            return super().shell(script)

    def clock():
        asked_by.append(threading.current_thread().name)
        return rig.now[0]

    rig.runner._machine_class = SlowMachine
    rig.runner._clock = clock
    rig.world.shell_answers = [(0, "first\n"), (0, "second\n")]
    answers = {}

    def read(name):
        answers[name] = rig.runner.hub_journal(["neutrino_demo"], 200)

    first = threading.Thread(target=read, args=("first",), name="first")
    first.start()
    assert entered.wait(5)
    rig.now[0] = 1.0
    waiting = threading.Thread(target=read, args=("waiting",), name="waiting")
    waiting.start()
    for _ in range(200):
        if "waiting" in asked_by:
            break
        threading.Event().wait(0.01)
    rig.now[0] = 2.0
    release.set()
    first.join(5)
    waiting.join(5)
    rig.now[0] = 3.0
    after = rig.runner.hub_journal(["neutrino_demo"], 200)

    assert answers == {"first": ["first"], "waiting": ["first"]}
    assert after == ["second"]
    assert (
        len(rig.world.scripts)
        - rig.world.scripts.index(
            next(item for item in rig.world.scripts if "journalctl" in item[2])
        )
        == 2
    )
