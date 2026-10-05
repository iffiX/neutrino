"""The agent's RustDesk on Linux: ``rustdesk.service`` in ``/etc``, what is
kept aside, and what is never stopped.

A packaged unit's own stop runs ``pkill -f "rustdesk --"``, which ends a
person's viewers too, so the host is stopped by signalling the unit's own
processes and a viewer is never ended. A unit file of the agent's name that
is not the agent's is moved aside and put back.
"""

import json
import os
import signal

import pytest

from neutrino_agent.modules.remote_desktop.linux_applier import (
    RemoteDesktopLinuxApplier,
    is_viewer,
)
from neutrino_agent.modules.subprocess_run import CommandResult

COPY = "/usr/lib/neutrino/agent/rustdesk/rustdesk"


class FakeSystemd:
    """``systemctl`` and ``ss`` answering from a table, recording each call."""

    def __init__(self):
        self.calls = []
        self.shown = {}
        self.listening = ""

    def __call__(self, command, *, is_checked=True, timeout_s=0, input_text=None):
        self.calls.append(list(command))
        if command[:2] == ["systemctl", "show"]:
            text = "".join(f"{key}={value}\n" for key, value in self.shown.items())
            return CommandResult(list(command), 0, text, "")
        if command[:2] == ["systemctl", "is-active"]:
            return CommandResult(list(command), 3, "inactive\n", "")
        if command[0] == "ss":
            return CommandResult(list(command), 0, self.listening, "")
        return CommandResult(list(command), 0, "", "")


def _process(proc, pid, program, *arguments):
    folder = proc / str(pid)
    folder.mkdir(parents=True)
    (folder / "cmdline").write_bytes(
        b"\0".join(part.encode() for part in (program, *arguments)) + b"\0"
    )
    os.symlink(program, folder / "exe")


@pytest.fixture()
def made(tmp_path):
    systemd = FakeSystemd()
    killed = []
    proc = tmp_path / "proc"
    proc.mkdir()

    def kill(pid, sent):
        killed.append((pid, sent))
        folder = proc / str(pid)
        if folder.exists():
            for child in folder.iterdir():
                child.unlink()
            folder.rmdir()

    applier = RemoteDesktopLinuxApplier(
        kept_dir=str(tmp_path / "kept"),
        run=systemd,
        program=COPY,
        unit_path=str(tmp_path / "etc" / "rustdesk.service"),
        proc_dir=str(proc),
        kill=kill,
        sleep=lambda seconds: None,
    )
    applier.systemd = systemd
    applier.killed = killed
    applier.proc = proc
    applier.root = tmp_path
    return applier


def _unit(made):
    return made.root / "etc" / "rustdesk.service"


# --- keeping aside ---


def test_nothing_registered_keeps_nothing(made):
    assert made.keep_aside() == {}
    assert not (made.root / "kept").exists()


def test_a_packaged_unit_is_recorded_as_it_was_and_not_moved(made):
    made.systemd.shown = {
        "FragmentPath": "/usr/lib/systemd/system/rustdesk.service",
        "UnitFileState": "enabled",
        "ActiveState": "active",
        "ExecStart": "{ path=/usr/bin/rustdesk ; argv[]=/usr/bin/rustdesk --service }",
    }

    kept = made.keep_aside()

    assert kept == {"is_enabled": True, "is_active": True, "is_moved": False}
    record = json.loads((made.root / "kept" / "service.json").read_text())
    assert record == kept


def test_a_unit_file_of_somebody_else_in_etc_is_moved_aside(made):
    _unit(made).parent.mkdir()
    _unit(made).write_text("[Service]\nExecStart=/usr/bin/rustdesk --service\n")
    made.systemd.shown = {
        "FragmentPath": str(_unit(made)),
        "UnitFileState": "enabled",
        "ActiveState": "inactive",
    }

    kept = made.keep_aside()

    assert kept["is_moved"] is True
    assert not _unit(made).exists()
    assert "/usr/bin/rustdesk" in (made.root / "kept" / "rustdesk.service").read_text()


def test_a_unit_that_runs_the_agents_copy_is_not_kept(made):
    made.systemd.shown = {
        "FragmentPath": "/lib/systemd/system/rustdesk.service",
        "UnitFileState": "enabled",
        "ActiveState": "active",
        "ExecStart": f"{{ path={COPY} ; argv[]={COPY} --service }}",
    }

    assert made.keep_aside() == {}


def test_the_agents_own_unit_is_not_kept(made):
    made.register()
    made.systemd.shown = {"FragmentPath": str(_unit(made))}

    assert made.keep_aside() == {}


# --- stopping ---


def test_the_host_is_stopped_by_signal_and_never_by_the_units_own_stop(made):
    made.stop_hosts()

    assert ["systemctl", "kill", "--signal=SIGTERM", "rustdesk.service"] in (
        made.systemd.calls
    )
    assert not any(call[:2] == ["systemctl", "stop"] for call in made.systemd.calls)


def test_every_host_is_ended_and_a_viewer_left_alone(made):
    _process(made.proc, 101, "/usr/bin/rustdesk", "--service")
    _process(made.proc, 102, "/usr/bin/rustdesk", "--server")
    _process(made.proc, 103, "/usr/bin/rustdesk", "--connect", "10.0.0.2:21118")
    _process(made.proc, 104, "/usr/bin/python3", "app.py")

    made.stop_hosts()

    assert (101, signal.SIGTERM) in made.killed
    assert (102, signal.SIGTERM) in made.killed
    assert not any(pid in (103, 104) for pid, _ in made.killed)


@pytest.mark.parametrize(
    "arguments, expected",
    [
        (["rustdesk", "--connect", "a"], True),
        (["rustdesk", "--file-transfer", "a"], True),
        (["rustdesk", "--port-forward", "a"], True),
        (["rustdesk", "--service"], False),
        (["rustdesk", "--server"], False),
        (["rustdesk", "--tray"], False),
        (["rustdesk"], False),
    ],
)
def test_which_rustdesk_is_a_viewer(arguments, expected):
    assert is_viewer(arguments) is expected


# --- registering ---


def test_the_unit_runs_the_copy_and_says_whose_it_is(made):
    made.register()

    text = _unit(made).read_text()
    assert text.startswith("# Written by the Neutrino agent")
    assert f"ExecStart={COPY} --service" in text
    assert "ExecStop" not in text
    assert made.is_registered() is True
    assert made.systemd.calls == [
        ["systemctl", "disable", "rustdesk.service"],
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "rustdesk.service"],
    ]


def test_start_restarts_the_unit(made):
    made.start(None)

    assert made.systemd.calls == [["systemctl", "restart", "rustdesk.service"]]


def test_unregistering_removes_the_agents_unit_and_ends_its_copy(made):
    made.register()
    _process(made.proc, 201, COPY, "--server")
    _process(made.proc, 202, "/usr/bin/rustdesk", "--connect", "a")
    made.systemd.calls.clear()

    made.unregister()

    assert not _unit(made).exists()
    assert ["systemctl", "disable", "rustdesk.service"] in made.systemd.calls
    assert ["systemctl", "daemon-reload"] in made.systemd.calls
    assert [pid for pid, _ in made.killed] == [201]


def test_unregistering_leaves_somebody_elses_unit_alone(made):
    _unit(made).parent.mkdir()
    _unit(made).write_text("[Service]\n")

    made.unregister()

    assert _unit(made).exists()
    assert made.systemd.calls == []


# --- putting back ---


def test_a_moved_unit_is_put_back_enabled_and_started_as_it_was(made):
    _unit(made).parent.mkdir()
    _unit(made).write_text("[Service]\nExecStart=/usr/bin/rustdesk --service\n")
    made.systemd.shown = {
        "FragmentPath": str(_unit(made)),
        "UnitFileState": "enabled",
        "ActiveState": "active",
    }
    made.keep_aside()
    made.systemd.calls.clear()

    made.restore()

    assert "/usr/bin/rustdesk" in _unit(made).read_text()
    assert made.systemd.calls == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "rustdesk.service"],
        ["systemctl", "start", "rustdesk.service"],
    ]
    assert not (made.root / "kept" / "service.json").exists()


def test_a_unit_that_was_off_stays_off(made):
    made.systemd.shown = {
        "FragmentPath": "/usr/lib/systemd/system/rustdesk.service",
        "UnitFileState": "disabled",
        "ActiveState": "inactive",
    }
    made.keep_aside()
    made.systemd.calls.clear()

    made.restore()

    assert made.systemd.calls == []


def test_nothing_kept_puts_nothing_back(made):
    made.restore()

    assert made.systemd.calls == []


# --- the socket table ---


def test_the_listener_is_read_from_the_socket_table(made):
    _process(made.proc, 301, COPY, "--server")
    made.systemd.listening = (
        'LISTEN 0 128 0.0.0.0:21118 0.0.0.0:* users:(("rustdesk",pid=301,fd=9))\n'
    )

    assert made.listening_programs(21118) == [COPY]
    assert made.systemd.calls[-1][:2] == ["ss", "-ltnpH"]


def test_nothing_listening_is_an_empty_list(made):
    assert made.listening_programs(21118) == []


def test_a_listener_whose_program_cannot_be_read_still_counts(made):
    made.systemd.listening = "LISTEN 0 128 0.0.0.0:21118 0.0.0.0:*\n"

    assert made.listening_programs(21118) == [""]


def test_the_copys_processes_are_told_from_anybody_elses(made):
    _process(made.proc, 401, COPY, "--service")
    _process(made.proc, 402, "/usr/bin/rustdesk", "--service")

    assert made.copy_pids() == [401]
    assert sorted(made.host_pids()) == [401, 402]
