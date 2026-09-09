"""The container applier's effects, with podman and systemd replaced."""

import pytest

from neutrino_agent.modules.podman import applier as applier_module
from neutrino_agent.modules.podman.applier import (
    PodmanContainerController,
    PodmanRegistriesApplier,
    PodmanStatusReader,
    PodmanUnitApplier,
    container_applier,
    is_quadlet_supported,
    is_version_at_least,
    journal_lines,
)
from neutrino_agent.modules.podman.constants import (
    PODMAN_GENERATED_MARKER,
    PODMAN_QUADLET_DIR,
    PODMAN_UNIT_DIR,
)
from neutrino_agent.modules.subprocess_run import CommandError, CommandResult


class FakeCommands:
    def __init__(self, answers=None):
        self.calls: list = []
        self.answers = dict(answers or {})

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        answer = self.answers.get(tuple(command[:2]), (0, ""))
        if isinstance(answer, Exception):
            raise answer
        exit_code, stdout = answer
        if is_checked and exit_code != 0:
            raise CommandError(command, "refused")
        return CommandResult(list(command), exit_code, stdout, "")


@pytest.fixture
def commands(monkeypatch):
    held = FakeCommands()
    monkeypatch.setattr(applier_module, "run", held)
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "inactive")
    return held


def test_version_comparison_reads_distribution_suffixes():
    assert is_version_at_least("4.3.1+ds1-8+deb12u1+b3", "4.4") is False
    assert is_version_at_least("4.9.4-rhel", "4.4") is True
    assert is_version_at_least("5.0", "4.4") is True
    assert is_version_at_least("", "4.4") is False


def test_the_version_line_podman_prints_decides_which_applier(commands):
    commands.answers[("/usr/bin/podman", "--version")] = (0, "podman version 3.4.4\n")
    assert is_quadlet_supported() is False
    assert container_applier().directory == PODMAN_UNIT_DIR

    commands.answers[("/usr/bin/podman", "--version")] = (
        0,
        "podman version 4.9.4-rhel\n",
    )
    assert is_quadlet_supported() is True
    assert container_applier().directory == PODMAN_QUADLET_DIR


def test_a_podman_that_will_not_run_gets_the_unit_that_works_everywhere(commands):
    commands.answers[("/usr/bin/podman", "--version")] = CommandError(
        ["podman"], "gone"
    )

    assert is_quadlet_supported() is False


def rendered(name: str, body: str = "x") -> str:
    return f"{PODMAN_GENERATED_MARKER}\n[Container]\n{body}\n"


def test_apply_writes_changed_files_drops_stale_ones_and_restarts(commands, tmp_path):
    directory = tmp_path / "systemd"
    directory.mkdir()
    (directory / "old.container").write_text(rendered("old"))
    (directory / "keep.container").write_text(rendered("keep"))
    (directory / "hand.container").write_text("[Container]\nmine\n")
    applier = PodmanUnitApplier(directory=str(directory), suffix=".container")

    note = applier.apply(
        {"keep.container": rendered("keep"), "web.container": rendered("web")},
        autostart_names=["web"],
    )

    assert "web.container" in note and "-old.container" in note
    assert not (directory / "old.container").exists()
    assert (directory / "hand.container").exists()
    assert ["systemctl", "disable", "--now", "old.service"] in commands.calls
    assert ["systemctl", "daemon-reload"] in commands.calls
    assert ["systemctl", "restart", "web.service"] in commands.calls
    assert ["systemctl", "restart", "keep.service"] not in commands.calls


def test_a_changed_non_autostart_container_restarts_only_if_running(
    commands, tmp_path, monkeypatch
):
    directory = tmp_path / "systemd"
    applier = PodmanUnitApplier(directory=str(directory), suffix=".service")

    applier.apply({"web.service": rendered("web")}, autostart_names=[])
    assert ["systemctl", "restart", "web.service"] not in commands.calls

    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "active")
    applier.apply({"web.service": rendered("web", "changed")}, autostart_names=[])
    assert ["systemctl", "restart", "web.service"] in commands.calls


def test_stop_all_takes_down_every_generated_unit_and_keeps_the_files(
    commands, tmp_path
):
    directory = tmp_path / "systemd"
    directory.mkdir()
    (directory / "web.container").write_text(rendered("web"))
    (directory / "hand.container").write_text("[Container]\nmine\n")

    PodmanUnitApplier(directory=str(directory), suffix=".container").stop_all()

    assert commands.calls == [["systemctl", "disable", "--now", "web.service"]]
    assert (directory / "web.container").exists()


def test_the_mirror_drop_in_is_written_and_removed(tmp_path, monkeypatch):
    path = tmp_path / "registries.conf.d/mirrors.conf"
    monkeypatch.setattr(applier_module, "PODMAN_REGISTRIES_CONF_PATH", str(path))
    applier = PodmanRegistriesApplier()

    assert applier.apply("[[registry]]\n") == "mirrors updated"
    assert path.read_text() == "[[registry]]\n"
    assert applier.apply("[[registry]]\n") == "mirrors unchanged"
    assert applier.apply("") == "mirrors removed"
    assert not path.exists()
    assert applier.apply("") == "no mirrors"


def test_a_declared_but_never_started_container_still_appears(commands):
    commands.answers[("/usr/bin/podman", "ps")] = (
        0,
        '[{"Names": ["webdav"], "Image": "nginx", "Status": "Up", "State": "running", '
        '"Ports": [{"host_port": 8081}]}]',
    )

    states = PodmanStatusReader().survey(declared_names=["webdav", "python"])

    by_name = {state.name: state for state in states}
    assert by_name["python"].status == "not created yet"
    assert by_name["python"].is_declared is True
    assert by_name["webdav"].is_running is True
    assert by_name["webdav"].host_ports == [8081]


def test_no_podman_surveys_as_nothing(commands):
    commands.answers[("/usr/bin/podman", "ps")] = CommandError(["podman"], "gone")

    assert PodmanStatusReader().survey(declared_names=["x"]) == []


def test_each_container_is_driven_through_its_rightful_owner(commands):
    controller = PodmanContainerController()

    controller.control("web", "restart", is_declared=True)
    controller.control("adhoc", "stop", is_declared=False)

    assert ["systemctl", "restart", "web.service"] in commands.calls
    assert ["/usr/bin/podman", "stop", "adhoc"] in commands.calls


def test_an_action_outside_the_list_is_refused():
    with pytest.raises(ValueError):
        PodmanContainerController().control("web", "rm", is_declared=True)


def test_the_journal_is_read_by_unit(commands):
    commands.answers[("journalctl", "-u")] = (0, "one\ntwo\n")

    assert journal_lines("web", 50) == ["one", "two"]
    assert [
        "journalctl",
        "-u",
        "web.service",
        "-n",
        "50",
        "--no-pager",
        "--output",
        "short-iso",
    ] in commands.calls
