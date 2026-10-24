"""The container applier's effects, with podman and systemd replaced."""

import subprocess

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
from neutrino_agent.modules.podman.config import PORT_MAPPING_PATTERN
from neutrino_agent.modules.podman.constants import (
    PODMAN_GENERATED_MARKER,
    PODMAN_QUADLET_DIR,
    PODMAN_UNIT_DIR,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult


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
            raise subprocess.CalledProcessError(
                exit_code, list(command), stderr="refused"
            )
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
    commands.answers[("/usr/bin/podman", "--version")] = subprocess.CalledProcessError(
        1, ["podman"], stderr="gone"
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

    assert commands.calls == [["systemctl", "stop", "web.service"]]
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


def test_each_host_port_is_bound_with_its_address_and_protocol(commands):
    """TCP and UDP alike; a port podman names no protocol for is TCP, and
    one on any other protocol is no binding."""
    commands.answers[("/usr/bin/podman", "ps")] = (
        0,
        '[{"Names": ["db"], "Image": "postgres", "Status": "Up", "State": "running", '
        '"Ports": [{"host_ip": "192.168.1.5", "host_port": 5432, "protocol": "tcp"}, '
        '{"host_ip": "", "host_port": 8080}, '
        '{"host_ip": "", "host_port": 5353, "protocol": "udp"}, '
        '{"host_ip": "", "host_port": 53, "protocol": "tcp"}, '
        '{"host_ip": "", "host_port": 53, "protocol": "udp"}, '
        '{"host_ip": "", "host_port": 9899, "protocol": "sctp"}]}]',
    )

    (state,) = PodmanStatusReader().survey(declared_names=[])

    assert state.host_bindings == [
        {"address": "192.168.1.5", "port": 5432, "protocol": "tcp", "detected": ""},
        {"address": "", "port": 8080, "protocol": "tcp", "detected": ""},
        {"address": "", "port": 5353, "protocol": "udp", "detected": ""},
        {"address": "", "port": 53, "protocol": "tcp", "detected": ""},
        {"address": "", "port": 53, "protocol": "udp", "detected": ""},
    ]
    assert state.host_ports == [53, 5353, 5432, 8080, 9899]


SURVEYED = (
    '[{"Names": ["web"], "Image": "nginx", "Status": "Up", "State": "running", '
    '"Ports": [{"host_ip": "127.0.0.1", "host_port": 8080, "protocol": "tcp"}, '
    '{"host_ip": "::", "host_port": 8080, "protocol": "tcp"}]}]'
)
INSPECTED = (
    '[{"Name": "web", "Mounts": [{"Source": "/mnt/c/data", "Destination": "/data"}, '
    '{"Name": "cache", "Destination": "/cache"}]}]'
)


def test_the_reader_by_default_asks_this_machines_podman_as_before(
    commands, monkeypatch
):
    """The machine's own podman for both reads, its unit directories for the
    unit, and every binding's address and mount's source as podman names
    them."""
    commands.answers[("/usr/bin/podman", "ps")] = (0, SURVEYED)
    commands.answers[("/usr/bin/podman", "inspect")] = (0, INSPECTED)

    def has_unit_file(name):
        return name == "web"

    monkeypatch.setattr(applier_module, "has_unit_file", has_unit_file)

    (state,) = PodmanStatusReader().survey(declared_names=["web"])

    assert commands.calls == [
        ["/usr/bin/podman", "ps", "-a", "--format", "json"],
        ["/usr/bin/podman", "inspect", "--type", "container", "web"],
    ]
    assert state.has_unit is True
    assert state.host_bindings == [
        {"address": "127.0.0.1", "port": 8080, "protocol": "tcp", "detected": ""},
        {"address": "::", "port": 8080, "protocol": "tcp", "detected": ""},
    ]
    assert state.volumes == ["/mnt/c/data:/data", "cache:/cache"]


PODMAN_MACHINE = (
    "podman.exe",
    "--url",
    "ssh://root@127.0.0.1:50123/run/podman/podman.sock",
)


def test_a_reader_given_its_podman_command_reads_a_podman_machine(monkeypatch):
    """Both reads through the command given, the unit by the check given,
    every binding on every address, and each mount's source turned back
    into the computer's own form."""
    calls = []
    asked_units = []

    def run(command, *, is_checked=True, input_text=None, timeout_s=120):
        calls.append(list(command))
        stdout = SURVEYED if command[len(PODMAN_MACHINE)] == "ps" else INSPECTED
        return CommandResult(list(command), 0, stdout, "")

    def has_unit(name):
        asked_units.append(name)
        return False

    def host_volume(source):
        return "C:\\data" if source == "/mnt/c/data" else source

    monkeypatch.setattr(applier_module, "run", run)
    reader = PodmanStatusReader(
        podman=PODMAN_MACHINE,
        has_unit=has_unit,
        is_address_kept=False,
        host_volume=host_volume,
    )

    (state,) = reader.survey(declared_names=[])

    assert calls == [
        [*PODMAN_MACHINE, "ps", "-a", "--format", "json"],
        [*PODMAN_MACHINE, "inspect", "--type", "container", "web"],
    ]
    assert asked_units == ["web"]
    assert state.has_unit is False
    assert state.host_bindings == [
        {"address": "", "port": 8080, "protocol": "tcp", "detected": ""}
    ]
    assert state.volumes == ["C:\\data:/data", "cache:/cache"]


def test_the_version_is_asked_of_the_podman_command_given(commands):
    commands.answers[("/usr/bin/podman", "--version")] = (0, "podman version 4.9.3\n")
    commands.answers[("podman.exe", "--url")] = (0, "podman.exe version 6.1.4\n")

    assert applier_module.podman_version() == "4.9.3"
    assert applier_module.podman_version(podman=("podman.exe", "--url", "u")) == (
        "6.1.4"
    )
    assert commands.calls == [
        ["/usr/bin/podman", "--version"],
        ["podman.exe", "--url", "u", "--version"],
    ]


def test_no_podman_surveys_as_nothing(commands):
    commands.answers[("/usr/bin/podman", "ps")] = subprocess.CalledProcessError(
        1, ["podman"], stderr="gone"
    )

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


def test_the_inspected_ports_keep_their_protocol_as_the_configuration_writes_it():
    """The same number on both protocols reads back as two ports, the UDP one
    with ``/udp``, so an imported container keeps what it publishes."""
    detail = {
        "HostConfig": {
            "PortBindings": {
                "53/udp": [{"HostIp": "", "HostPort": "5353"}],
                "53/tcp": [{"HostIp": "", "HostPort": "5353"}],
                "80": [{"HostIp": "", "HostPort": "8080"}],
                "9899/sctp": [{"HostIp": "", "HostPort": "9899"}],
            }
        }
    }

    ports = applier_module._inspected_ports(detail)

    assert ports == ["5353:53", "5353:53/udp", "8080:80"]
    for port in ports:
        assert PORT_MAPPING_PATTERN.match(port)


class RecordingProbe:
    """Answers ``https`` for every port it is asked about, and records them."""

    def __init__(self):
        self.asked: list = []

    def detected(self, targets):
        self.asked.append(list(targets))
        return {key: "https" for key, _, _ in targets}


def test_the_probe_is_asked_for_each_tcp_binding_of_a_running_container(commands):
    """Keyed by the container's id, its start and the binding; a UDP binding
    and a stopped container are never probed, and a binding on one address
    is probed there."""
    commands.answers[("/usr/bin/podman", "ps")] = (
        0,
        '[{"Id": "aa", "StartedAt": 1700000000, "Names": ["web"], "Image": "nginx", '
        '"Status": "Up", "State": "running", '
        '"Ports": [{"host_ip": "", "host_port": 8080, "protocol": "tcp"}, '
        '{"host_ip": "192.168.1.5", "host_port": 8443, "protocol": "tcp"}, '
        '{"host_ip": "0.0.0.0", "host_port": 9000, "protocol": "tcp"}, '
        '{"host_ip": "", "host_port": 5353, "protocol": "udp"}]}, '
        '{"Id": "bb", "StartedAt": 1700000001, "Names": ["old"], "Image": "nginx", '
        '"Status": "Exited", "State": "exited", '
        '"Ports": [{"host_ip": "", "host_port": 8081, "protocol": "tcp"}]}]',
    )
    probe = RecordingProbe()

    old, web = PodmanStatusReader(probe=probe).survey(declared_names=[])

    assert probe.asked == [
        [
            (("aa", "1700000000", "", 8080), "127.0.0.1", 8080),
            (("aa", "1700000000", "192.168.1.5", 8443), "192.168.1.5", 8443),
            (("aa", "1700000000", "0.0.0.0", 9000), "127.0.0.1", 9000),
        ]
    ]
    assert [binding["detected"] for binding in web.host_bindings] == [
        "https",
        "https",
        "https",
        "",
    ]
    assert old.host_bindings[0]["detected"] == ""
