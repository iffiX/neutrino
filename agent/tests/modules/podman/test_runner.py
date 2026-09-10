"""The container engine runner: validate, apply, stop, details, commands."""

import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.podman import runner as runner_module
from neutrino_agent.modules.podman.applier import PodmanContainerState
from neutrino_agent.modules.podman.runner import PodmanModuleRunner
from neutrino_agent.platforms.base import AgentPlatform

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

    good = runner.command("podman_control", {"name": "web", "action": "restart"})
    ghost = runner.command("podman_control", {"name": "ghost", "action": "start"})
    verb = runner.command("podman_control", {"name": "web", "action": "rm"})

    assert good["exit_code"] == 0
    assert FakeController.calls == [("web", "restart", True)]
    assert ghost["code"] == "container_unknown"
    assert verb["code"] == "unsupported_action"


def test_a_bad_name_never_reaches_a_command(runner):
    outcome = runner.command("podman_journal", {"name": "../etc"})

    assert outcome["code"] == "container_name_invalid"


def test_a_refused_control_is_typed(runner):
    FakeController.error = subprocess.CalledProcessError(
        1, ["systemctl"], stderr="will not start"
    )

    outcome = runner.command("podman_control", {"name": "web", "action": "start"})

    assert outcome["code"] == "command_failed"


def test_the_journal_streams_its_lines_and_carries_them_in_the_output(runner):
    lines: list = []

    outcome = runner.command("podman_journal", {"name": "web"}, lines.append)

    assert lines == ["a", "b"]
    assert outcome["output"] == "a\nb"
    assert outcome["exit_code"] == 0
