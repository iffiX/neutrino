"""The container engine runner: validate, apply, stop, verbs, and what it observes.

What these pin beside the verbs: ``observe()`` reads the binary, the unit
and the details in one go, and each container's details are what
``podman ps -a --format json`` and ``podman inspect`` say, image, ports,
volumes, environment and whether a unit stands for it, so containers
somebody started by hand are reported the way the hub imports them. The
``podman`` package installed and removed only with the package mark: a
Podman found before the install is the person's, left out of the packages
and kept by an uninstall, a ``runc`` the machine lacks installed beside it
and owed while it is missing, and ``runc`` never removed.
"""

import json
import os
import shutil
import subprocess

import pytest

from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.shared import system_package as system_package_module
from neutrino_agent.modules.podman import applier as applier_module
from neutrino_agent.modules.podman import runner as runner_module
from neutrino_agent.modules.podman.applier import PodmanContainerState
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms import base as platforms_base_module
from neutrino_agent.platforms.base import AgentPlatform

# What ``podman ps -a --format json`` prints for a running and an exited
# container, cut to the fields that are read.
PS_OUTPUT = json.dumps(
    [
        {
            "Id": "0a1b",
            "Names": ["web"],
            "Image": "docker.io/library/nginx:1.27",
            "State": "running",
            "StartedAt": 1791761649,
            "Status": "Up 2 hours",
            "Ports": [
                {
                    "host_ip": "",
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
            "Status": "Exited (0) 3 days ago",
            "Ports": None,
        },
    ]
)

# What ``podman inspect`` prints for the same two, cut the same way.
INSPECT_OUTPUT = json.dumps(
    [
        {
            "Id": "0a1b",
            "Name": "web",
            "Config": {
                "Image": "docker.io/library/nginx:1.27",
                "Env": [
                    "PATH=/usr/sbin:/usr/bin",
                    "NGINX_VERSION=1.27.0",
                    "container=podman",
                ],
            },
            "HostConfig": {
                "PortBindings": {"80/tcp": [{"HostIp": "", "HostPort": "8080"}]}
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/srv/web",
                    "Destination": "/usr/share/nginx/html",
                    "RW": True,
                },
                {
                    "Type": "volume",
                    "Name": "webdata",
                    "Source": "/var/lib/containers/storage/volumes/webdata/_data",
                    "Destination": "/data",
                },
            ],
        },
        {
            "Id": "2c3d",
            "Name": "adhoc",
            "Config": {
                "Image": "docker.io/library/alpine:3.20",
                "Env": ["PATH=/usr/bin"],
            },
            "HostConfig": {"PortBindings": {}},
            "Mounts": [],
        },
    ]
)

CONFIG = {
    "containers": [{"name": "web", "image": "nginx", "ports": ["8080:80"]}],
    "mirrors": ["mirror.example"],
}


class FakeUnitApplier:
    applied: list = []
    stops = 0
    driven: list = []
    removed: list = []

    def apply(self, rendered, environments, *, autostart_names, source_keys=None):
        assert sorted(environments) == [
            name[: -len(".service")] + ".env" for name in sorted(rendered)
        ]
        FakeUnitApplier.applied.append((sorted(rendered), autostart_names))
        return "containers: web"

    def stop_all(self):
        FakeUnitApplier.stops += 1

    def drive(self, names, action):
        FakeUnitApplier.driven.append((list(names), action))

    def remove(self, names):
        FakeUnitApplier.removed.append(list(names))
        return list(names)

    def remove_all(self):
        FakeUnitApplier.removed.append(["*"])


class FakeRegistries:
    written: list = []

    def apply(self, rendered):
        FakeRegistries.written.append(rendered)
        return "mirrors updated"


class FakeReader:
    def __init__(self, *, probe=None):
        self.probe = probe

    def survey(self, *, declared_names, hub_names=None):
        return [
            PodmanContainerState(
                "web",
                "nginx",
                "Up",
                True,
                "declared" if "web" in declared_names else "manual",
                host_ports=[8080],
            ),
            PodmanContainerState("adhoc", "alpine", "Exited", False, "manual"),
        ]


class FakeProbe:
    """Answers ``http`` for every port it is asked about, and records them."""

    asked: list = []

    def detected(self, targets):
        FakeProbe.asked.append(list(targets))
        return {key: "http" for key, _, _ in targets}


class FakeController:
    calls: list = []
    error = None

    def control(self, name, action, *, source):
        if FakeController.error is not None:
            raise FakeController.error
        FakeController.calls.append((name, action, source))


class FakeRenderer:
    """Renders one file per container it is given, and remembers the context."""

    seen: list = []

    def __init__(self, *, config, context=None):
        FakeRenderer.seen.append((config, context))
        self._config = config

    def _names(self):
        return [
            c.name for c in [*self._config.containers, *self._config.hub_containers]
        ]

    def render(self):
        return {f"{name}.service": "x" for name in self._names()}

    def environment_files(self):
        return {f"{name}.env": "x" for name in self._names()}

    def source_keys(self):
        return {}


class FakeSystem:
    """Records every command the runner itself runs; podman's and systemd's answers are canned."""

    def __init__(self):
        self.calls: list = []
        self.error = None
        self.answers: dict = {}

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        if self.error is not None:
            raise self.error
        return CommandResult(list(command), 0, self.answers.get(command[-1], ""), "")

    def changes(self) -> list:
        """The commands that change a unit, every ``systemctl show`` left out."""
        return [call for call in self.calls if call[:2] != ["systemctl", "show"]]


@pytest.fixture
def system(monkeypatch):
    """Every command the runner runs, ``systemctl`` and podman's network and
    image reads among them, recorded and never started."""
    held = FakeSystem()
    monkeypatch.setattr(runner_module, "run", held)
    monkeypatch.setattr(runner_module, "network_gateway", lambda name: "10.88.0.1")
    monkeypatch.setattr(runner_module, "ensure_network", lambda name: False)
    monkeypatch.setattr(runner_module, "image_references", lambda: set())
    monkeypatch.setattr(runner_module, "fastest_sources", lambda names, sets: ({}, {}))
    return held


@pytest.fixture
def runner(monkeypatch, system, tmp_path):
    FakeUnitApplier.applied = []
    FakeUnitApplier.stops = 0
    FakeUnitApplier.driven = []
    FakeUnitApplier.removed = []
    FakeRenderer.seen = []
    FakeRegistries.written = []
    FakeController.calls = []
    FakeController.error = None
    FakeProbe.asked = []
    monkeypatch.setattr(runner_module, "PodmanServiceProbe", FakeProbe)
    monkeypatch.setattr(runner_module, "PodmanUnitApplier", FakeUnitApplier)
    monkeypatch.setattr(runner_module, "PodmanRegistriesApplier", FakeRegistries)
    monkeypatch.setattr(runner_module, "PodmanStatusReader", FakeReader)
    monkeypatch.setattr(runner_module, "PodmanContainerController", FakeController)
    monkeypatch.setattr(runner_module, "podman_version", lambda: "4.9.3")
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "active")
    monkeypatch.setattr(runner_module, "journal_lines", lambda name, lines: ["a", "b"])
    monkeypatch.setattr(runner_module, "PodmanUnitRenderer", FakeRenderer)
    return PodmanModuleRunner(platform=AgentPlatform(), log=lambda m: None)


def test_validate_refuses_typed(runner):
    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({"containers": [{"name": "Bad", "image": "x"}]})

    assert refused.value.code == "container_name_invalid"


def test_apply_renders_the_units_and_the_mirrors(runner):
    runner.apply(CONFIG)

    assert FakeUnitApplier.applied == [(["web.service"], ["web"])]
    assert 'location = "mirror.example"' in FakeRegistries.written[0]


def test_a_refused_apply_is_typed(runner, monkeypatch):
    def refuse(self, rendered, environments, *, autostart_names, source_keys=None):
        raise subprocess.CalledProcessError(1, ["systemctl"], stderr="bad unit")

    monkeypatch.setattr(FakeUnitApplier, "apply", refuse)

    with pytest.raises(ModuleApplyError) as refused:
        runner.apply(CONFIG)

    assert refused.value.code == "apply_failed"


def test_stop_takes_every_container_down_then_turns_the_service_and_socket_off(
    runner, system
):
    runner.stop()

    assert FakeUnitApplier.stops == 1
    assert system.changes() == [
        ["systemctl", "disable", "--now", "podman.service"],
        ["systemctl", "disable", "--now", "podman.socket"],
    ]


def plain_step(name):
    return ModuleStep(name=name, run=None)


def test_every_step_of_the_module_s_own_task_takes_containers_alone(runner):
    assert runner.step_locks("packages") == (("containers", "alone"),)
    assert runner.step_locks("configure") == (("containers", "alone"),)
    assert runner.step_locks("stop") == (("containers", "alone"),)


def test_the_configure_under_stopped_writes_nothing_and_runs_no_systemctl(
    runner, system
):
    """A join adopts a person's Podman stopped: the container the person
    started by hand gets no unit and no environment file, and reads as the
    person's until the first Start writes the configuration."""
    lines: list = []
    runner._log = lines.append
    steps = runner.configure_steps(
        CONFIG, "stopped", [plain_step("configure"), plain_step("stop")]
    )

    steps[0].run(None)

    assert [step.name for step in steps] == ["configure", "stop"]
    assert FakeUnitApplier.applied == []
    assert FakeRegistries.written == []
    assert system.calls == []
    assert lines == ["podman: kept the configuration for the next Start"]
    by_name = {c["name"]: c for c in runner.details({})["containers"]}
    assert by_name["web"]["source"] == "manual"


def test_the_configure_under_stopped_raises_a_refused_container_and_writes_nothing(
    runner, system
):
    refused = {"containers": [{"name": "bad", "image": "has space"}], "mirrors": []}

    with pytest.raises(ModuleApplyError) as raised:
        runner.apply_stopped(refused)

    assert raised.value.code == "image_invalid"
    assert FakeUnitApplier.applied == []
    assert system.calls == []


def test_a_start_after_the_configure_under_stopped_writes_the_configuration(runner):
    runner.apply_stopped(CONFIG)

    runner.apply(CONFIG)

    assert FakeUnitApplier.applied == [(["web.service"], ["web"])]


def test_the_configure_under_running_is_the_core_s_own(runner):
    steps = [plain_step("configure"), plain_step("start")]

    assert runner.configure_steps(CONFIG, "running", steps) is steps


def test_start_turns_the_socket_on(runner, system):
    runner.start()

    assert system.changes() == [["systemctl", "enable", "--now", "podman.socket"]]


def test_a_refused_socket_is_apply_failed(runner, system):
    system.error = subprocess.CalledProcessError(1, ["systemctl"], stderr="denied")

    with pytest.raises(ModuleApplyError) as refused:
        runner.start()

    assert refused.value.code == "apply_failed"


class FakeMachine:
    """The machine's programs on the path and its package manager: a package
    installed puts its program on the path, and one removed takes it off."""

    def __init__(self, monkeypatch, runner, programs=()):
        self.programs = set(programs)
        self.installed: list = []
        self.removed: list = []
        self.install_error = None
        self.is_installing = True
        monkeypatch.setattr(shutil, "which", self.which)
        runner._platform.install_system_packages = self.install
        runner._platform.remove_system_packages = self.remove

    def which(self, name):
        found = os.path.basename(name)
        return f"/usr/bin/{found}" if found in self.programs else None

    def install(self, names):
        self.installed.append(list(names))
        if self.install_error is not None:
            raise self.install_error
        if self.is_installing:
            self.programs.update(names)
        return ""

    def remove(self, names):
        self.removed.append(list(names))
        self.programs.difference_update(names)
        return ""


RECIPE = {
    "method": "system",
    "params": {
        "packages": ["podman", "runc"],
        "verify": "podman --version",
        "uninstall": {"packages": ["podman"], "post_uninstall": []},
    },
}


def package_mark(tmp_path):
    return tmp_path / "podman" / "package_mark"


def test_the_install_turns_the_socket_on_after_the_packages(
    runner, system, monkeypatch
):
    machine = FakeMachine(monkeypatch, runner)

    runner.install({"method": "system", "params": {"packages": ["podman"]}})

    assert machine.installed == [["podman"]]
    assert system.calls == [["systemctl", "enable", "--now", "podman.socket"]]


def test_the_install_leaves_runc_out_where_a_runc_is_on_the_path(
    runner, system, monkeypatch
):
    """Docker CE's containerd.io includes a runc and conflicts with the
    distribution's package, which apt would remove Docker for."""
    machine = FakeMachine(monkeypatch, runner, programs={"runc"})

    runner.install(RECIPE)

    assert machine.installed == [["podman"]]
    assert RECIPE["params"]["packages"] == ["podman", "runc"]


def test_a_machine_with_no_podman_gets_the_packages_and_the_package_mark(
    runner, system, monkeypatch, tmp_path
):
    machine = FakeMachine(monkeypatch, runner)

    runner.install(RECIPE)

    assert machine.installed == [["podman", "runc"]]
    assert package_mark(tmp_path).is_file()
    assert oct(package_mark(tmp_path).stat().st_mode & 0o777) == oct(0o600)
    assert runner.is_software_kept() is False
    assert system.calls == [["systemctl", "enable", "--now", "podman.socket"]]


def test_a_persons_podman_gets_no_package_manager_and_no_mark(
    runner, system, monkeypatch, tmp_path
):
    lines: list = []
    runner._log = lines.append
    machine = FakeMachine(monkeypatch, runner, programs={"podman", "runc"})

    runner.install(RECIPE)

    assert machine.installed == []
    assert not package_mark(tmp_path).exists()
    assert "podman: found the machine's own Podman, left its package out" in lines
    assert runner.is_software_kept() is True
    assert system.changes() == [["systemctl", "enable", "--now", "podman.socket"]]


def test_a_persons_podman_with_no_runc_gets_runc_alone(
    runner, system, monkeypatch, tmp_path
):
    machine = FakeMachine(monkeypatch, runner, programs={"podman"})

    runner.install(RECIPE)

    assert machine.installed == [["runc"]]
    assert not package_mark(tmp_path).exists()
    assert runner.is_software_kept() is True


def test_a_machine_with_no_runc_owes_the_install_until_one_is_on_the_path(
    runner, monkeypatch
):
    """A person's Podman that came without runc passes verify; the core plans
    the owed install only under installed or running, so a join that adopts
    it stopped installs nothing."""
    machine = FakeMachine(monkeypatch, runner, programs={"podman"})

    assert runner.is_install_owed(RECIPE) is True
    machine.programs.add("runc")
    assert runner.is_install_owed(RECIPE) is False


def test_a_recipe_that_names_no_runc_owes_no_install(runner, monkeypatch):
    FakeMachine(monkeypatch, runner, programs={"podman"})

    assert runner.is_install_owed({"params": {"packages": ["podman"]}}) is False
    assert runner.is_install_owed({}) is False


def test_the_module_s_podman_goes_to_the_package_manager_again_with_its_mark(
    runner, system, monkeypatch, tmp_path
):
    machine = FakeMachine(monkeypatch, runner)
    runner.install(RECIPE)

    runner.install(RECIPE)

    assert machine.installed == [["podman", "runc"], ["podman"]]
    assert package_mark(tmp_path).is_file()


@pytest.mark.parametrize("is_failed", [True, False])
def test_a_run_that_leaves_no_podman_leaves_no_mark(
    runner, system, monkeypatch, tmp_path, is_failed
):
    machine = FakeMachine(monkeypatch, runner)
    machine.is_installing = False
    if is_failed:
        machine.install_error = InstallError("apt-get failed", exit_code=100)

    try:
        runner.install(RECIPE)
    except InstallError:
        assert is_failed

    assert machine.installed == [["podman", "runc"]]
    assert not package_mark(tmp_path).exists()
    assert runner.is_software_kept() is False


def test_an_uninstall_with_the_mark_removes_podman_and_the_mark_and_keeps_runc(
    runner, system, monkeypatch, tmp_path
):
    machine = FakeMachine(monkeypatch, runner)
    runner.install(RECIPE)

    runner.uninstall(RECIPE)

    assert machine.removed == [["podman"]]
    assert machine.programs == {"runc"}
    assert not package_mark(tmp_path).exists()
    assert not (tmp_path / "podman").exists()
    assert runner.verify({}) is False


def test_an_uninstall_of_a_persons_podman_removes_no_package(
    runner, system, monkeypatch, tmp_path
):
    lines: list = []
    runner._log = lines.append
    machine = FakeMachine(monkeypatch, runner, programs={"podman", "runc"})
    runner.install(RECIPE)

    runner.uninstall(RECIPE)

    assert machine.removed == []
    assert machine.programs == {"podman", "runc"}
    assert "podman: removed no package" in lines
    assert not (tmp_path / "podman").exists()
    assert runner.is_software_kept() is True


UBUNTU_UNITS = {
    "podman.socket": "UnitFileState=enabled\nActiveState=active\n",
    "podman.service": "UnitFileState=enabled\nActiveState=inactive\n",
}
PUT_BACK_AS_UBUNTU_HAS_THEM = [
    ["systemctl", "enable", "podman.socket"],
    ["systemctl", "start", "podman.socket"],
    ["systemctl", "enable", "podman.service"],
    ["systemctl", "stop", "podman.service"],
]


def found_units(tmp_path):
    return tmp_path / "podman" / "found_units"


def test_a_persons_podman_units_are_put_back_at_the_uninstall_as_the_start_found_them(
    runner, system, monkeypatch, tmp_path
):
    """Ubuntu's package enables both units, and Stop disables both."""
    lines: list = []
    runner._log = lines.append
    FakeMachine(monkeypatch, runner, programs={"podman", "runc"})
    system.answers = dict(UBUNTU_UNITS)

    runner.start()
    system.answers = {}
    runner.start()
    runner.stop()
    runner.remove_configuration()
    system.calls.clear()
    runner.uninstall(RECIPE)

    assert system.changes() == PUT_BACK_AS_UBUNTU_HAS_THEM
    assert not found_units(tmp_path).exists()
    assert "podman: put podman.socket and podman.service back as they were" in lines


def test_a_persons_podman_units_are_kept_before_the_install_turns_the_socket_on(
    runner, system, monkeypatch, tmp_path
):
    FakeMachine(monkeypatch, runner, programs={"podman", "runc"})
    system.answers = dict(UBUNTU_UNITS)

    runner.install(RECIPE)

    shows = [call[-1] for call in system.calls if call[:2] == ["systemctl", "show"]]
    assert shows == ["podman.socket", "podman.service"]
    assert system.calls.index(["systemctl", "enable", "--now", "podman.socket"]) > 1
    assert oct(found_units(tmp_path).stat().st_mode & 0o777) == oct(0o600)


def test_a_stop_with_nothing_kept_keeps_what_the_units_were(
    runner, system, monkeypatch, tmp_path
):
    FakeMachine(monkeypatch, runner, programs={"podman", "runc"})
    system.answers = dict(UBUNTU_UNITS)

    runner.stop()
    system.calls.clear()
    runner.uninstall(RECIPE)

    assert system.changes() == PUT_BACK_AS_UBUNTU_HAS_THEM


FEDORA_UNITS_THE_PERSON_ENABLED = {
    "podman.socket": "UnitFileState=enabled\nActiveState=inactive\n",
    "podman.service": "UnitFileState=disabled\nActiveState=inactive\n",
}


def test_a_stop_with_nothing_kept_and_the_socket_off_leaves_both_units_as_they_are(
    runner, system, monkeypatch, tmp_path
):
    """A join adopts a person's Podman whose socket is not active stopped:
    on Fedora 42 the person had enabled podman.socket for the next boot."""
    lines: list = []
    runner._log = lines.append
    FakeMachine(monkeypatch, runner, programs={"podman"})
    system.answers = dict(FEDORA_UNITS_THE_PERSON_ENABLED)
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "inactive")

    runner.stop()

    assert system.calls == []
    assert FakeUnitApplier.stops == 1
    assert not found_units(tmp_path).exists()
    assert "podman: left podman.socket and podman.service as they are" in lines


def test_a_stop_after_a_start_disables_both_units_with_the_socket_off(
    runner, system, monkeypatch, tmp_path
):
    FakeMachine(monkeypatch, runner, programs={"podman"})
    system.answers = dict(FEDORA_UNITS_THE_PERSON_ENABLED)
    runner.start()
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "inactive")
    system.calls.clear()

    runner.stop()

    assert system.changes() == [
        ["systemctl", "disable", "--now", "podman.service"],
        ["systemctl", "disable", "--now", "podman.socket"],
    ]


def test_the_module_s_podman_is_stopped_with_its_socket_off_too(
    runner, system, monkeypatch, tmp_path
):
    FakeMachine(monkeypatch, runner)
    runner.install(RECIPE)
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "inactive")
    system.calls.clear()

    runner.stop()

    assert system.changes() == [
        ["systemctl", "disable", "--now", "podman.service"],
        ["systemctl", "disable", "--now", "podman.socket"],
    ]
    assert not found_units(tmp_path).exists()


def test_an_uninstall_with_nothing_kept_leaves_the_units_as_they_are(
    runner, system, monkeypatch, tmp_path
):
    FakeMachine(monkeypatch, runner, programs={"podman", "runc"})

    runner.uninstall(RECIPE)

    assert system.calls == []


def test_the_module_s_podman_keeps_and_puts_back_no_unit(
    runner, system, monkeypatch, tmp_path
):
    machine = FakeMachine(monkeypatch, runner)
    runner.install(RECIPE)
    runner.start()
    runner.stop()
    system.calls.clear()

    runner.uninstall(RECIPE)

    assert machine.removed == [["podman"]]
    assert not found_units(tmp_path).exists()
    assert [call for call in system.calls if call[0] == "systemctl"] == []


def test_is_active_is_the_units_word(runner, monkeypatch):
    asked: list = []
    monkeypatch.setattr(
        runner_module, "unit_state", lambda unit: asked.append(unit) or "active"
    )
    assert runner.is_active() is True
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "inactive")
    assert runner.is_active() is False
    assert asked == ["podman.socket"]


def test_the_own_check_is_the_engines_binary(runner, monkeypatch):
    monkeypatch.setattr(
        system_package_module.shutil,
        "which",
        lambda name: name if name.endswith("podman") else None,
    )
    assert runner.verify({}) is True
    monkeypatch.setattr(system_package_module.shutil, "which", lambda name: None)
    assert runner.verify({}) is False


def test_a_declaration_is_surveyed_while_its_start_still_waits(runner, monkeypatch):
    """The declared names reach the survey before the units are started,
    so a report taken during an image pull lists the container."""
    seen: list = []

    def start(self, rendered, environments, *, autostart_names, source_keys=None):
        seen.append(runner.details({})["containers"])

    monkeypatch.setattr(FakeUnitApplier, "apply", start)

    runner.apply(CONFIG)

    assert [c["name"] for c in seen[0] if c["source"] == "declared"] == ["web"]


def test_details_separate_declared_from_manual(runner):
    runner.apply(CONFIG)

    details = runner.details({})

    by_name = {c["name"]: c for c in details["containers"]}
    assert by_name["web"]["source"] == "declared"
    assert by_name["web"]["host_ports"] == [8080]
    assert by_name["adhoc"]["source"] == "manual"
    assert details["mirrors"] == ["mirror.example"]
    assert details["version"] == "4.9.3"
    assert details["is_active"] is True


def test_control_drives_a_known_container_and_refuses_an_unknown(runner):
    runner.apply(CONFIG)

    good = runner.command("control", {"name": "web", "action": "restart"})
    ghost = runner.command("control", {"name": "ghost", "action": "start"})
    verb = runner.command("control", {"name": "web", "action": "rm"})

    assert good["exit_code"] == 0
    assert FakeController.calls == [("web", "restart", "declared")]
    assert ghost["code"] == "container_unknown"
    assert verb["code"] == "verb_unknown"
    assert verb["params"] == {"module": "podman", "verb": "rm"}


def test_a_verb_the_module_does_not_have_is_refused(runner):
    outcome = runner.command("set_password", {"name": "web"})

    assert outcome["code"] == "verb_unknown"
    assert outcome["params"] == {"module": "podman", "verb": "set_password"}


def test_validate_is_a_verb_every_module_answers(runner):
    good = runner.command("validate", {"config": CONFIG})
    bad = runner.command("validate", {"config": {"containers": [{"name": "../x"}]}})

    assert (good["exit_code"], good["code"]) == (0, "")
    assert (bad["exit_code"], bad["code"]) == (1, "container_name_invalid")


# --- what a hand-run engine observes as ---


def podman_commands(monkeypatch):
    """podman answered from the fixtures; ``web`` has a unit, ``adhoc`` none."""
    asked: list = []

    def run(command, *, is_checked=True, input_text=None, timeout_s=120):
        asked.append(list(command))
        if command[1] == "ps":
            return CommandResult(command, 0, PS_OUTPUT, "")
        if command[1] == "inspect":
            return CommandResult(command, 0, INSPECT_OUTPUT, "")
        raise OSError(f"{command[0]} is not here")

    monkeypatch.setattr(applier_module, "run", run)
    monkeypatch.setattr(applier_module, "has_unit_file", lambda name: name == "web")
    monkeypatch.setattr(
        runner_module, "PodmanStatusReader", applier_module.PodmanStatusReader
    )
    monkeypatch.setattr(
        system_package_module.shutil, "which", lambda name: "/usr/bin/podman"
    )
    return asked


def test_the_details_read_what_podman_itself_says_of_each_container(
    runner, monkeypatch
):
    asked = podman_commands(monkeypatch)

    details = runner.details({})

    assert runner.is_active() is True
    assert set(details) == {"containers", "mirrors", "version", "is_active"}
    assert details["version"] == "4.9.3"
    by_name = {container["name"]: container for container in details["containers"]}
    assert by_name["web"] == {
        "name": "web",
        "image": "docker.io/library/nginx:1.27",
        "status": "Up 2 hours",
        "is_running": True,
        "source": "manual",
        "module": "",
        "host_ports": [8080],
        "ports": ["8080:80"],
        "volumes": [
            "/srv/web:/usr/share/nginx/html",
            "webdata:/data",
        ],
        "environment": [
            "PATH=/usr/sbin:/usr/bin",
            "NGINX_VERSION=1.27.0",
            "container=podman",
        ],
        "has_unit": True,
        "host_bindings": [
            {"address": "", "port": 8080, "protocol": "tcp", "detected": "http"}
        ],
    }
    assert FakeProbe.asked == [[(("0a1b", "1791761649", "", 8080), "127.0.0.1", 8080)]]
    assert by_name["adhoc"]["is_running"] is False
    assert by_name["adhoc"]["host_bindings"] == []
    assert by_name["adhoc"]["ports"] == []
    assert by_name["adhoc"]["volumes"] == []
    assert by_name["adhoc"]["has_unit"] is False
    # One inspect for every listed container, never one per container.
    assert [c for c in asked if c[1] == "inspect"] == [
        [applier_module.PODMAN_BINARY, "inspect", "--type", "container", "web", "adhoc"]
    ]


def test_the_details_mark_the_containers_the_hub_declares(runner, monkeypatch):
    podman_commands(monkeypatch)
    runner.apply(CONFIG)

    by_name = {c["name"]: c for c in runner.details({})["containers"]}

    assert by_name["web"]["source"] == "declared"
    assert by_name["adhoc"]["source"] == "manual"


def test_removing_the_configuration_drops_the_units_and_the_mirrors(
    runner, monkeypatch, tmp_path
):
    units = tmp_path / "system"
    units.mkdir()
    envs = tmp_path / "env"
    envs.mkdir()
    (units / "web.service").write_text(
        applier_module.PODMAN_GENERATED_MARKER + "\n[Service]\n"
    )
    (envs / "web.env").write_text(applier_module.PODMAN_GENERATED_MARKER + "\n")
    (units / "theirs.service").write_text("[Service]\n")
    mirrors = tmp_path / "99_neutrino_mirrors.conf"
    mirrors.write_text("[[registry]]")
    monkeypatch.setattr(applier_module, "PODMAN_REGISTRIES_CONF_PATH", str(mirrors))
    monkeypatch.setattr(runner_module, "run", lambda command, **kwargs: None)
    monkeypatch.setattr(
        runner_module, "PodmanRegistriesApplier", applier_module.PodmanRegistriesApplier
    )
    monkeypatch.setattr(
        runner_module,
        "PodmanUnitApplier",
        lambda: applier_module.PodmanUnitApplier(
            directory=str(units), env_directory=str(envs), quadlet_directories=()
        ),
    )
    monkeypatch.setattr(applier_module, "run", lambda command, **kwargs: None)

    runner.remove_configuration()

    assert sorted(path.name for path in units.iterdir()) == ["theirs.service"]
    assert not envs.exists()
    assert not mirrors.exists()


def test_a_bad_name_never_reaches_a_command(runner):
    outcome = runner.command("journal", {"name": "../etc"})

    assert outcome["code"] == "container_name_invalid"


def test_a_refused_control_is_typed(runner):
    FakeController.error = subprocess.CalledProcessError(
        1, ["systemctl"], stderr="will not start"
    )

    outcome = runner.command("control", {"name": "web", "action": "start"})

    assert outcome["code"] == "command_failed"


def test_the_journal_streams_its_lines_and_carries_them_in_the_output(runner):
    lines: list = []

    outcome = runner.command("journal", {"name": "web"}, lines.append)

    assert lines == ["a", "b"]
    assert outcome["output"] == "a\nb"
    assert outcome["exit_code"] == 0


def test_a_journal_naming_no_container_is_the_modules_own(runner, monkeypatch):
    asked: list = []
    monkeypatch.setattr(
        "neutrino_agent.modules.shared.base.units_journal",
        lambda units, lines: asked.append(list(units)) or ["line"],
    )
    runner.apply(CONFIG)

    outcome = runner.command("journal", {})

    assert outcome == {"exit_code": 0, "code": "", "params": {}, "output": "line"}
    assert asked == [["podman.socket", "web.service"]]


# --- hub containers on Linux ---

HUB_DIGEST = "sha256:" + "d" * 64

HUB_CONFIG = {
    "containers": [{"name": "web", "image": "nginx", "ports": ["8080:80"]}],
    "mirrors": [],
    "hub_containers": [
        {
            "module": "demo",
            "name": "neutrino_demo",
            "image": {"digest": HUB_DIGEST, "sources": ["ghcr.io/acme/demo"]},
            "volumes": ["neutrino_demo_data:/data"],
            "source_sets": ["pypi"],
            "page_port": 8787,
        },
        {
            "module": "late",
            "name": "neutrino_late",
            "image": {
                "digest": HUB_DIGEST.replace("d", "f"),
                "sources": ["ghcr.io/a/l"],
            },
        },
    ],
}


@pytest.fixture
def hub_runner(runner, monkeypatch):
    """The runner with demo's image in the store and late's missing."""
    made: list = []
    monkeypatch.setattr(
        runner_module, "image_references", lambda: {"ghcr.io/acme/demo@" + HUB_DIGEST}
    )
    monkeypatch.setattr(
        runner_module, "ensure_network", lambda name: made.append(name) or True
    )
    monkeypatch.setattr(
        runner_module,
        "fastest_sources",
        lambda names, sets: (
            {name: sets[name]["sources"][0] for name in names if name in sets},
            {name: sets[name]["variables"] for name in names if name in sets},
        ),
    )
    runner._page_ports._pick = lambda taken: 40123
    runner.made = made
    return runner


def test_a_module_s_containers_are_rendered_once_its_images_are_in_the_store(
    hub_runner,
):
    hub_runner.take_source_sets(
        {
            "pypi": {
                "probe": "/pip/",
                "sources": ["https://p.example"],
                "variables": ["V"],
            }
        }
    )

    hub_runner.apply(HUB_CONFIG)

    rendered, context = FakeRenderer.seen[-1]
    assert [c.name for c in rendered.hub_containers] == ["neutrino_demo"]
    assert hub_runner.made == ["neutrino_demo"]
    assert context.gateways == {"podman": "10.88.0.1", "neutrino_demo": "10.88.0.1"}
    assert context.images == {"neutrino_demo": "ghcr.io/acme/demo@" + HUB_DIGEST}
    assert context.page_ports == {"neutrino_demo": 40123}
    assert context.sources == {"pypi": "https://p.example"}
    assert FakeUnitApplier.applied[-1] == (
        ["neutrino_demo.service", "web.service"],
        ["web", "neutrino_demo"],
    )
    assert hub_runner.hub_names() == {"demo": ["neutrino_demo"]}


def test_the_page_port_is_picked_once_and_kept_in_the_module_s_record(hub_runner):
    hub_runner.apply(HUB_CONFIG)
    hub_runner._page_ports._pick = lambda taken: 50000
    hub_runner.apply(HUB_CONFIG)

    assert FakeRenderer.seen[-1][1].page_ports == {"neutrino_demo": 40123}
    assert hub_runner.page_port("demo", "neutrino_demo") == 40123


def test_the_record_and_the_page_ports_are_under_the_state_root(
    hub_runner, monkeypatch, tmp_path
):
    config_root = tmp_path / "config"
    state_root = tmp_path / "state"
    monkeypatch.setattr(platforms_base_module, "AGENT_DATA_DIR_POSIX", str(config_root))
    monkeypatch.setattr(platforms_base_module, "AGENT_VAR_DIR", str(state_root))
    runner = PodmanModuleRunner(platform=AgentPlatform(), log=lambda m: None)

    runner.apply(HUB_CONFIG)

    assert (state_root / "podman" / "root.json").is_file()
    assert (state_root / "demo" / "page_ports.json").is_file()
    assert not config_root.exists()


def test_the_record_names_the_declared_and_hub_containers_after_a_start(
    hub_runner, tmp_path
):
    hub_runner.apply(HUB_CONFIG)

    restarted = PodmanModuleRunner(platform=AgentPlatform(), log=lambda m: None)

    assert restarted._declared_names() == ["web"]
    assert restarted.hub_names() == {"demo": ["neutrino_demo"]}
    assert restarted.journal_units() == ["podman.socket", "web.service"]


def test_the_module_s_journal_leaves_out_a_container_module_s_units(hub_runner):
    hub_runner.apply(HUB_CONFIG)

    assert hub_runner.journal_units() == ["podman.socket", "web.service"]


def test_dropping_a_module_removes_its_units_and_forgets_it(hub_runner):
    hub_runner.apply(HUB_CONFIG)

    hub_runner.drop_hub_containers("demo")

    assert FakeUnitApplier.removed == [["neutrino_demo"]]
    assert hub_runner.hub_names() == {}
    restarted = PodmanModuleRunner(platform=AgentPlatform(), log=lambda m: None)
    assert restarted.hub_names() == {}
    assert hub_runner._page_ports.ports("demo") == {}


def test_a_refused_declared_container_is_left_out_and_the_rest_applied(hub_runner):
    """A hand-started container with no image, imported by a hub the machine
    joined, leaves the module's containers to be applied."""
    lines: list = []
    hub_runner._log = lines.append
    config = dict(
        HUB_CONFIG,
        containers=[{"name": "r36hand", "image": ""}, *HUB_CONFIG["containers"]],
    )

    with pytest.raises(ModuleApplyError) as refused:
        hub_runner.apply(config)

    assert (refused.value.code, refused.value.params) == (
        "image_invalid",
        {"name": "r36hand", "image": ""},
    )
    assert FakeUnitApplier.applied == [
        (["neutrino_demo.service", "web.service"], ["web", "neutrino_demo"])
    ]
    assert hub_runner._declared_names() == ["web"]
    assert lines[-1] == "podman: containers: web; mirrors updated; left out r36hand"


def test_a_declared_container_named_like_a_hub_container_is_the_one_left_out(
    hub_runner,
):
    config = dict(HUB_CONFIG, containers=[{"name": "neutrino_demo", "image": "x"}])

    with pytest.raises(ModuleApplyError) as refused:
        hub_runner.apply(config)

    assert (refused.value.code, refused.value.params) == (
        "container_name_duplicate",
        {"name": "neutrino_demo"},
    )
    assert FakeUnitApplier.applied == [(["neutrino_demo.service"], ["neutrino_demo"])]


def test_validate_refuses_a_configuration_holding_a_refused_container(runner):
    config = dict(
        CONFIG, containers=[{"name": "r36hand", "image": ""}, *CONFIG["containers"]]
    )

    outcome = runner.command("validate", {"config": config})

    assert (outcome["exit_code"], outcome["code"]) == (1, "image_invalid")


def test_a_module_s_containers_are_applied_once_their_units_are_written(
    hub_runner, monkeypatch
):
    changed = json.loads(json.dumps(HUB_CONFIG))
    changed["hub_containers"][0]["environment"] = ["COOKIE_NAME=new"]

    before = hub_runner.is_applied("demo")
    hub_runner.take_config(HUB_CONFIG)
    hub_runner.apply(HUB_CONFIG)
    applied = hub_runner.is_applied("demo")
    hub_runner.take_config(changed)
    with pytest.raises(ModuleApplyError):
        hub_runner.apply(dict(changed, mirrors=["http://mirror.example"]))

    assert (before, applied) == (True, True)
    assert hub_runner.is_applied("demo") is False
    assert hub_runner.is_applied("late") is False


def test_a_restarted_agent_counts_a_module_s_containers_written_until_its_first_apply(
    hub_runner, monkeypatch
):
    hub_runner.apply(HUB_CONFIG)
    restarted = PodmanModuleRunner(platform=AgentPlatform(), log=lambda m: None)
    restarted.take_config(HUB_CONFIG)

    before = restarted.is_applied("demo")

    def refuse(self, rendered, environments, *, autostart_names, source_keys=None):
        raise subprocess.CalledProcessError(1, ["systemctl"], stderr="bad unit")

    monkeypatch.setattr(FakeUnitApplier, "apply", refuse)
    with pytest.raises(ModuleApplyError):
        restarted.apply(HUB_CONFIG)

    assert before is True
    assert restarted.is_applied("demo") is False


def test_a_container_module_reaches_podman_through_the_runner(runner):
    assert runner.podman_command() == ("/usr/bin/podman",)
    assert runner.is_engine_active() is True
    runner.drive_hub_containers(["neutrino_demo"], "start")
    assert FakeUnitApplier.driven == [(["neutrino_demo"], "start")]
    assert runner.hub_journal(["a", "b"], 5) == ["a", "b", "a", "b"]


def test_a_removed_configuration_forgets_the_record(hub_runner):
    hub_runner.apply(HUB_CONFIG)
    hub_runner.remove_configuration()

    restarted = PodmanModuleRunner(platform=AgentPlatform(), log=lambda m: None)

    assert restarted.hub_names() == {}
    assert restarted._declared_names() == []
