"""The resident PowerShell host, driven against a fake host program speaking its protocol.

What these pin: nothing starts until the first call, and the command line
runs the library this package ships; each call is one request line with
its own id, answered by the value it carries, and calls never overlap; a
refusal is ``ModuleApplyError`` with its code and params and an error is
``OSError`` with its message, the host kept after a read; every operation
is a read or a change, and only the library's ``Get-`` functions read; a
read leaves the host running, while a change is answered, refused or
failed, then the host is stopped and the next call starts another; a host
that does not answer in time is killed with ``TimeoutError`` and the next
call starts another, while a call that cannot get the host in time kills
nothing; a host that passes the private bytes ceiling answers, then is
stopped; an idle host is stopped; a stop closes its standard input; a
crash, an answer to another request, or a host that cannot start is
``OSError``, and the next call starts again; a line that is no JSON, and
a byte order mark, are passed over; an operation the library lacks is
refused before anything starts.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms.powershell_host import (
    WINDOWS_POWERSHELL_HOST_CHANGING_OPS,
    WINDOWS_POWERSHELL_HOST_OPS,
    WindowsPowerShellHost,
    agent_host,
    host_command,
    library_path,
)

FAKE_HOST = str(Path(__file__).parent / "fake_powershell_host.py")
HOST_READS = {
    "task_read",
    "task_states",
    "share_status",
    "share_log",
    "thermal_zones",
    "added_list",
    "relay_rules_read",
}
HOST_CHANGES = {
    "task_write",
    "task_run_once",
    "task_start",
    "task_stop",
    "task_remove",
    "rules_forget",
    "share_apply",
    "share_withdraw",
    "share_password",
    "added_remove",
    "relay_rules_write",
}


class Starter:
    """Starts the fake host for the command line the host hands it."""

    def __init__(self, log):
        self.log = log
        self.commands: list = []
        self.processes: list = []

    def __call__(self, argv):
        self.commands.append(list(argv))
        process = subprocess.Popen(
            [sys.executable, FAKE_HOST, str(self.log)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        self.processes.append(process)
        return process

    def lines(self) -> list:
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def starts(self) -> int:
        return sum(line.startswith("start ") for line in self.lines())


@pytest.fixture
def started(tmp_path):
    starter = Starter(tmp_path / "host.log")
    hosts = []

    def make(**kwargs):
        host = WindowsPowerShellHost(start_process=starter, **kwargs)
        hosts.append(host)
        return host

    yield starter, make
    for host in hosts:
        host.stop()


def wait_for(predicate, timeout_s=5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_nothing_starts_before_the_first_call_and_the_library_is_the_package_s(
    started,
):
    starter, make = started
    host = make()

    assert starter.commands == []
    assert host.call("task_read", {"value": {"is_present": True}}) == {
        "is_present": True
    }
    (command,) = starter.commands
    assert command == host_command(library_path())
    assert command[:6] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
    ]
    assert Path(command[6]).parts[-4:] == (
        "neutrino_agent",
        "data",
        "windows",
        "powershell_host.ps1",
    )
    assert os.path.isfile(command[6])


def test_each_call_has_its_own_id_and_one_host_answers_them_all(started):
    starter, make = started
    host = make()

    assert host.call("task_states", {"value": {"tasks": []}}) == {"tasks": []}
    assert host.call("thermal_zones", {}) == {}
    assert host.call("task_read", {"value": {"a": [1]}}) == {"a": [1]}

    assert starter.starts() == 1
    assert [line for line in starter.lines() if line.startswith("begin")] == [
        "begin 1 task_states",
        "begin 2 thermal_zones",
        "begin 3 task_read",
    ]


def test_calls_from_two_threads_never_overlap(started):
    starter, make = started
    host = make()
    answers = []

    def ask(value):
        answers.append(
            host.call("task_read", {"mode": "sleep", "seconds": 0.2, "value": value})
        )

    threads = [threading.Thread(target=ask, args=({"n": n},)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(answer["n"] for answer in answers) == [1, 2]
    steps = [
        line.split()[0]
        for line in starter.lines()
        if line.split()[0] in ("begin", "end")
    ]
    assert steps == ["begin", "end", "begin", "end"]


def test_a_refusal_is_a_module_apply_error_and_an_error_an_os_error(started):
    starter, make = started
    host = make()

    with pytest.raises(ModuleApplyError) as refused:
        host.call(
            "task_read",
            {
                "mode": "refuse",
                "code": "credential_invalid",
                "params": {"account": "ann"},
            },
        )
    with pytest.raises(OSError, match="Access is denied"):
        host.call("task_states", {"mode": "error", "message": "Access is denied."})

    assert (refused.value.code, refused.value.params) == (
        "credential_invalid",
        {"account": "ann"},
    )
    assert host.call("task_read", {}) == {}
    assert starter.starts() == 1


def test_every_operation_is_a_read_or_a_change_exactly_once():
    assert HOST_READS.isdisjoint(HOST_CHANGES)
    assert HOST_READS | HOST_CHANGES == set(WINDOWS_POWERSHELL_HOST_OPS)
    assert WINDOWS_POWERSHELL_HOST_CHANGING_OPS == HOST_CHANGES
    for op, name in WINDOWS_POWERSHELL_HOST_OPS.items():
        assert name.startswith("Get-") == (op in HOST_READS), op


def test_a_read_leaves_the_host_running(started):
    starter, make = started
    host = make()

    for op in sorted(HOST_READS):
        assert host.call(op, {"value": {"op": op}}) == {"op": op}

    assert starter.starts() == 1
    assert starter.processes[0].poll() is None
    assert "eof" not in starter.lines()


def test_a_change_is_answered_then_the_host_stops_and_the_next_call_starts_another(
    started,
):
    starter, make = started
    host = make()

    for count, op in enumerate(sorted(HOST_CHANGES), start=1):
        assert host.call(op, {"value": {"op": op}}) == {"op": op}
        assert starter.starts() == count
        assert starter.lines()[-1] == "eof"
        assert starter.processes[-1].poll() == 0

    assert host.call("task_read", {"value": {"n": 1}}) == {"n": 1}
    assert starter.starts() == len(HOST_CHANGES) + 1
    assert starter.processes[-1].poll() is None


def test_a_change_refused_or_failed_stops_the_host_too(started):
    starter, make = started
    host = make()

    with pytest.raises(ModuleApplyError):
        host.call(
            "share_apply",
            {"mode": "refuse", "code": "share_name_taken", "params": {}},
        )
    assert starter.processes[0].poll() == 0
    with pytest.raises(OSError, match="Access is denied"):
        host.call("task_write", {"mode": "error", "message": "Access is denied."})
    assert starter.processes[1].poll() == 0

    host.call("task_read", {})
    assert starter.starts() == 3


def test_a_host_that_does_not_answer_in_time_is_killed_and_started_again(started):
    starter, make = started
    host = make()

    with pytest.raises(TimeoutError):
        host.call("task_read", {"mode": "sleep", "seconds": 30}, timeout_s=0.5)

    assert starter.processes[0].poll() is not None
    assert host.call("task_read", {"value": {"is_present": False}}) == {
        "is_present": False
    }
    assert starter.starts() == 2


def test_a_call_that_cannot_get_the_host_in_time_kills_nothing(started):
    starter, make = started
    host = make()
    answers = []

    def ask_long():
        args = {"mode": "sleep", "seconds": 1, "value": {"n": 1}}
        answers.append(host.call("task_read", args))

    first = threading.Thread(target=ask_long)
    first.start()
    assert wait_for(lambda: "begin 1 task_read" in starter.lines())

    with pytest.raises(TimeoutError, match="busy"):
        host.call("task_read", {}, timeout_s=0.2)

    first.join()
    assert answers == [{"n": 1}]
    assert starter.starts() == 1


def test_the_private_bytes_ceiling_stops_the_host_after_its_answer(started):
    starter, make = started
    host = make(private_bytes_max=5000)

    assert host.call("task_read", {"private_bytes": 5001, "value": {"n": 1}}) == {
        "n": 1
    }
    assert "eof" in starter.lines()
    assert starter.processes[0].poll() == 0

    host.call("task_read", {"private_bytes": 5000})
    host.call("task_read", {"private_bytes": 5000})
    assert starter.starts() == 2


def test_an_idle_host_is_stopped_and_the_next_call_starts_another(started):
    starter, make = started
    host = make(idle_s=0.3)

    host.call("task_read", {})
    assert wait_for(lambda: "eof" in starter.lines())
    assert wait_for(lambda: starter.processes[0].poll() is not None)

    host.call("task_read", {})
    assert starter.starts() == 2


def test_a_stop_closes_the_host_s_standard_input(started):
    starter, make = started
    host = make()
    host.call("task_read", {})

    host.stop()

    assert starter.lines()[-1] == "eof"
    assert starter.processes[0].poll() == 0
    host.stop()


def test_a_crash_mid_call_is_an_os_error_and_the_next_call_starts_again(started):
    starter, make = started
    host = make()

    with pytest.raises(OSError, match="ended during task_start"):
        host.call("task_start", {"mode": "crash"})

    assert host.call("task_start", {}) == {}
    assert starter.starts() == 2


def test_an_answer_to_another_request_is_an_os_error_and_restarts(started):
    starter, make = started
    host = make()

    with pytest.raises(OSError, match="answered request 101 to request 1"):
        host.call("task_read", {"mode": "wrong_id"})

    host.call("task_read", {})
    assert starter.starts() == 2


def test_a_line_that_is_no_json_and_a_byte_order_mark_are_passed_over(started):
    _starter, make = started
    host = make()

    assert host.call("task_read", {"mode": "noise", "value": {"n": 1}}) == {"n": 1}
    assert host.call("task_read", {"mode": "bom", "value": {"n": 2}}) == {"n": 2}


def test_an_answer_that_is_no_object_is_an_os_error(started):
    _starter, make = started
    host = make()

    with pytest.raises(OSError, match="no object"):
        host.call("task_read", {"value": [1, 2]})


def test_an_operation_the_library_lacks_starts_nothing(started):
    starter, make = started
    host = make()

    with pytest.raises(ValueError):
        host.call("run_anything", {})

    assert starter.commands == []


def test_a_host_that_cannot_start_is_an_os_error():
    def missing(argv):
        raise FileNotFoundError(argv[0])

    with pytest.raises(OSError):
        WindowsPowerShellHost(start_process=missing).call("task_read", {})


def test_the_agent_has_one_host():
    assert agent_host() is agent_host()
