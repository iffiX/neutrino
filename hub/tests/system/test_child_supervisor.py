"""The children of the hub's one service on macOS and Windows.

Driven through a fake Popen and a clock moved by hand: a child started from
its start line, stopped and kept stopped, started again after a wait that
doubles, its output written to a log file rotated by size.
"""

import time

import pytest

from neutrino_hub.system import child_supervisor
from neutrino_hub.system.child_supervisor import ChildProcessSupervisor, ChildStartLine
from neutrino_hub.system.constants import (
    SYSTEM_CHILD_RESTART_MAX_S,
    SYSTEM_CHILD_RESTART_MIN_S,
    SYSTEM_CHILD_STABLE_S,
)
from tests.conftest import FakeClock, FakePopen

XRAY = ChildStartLine(
    argv=["/app/bin/xray", "run", "-config", "/state/generated/xray.json"],
    env={"XRAY_LOCATION_ASSET": "/state/geodata"},
)


@pytest.fixture
def popen():
    return FakePopen()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def supervisor(tmp_path, popen, clock):
    return ChildProcessSupervisor(
        log_dir=tmp_path / "log",
        base_env={"PATH": "/usr/bin"},
        start_process=popen,
        clock=clock,
        log=lambda line: None,
    )


def test_a_child_starts_from_its_start_line_with_its_environment(supervisor, popen):
    supervisor.set_start_line("xray", XRAY)

    supervisor.start("xray")

    (child,) = popen.started
    assert child.argv == XRAY.argv
    assert child.env == {"PATH": "/usr/bin", "XRAY_LOCATION_ASSET": "/state/geodata"}
    assert supervisor.is_running("xray")


def test_a_child_with_no_start_line_is_refused(supervisor):
    with pytest.raises(KeyError):
        supervisor.start("easytier")


def test_a_running_child_is_not_started_twice(supervisor, popen):
    supervisor.set_start_line("xray", XRAY)
    supervisor.start("xray")

    supervisor.start("xray")

    assert len(popen.started) == 1


def test_a_stopped_child_stays_stopped(supervisor, popen, clock):
    supervisor.set_start_line("xray", XRAY)
    supervisor.start("xray")

    supervisor.stop("xray")
    clock.now += SYSTEM_CHILD_RESTART_MAX_S * 2
    supervisor.tick()

    assert popen.started[0].is_terminated
    assert not supervisor.is_running("xray")
    assert len(popen.started) == 1


def test_a_child_that_ends_starts_again_after_its_wait(supervisor, popen, clock):
    supervisor.set_start_line("xray", XRAY)
    supervisor.start("xray")

    popen.started[0].end(1)
    supervisor.tick()
    assert not supervisor.is_running("xray")
    clock.now += SYSTEM_CHILD_RESTART_MIN_S - 0.1
    supervisor.tick()
    assert len(popen.started) == 1
    clock.now += 0.2
    supervisor.tick()

    assert len(popen.started) == 2
    assert supervisor.is_running("xray")


def test_the_wait_doubles_while_a_child_keeps_ending(supervisor, popen, clock):
    supervisor.set_start_line("xray", XRAY)
    supervisor.start("xray")
    waits = []
    for _ in range(3):
        popen.started[-1].end(1)
        supervisor.tick()
        ended_at = clock.now
        while len(popen.started) == len(waits) + 1:
            clock.now += 0.5
            supervisor.tick()
        waits.append(clock.now - ended_at)

    assert waits[0] < waits[1] < waits[2]
    assert waits[1] >= 2 * SYSTEM_CHILD_RESTART_MIN_S


def test_a_child_that_ran_long_enough_waits_the_least_again(supervisor, popen, clock):
    supervisor.set_start_line("xray", XRAY)
    supervisor.start("xray")
    for _ in range(3):
        popen.started[-1].end(1)
        supervisor.tick()
        clock.now += SYSTEM_CHILD_RESTART_MAX_S
        supervisor.tick()
    clock.now += SYSTEM_CHILD_STABLE_S

    popen.started[-1].end(1)
    supervisor.tick()
    clock.now += SYSTEM_CHILD_RESTART_MIN_S
    supervisor.tick()

    assert len(popen.started) == 5


def test_a_start_that_fails_is_tried_again_after_the_wait(supervisor, popen, clock):
    supervisor.set_start_line("xray", XRAY)
    popen.is_refusing = True

    supervisor.start("xray")
    popen.is_refusing = False
    clock.now += SYSTEM_CHILD_RESTART_MIN_S
    supervisor.tick()

    assert supervisor.is_running("xray")


def test_restart_ends_the_child_and_starts_another(supervisor, popen):
    supervisor.set_start_line("xray", XRAY)
    supervisor.start("xray")

    supervisor.restart("xray")

    assert popen.started[0].is_terminated
    assert len(popen.started) == 2
    assert supervisor.is_running("xray")


def test_forgetting_a_start_line_stops_the_child(supervisor, popen):
    supervisor.set_start_line("xray", XRAY)
    supervisor.start("xray")

    supervisor.set_start_line("xray", None)

    assert popen.started[0].is_terminated
    assert supervisor.start_line("xray") is None


def test_stop_all_ends_every_child(supervisor, popen, clock):
    supervisor.set_start_line("xray", XRAY)
    supervisor.set_start_line("netbird", ChildStartLine(argv=["/app/bin/netbird"]))
    supervisor.start("xray")
    supervisor.start("netbird")

    supervisor.stop_all()
    clock.now += SYSTEM_CHILD_RESTART_MAX_S
    supervisor.tick()

    assert all(child.is_terminated for child in popen.started)
    assert len(popen.started) == 2


def test_a_childs_output_goes_to_its_log_file(tmp_path, clock):
    popen = FakePopen(output=b"first line\nsecond line\n")
    supervisor = ChildProcessSupervisor(
        log_dir=tmp_path / "log",
        base_env={},
        start_process=popen,
        clock=clock,
        log=lambda line: None,
    )
    supervisor.set_start_line("xray", XRAY)

    supervisor.start("xray")

    path = tmp_path / "log" / "xray.log"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and "second line" not in _text(path):
        time.sleep(0.01)
    assert _text(path) == "first line\nsecond line\n"


def test_a_start_line_may_name_another_log_file(tmp_path, clock):
    popen = FakePopen(output=b"panic\n")
    supervisor = ChildProcessSupervisor(
        log_dir=tmp_path, base_env={}, start_process=popen, clock=clock
    )
    supervisor.set_start_line(
        "netbird", ChildStartLine(argv=["/app/bin/netbird"], log_name="netbird_console")
    )

    supervisor.start("netbird")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not _text(tmp_path / "netbird_console.log"):
        time.sleep(0.01)
    assert _text(tmp_path / "netbird_console.log") == "panic\n"
    assert not (tmp_path / "netbird.log").exists()


def test_the_log_file_is_rotated_by_size(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(child_supervisor, "SYSTEM_CHILD_LOG_MAX_BYTES", 64)
    monkeypatch.setattr(child_supervisor, "SYSTEM_CHILD_LOG_BACKUP_COUNT", 2)
    popen = FakePopen(output=b"".join(b"line %02d of output\n" % n for n in range(40)))
    supervisor = ChildProcessSupervisor(
        log_dir=tmp_path, base_env={}, start_process=popen, clock=clock
    )
    supervisor.set_start_line("xray", XRAY)

    supervisor.start("xray")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and "line 39" not in _text(tmp_path / "xray.log"):
        time.sleep(0.01)
    supervisor.stop_all()
    kept = sorted(path.name for path in tmp_path.iterdir())
    assert kept == ["xray.log", "xray.log.1", "xray.log.2"]
    assert all(path.stat().st_size <= 64 for path in tmp_path.iterdir())


def test_a_started_child_is_handed_to_on_started(tmp_path, popen, clock):
    tied = []
    supervisor = ChildProcessSupervisor(
        log_dir=tmp_path,
        base_env={},
        start_process=popen,
        on_started=tied.append,
        creation_flags=0x08000000,
        clock=clock,
    )
    supervisor.set_start_line("xray", XRAY)

    supervisor.start("xray")

    assert tied == popen.started
    assert popen.creation_flags == [0x08000000]


def test_a_start_line_reads_back_what_it_wrote():
    line = ChildStartLine(argv=["/a", "b"], env={"K": "v"}, cwd="/w", log_name="n")

    assert ChildStartLine.from_dict(line.to_dict()) == line


def test_a_start_line_without_an_argument_vector_is_refused():
    with pytest.raises(ValueError):
        ChildStartLine.from_dict({"argv": []})


def _text(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
