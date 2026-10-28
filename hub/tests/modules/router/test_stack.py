"""The hand-back starts again every manager the takeover stood down. It
leaves the system's dhcpcd unit disabled when the hub's own dependency
installed it."""

import json

import pytest

from neutrino_hub.modules.router import stack
from neutrino_hub.utils.subprocess_run import CommandResult

UNIT_PATH = "/lib/systemd/system/dhcpcd.service"


class Machine:
    """A machine's apt marks and file lists, recording every command run."""

    def __init__(self, *, auto=(), files=None):
        self.auto = set(auto)
        self.files = files or {}
        self.ran: list = []

    def run(self, command, **keywords):
        self.ran.append(command)
        if command[:2] == ["apt-mark", "showauto"]:
            out = "".join(f"{name}\n" for name in command[2:] if name in self.auto)
            return CommandResult(command=command, exit_code=0, stdout=out, stderr="")
        if command[:2] == ["dpkg-query", "-L"]:
            listed = self.files.get(command[2])
            if listed is None:
                return CommandResult(
                    command=command, exit_code=1, stdout="", stderr="not installed"
                )
            out = "".join(f"{path}\n" for path in listed)
            return CommandResult(command=command, exit_code=0, stdout=out, stderr="")
        return CommandResult(command=command, exit_code=0, stdout="", stderr="")

    def systemctl(self) -> list:
        return [command[1:] for command in self.ran if command[0] == "systemctl"]


@pytest.fixture
def record(monkeypatch, tmp_path):
    path = tmp_path / "stood_down.json"
    monkeypatch.setattr(stack, "ROUTER_STACK_RECORD_PATH", path)
    return path


def _machine(monkeypatch, **keywords) -> Machine:
    machine = Machine(**keywords)
    monkeypatch.setattr(stack, "run", machine.run)
    return machine


def test_ubuntu_22_04_s_dhcpcd5_installed_for_the_hub_is_the_hub_s(monkeypatch):
    _machine(monkeypatch, auto={"dhcpcd5"}, files={"dhcpcd5": [UNIT_PATH]})

    assert stack.is_from_hub_dependency("dhcpcd.service")


def test_a_dhcpcd5_installed_by_hand_is_the_machine_s(monkeypatch):
    _machine(monkeypatch, files={"dhcpcd5": [UNIT_PATH]})

    assert not stack.is_from_hub_dependency("dhcpcd.service")


def test_dhcpcd_base_ships_no_unit(monkeypatch):
    """On Debian 12 and Ubuntu 24.04 the unit belongs to `dhcpcd`, a package
    the hub does not name."""
    _machine(
        monkeypatch,
        auto={"dhcpcd-base"},
        files={"dhcpcd-base": ["/usr/sbin/dhcpcd"], "dhcpcd": [UNIT_PATH]},
    )

    assert not stack.is_from_hub_dependency("dhcpcd.service")


def test_no_other_unit_is_the_hub_s(monkeypatch):
    machine = _machine(monkeypatch, auto={"dhcpcd5"}, files={"dhcpcd5": [UNIT_PATH]})

    assert not stack.is_from_hub_dependency("NetworkManager.service")
    assert machine.ran == []


def test_a_machine_without_apt_has_no_unit_of_the_hub_s(monkeypatch):
    """On RHEL and Arch the run of apt-mark exits 127 with no output."""

    def no_apt(command, **keywords):
        return CommandResult(command=command, exit_code=127, stdout="", stderr="")

    monkeypatch.setattr(stack, "run", no_apt)

    assert not stack.is_from_hub_dependency("dhcpcd.service")


def test_the_hand_back_leaves_the_hub_s_dhcpcd_disabled(monkeypatch, record):
    """A takeover under 0.5.2 masked it with the machine's own manager."""
    record.write_text(json.dumps(["dhcpcd.service", "systemd-networkd.service"]))
    machine = _machine(monkeypatch, auto={"dhcpcd5"}, files={"dhcpcd5": [UNIT_PATH]})

    changes = stack.stand_up()

    assert machine.systemctl() == [
        ["unmask", "dhcpcd.service"],
        ["unmask", "systemd-networkd.service"],
        ["disable", "dhcpcd.service"],
        ["enable", "--now", "systemd-networkd.service"],
    ]
    assert changes == [
        "left dhcpcd.service disabled",
        "started systemd-networkd.service",
    ]
    assert not record.exists()


def test_the_hand_back_starts_a_dhcpcd_that_ran_the_machine(monkeypatch, record):
    """Raspberry Pi OS with dhcpcd as its one manager gets it back."""
    record.write_text(json.dumps(["dhcpcd.service"]))
    machine = _machine(monkeypatch, files={"dhcpcd5": [UNIT_PATH]})

    changes = stack.stand_up()

    assert machine.systemctl() == [
        ["unmask", "dhcpcd.service"],
        ["enable", "--now", "dhcpcd.service"],
    ]
    assert changes == ["started dhcpcd.service"]


def test_a_hand_back_with_nothing_stood_down_runs_nothing(monkeypatch, record):
    machine = _machine(monkeypatch)

    assert stack.stand_up() == []
    assert machine.ran == []
