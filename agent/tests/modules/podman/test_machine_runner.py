"""The Podman machine runner, driven through a fake system applier, a fake
machine and a recorded launchd.

What these pin: the artifacts kept as the publisher's files with an msi or
a pkg handed to the system's installer; a restart owed holding the apply as
``reboot_required``; each refusal before anything runs, a Windows disk of 0
among them; a new machine made from the kept image and sized where the
provider takes no size at init, and removed when that sizing fails; a
machine taken over made rootful and sized, refused a smaller disk; a change
of size against the last apply, the disk grown and never shrunk; a new account stopping the old
machine and removing its keeper; the wait for the machine to answer; the one
root script; the reads through the ssh URL with addresses blanked and
folders back in the computer's form; the read's command a container's
shell runs through, empty before any apply; the keeper's log in the
journal; the verbs; stop, removal and uninstall keeping the machine; and a
restarted agent reading on from the record.
"""

import json
import os
import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.podman import applier as applier_module
from neutrino_agent.modules.podman import machine_runner as machine_runner_module
from neutrino_agent.modules.podman.config import PodmanConfig
from neutrino_agent.modules.podman.machine import PodmanMachineState
from neutrino_agent.modules.podman.machine_runner import (
    PODMAN_GIB,
    PodmanMachineModuleRunner,
    PodmanSystemApplier,
)
from neutrino_agent.modules.podman.renderer import (
    PodmanMachineScriptRenderer,
    PodmanRenderContext,
    machine_control_script,
    machine_drop_script,
    machine_journal_script,
    machine_stop_script,
)
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
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
            code, output = (
                world.shell_answers.pop(0) if world.shell_answers else (0, "")
            )
            return subprocess.CompletedProcess([], code, output, "")

        def control(self, name, action):
            world.calls.append((self.account, "control", name, action))

    return FakeMachine


class FakeSystem(PodmanSystemApplier):
    """The system's part, recorded; its program a file in the test's directory."""

    provider = "applehv"

    def __init__(self, binary, provider="applehv"):
        self.binary = binary
        self.provider = provider
        self.calls: list = []
        self.is_pending = False
        self.disk = 0
        self.disk_error = None
        self.facts = (8, 16)

    def install_artifact(self, artifact, path):
        self.calls.append(("install", artifact["name"], os.path.basename(path)))

    def is_reboot_pending(self):
        return self.is_pending

    def uninstall(self):
        self.calls.append(("uninstall",))

    def host_facts(self):
        return self.facts

    def disk_gib(self, machine):
        return self.disk

    def halt(self, machine):
        self.calls.append(("halt", machine.account))

    def terminate(self, machine):
        self.calls.append(("terminate", machine.account))

    def write_resources(self, machine, *, cpus, memory_gib):
        self.calls.append(("resources", machine.account, cpus, memory_gib))

    def resize_disk(self, machine, *, disk_gib):
        self.calls.append(("disk", machine.account, disk_gib))
        if self.disk_error is not None:
            raise self.disk_error

    def machine_environment(self, account):
        return {"TMPDIR": f"/var/folders/{account}/T/"}


class Launchctl:
    """launchctl, recorded: a job loaded by ``bootstrap`` until ``bootout``."""

    def __init__(self):
        self.calls: list = []
        self.loaded: set = set()

    def __call__(self, command, *, is_checked=True, **_):
        self.calls.append(list(command))
        verb = command[1]
        if verb == "print":
            label = command[2].split("/", 1)[1]
            code = 0 if label in self.loaded else 113
            return CommandResult(list(command), code, "state = running\n", "")
        if verb == "bootstrap":
            self.loaded.add(os.path.basename(command[3])[: -len(".plist")])
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

    def agent_log_path(self):
        return os.path.join(self._root, "agent.log")

    def account_home(self, account):
        return f"/Users/{account}"

    def open_to_accounts(self, directory):
        self.opened.append(directory)


class FakeProbe:
    """Answers ``http`` for every port it is asked about, and records them."""

    asked: list = []

    def detected(self, targets):
        FakeProbe.asked.append(list(targets))
        return {key: "http" for key, _, _ in targets}


def lookup(account):
    if account not in ("me", "ann"):
        raise KeyError(account)
    return AccountEntry(501, 20, f"/Users/{account}", "/bin/zsh")


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
            lookup_account=lookup,
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


# --- the install ---


def test_an_msi_or_a_pkg_is_kept_and_handed_to_the_systems_installer(rig, tmp_path):
    package = tmp_path / "download"
    package.write_text("pkg bytes")
    artifact = {"name": "podman", "kind": "pkg", "directory": "podman"}

    rig.runner.install_artifact({}, artifact, str(package))

    kept = tmp_path / "state" / "podman" / "podman" / "podman.pkg"
    assert kept.read_text() == "pkg bytes"
    assert not package.exists()
    assert rig.system.calls == [("install", "podman", "podman.pkg")]
    assert rig.platform.opened == [str(tmp_path / "state" / "podman")]


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


# --- refusals ---


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


def test_a_folder_the_machine_cannot_reach_is_refused_before_anything_runs(rig):
    config = dict(CONFIG, containers=[dict(CONTAINERS[0], volumes=["/opt/www:/srv"])])

    assert refusal(lambda: rig.runner.apply(config)).code == "volume_not_shared"
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
    assert rig.plist().is_file()
    assert rig.launchctl.verbs() == ["bootout", "bootstrap"]
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
        }
    ]
    assert rig.lines[-1] == "podman: made the machine of me; containers unchanged"


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

    assert rig.system.calls == [("resources", "me", 4, 2), ("disk", "me", 100)]
    assert rig.world.calls[0][1] == "init"
    assert ("me", "info") in rig.world.calls


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
    assert rig.launchctl.verbs() == ["bootout", "bootout", "bootstrap"]
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
    assert rig.launchctl.verbs()[0] == "bootout"
    assert "set the machine back to WSL's NAT networking" in rig.lines[-1]
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
    assert rig.launchctl.verbs() == []
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


def test_a_containers_journal_is_read_in_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.shell_answers = [(0, "line one\nline two\n")]
    seen = []

    outcome = rig.runner.command("journal", {"name": "web"}, seen.append)

    assert outcome["output"] == "line one\nline two"
    assert seen == ["line one", "line two"]
    assert rig.world.scripts[-1][2] == machine_journal_script("web", 200)


def test_a_verb_before_any_apply_knows_no_container(rig):
    assert rig.runner.command("control", {"name": "web", "action": "stop"})["code"] == (
        "container_unknown"
    )


# --- stop, removal, uninstall ---


def test_stop_stops_the_declared_containers_and_leaves_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.calls.clear()

    rig.runner.stop()

    assert rig.world.scripts[-1][2] == machine_stop_script()
    assert rig.world.calls == []


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


def test_a_machine_that_cannot_take_the_script_still_loses_its_keeper(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.world.shell_answers = [(255, "ssh: connect refused\n")]

    rig.runner.remove_configuration()

    assert not rig.plist().exists()
    assert any("script failed" in line for line in rig.lines)


def test_uninstall_removes_podman_and_the_kept_files_and_keeps_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)

    rig.runner.uninstall({})

    assert rig.system.calls[-1] == ("uninstall",)
    assert not (rig.tmp_path / "state" / "podman").exists()
    assert not rig.plist().exists()
    assert rig.record() == []
    assert "me" in rig.world.present


def test_another_version_uninstalls_the_podman_package_first_and_keeps_wsl(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.system.calls.clear()

    rig.runner.uninstall_package({}, {"name": "wsl", "kind": "msi"})
    rig.runner.uninstall_package({}, {"name": "podman", "kind": "msi"})

    assert rig.system.calls == [("uninstall",)]
    assert "me" in rig.world.present
    assert rig.plist().exists()


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
    rig.runner._page_ports._pick = lambda: 40999
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


def test_a_container_module_drives_and_drops_its_containers_in_the_machine(rig):
    rig.keep_image()
    rig.runner.apply(CONFIG)
    rig.runner._config = PodmanConfig.from_dict(HUB_CONFIG)

    rig.runner.drive_hub_containers(["neutrino_demo"], "restart")
    rig.runner.drop_hub_containers("demo")

    assert rig.world.scripts[-2][2] == "systemctl restart neutrino_demo.service\n"
    assert rig.world.scripts[-1][2] == machine_drop_script(["neutrino_demo"])
    assert rig.runner.hub_names() == {"late": ["neutrino_late"]}
