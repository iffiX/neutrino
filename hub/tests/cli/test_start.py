"""Starting the hub's units, as the pair of ``nhub stop``."""

import subprocess

import pytest

from neutrino_hub.cli import entry
from neutrino_hub.cli import start as start_module
from neutrino_hub.cli import stop as stop_module


@pytest.fixture
def systemd(monkeypatch):
    """A systemd that records what it was asked, and answers as told."""
    asked: list = []
    state = {
        "is_installed": True,
        "is_active": False,
        "disabled": (),
        "refusing": (),
    }

    class Controller:
        def status(self, name):
            return type(
                "Status",
                (),
                {
                    "is_installed": state["is_installed"],
                    "is_active": state["is_active"],
                    "is_enabled": name not in state["disabled"],
                },
            )()

        def control(self, name, action):
            asked.append((name, action))
            if name in state["refusing"]:
                raise subprocess.TimeoutExpired(["systemctl", "start", name], 60)

    monkeypatch.setattr(start_module, "SystemdServiceController", Controller)
    return asked, state


def test_every_enabled_unit_starts_in_the_reverse_of_the_stop_order(systemd):
    asked, _ = systemd

    assert start_module.start(list(start_module.START_ORDER), is_enabled_only=True) == 0
    assert [name for name, _ in asked] == list(reversed(stop_module.STOP_ORDER))
    assert {action for _, action in asked} == {"start"}


def test_the_routing_state_starts_before_the_panel(systemd):
    asked, _ = systemd
    start_module.start(list(start_module.START_ORDER), is_enabled_only=True)

    names = [name for name, _ in asked]
    assert names.index("router") < names.index("web")


def test_a_unit_boot_would_not_start_is_left_alone(systemd):
    asked, state = systemd
    state["disabled"] = ("cliproxyapi",)

    start_module.start(list(start_module.START_ORDER), is_enabled_only=True)

    assert "cliproxyapi" not in [name for name, _ in asked]


def test_one_unit_named_starts_even_when_it_is_not_enabled(systemd):
    asked, state = systemd
    state["disabled"] = ("cliproxyapi",)

    start_module.start(["cliproxyapi"], is_enabled_only=False)

    assert asked == [("cliproxyapi", "start")]


def test_a_running_unit_is_left_running(systemd, capsys):
    asked, state = systemd
    state["is_active"] = True

    assert start_module.start(["xray"], is_enabled_only=False) == 0
    assert asked == []
    assert "xray: already running" in capsys.readouterr().out


def test_a_unit_that_will_not_start_does_not_hide_the_others(systemd, capsys):
    asked, state = systemd
    state["refusing"] = ("xray",)

    code = start_module.start(list(start_module.START_ORDER), is_enabled_only=True)

    assert code == 1
    assert [name for name, _ in asked] == list(start_module.START_ORDER)
    assert "xray: did not start" in capsys.readouterr().err


def test_every_service_stop_can_name_start_can_name(monkeypatch):
    """The pair is read together: `--only-web` stops one and `--only-web`
    starts it."""
    chosen: list = []
    monkeypatch.setattr(
        start_module,
        "start",
        lambda names, *, is_enabled_only: chosen.extend(names) or 0,
    )
    monkeypatch.setattr(
        start_module,
        "start_engine",
        lambda name, interface: chosen.append(f"{name}@{interface}") or 0,
    )

    for name in stop_module.STOP_ORDER:
        monkeypatch.setattr("sys.argv", ["nhub-start", f"--only-{name}", "--yes"])
        assert start_module.main() == 0
    for name in stop_module.STOP_PER_INTERFACE:
        monkeypatch.setattr(
            "sys.argv",
            ["nhub-start", f"--only-{name}", "--interface", "eth0", "--yes"],
        )
        assert start_module.main() == 0

    assert chosen == list(stop_module.STOP_ORDER) + [
        "supplicant@eth0",
        "dhcpcd@eth0",
    ]


def test_it_asks_first_and_a_no_starts_nothing(monkeypatch):
    chosen: list = []
    monkeypatch.setattr(
        start_module,
        "start",
        lambda names, *, is_enabled_only: chosen.extend(names) or 0,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    monkeypatch.setattr("sys.argv", ["nhub-start"])

    assert start_module.main() == 1
    assert chosen == []


def test_a_yes_at_the_prompt_starts_every_enabled_unit(monkeypatch):
    chosen: list = []
    monkeypatch.setattr(
        start_module,
        "start",
        lambda names, *, is_enabled_only: chosen.append((names, is_enabled_only)) or 0,
    )
    questions: list = []
    monkeypatch.setattr(
        "builtins.input", lambda prompt: questions.append(prompt) or "y"
    )
    monkeypatch.setattr("sys.argv", ["nhub-start"])

    assert start_module.main() == 0
    assert questions == ["Start the hub's units? [y/N] "]
    assert chosen == [(list(start_module.START_ORDER), True)]


def test_a_per_interface_engine_needs_the_interface(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["nhub-start", "--only-dhcpcd", "--yes"])

    assert start_module.main() == 1
    assert "needs --interface" in capsys.readouterr().err


def test_a_per_interface_engine_is_started_by_its_own_unit(monkeypatch):
    started: list = []

    class Engine:
        def __init__(self, *, interface):
            self.unit = f"neutrino_hub_supplicant@{interface}.service"

        is_running = False

        def start(self):
            started.append(self.unit)

    monkeypatch.setattr(start_module, "RouterWifiClient", Engine)

    assert start_module.start_engine("supplicant", "wlp3s0") == 0
    assert started == ["neutrino_hub_supplicant@wlp3s0.service"]


def test_an_engine_already_running_is_left_alone(monkeypatch):
    class Engine:
        def __init__(self, *, interface):
            self.unit = f"neutrino_hub_dhcpcd@{interface}.service"

        is_running = True

        def start(self):
            raise AssertionError("started twice")

    monkeypatch.setattr(start_module, "RouterDhcpClient", Engine)

    assert start_module.start_engine("dhcpcd", "enp2s0") == 0


def test_start_is_a_subcommand_beside_stop_and_run_says_what_it_is():
    assert "start" in entry.COMMANDS
    assert "stop" in entry.COMMANDS
    assert "the units" in entry.COMMANDS["run"][1]


def test_macos_and_windows_start_the_hubs_one_service(hub_service, monkeypatch):
    monkeypatch.setattr(start_module.sys, "argv", ["nhub start", "--yes"])

    assert start_module.main() == 0
    assert hub_service.is_running


def test_a_running_service_is_left_as_it_is(hub_service, capsys):
    hub_service.is_running = True

    assert start_module.start_service() == 0
    assert "already running" in capsys.readouterr().out


def test_a_service_that_will_not_start_says_so(hub_service, capsys):
    hub_service.is_refusing = True

    assert start_module.start_service() == 1
    assert "did not start" in capsys.readouterr().err


def test_the_only_flags_are_linuxs(hub_service, monkeypatch, capsys):
    monkeypatch.setattr(start_module.sys, "argv", ["nhub start", "--only-xray"])

    assert start_module.main() == 2
    assert "systemd unit" in capsys.readouterr().err
    assert not hub_service.is_running
