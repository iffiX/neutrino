"""The Windows seat: the console session's user, and netstat's rows.

The session API is a fake that fills the buffer it is handed; netstat is
faked at ``subprocess.run``. What is pinned is who the seat says is at the
screen, how the established rows on the direct port are counted, and that a
Windows screen has nothing for a peer to wait on.
"""

import ctypes
import subprocess

from neutrino_agent.rdp import windows_seat as seat_module
from neutrino_agent.rdp.windows_seat import WindowsSeat


class FakeKernel32:
    def __init__(self, session):
        self.session = session

    def WTSGetActiveConsoleSessionId(self):
        return self.session


class FakeWtsapi32:
    """WTSQuerySessionInformationW answering one user name."""

    def __init__(self, name, *, is_answering=True):
        self.name = ctypes.c_wchar_p(name)
        self.is_answering = is_answering
        self.asked = []
        self.freed = []

    def WTSQuerySessionInformationW(self, server, session, info_class, buffer, size):
        self.asked.append((server, session, info_class))
        if not self.is_answering:
            return 0
        buffer._obj.value = self.name.value
        size._obj.value = 2 * (len(self.name.value) + 1)
        return 1

    def WTSFreeMemory(self, memory):
        self.freed.append(memory)


def test_the_console_sessions_user_is_the_seat():
    wtsapi32 = FakeWtsapi32("pat")
    seat = WindowsSeat(kernel32=FakeKernel32(2), wtsapi32=wtsapi32)

    assert seat.graphical_accounts() == ["pat"]
    assert wtsapi32.asked == [(None, 2, 5)]
    assert len(wtsapi32.freed) == 1


def test_the_sign_in_screen_is_nobody_seated():
    seat = WindowsSeat(kernel32=FakeKernel32(1), wtsapi32=FakeWtsapi32(""))

    assert seat.graphical_accounts() == []


def test_no_console_session_is_nobody_seated():
    wtsapi32 = FakeWtsapi32("pat")
    seat = WindowsSeat(kernel32=FakeKernel32(0xFFFFFFFF), wtsapi32=wtsapi32)

    assert seat.graphical_accounts() == []
    assert wtsapi32.asked == []


def test_a_session_api_that_refuses_cannot_say():
    seat = WindowsSeat(
        kernel32=FakeKernel32(1), wtsapi32=FakeWtsapi32("pat", is_answering=False)
    )

    assert seat.graphical_accounts() is None


def test_a_windows_screen_is_always_a_desktop_with_nothing_to_wait_on():
    seat = WindowsSeat(kernel32=FakeKernel32(1), wtsapi32=FakeWtsapi32("pat"))

    assert seat.has_desktop_session() is True
    assert seat.screen_attention("C:\\Users\\pat") == ""


NETSTAT_SAMPLE = """
Active Connections

  Proto  Local Address          Foreign Address        State
  TCP    0.0.0.0:21118          0.0.0.0:0              LISTENING
  TCP    192.0.2.10:21118       192.0.2.20:50123       ESTABLISHED
  TCP    192.0.2.10:21118       192.0.2.21:50124       ESTABLISHED
  TCP    192.0.2.10:22          192.0.2.22:50125       ESTABLISHED
  TCP    [::1]:21118            [::1]:50126            ESTABLISHED
  TCP    192.0.2.10:21118       192.0.2.23:50127       TIME_WAIT
"""


def test_the_peers_are_the_established_rows_on_the_direct_port(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=NETSTAT_SAMPLE)

    monkeypatch.setattr(seat_module.subprocess, "run", run)
    seat = WindowsSeat(kernel32=FakeKernel32(1), wtsapi32=FakeWtsapi32("pat"))

    assert seat.connected_count(21118) == 3
    assert seat.connected_count(22) == 1
    assert calls[0] == ["netstat", "-an", "-p", "TCP"]


def test_a_netstat_that_cannot_run_counts_nobody(monkeypatch):
    def run(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(seat_module.subprocess, "run", run)
    seat = WindowsSeat(kernel32=FakeKernel32(1), wtsapi32=FakeWtsapi32("pat"))

    assert seat.connected_count(21118) == 0
