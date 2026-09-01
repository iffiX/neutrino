"""What the remote-desktop probe reports, and what it must not.

A machine that is off, a password that is wrong and a host key that changed
all come back as one failed command. Reporting that as "not installed" tells
somebody to install software that may already be there, onto a device the box
cannot reach — and it is the half of the device drawer people compare against
the module list, so the two disagree for reasons neither of them states.
"""

import asyncio

from neutrino_hub.modules.devices.constants import SSH_UNREACHABLE_STATUS
from neutrino_hub.modules.devices.remote_desktop import RemoteDesktopManager


class FakeOperator:
    """One canned answer for the probe, then "active" for anything after."""

    def __init__(self, code: int, output: str = ""):
        self._first = (code, output)
        self.asked: list = []

    async def run_once(self, command: str):
        self.asked.append(command)
        if len(self.asked) == 1:
            return self._first
        return 0, "active"

    async def run_privileged_once(self, command: str):
        return 0, ""


def test_a_device_that_cannot_be_reached_says_so():
    operator = FakeOperator(SSH_UNREACHABLE_STATUS, "Connection refused")

    status = asyncio.run(RemoteDesktopManager(operator=operator).status("anydesk"))

    assert status.unreachable == "Connection refused"
    assert not status.is_installed


def test_a_device_without_the_software_is_not_unreachable():
    """The probe ran and answered. That is a different sentence."""
    operator = FakeOperator(1)

    status = asyncio.run(RemoteDesktopManager(operator=operator).status("anydesk"))

    assert status.unreachable == ""
    assert not status.is_installed


def test_a_device_with_it_installed_reports_neither():
    operator = FakeOperator(0)

    status = asyncio.run(RemoteDesktopManager(operator=operator).status("anydesk"))

    assert status.unreachable == ""
    assert status.is_installed
