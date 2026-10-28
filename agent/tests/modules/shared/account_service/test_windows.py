"""Instances on Windows, with the PowerShell host, icacls and the process table faked.

What these pin: a write puts the account's files and its log on disk,
reachable by the account, SYSTEM and the administrators alone through
icacls, and asks the host to register a task signed in with the account's
login only when the task is missing or its description differs, a changed
one after its instance is stopped; a service with an environment or a
working directory runs a script, a bare one runs the program itself; a
service that discards its output runs its script into the null device and
is found by the script; the task's description carries a digest that moves
when what it runs, its login or a file it reads changes; every write and a
forget remove the rules an older build opened; a stop takes the instance's
process tree before the task stops and ends it after; a start first ends
what is left of the instance; an instance whose service names a port runs
only while a process of its tree listens on it, any other while its task
runs; a task Windows cannot sign in reads ``credential_invalid``; a
remove unregisters the task and deletes what it ran from; and every write
holds the account's batch logon right before the task is read, and a
remove releases it after the task is unregistered. Every request the host
is sent is pinned whole.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountService,
    ServiceMachine,
)
from neutrino_agent.modules.shared.account_service.windows import (
    render_script,
    task_arguments,
    task_description,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from tests.conftest import FakeBatchLogon, FakeProcessTable, RecordingHost

SYSTEM = "*S-1-5-18"
ADMINISTRATORS = "*S-1-5-32-544"


class Icacls:
    """icacls, recording each argument vector and exiting with a set code."""

    def __init__(self, code=0):
        self.calls: list = []
        self.code = code

    def __call__(self, argv, **_):
        self.calls.append(list(argv))
        return CommandResult(
            command=list(argv), exit_code=self.code, stdout="", stderr=""
        )


class Timeline:
    """One list the host and the process table both write their steps to."""

    def __init__(self, processes=(), listeners=None, answers=None):
        self.steps: list = []
        self.host = RecordingHost(answers)
        self.table = FakeProcessTable(processes, listeners)
        host_call = self.host.call
        table_entries = self.table.entries
        table_end = self.table.end

        def call(op, args, **kwargs):
            self.steps.append(op)
            return host_call(op, args, **kwargs)

        def entries():
            self.steps.append("entries")
            return table_entries()

        def end(pids):
            self.steps.append(("end", list(pids)))
            table_end(pids)

        self.host.call = call
        self.table.entries = entries
        self.table.end = end


@pytest.fixture
def module_dir(tmp_path):
    return str(tmp_path / "demo")


def service_with(module_dir, **changes) -> AccountService:
    fields = {
        "name": "demo",
        "title": "Demo",
        "account": "hanha",
        "command": (module_dir + "\\demo.exe", "--port", "8000"),
        "password": "pw",
    }
    fields.update(changes)
    return AccountService(**fields)


def machine_with(
    module_dir, host, table=None, run=None, batch_logon=None
) -> ServiceMachine:
    return ServiceMachine(
        os_name="windows",
        module_dir=module_dir,
        record_dir="C:\\ProgramData\\Neutrino\\agent\\config\\demo",
        lookup_account=lambda account: None,
        run=run if run is not None else Icacls(),
        powershell=host,
        processes=table if table is not None else FakeProcessTable(),
        batch_logon=batch_logon,
    )


def read(path) -> bytes:
    with open(path, "rb") as stream:
        return stream.read()


def test_a_bare_service_is_a_task_running_the_program_itself(module_dir):
    host = RecordingHost({"task_read": {"is_present": False}})
    icacls = Icacls()
    token = module_dir + "\\tokens\\hanha.token"
    log = module_dir + "\\hanha.log"
    service = service_with(module_dir, files=((token, "t-1"),), listen_port=8000)

    assert account_service.write(service, machine_with(module_dir, host, run=icacls))

    arguments = f'/s /c "{module_dir}\\demo.exe --port 8000 >> {log} 2>&1"'
    assert host.calls == [
        ("task_read", {"task": "neutrino_demo_hanha"}),
        (
            "task_write",
            {
                "task": "neutrino_demo_hanha",
                "description": task_description(arguments, service, ["t-1"]),
                "program": "cmd.exe",
                "arguments": arguments,
                "account": "hanha",
                "password": "pw",  # scan: allow
            },
        ),
        ("rules_forget", {"prefix": "neutrino_demo_port_"}),
    ]
    assert read(token) == b"t-1"
    assert read(log) == b""
    assert icacls.calls == [
        [
            "icacls.exe",
            token,
            "/inheritance:r",
            "/grant:r",
            "hanha:R",
            f"{SYSTEM}:F",
            f"{ADMINISTRATORS}:F",
        ],
        [
            "icacls.exe",
            log,
            "/inheritance:r",
            "/grant:r",
            "hanha:M",
            f"{SYSTEM}:F",
            f"{ADMINISTRATORS}:F",
        ],
    ]
    assert "pw" not in host.args_of("task_write")[0]["description"]


def test_a_service_with_an_environment_runs_a_script(module_dir):
    host = RecordingHost({"task_read": {"is_present": False}})
    service = service_with(
        module_dir,
        command=("C:\\node\\node.exe", "C:\\app\\index.js"),
        environment={"HOST": "127.0.0.1", "PATH": "C:\\node;%PATH%"},
        working_directory="~",
    )

    account_service.write(service, machine_with(module_dir, host))

    script_path = module_dir + "\\run\\hanha.cmd"
    log = module_dir + "\\hanha.log"
    (written,) = host.args_of("task_write")
    assert written["arguments"] == f'/s /c "{script_path} >> {log} 2>&1"'
    assert read(script_path) == (
        b"@echo off\r\n"
        b'set "HOST=127.0.0.1"\r\n'
        b'set "PATH=C:\\node;%PATH%"\r\n'
        b'cd /d "%USERPROFILE%"\r\n'
        b"C:\\node\\node.exe C:\\app\\index.js\r\n"
    )


def test_a_directory_the_account_owns_is_made_and_left_to_it(module_dir, tmp_path):
    host = RecordingHost({"task_read": {"is_present": False}})
    icacls = Icacls()
    directory = str(tmp_path / "data")
    service = service_with(module_dir, directories=(directory,))

    account_service.write(service, machine_with(module_dir, host, run=icacls))

    assert (tmp_path / "data").is_dir()
    assert [
        "icacls.exe",
        directory,
        "/inheritance:r",
        "/grant:r",
        "hanha:(OI)(CI)M",
        f"{SYSTEM}:(OI)(CI)F",
        f"{ADMINISTRATORS}:(OI)(CI)F",
    ] in icacls.calls


def test_a_file_icacls_refuses_fails_the_write_before_any_task(module_dir):
    host = RecordingHost({"task_read": {"is_present": False}})
    token = module_dir + "\\tokens\\hanha.token"
    service = service_with(module_dir, files=((token, "t"),))

    with pytest.raises(OSError, match="icacls refused"):
        account_service.write(service, machine_with(module_dir, host, run=Icacls(5)))

    assert host.calls == []


def test_a_discarded_output_runs_the_script_into_the_null_device(module_dir):
    host = RecordingHost({"task_read": {"is_present": False}})
    script_path = module_dir + "\\run\\hanha.cmd"
    table = FakeProcessTable([(40, 4, 10, "cmd.exe", f'cmd /c "{script_path}"', "")])
    machine = machine_with(module_dir, host, table)
    service = service_with(module_dir, is_output_discarded=True)

    account_service.write(service, machine)
    account_service.stop(service, machine)

    (written,) = host.args_of("task_write")
    assert written["arguments"] == f'/s /c "{script_path} > NUL 2>&1"'
    assert table.ended == [40]
    assert (
        task_arguments("C:\\x.exe", ["--a"], "") == '/s /c "C:\\x.exe --a > NUL 2>&1"'
    )


def test_a_script_without_a_working_directory_enters_none(module_dir):
    text = render_script(service_with(module_dir, environment={"A": "1"}))

    assert (
        text == "@echo off\r\n"
        'set "A=1"\r\n'
        f"{module_dir}\\demo.exe --port 8000\r\n"
    )


def test_the_digest_moves_with_the_login_the_command_and_a_file(module_dir):
    def description(**changes):
        host = RecordingHost({"task_read": {"is_present": False}})
        account_service.write(
            service_with(module_dir, **changes), machine_with(module_dir, host)
        )
        return host.args_of("task_write")[0]["description"]

    token = module_dir + "\\t"
    assert description() == description()
    assert description().startswith("neutrino:")
    assert description(password="new") != description()
    assert description(command=(module_dir + "\\demo.exe", "--port", "8001")) != (
        description()
    )
    assert description(files=((token, "a"),)) != description(files=((token, "b"),))


def test_an_unchanged_task_is_left_running(module_dir):
    first = RecordingHost({"task_read": {"is_present": False}})
    service = service_with(module_dir)
    account_service.write(service, machine_with(module_dir, first))
    (written,) = first.args_of("task_write")
    timeline = Timeline(
        answers={
            "task_read": {
                "is_present": True,
                "description": written["description"],
                "state": "Running",
            }
        }
    )

    is_registered = account_service.write(
        service, machine_with(module_dir, timeline.host, timeline.table)
    )

    assert is_registered is False
    assert timeline.steps == ["task_read", "rules_forget"]


def test_a_changed_task_stops_its_instance_before_it_is_registered_again(module_dir):
    log = module_dir + "\\hanha.log"
    timeline = Timeline(
        processes=[
            (30, 4, 100, "cmd.exe", f'cmd.exe /s /c "x >> {log} 2>&1"', ""),
            (31, 30, 101, "node.exe", "node index.js", ""),
        ],
        answers={
            "task_read": {
                "is_present": True,
                "description": "neutrino:old",
                "state": "",
            }
        },
    )

    account_service.write(
        service_with(module_dir),
        machine_with(module_dir, timeline.host, timeline.table),
    )

    assert timeline.steps == [
        "task_read",
        "entries",
        "task_stop",
        ("end", [30, 31]),
        "task_write",
        "rules_forget",
    ]


def test_a_refused_login_is_credential_invalid(module_dir):
    error = ModuleApplyError("credential_invalid", {"account": "hanha"})
    host = RecordingHost({"task_read": {"is_present": False}, "task_write": error})

    with pytest.raises(ModuleApplyError) as refused:
        account_service.write(service_with(module_dir), machine_with(module_dir, host))

    assert refused.value.code == "credential_invalid"


def test_a_write_holds_the_batch_logon_right_before_the_task_is_read(module_dir):
    host = RecordingHost({"task_read": {"is_present": False}})
    machine = machine_with(module_dir, host, batch_logon=FakeBatchLogon(host.calls))

    account_service.write(service_with(module_dir), machine)

    assert host.ops() == ["batch_logon_hold", "task_read", "task_write", "rules_forget"]
    assert host.args_of("batch_logon_hold") == [
        {"account": "hanha", "task": "neutrino_demo_hanha"}
    ]


def test_a_write_the_batch_logon_right_refuses_registers_no_task(module_dir):
    host = RecordingHost({"task_read": {"is_present": False}})
    batch_logon = FakeBatchLogon(host.calls)

    def refuse(account, task, password):
        raise ModuleApplyError("credential_invalid", {"account": account})

    batch_logon.hold = refuse

    with pytest.raises(ModuleApplyError):
        account_service.write(
            service_with(module_dir),
            machine_with(module_dir, host, batch_logon=batch_logon),
        )

    assert host.calls == []


def test_a_remove_releases_the_batch_logon_right_after_the_task_goes(module_dir):
    host = RecordingHost()
    machine = machine_with(module_dir, host, batch_logon=FakeBatchLogon(host.calls))

    account_service.remove(service_with(module_dir), machine)

    assert host.ops() == ["task_stop", "task_remove", "batch_logon_release"]
    assert host.args_of("batch_logon_release") == [
        {"account": "hanha", "task": "neutrino_demo_hanha"}
    ]


def test_a_path_with_spaces_is_quoted_inside_the_command():
    arguments = task_arguments(
        "C:\\Program Data\\demo\\demo.exe",
        ["--port", "8000"],
        "C:\\Program Data\\demo\\ann.log",
    )

    assert arguments == (
        '/s /c ""C:\\Program Data\\demo\\demo.exe" --port 8000 '
        '>> "C:\\Program Data\\demo\\ann.log" 2>&1"'
    )


def test_a_stop_takes_the_tree_before_the_task_stops_and_ends_it_after(module_dir):
    log = module_dir + "\\hanha.log"
    timeline = Timeline(
        processes=[
            (4, 0, 0, "System", "", ""),
            (30, 4, 100, "cmd.exe", f'cmd.exe /s /c "code.exe >> {log} 2>&1"', ""),
            (31, 30, 101, "code.exe", "code.exe serve-web", ""),
            (32, 31, 102, "node.exe", "node server.js", ""),
            (33, 30, 50, "old.exe", "a process that took a reused pid", ""),
            (34, 4, 103, "other.exe", "someone else's", ""),
        ]
    )

    account_service.stop(
        service_with(module_dir),
        machine_with(module_dir, timeline.host, timeline.table),
    )

    assert timeline.steps == ["entries", "task_stop", ("end", [30, 31, 32])]
    assert timeline.host.args_of("task_stop") == [{"task": "neutrino_demo_hanha"}]


def test_a_start_first_ends_what_is_left_of_the_instance(module_dir):
    timeline = Timeline(answers={"task_read": {"is_present": True, "state": "Ready"}})
    machine = machine_with(module_dir, timeline.host, timeline.table)

    account_service.start(service_with(module_dir), machine, is_restart=True)

    assert timeline.steps == [
        "task_read",
        "entries",
        "task_stop",
        ("end", []),
        "task_start",
    ]
    assert timeline.host.args_of("task_start") == [{"task": "neutrino_demo_hanha"}]


def test_a_running_task_is_not_started_again(module_dir):
    host = RecordingHost({"task_read": {"is_present": True, "state": "Running"}})

    account_service.start(
        service_with(module_dir), machine_with(module_dir, host), is_restart=False
    )

    assert host.ops() == ["task_read"]


def test_a_remove_unregisters_the_task_and_deletes_what_it_ran_from(
    module_dir, tmp_path
):
    host = RecordingHost({"task_read": {"is_present": False}})
    machine = machine_with(module_dir, host)
    token = module_dir + "\\tokens\\hanha.token"
    directory = str(tmp_path / "data")
    service = service_with(
        module_dir,
        files=((token, "t"),),
        directories=(directory,),
        environment={"A": "1"},
    )
    account_service.write(service, machine)
    (tmp_path / "data" / "kept.txt").write_text("x")

    account_service.remove(service, machine)

    assert host.ops()[-2:] == ["task_stop", "task_remove"]
    assert host.args_of("task_remove") == [{"task": "neutrino_demo_hanha"}]
    for path in (token, module_dir + "\\run\\hanha.cmd", module_dir + "\\hanha.log"):
        with pytest.raises(OSError):
            read(path)
    assert not (tmp_path / "data").exists()


def test_the_states_read_each_task_its_listener_and_its_last_result(module_dir):
    log = module_dir + "\\hanha.log"
    host = RecordingHost(
        {
            "task_states": {
                "tasks": [
                    {
                        "name": "neutrino_demo_hanha",
                        "state": "Ready",
                        "last_result": -2147023570,
                    },
                    {"name": "neutrino_demo_bob", "state": "Running", "last_result": 0},
                ]
            }
        }
    )
    table = FakeProcessTable(
        [
            (30, 4, 100, "cmd.exe", f'cmd.exe /s /c "code.exe >> {log} 2>&1"', ""),
            (31, 30, 101, "code.exe", "code.exe serve-web --port 8000", ""),
        ],
        listeners={8000: [31]},
    )
    services = [
        service_with(module_dir, listen_port=8000),
        service_with(module_dir, account="bob"),
    ]

    states = account_service.states(services, machine_with(module_dir, host, table))

    assert states == {
        "hanha": {"is_running": True, "code": "credential_invalid"},
        "bob": {"is_running": True, "code": ""},
    }
    assert host.calls == [("task_states", {"prefix": "neutrino_demo_"})]


@pytest.mark.parametrize(
    "task_state,listeners,listen_port,is_running",
    [
        ("Running", {8000: [31]}, 8000, True),
        ("Running", {}, 8000, False),
        ("Ready", {8000: [31]}, 8000, True),
        ("Running", {8000: [99]}, 8000, False),
        ("Running", {}, 0, True),
        ("Ready", {8000: [31]}, 0, False),
    ],
)
def test_an_instance_with_a_port_runs_only_while_its_tree_listens_on_it(
    module_dir, task_state, listeners, listen_port, is_running
):
    log = module_dir + "\\hanha.log"
    host = RecordingHost(
        {
            "task_states": {
                "tasks": [
                    {
                        "name": "neutrino_demo_hanha",
                        "state": task_state,
                        "last_result": 0,
                    }
                ]
            }
        }
    )
    table = FakeProcessTable(
        [
            (30, 4, 100, "cmd.exe", f'cmd.exe /s /c "x >> {log} 2>&1"', ""),
            (31, 30, 101, "node.exe", "node index.js", ""),
            (99, 4, 5, "other.exe", "someone else's", ""),
        ],
        listeners=listeners,
    )

    states = account_service.states(
        [service_with(module_dir, listen_port=listen_port)],
        machine_with(module_dir, host, table),
    )

    assert states["hanha"]["is_running"] is is_running


def test_a_discarded_output_is_found_listening_by_its_script(module_dir):
    script_path = module_dir + "\\run\\hanha.cmd"
    host = RecordingHost(
        {"task_states": {"tasks": [{"name": "neutrino_demo_hanha", "state": "Ready"}]}}
    )
    table = FakeProcessTable(
        [
            (30, 4, 100, "cmd.exe", f'cmd.exe /s /c "{script_path} > NUL 2>&1"', ""),
            (31, 30, 101, "codeg-server.exe", "codeg-server", ""),
        ],
        listeners={8000: [31]},
    )

    states = account_service.states(
        [service_with(module_dir, listen_port=8000, is_output_discarded=True)],
        machine_with(module_dir, host, table),
    )

    assert states["hanha"]["is_running"] is True


def test_a_status_the_host_cannot_give_reads_as_nothing_running(module_dir):
    host = RecordingHost({"task_states": OSError("gone")})

    states = account_service.states(
        [service_with(module_dir)], machine_with(module_dir, host)
    )

    assert states == {"hanha": {"is_running": False, "code": ""}}
    assert account_service.states([], machine_with(module_dir, host)) == {}


def test_forget_removes_the_rules_an_older_build_opened(module_dir):
    host = RecordingHost()

    account_service.forget("demo", machine_with(module_dir, host))

    assert host.calls == [("rules_forget", {"prefix": "neutrino_demo_port_"})]
