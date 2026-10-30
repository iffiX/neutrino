"""Instances on macOS, with launchd and the account database faked.

What these pin: each instance is a LaunchDaemon whose plist names the
account in ``UserName`` and carries an environment, a working directory and
a umask only when the service names them; the log file belongs to the
account, mode 0600, and a service that discards its output gets no log
file and no output paths; a plist holding a secret is root-only; a changed plist
or a job launchd does not hold is loaded again and a held unchanged one is
left alone; a remove boots the job out and deletes its plist, its log and
the account's files; and a state reads launchd's own word.
"""

import os
import plistlib
import stat

import pytest

from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
    ServiceMachine,
)
from neutrino_agent.modules.shared.account_service.darwin import render_plist
from neutrino_agent.modules.shared.subprocess_run import CommandResult

LABEL = "com.neutrino.demo.ann"


class Launchd:
    """launchctl, recorded; a label in ``loaded`` prints as running."""

    def __init__(self):
        self.calls: list = []
        self.loaded: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["launchctl", "print"]:
            label = command[2].split("/", 1)[1]
            if label not in self.loaded:
                return CommandResult(command, 113, "", "")
            return CommandResult(command, 0, "\tstate = running\n", "")
        if command[:2] == ["launchctl", "bootstrap"]:
            self.loaded.add(os.path.basename(command[3])[: -len(".plist")])
        if command[:2] == ["launchctl", "bootout"]:
            self.loaded.discard(command[2].split("/", 1)[1])
        return CommandResult(command, 0, "", "")


def service_with(**changes) -> AccountService:
    fields = {
        "name": "demo",
        "title": "Demo",
        "account": "ann",
        "command": ("/opt/demo/bin/demo", "--port", "8000"),
    }
    fields.update(changes)
    return AccountService(**fields)


@pytest.fixture
def launchd():
    return Launchd()


@pytest.fixture
def owners():
    return []


@pytest.fixture
def machine(launchd, tmp_path, owners):
    (tmp_path / "LaunchDaemons").mkdir()

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return AccountEntry(501, 20, "/Users/ann", "/bin/zsh")

    return ServiceMachine(
        os_name="darwin",
        module_dir=str(tmp_path / "state" / "demo"),
        record_dir=str(tmp_path / "config" / "demo"),
        lookup_account=lookup,
        run=launchd,
        chown=lambda path, uid, gid: owners.append((os.path.basename(path), uid, gid)),
        launchd_dir=str(tmp_path / "LaunchDaemons"),
        log_dir=str(tmp_path / "Logs"),
    )


def test_the_plist_carries_only_what_the_service_names():
    bare = plistlib.loads(
        render_plist(service_with(), home="/Users/ann", log_path="/Logs/demo_ann.log")
    )
    full = plistlib.loads(
        render_plist(
            service_with(
                environment={"HOME": "/Users/ann"}, working_directory="~", umask="077"
            ),
            home="/Users/ann",
            log_path="/Logs/demo_ann.log",
        )
    )

    assert bare == {
        "Label": LABEL,
        "UserName": "ann",
        "ProgramArguments": ["/opt/demo/bin/demo", "--port", "8000"],
        "StandardOutPath": "/Logs/demo_ann.log",
        "StandardErrorPath": "/Logs/demo_ann.log",
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    assert full["EnvironmentVariables"] == {"HOME": "/Users/ann"}
    assert full["WorkingDirectory"] == "/Users/ann"
    assert full["Umask"] == 0o77


def test_an_instance_gets_its_log_its_files_and_its_plist(
    machine, launchd, tmp_path, owners
):
    token = str(tmp_path / "state" / "demo" / "tokens" / "ann.token")
    service = service_with(files=((token, "t-ann"),))

    assert account_service.write(service, machine) is True
    assert account_service.write(service, machine) is False

    plist_path = tmp_path / "LaunchDaemons" / f"{LABEL}.plist"
    assert stat.S_IMODE(os.stat(plist_path).st_mode) == 0o644
    assert plistlib.loads(plist_path.read_bytes())["UserName"] == "ann"
    log = tmp_path / "Logs" / "demo_ann.log"
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(token).st_mode) == 0o600
    assert owners[:2] == [("ann.token", 501, 20), ("demo_ann.log", 501, 20)]
    assert launchd.calls == []


def test_a_discarded_output_names_no_log_file(machine, launchd, tmp_path, owners):
    service = service_with(is_output_discarded=True)

    assert account_service.write(service, machine) is True

    plist = plistlib.loads((tmp_path / "LaunchDaemons" / f"{LABEL}.plist").read_bytes())
    assert "StandardOutPath" not in plist and "StandardErrorPath" not in plist
    assert not (tmp_path / "Logs").exists()
    assert owners == []
    account_service.remove(service, machine)
    assert os.listdir(tmp_path / "LaunchDaemons") == []


def test_a_plist_holding_a_secret_is_root_only(machine, tmp_path):
    account_service.write(
        service_with(environment={"SECRET": "x"}, is_environment_secret=True), machine
    )

    plist_path = tmp_path / "LaunchDaemons" / f"{LABEL}.plist"
    assert stat.S_IMODE(os.stat(plist_path).st_mode) == 0o600


def test_a_write_keeps_what_the_log_holds(machine, tmp_path):
    account_service.write(service_with(), machine)
    log = tmp_path / "Logs" / "demo_ann.log"
    log.write_text("listening\n")

    account_service.write(service_with(), machine)

    assert log.read_text() == "listening\n"


def test_a_changed_or_unheld_job_is_loaded_again_and_a_held_one_left(
    machine, launchd, tmp_path
):
    service = service_with()
    account_service.write(service, machine)
    plist_path = str(tmp_path / "LaunchDaemons" / f"{LABEL}.plist")

    account_service.start(service, machine, is_restart=False)
    account_service.start(service, machine, is_restart=False)
    account_service.start(service, machine, is_restart=True)

    # Each start enables the job first, so one a stop disabled loads again.
    enable = ["launchctl", "enable", f"system/{LABEL}"]
    assert launchd.calls == [
        enable,
        ["launchctl", "print", f"system/{LABEL}"],
        ["launchctl", "bootout", f"system/{LABEL}"],
        ["launchctl", "bootstrap", "system", plist_path],
        enable,
        ["launchctl", "print", f"system/{LABEL}"],
        enable,
        ["launchctl", "bootout", f"system/{LABEL}"],
        ["launchctl", "bootstrap", "system", plist_path],
    ]


def test_a_stop_disables_and_boots_the_job_out_and_a_remove_deletes_its_files(
    machine, launchd, tmp_path
):
    token = str(tmp_path / "tokens" / "ann.token")
    service = service_with(files=((token, "t"),), directories=(str(tmp_path / "run"),))
    account_service.write(service, machine)
    launchd.calls.clear()

    account_service.stop(service, machine)
    account_service.remove(service, machine)

    # A stopped job stays stopped across a reboot.
    assert (
        launchd.calls
        == [
            ["launchctl", "disable", f"system/{LABEL}"],
            ["launchctl", "bootout", f"system/{LABEL}"],
        ]
        * 2
    )
    assert os.listdir(tmp_path / "LaunchDaemons") == []
    assert os.listdir(tmp_path / "Logs") == []
    assert not os.path.exists(token) and not os.path.exists(tmp_path / "run")


def test_the_states_read_launchd(machine, launchd):
    launchd.loaded.add(LABEL)

    assert account_service.states(
        [service_with(), service_with(account="bob")], machine
    ) == {
        "ann": {"is_running": True, "code": ""},
        "bob": {"is_running": False, "code": ""},
    }


def test_a_named_log_file_is_the_services_own(machine, tmp_path):
    account_service.write(service_with(log_name="own.log"), machine)

    plist = plistlib.loads((tmp_path / "LaunchDaemons" / f"{LABEL}.plist").read_bytes())
    assert plist["StandardOutPath"] == str(tmp_path / "Logs" / "own.log")
    assert account_service.log_path("demo", "ann", machine, "own.log") == (
        str(tmp_path / "Logs" / "own.log")
    )


def test_forget_has_nothing_to_delete(machine, launchd):
    account_service.forget("demo", machine)

    assert launchd.calls == []
