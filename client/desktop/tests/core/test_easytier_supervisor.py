"""The one core the EasyTier daemon runs, against fake processes and a fake clock.

Pinned here: no core starts while the command is None; a change stops the
running core before the next starts; a core that ends by itself waits
before it starts again, the wait doubling to its most and falling back to
the least after a core that ran long enough; a failed start waits the same
way; a stop ends the core, killing one that does not end when asked; the
core's output reaches the core log line by line; the Windows tie is called
with each process.
"""

import io
import subprocess
import threading
import time

from neutrino_client.constants import (
    CLIENT_EASYTIER_RESTART_MAX_S,
    CLIENT_EASYTIER_RESTART_MIN_S,
    CLIENT_EASYTIER_STABLE_S,
)
from neutrino_client.core.easytier_supervisor import EasytierCoreSupervisor
from tests.conftest import discard


class FakeProcess:
    """A core: running until it is ended, or until the test ends it."""

    def __init__(self, argv, env, output=b""):
        self.argv = argv
        self.env = env
        self.status = None
        self.terminated = 0
        self.killed = 0
        self.is_deaf = False
        self.pid = 4000
        self.stdout = io.BytesIO(output)

    def poll(self):
        return self.status

    def terminate(self):
        self.terminated += 1
        if not self.is_deaf:
            self.status = -15

    def kill(self):
        self.killed += 1
        self.status = -9

    def wait(self, timeout=None):
        if self.status is None:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.status


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Harness:
    def __init__(self, command=(["core"], {"A": "1"}), output=b""):
        self.command = command
        self.started = []
        self.bound = []
        self.lines = []
        self.clock = Clock()
        self.error = None
        self.output = output
        self.supervisor = EasytierCoreSupervisor(
            command_of=lambda: self.command,
            log=discard,
            core_log=self.lines.append,
            start_process=self.start,
            on_started=self.bound.append,
            clock=self.clock,
        )

    def start(self, argv, env):
        if self.error is not None:
            raise self.error
        process = FakeProcess(argv, env, self.output)
        self.started.append(process)
        return process


def test_nothing_configured_starts_no_core():
    harness = Harness(command=None)

    harness.supervisor.apply()
    harness.clock.now += 1000
    harness.supervisor.tick()

    assert harness.started == []
    assert harness.supervisor.is_running is False


def test_a_change_stops_the_core_before_the_next_starts():
    harness = Harness()
    harness.supervisor.apply()
    first = harness.started[0]

    harness.command = (["core", "--config-dir", "d"], {})
    harness.supervisor.apply()

    assert first.terminated == 1
    assert [p.argv for p in harness.started] == [
        ["core"],
        ["core", "--config-dir", "d"],
    ]
    assert harness.supervisor.is_running is True
    assert harness.bound == harness.started


def test_nothing_left_stops_the_core_and_starts_none():
    harness = Harness()
    harness.supervisor.apply()

    harness.command = None
    harness.supervisor.apply()

    assert harness.started[0].terminated == 1
    assert len(harness.started) == 1
    assert harness.supervisor.is_running is False


def ended_and_waited(harness) -> float:
    """End the running core and step the clock until the next one starts."""
    harness.started[-1].status = 1
    harness.supervisor.tick()
    count = len(harness.started)
    waited = 0.0
    while len(harness.started) == count:
        harness.clock.now += 0.5
        waited += 0.5
        harness.supervisor.tick()
    return waited


def test_a_core_that_ends_waits_then_starts_again_doubling_to_the_most():
    harness = Harness()
    harness.supervisor.apply()

    waits = [ended_and_waited(harness) for _round in range(9)]

    assert waits[:3] == [
        CLIENT_EASYTIER_RESTART_MIN_S,
        CLIENT_EASYTIER_RESTART_MIN_S * 2,
        CLIENT_EASYTIER_RESTART_MIN_S * 4,
    ]
    assert waits == sorted(waits)
    assert waits[-1] == CLIENT_EASYTIER_RESTART_MAX_S


def test_a_core_that_ran_long_enough_waits_the_least_again():
    harness = Harness()
    harness.supervisor.apply()
    for _round in range(4):
        harness.started[-1].status = 1
        harness.supervisor.tick()
        harness.clock.now += CLIENT_EASYTIER_RESTART_MAX_S
        harness.supervisor.tick()
    assert harness.supervisor.restart_wait_s > CLIENT_EASYTIER_RESTART_MIN_S

    harness.clock.now += CLIENT_EASYTIER_STABLE_S
    harness.supervisor.tick()

    assert harness.supervisor.restart_wait_s == CLIENT_EASYTIER_RESTART_MIN_S


def test_a_change_resets_the_wait():
    harness = Harness()
    harness.supervisor.apply()
    harness.started[-1].status = 1
    harness.supervisor.tick()
    assert harness.supervisor.restart_wait_s > CLIENT_EASYTIER_RESTART_MIN_S

    harness.supervisor.apply()

    assert harness.supervisor.restart_wait_s == CLIENT_EASYTIER_RESTART_MIN_S
    assert harness.supervisor.is_running is True


def test_a_failed_start_waits_and_tries_again():
    harness = Harness()
    harness.error = FileNotFoundError(2, "No such file")

    harness.supervisor.apply()
    assert harness.started == []

    harness.error = None
    harness.clock.now += CLIENT_EASYTIER_RESTART_MIN_S
    harness.supervisor.tick()

    assert len(harness.started) == 1


def test_a_stop_ends_the_core_and_kills_one_that_does_not_end():
    harness = Harness()
    harness.supervisor.apply()
    core = harness.started[0]
    core.is_deaf = True

    harness.supervisor.stop()

    assert (core.terminated, core.killed) == (1, 1)
    assert harness.supervisor.is_running is False
    harness.clock.now += 1000
    harness.supervisor.tick()
    assert len(harness.started) == 1


def test_the_cores_output_reaches_the_core_log_line_by_line():
    harness = Harness(output=b"one\r\ntwo \xff\n")

    harness.supervisor.apply()
    deadline = time.monotonic() + 5
    while len(harness.lines) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert harness.lines == ["one", "two �"]


def test_the_watch_thread_restarts_a_core_that_ended():
    """The real thread and clock, with a core that ends at once."""
    started = []
    ended = threading.Event()

    def start(argv, env):
        process = FakeProcess(argv, env)
        if not started:
            process.status = 1
            ended.set()
        started.append(process)
        return process

    supervisor = EasytierCoreSupervisor(
        command_of=lambda: (["core"], {}), log=discard, start_process=start
    )
    supervisor.apply()
    supervisor.start()
    deadline = time.monotonic() + 10
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    supervisor.stop()

    assert len(started) == 2
    assert started[1].terminated == 1


def test_a_supervisor_named_for_another_program_logs_under_that_name():
    lines = []
    process = FakeProcess(["tun2socks"], {})
    supervisor = EasytierCoreSupervisor(
        command_of=lambda: (["tun2socks"], {}),
        log=lines.append,
        start_process=lambda argv, env: process,
        name="tun2socks",
    )

    supervisor.apply()
    supervisor.stop()

    assert lines == ["tun2socks started as 4000", "tun2socks stopped"]
