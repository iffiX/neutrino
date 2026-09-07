"""What the remote-desktop probe reports, and what it must not.

A machine that is off, a password that is wrong and a host key that changed
all come back as one failed command. Reporting that as "not installed" tells
somebody to install software that may already be there, onto a device the box
cannot reach — and it is the half of the device drawer people compare against
the module list, so the two disagree for reasons neither of them states.
"""

import asyncio

from neutrino_hub.modules.devices.constants import SSH_UNREACHABLE_STATUS
from neutrino_hub.modules.devices.remote_desktop import (
    RemoteDesktopManager,
    teamviewer_id,
)


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


# --- TeamViewer, whose id is drawn in a table and only for root ---

# What `teamviewer info` really prints on 15.61.3, escapes and all.
TEAMVIEWER_INFO = (
    "\x1b[1m TeamViewer                          \x1b[0m 15.61.3  (DEB) \n"
    "\n"
    "\x1b[1m TeamViewer ID:                      \x1b[0m  1146575818\n"
    " 1146575818 \n"
    "\n"
    "\x1b[1m teamviewerd status                  \x1b[0m teamviewerd.service\n"
)

# What the same command prints to anyone who is not root.
TEAMVIEWER_INFO_UNPRIVILEGED = (
    "\x1b[1m TeamViewer                          \x1b[0m 15.61.3  (DEB) \n"
    "grep: /opt/teamviewer/config/global.conf: Permission denied\n"
    "\x1b[1m TeamViewer ID:                      \x1b[0m  \n"
    "Try restarting the TeamViewer daemon (e.g. teamviewer --daemon restart)\n"
)


class PrivilegedFakeOperator(FakeOperator):
    """A fake that answers the privileged read with what a root shell would."""

    def __init__(self, code: int, output: str = "", privileged: str = ""):
        super().__init__(code, output)
        self._privileged = privileged
        self.privileged_asked: list = []

    async def run_privileged_once(self, command: str):
        self.privileged_asked.append(command)
        return 0, self._privileged


def test_the_teamviewer_id_is_read_out_of_the_table_it_is_drawn_in():
    assert teamviewer_id(TEAMVIEWER_INFO) == "1146575818"


def test_an_id_teamviewer_would_not_print_is_no_id():
    """A daemon that is down, and a caller who is not root, both get a blank
    where the id goes — which is not an id and must not be shown as one."""
    assert teamviewer_id(TEAMVIEWER_INFO_UNPRIVILEGED) == ""
    assert teamviewer_id("") == ""


def test_teamviewers_id_is_asked_for_as_root_and_anydesks_is_not():
    """TeamViewer reads its id from a file under /opt only root opens, so an
    unprivileged ask would report a running product with no id at all."""
    operator = PrivilegedFakeOperator(0, privileged=TEAMVIEWER_INFO)

    status = asyncio.run(RemoteDesktopManager(operator=operator).status("teamviewer"))

    assert status.session_id == "1146575818"
    assert "teamviewer info" in operator.privileged_asked
    assert not any("info" in command for command in operator.asked)


def test_the_teamviewer_probe_looks_for_its_own_daemon():
    """`teamviewerd`, not `teamviewer`: the unit the package installs is the
    daemon, and asking after the wrong name reads as never running."""
    operator = PrivilegedFakeOperator(0, privileged=TEAMVIEWER_INFO)

    asyncio.run(RemoteDesktopManager(operator=operator).status("teamviewer"))

    assert any("systemctl is-active teamviewerd" in c for c in operator.asked)
