"""The Linux process controller still says to systemd exactly what it said.

Every verb of the controller interface is one ``systemctl`` call on the
unit behind the name, and a start line is the drop-in EasyTier wrote.
"""

import pytest

from neutrino_hub.modules.easytier.renderer import render_dropin
from neutrino_hub.platforms import detect
from neutrino_hub.system import systemd_ctl
from neutrino_hub.system.process_control import ProcessController
from neutrino_hub.system.systemd_ctl import SystemdServiceController, start_line_dropin


class _Result:
    def __init__(self, stdout: str = ""):
        self.stdout = stdout
        self.stderr = ""
        self.is_success = True


@pytest.fixture
def systemctl(monkeypatch):
    """Every command the controller runs, answered as a unit that runs."""
    calls: list = []

    def fake_run(command, **keywords):
        calls.append(list(command))
        return _Result("LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n")

    monkeypatch.setattr(systemd_ctl, "run", fake_run)
    return calls


@pytest.mark.feature("proxy")
@pytest.mark.parametrize("verb", ["start", "stop", "restart", "enable", "disable"])
def test_each_verb_is_the_systemctl_call_it_always_was(systemctl, verb):
    getattr(SystemdServiceController(), verb)("xray")

    assert systemctl == [["systemctl", verb, "neutrino_hub_xray.service"]]


@pytest.mark.parametrize(
    ("name", "unit"),
    [
        ("web", "neutrino_hub_web.service"),
        ("router", "neutrino_hub_router.service"),
        ("dnsmasq", "neutrino_hub_dnsmasq.service"),
        ("cliproxyapi", "neutrino_hub_cliproxyapi.service"),
        pytest.param(
            "netbird",
            "neutrino_hub_netbird.service",
            marks=pytest.mark.feature("netbird"),
        ),
        ("easytier", "neutrino_hub_easytier.service"),
    ],
)
def test_each_name_maps_to_its_unit(systemctl, name, unit):
    SystemdServiceController().control(name, "restart")

    assert systemctl == [["systemctl", "restart", unit]]


def test_is_active_and_is_enabled_read_the_units_properties(systemctl):
    controller = SystemdServiceController()

    assert controller.is_active("web")
    assert controller.is_enabled("web")
    assert systemctl[0][:3] == ["systemctl", "show", "neutrino_hub_web.service"]


def test_reload_is_daemon_reload(systemctl):
    SystemdServiceController().reload()

    assert systemctl == [["systemctl", "daemon-reload"]]


@pytest.mark.feature("netbird")
def test_the_journal_is_journalctl_on_the_unit(systemctl):
    SystemdServiceController().journal("netbird", line_count=7)

    assert systemctl == [
        [
            "journalctl",
            "-u",
            "neutrino_hub_netbird.service",
            "-n",
            "7",
            "--no-pager",
            "--output",
            "short-iso",
        ]
    ]


def test_a_start_line_is_the_drop_in_easytier_wrote(systemctl, monkeypatch, tmp_path):
    monkeypatch.setattr(systemd_ctl, "SYSTEM_SYSTEMD_DIR", tmp_path)
    arguments = [
        "-c",
        "/var/lib/neutrino/hub/generated/easytier.toml",
        "--rpc-portal",
        "x",
    ]

    SystemdServiceController().set_start_line(
        "easytier", ["/opt/neutrino/hub/bin/easytier-core", *arguments], {}, None
    )

    path = tmp_path / "neutrino_hub_easytier.service.d" / "arguments.conf"
    assert path.read_text() == render_dropin(
        arguments, core_path="/opt/neutrino/hub/bin/easytier-core"
    )
    assert systemctl == [["systemctl", "daemon-reload"]]


def test_no_start_line_removes_the_drop_in(systemctl, monkeypatch, tmp_path):
    monkeypatch.setattr(systemd_ctl, "SYSTEM_SYSTEMD_DIR", tmp_path)
    controller = SystemdServiceController()
    controller.set_start_line("easytier", ["/bin/true"], {}, None)

    controller.set_start_line("easytier", None, {}, None)

    assert not (
        tmp_path / "neutrino_hub_easytier.service.d" / "arguments.conf"
    ).exists()


def test_a_start_line_carries_its_environment_and_directory():
    text = start_line_dropin(["/bin/x", "a b"], {"K": "v%"}, "/work")

    assert text == (
        "[Service]\n"
        'Environment="K=v%%"\n'
        "WorkingDirectory=/work\n"
        "ExecStart=\n"
        'ExecStart="/bin/x" "a b"\n'
    )


def test_an_unknown_name_is_refused(systemctl):
    with pytest.raises(KeyError):
        SystemdServiceController().start("samba")
    assert systemctl == []


def test_linux_hands_out_the_systemd_controller_once(monkeypatch):
    monkeypatch.setattr(detect.sys, "platform", "linux")

    controller = detect.process_controller()

    assert isinstance(controller, SystemdServiceController)
    assert isinstance(controller, ProcessController)
    assert detect.process_controller() is controller


def test_the_relay_is_a_unit_of_its_own(systemctl):
    SystemdServiceController().control("relay", "restart")

    assert systemctl == [["systemctl", "restart", "neutrino_hub_relay.service"]]


def test_the_process_id_is_the_units_main_pid(monkeypatch):
    answers = {"MainPID": "4242"}

    def fake_run(command, **keywords):
        return _Result("".join(f"{key}={value}\n" for key, value in answers.items()))

    monkeypatch.setattr(systemd_ctl, "run", fake_run)

    assert SystemdServiceController().process_id("relay") == 4242
    answers["MainPID"] = "0"
    assert SystemdServiceController().process_id("relay") == 0


def test_the_run_output_is_the_last_main_process_lines_alone(monkeypatch):
    calls: list = []

    def fake_run(command, **keywords):
        calls.append(list(command))
        if command[0] == "systemctl":
            return _Result("ExecMainPID=777\n")
        return _Result("Warning: Permanently added\nrelay@vps: Permission denied\n")

    monkeypatch.setattr(systemd_ctl, "run", fake_run)

    lines = SystemdServiceController().run_output("relay", line_count=20)

    assert lines == ["Warning: Permanently added", "relay@vps: Permission denied"]
    assert calls[1] == [
        "journalctl",
        "_SYSTEMD_UNIT=neutrino_hub_relay.service",
        "_PID=777",
        "-n",
        "20",
        "--no-pager",
        "--output",
        "cat",
    ]


def test_a_unit_that_never_ran_has_no_run_output(monkeypatch):
    calls: list = []

    def fake_run(command, **keywords):
        calls.append(list(command))
        return _Result("ExecMainPID=0\n")

    monkeypatch.setattr(systemd_ctl, "run", fake_run)

    assert SystemdServiceController().run_output("relay", line_count=20) == []
    assert [call[0] for call in calls] == ["systemctl"]
