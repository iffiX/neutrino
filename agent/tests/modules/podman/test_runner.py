"""The container engine runner: validate, apply, stop, verbs, and what it observes.

What these pin beside the verbs: ``observe()`` reads the binary, the unit
and the details in one go, and each container's details are what
``podman ps -a --format json`` and ``podman inspect`` say, image, ports,
volumes, environment and whether a unit stands for it, so containers
somebody started by hand are reported the way the hub imports them.
"""

import json
import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules import system_package as system_package_module
from neutrino_agent.modules.podman import applier as applier_module
from neutrino_agent.modules.podman import runner as runner_module
from neutrino_agent.modules.podman.applier import PodmanContainerState
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.modules.subprocess_run import CommandResult
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

    def apply(self, rendered, *, autostart_names):
        FakeUnitApplier.applied.append((sorted(rendered), autostart_names))
        return "containers: web"

    def stop_all(self):
        FakeUnitApplier.stops += 1


class FakeRegistries:
    written: list = []

    def apply(self, rendered):
        FakeRegistries.written.append(rendered)
        return "mirrors updated"


class FakeReader:
    def survey(self, *, declared_names):
        return [
            PodmanContainerState(
                "web", "nginx", "Up", True, "web" in declared_names, [8080]
            ),
            PodmanContainerState("adhoc", "alpine", "Exited", False, False, []),
        ]


class FakeController:
    calls: list = []
    error = None

    def control(self, name, action, *, is_declared):
        if FakeController.error is not None:
            raise FakeController.error
        FakeController.calls.append((name, action, is_declared))


@pytest.fixture
def runner(monkeypatch):
    FakeUnitApplier.applied = []
    FakeUnitApplier.stops = 0
    FakeRegistries.written = []
    FakeController.calls = []
    FakeController.error = None
    monkeypatch.setattr(runner_module, "container_applier", FakeUnitApplier)
    monkeypatch.setattr(runner_module, "PodmanRegistriesApplier", FakeRegistries)
    monkeypatch.setattr(runner_module, "PodmanStatusReader", FakeReader)
    monkeypatch.setattr(runner_module, "PodmanContainerController", FakeController)
    monkeypatch.setattr(runner_module, "podman_version", lambda: "4.9.3")
    monkeypatch.setattr(runner_module, "unit_state", lambda unit: "active")
    monkeypatch.setattr(runner_module, "journal_lines", lambda name, lines: ["a", "b"])
    monkeypatch.setattr(
        runner_module,
        "container_renderer",
        lambda config: type("R", (), {"render": lambda self: {"web.container": "x"}})(),
    )
    return PodmanModuleRunner(platform=AgentPlatform(), log=lambda m: None)


def test_validate_refuses_typed(runner):
    with pytest.raises(ModuleApplyError) as refused:
        runner.validate({"containers": [{"name": "Bad", "image": "x"}]})

    assert refused.value.code == "container_name_invalid"


def test_apply_renders_the_units_and_the_mirrors(runner):
    runner.apply(CONFIG)

    assert FakeUnitApplier.applied == [(["web.container"], ["web"])]
    assert 'location = "mirror.example"' in FakeRegistries.written[0]


def test_a_refused_apply_is_typed(runner, monkeypatch):
    def refuse(self, rendered, *, autostart_names):
        raise subprocess.CalledProcessError(1, ["systemctl"], stderr="bad unit")

    monkeypatch.setattr(FakeUnitApplier, "apply", refuse)

    with pytest.raises(ModuleApplyError) as refused:
        runner.apply(CONFIG)

    assert refused.value.code == "apply_failed"


def test_stop_takes_every_declared_container_down(runner):
    runner.stop()

    assert FakeUnitApplier.stops == 1


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

    def start(self, rendered, *, autostart_names):
        seen.append(runner.details({})["containers"])

    monkeypatch.setattr(FakeUnitApplier, "apply", start)

    runner.apply(CONFIG)

    assert [c["name"] for c in seen[0] if c["is_declared"]] == ["web"]


def test_details_separate_declared_from_ad_hoc(runner):
    runner.apply(CONFIG)

    details = runner.details({})

    by_name = {c["name"]: c for c in details["containers"]}
    assert by_name["web"]["is_declared"] is True
    assert by_name["web"]["host_ports"] == [8080]
    assert by_name["adhoc"]["is_declared"] is False
    assert details["mirrors"] == ["mirror.example"]
    assert details["version"] == "4.9.3"
    assert details["is_active"] is True


def test_control_drives_a_known_container_and_refuses_an_unknown(runner):
    runner.apply(CONFIG)

    good = runner.command("control", {"name": "web", "action": "restart"})
    ghost = runner.command("control", {"name": "ghost", "action": "start"})
    verb = runner.command("control", {"name": "web", "action": "rm"})

    assert good["exit_code"] == 0
    assert FakeController.calls == [("web", "restart", True)]
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


def test_observe_reads_what_podman_itself_says_of_each_container(runner, monkeypatch):
    asked = podman_commands(monkeypatch)

    observed = runner.observe({})

    assert (observed["is_installed"], observed["is_active"]) == (True, True)
    details = observed["details"]
    assert set(details) == {"containers", "mirrors", "version", "is_active"}
    assert details["version"] == "4.9.3"
    by_name = {container["name"]: container for container in details["containers"]}
    assert by_name["web"] == {
        "name": "web",
        "image": "docker.io/library/nginx:1.27",
        "status": "Up 2 hours",
        "is_running": True,
        "is_declared": False,
        "host_ports": [8080],
        "ports": ["8080:80"],
        "volumes": [
            "/srv/web:/usr/share/nginx/html",
            "/var/lib/containers/storage/volumes/webdata/_data:/data",
        ],
        "environment": [
            "PATH=/usr/sbin:/usr/bin",
            "NGINX_VERSION=1.27.0",
            "container=podman",
        ],
        "has_unit": True,
    }
    assert by_name["adhoc"]["is_running"] is False
    assert by_name["adhoc"]["ports"] == []
    assert by_name["adhoc"]["volumes"] == []
    assert by_name["adhoc"]["has_unit"] is False
    # One inspect for every listed container, never one per container.
    assert [c for c in asked if c[1] == "inspect"] == [
        [applier_module.PODMAN_BINARY, "inspect", "--type", "container", "web", "adhoc"]
    ]


def test_observe_marks_the_containers_the_hub_declares(runner, monkeypatch):
    podman_commands(monkeypatch)
    runner.apply(CONFIG)

    by_name = {c["name"]: c for c in runner.observe({})["details"]["containers"]}

    assert by_name["web"]["is_declared"] is True
    assert by_name["adhoc"]["is_declared"] is False


def test_removing_the_configuration_drops_the_units_and_the_mirrors(
    runner, monkeypatch, tmp_path
):
    units = tmp_path / "systemd"
    units.mkdir()
    (units / "web.container").write_text(
        applier_module.PODMAN_GENERATED_MARKER + "\n[Container]\n"
    )
    (units / "theirs.container").write_text("[Container]\n")
    mirrors = tmp_path / "99_neutrino_mirrors.conf"
    mirrors.write_text("[[registry]]")
    monkeypatch.setattr(applier_module, "PODMAN_REGISTRIES_CONF_PATH", str(mirrors))
    monkeypatch.setattr(runner_module, "run", lambda command, **kwargs: None)
    monkeypatch.setattr(
        runner_module, "PodmanRegistriesApplier", applier_module.PodmanRegistriesApplier
    )
    monkeypatch.setattr(
        runner_module,
        "container_applier",
        lambda: applier_module.PodmanUnitApplier(
            directory=str(units), suffix=".container"
        ),
    )
    monkeypatch.setattr(applier_module, "run", lambda command, **kwargs: None)

    runner.remove_configuration()

    assert sorted(path.name for path in units.iterdir()) == ["theirs.container"]
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
