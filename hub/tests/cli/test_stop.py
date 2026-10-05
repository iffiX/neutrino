"""Stopping what the hub runs, and what it deliberately leaves alone."""

import io
import subprocess

import pytest

from neutrino_hub import edition
from neutrino_hub.cli import stop as stop_module

# The proxy core's unit, where the tree carries the proxy.
XRAY = ["xray"] if edition.has_feature("proxy") else []


@pytest.fixture
def systemd(monkeypatch):
    """A systemd that records what it was asked, and answers as told."""
    asked: list = []
    state = {"is_installed": True, "is_active": True, "refusing": ()}

    class Controller:
        def status(self, name):
            return type(
                "Status",
                (),
                {
                    "is_installed": state["is_installed"],
                    "is_active": state["is_active"],
                },
            )()

        def control(self, name, action):
            asked.append((name, action))
            if name in state["refusing"]:
                raise subprocess.TimeoutExpired(["systemctl", "stop", name], 60)

    monkeypatch.setattr(stop_module, "SystemdServiceController", Controller)
    return asked, state


def test_everything_the_hub_runs_is_stopped(systemd):
    asked, _ = systemd

    assert stop_module.stop(list(stop_module.STOP_ORDER)) == 0
    assert [name for name, _ in asked] == list(stop_module.STOP_ORDER)


def test_the_panel_is_stopped_before_what_it_serves(systemd):
    """It is what a person is holding: stopping it while the proxy under it
    is already gone means a page that hangs rather than one that closes."""
    asked, _ = systemd
    stop_module.stop(list(stop_module.STOP_ORDER))

    names = [name for name, _ in asked]
    assert names.index("web") < names.index("dnsmasq")


def test_one_service_can_be_named(systemd):
    asked, _ = systemd

    stop_module.stop(["xray"])

    assert asked == [("xray", "stop")]


def test_every_service_run_starts_can_be_stopped_by_the_same_flag(monkeypatch):
    """The pair is read together, so `--only-web` starts one and `--only-web`
    stops it. A service `run` can start and `stop` cannot name is a box with
    something running that this command claims to have stopped."""
    chosen: list = []
    monkeypatch.setattr(stop_module, "stop", lambda names: chosen.extend(names) or 0)
    monkeypatch.setattr(
        stop_module,
        "stop_engine",
        lambda name, interface: chosen.append(f"{name}@{interface}") or 0,
    )

    for name in ("web", *XRAY, "cliproxyapi", "dnsmasq"):
        monkeypatch.setattr("sys.argv", ["nhub-stop", f"--only-{name}", "--yes"])
        assert stop_module.main() == 0
    for name in ("supplicant", "dhcpcd"):
        monkeypatch.setattr(
            "sys.argv",
            ["nhub-stop", f"--only-{name}", "--interface", "eth0", "--yes"],
        )
        assert stop_module.main() == 0

    assert chosen == [
        "web",
        *XRAY,
        "cliproxyapi",
        "dnsmasq",
        "supplicant@eth0",
        "dhcpcd@eth0",
    ]


def test_a_per_interface_engine_needs_the_interface(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["nhub-stop", "--only-dhcpcd"])

    assert stop_module.main() == 1
    assert "needs --interface" in capsys.readouterr().err


def test_a_per_interface_engine_is_stopped_by_its_own_unit(monkeypatch):
    """A box left holding a lease it asked for has not stopped running the
    hub, whatever the panel is doing."""
    stopped: list = []

    class Engine:
        def __init__(self, *, interface):
            self.unit = f"neutrino_hub_dhcpcd@{interface}.service"

        is_running = True

        def stop(self):
            stopped.append(self.unit)

    monkeypatch.setattr(stop_module, "RouterDhcpClient", Engine)

    assert stop_module.stop_engine("dhcpcd", "enp2s0") == 0
    assert stopped == ["neutrino_hub_dhcpcd@enp2s0.service"]


def test_an_engine_that_was_never_running_is_left_alone(monkeypatch):
    class Engine:
        def __init__(self, *, interface):
            self.unit = "unit"

        is_running = False

        def stop(self):
            raise AssertionError("there was nothing to stop")

    monkeypatch.setattr(stop_module, "RouterWifiClient", Engine)

    assert stop_module.stop_engine("supplicant", "wlp3s0") == 0


def test_the_engines_come_from_the_configuration(monkeypatch):
    """systemd is not asked which templated units exist; `config/` is the
    record of which interfaces the hub was driving."""
    monkeypatch.setattr(
        stop_module,
        "read_config",
        lambda name: {"mode": "router", "interfaces": [{"name": "enp2s0"}]},
    )

    assert stop_module._configured_engines() == [
        ("supplicant", "enp2s0"),
        ("dhcpcd", "enp2s0"),
    ]


def test_a_box_with_no_configuration_left_has_no_engines(monkeypatch):
    def missing(name):
        raise FileNotFoundError(name)

    monkeypatch.setattr(stop_module, "read_config", missing)

    assert stop_module._configured_engines() == []


def test_the_optional_modules_are_left_running(systemd):
    """Samba serves shares whether or not this box routes anything, so a
    plain stop is the hub going quiet rather than the machine going down."""
    asked, _ = systemd
    stop_module.stop(list(stop_module.STOP_ORDER))

    stopped = {name for name, _ in asked}
    assert stopped.isdisjoint({"samba", "gitea", "netbird", "podman", "zfs"})


def test_a_unit_this_box_does_not_have_is_not_asked_about(systemd):
    asked, state = systemd
    state["is_installed"] = False

    assert stop_module.stop(list(stop_module.STOP_ORDER)) == 0
    assert asked == []


def test_what_is_already_stopped_is_left_alone(systemd):
    asked, state = systemd
    state["is_active"] = False

    assert stop_module.stop(list(stop_module.STOP_ORDER)) == 0
    assert asked == []


def test_one_refusal_does_not_stop_the_rest(systemd):
    """A unit that will not stop must not hide what happened to the others."""
    asked, state = systemd
    state["refusing"] = ("dnsmasq",)

    assert stop_module.stop(list(stop_module.STOP_ORDER)) == 1
    assert [name for name, _ in asked] == list(stop_module.STOP_ORDER)


def test_macos_and_windows_stop_the_hubs_one_service(hub_service, monkeypatch):
    hub_service.is_running = True
    monkeypatch.setattr(stop_module.sys, "argv", ["nhub stop", "--yes"])

    assert stop_module.main() == 0
    assert not hub_service.is_running


def test_a_stopped_service_is_not_stopped_again(hub_service, capsys):
    assert stop_module.stop_everything() == 0
    assert "already stopped" in capsys.readouterr().out


def test_a_service_that_will_not_stop_says_so(hub_service, capsys):
    hub_service.is_running = True
    hub_service.is_refusing = True

    assert stop_module.stop_service() == 1
    assert "did not stop" in capsys.readouterr().err


def test_one_daemon_cannot_be_named_outside_linux(hub_service, monkeypatch, capsys):
    hub_service.is_running = True
    monkeypatch.setattr(stop_module.sys, "argv", ["nhub stop", "--only-web"])

    assert stop_module.main() == 2
    assert hub_service.is_running


def refuse_to_ask(prompt):
    raise AssertionError("asked with no terminal")


def recorded_stops(monkeypatch) -> list:
    chosen: list = []
    monkeypatch.setattr(stop_module, "stop", lambda names: chosen.extend(names) or 0)
    monkeypatch.setattr(
        stop_module, "stop_everything", lambda: chosen.append("everything") or 0
    )
    return chosen


def test_it_asks_first_and_a_no_stops_nothing(terminal, monkeypatch):
    chosen = recorded_stops(monkeypatch)
    questions: list = []
    monkeypatch.setattr(
        "builtins.input", lambda prompt: questions.append(prompt) or "n"
    )
    monkeypatch.setattr("sys.argv", ["nhub-stop"])

    assert stop_module.main() == 1
    assert questions == ["Stop the hub's units? [y/N] "]
    assert chosen == []


def test_a_yes_at_the_prompt_stops_everything(terminal, monkeypatch):
    chosen = recorded_stops(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr("sys.argv", ["nhub-stop"])

    assert stop_module.main() == 0
    assert chosen == ["everything"]


def test_yes_on_the_command_line_stops_without_asking(monkeypatch):
    chosen = recorded_stops(monkeypatch)
    monkeypatch.setattr("builtins.input", refuse_to_ask)
    monkeypatch.setattr("sys.argv", ["nhub-stop", "--only-web", "--yes"])

    assert stop_module.main() == 0
    assert chosen == ["web"]


def test_with_no_terminal_it_names_yes_and_stops_nothing(monkeypatch, capsys):
    chosen = recorded_stops(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("builtins.input", refuse_to_ask)
    monkeypatch.setattr("sys.argv", ["nhub-stop"])

    assert stop_module.main() == 1
    assert chosen == []
    error = capsys.readouterr().err
    assert error.strip().count("\n") == 0
    assert "--yes" in error
