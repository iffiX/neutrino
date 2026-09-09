"""Reading whether a unit is installed, running and enabled.

What this guards is one bug with a long reach: the panel and the setup wizard
both drew every optional module as installed on Debian 12, because the answer
was being read out of the words `systemctl is-enabled` prints for a unit that
does not exist — and those words are a systemd version's, not an interface.
A module shown as installed is a module whose Enable button fails with a raw
systemd error, and a wizard that offers to install what is already there.
"""

import pytest

from neutrino_hub.system import systemd_ctl
from neutrino_hub.system.systemd_ctl import SystemdServiceController

# What `systemctl show -p LoadState -p ActiveState -p UnitFileState` answers,
# copied from the machines. A unit that is not there answers all three; it
# does not fail.
ABSENT = "LoadState=not-found\nActiveState=inactive\nUnitFileState=\n"
RUNNING = "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
STOPPED = "LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n"
STATIC = "LoadState=loaded\nActiveState=active\nUnitFileState=static\n"
MASKED = "LoadState=masked\nActiveState=inactive\nUnitFileState=masked\n"


@pytest.fixture
def systemd(monkeypatch):
    """Answer `systemctl show` from a dictionary of unit to output."""
    answers: dict = {}

    def fake_run(command, **keywords):
        assert command[:2] == ["systemctl", "show"], command
        return _Result(answers.get(command[2], ABSENT))

    monkeypatch.setattr(systemd_ctl, "run", fake_run)
    return answers


class _Result:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.stderr = ""
        self.is_success = True


def test_a_unit_that_is_not_there_is_not_installed(systemd):
    status = SystemdServiceController().status("netbird")

    assert not status.is_installed
    assert not status.is_active
    assert not status.is_enabled


def test_a_running_unit_reads_as_all_three(systemd):
    systemd["neutrino_hub_web.service"] = RUNNING

    status = SystemdServiceController().status("web")

    assert status.is_installed
    assert status.is_active
    assert status.is_enabled


def test_an_installed_unit_that_is_stopped_is_still_installed(systemd):
    """The distinction the Services page is built on: a module that is there
    and switched off is not one that has to be installed again."""
    systemd["netbird.service"] = STOPPED

    status = SystemdServiceController().status("netbird")

    assert status.is_installed
    assert not status.is_active
    assert not status.is_enabled


def test_a_unit_with_no_install_section_counts_as_enabled(systemd):
    """`static` is what a unit something else pulls in reports, and it starts
    at boot as surely as an enabled one."""
    systemd["netbird.service"] = STATIC

    assert SystemdServiceController().status("netbird").is_enabled


def test_a_masked_unit_is_installed_and_not_enabled(systemd):
    """Masking is what the hub does to a manager it has taken over from, and
    the unit is still on the disk."""
    systemd["netbird.service"] = MASKED

    status = SystemdServiceController().status("netbird")

    assert status.is_installed
    assert not status.is_enabled


def test_the_state_is_read_in_one_call_per_unit(systemd, monkeypatch):
    """`status_all` runs over every managed unit, and two invocations each was
    two process spawns per row of a page that is polled."""
    calls: list = []

    def counting_run(command, **keywords):
        calls.append(command)
        return _Result(ABSENT)

    monkeypatch.setattr(systemd_ctl, "run", counting_run)

    SystemdServiceController().status("web")

    assert len(calls) == 1
