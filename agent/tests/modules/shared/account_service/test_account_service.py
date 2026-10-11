"""The account service layer's one definition and its dispatch by system.

What these pin: the names an instance takes on each system follow the
module's name and the account; a file is written only when its text
changes; the account's files land mode 0600 and its directories 0700, each
handed to the account; a system the layer has no file for is refused typed;
and the log path and the units answer per system.
"""

import os
import stat

import pytest

from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
    ServiceMachine,
    label,
    remove_account_files,
    task_name,
    unit_name,
    write_account_files,
    write_if_changed,
)


def machine_for(os_name, tmp_path, **tools) -> ServiceMachine:
    return ServiceMachine(
        os_name=os_name,
        module_dir=str(tmp_path / "state" / "demo"),
        record_dir=str(tmp_path / "config" / "demo"),
        lookup_account=lambda account: AccountEntry(1000, 1000, "/home/ann"),
        **tools,
    )


def test_the_names_follow_the_module_and_the_account():
    assert unit_name("vscode", "ann") == "neutrino_vscode@ann.service"
    assert label("code_server", "ann") == "com.neutrino.code_server.ann"
    assert task_name("cloudcli", "ann") == "neutrino_cloudcli_ann"


def test_a_file_is_written_only_when_its_text_changes(tmp_path):
    path = str(tmp_path / "ann.token")

    assert write_if_changed(path, "t1", 0o600) is True
    assert write_if_changed(path, "t1", 0o600) is False
    assert write_if_changed(path, "t2", 0o600) is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_the_accounts_files_and_directories_are_its_own(tmp_path):
    owners = []
    machine = machine_for(
        "linux", tmp_path, chown=lambda path, uid, gid: owners.append((path, uid, gid))
    )
    token = str(tmp_path / "tokens" / "ann.token")
    run_dir = str(tmp_path / "run" / "ann")
    service = AccountService(
        name="demo",
        title="Demo",
        account="ann",
        command=("/bin/demo",),
        files=((token, "t-ann"),),
        directories=(run_dir,),
    )
    entry = AccountEntry(1001, 1002, "/home/ann")

    assert write_account_files(service, entry, machine) is True
    assert write_account_files(service, entry, machine) is False

    assert open(token).read() == "t-ann"
    assert stat.S_IMODE(os.stat(token).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(run_dir).st_mode) == 0o700
    assert owners[:2] == [(token, 1001, 1002), (run_dir, 1001, 1002)]
    remove_account_files(service)
    assert not os.path.exists(token) and not os.path.exists(run_dir)


def test_a_system_without_a_file_is_refused_typed(tmp_path):
    machine = machine_for("plan9", tmp_path)
    service = AccountService(name="demo", title="Demo", account="ann", command=("x",))

    for call in (
        lambda: account_service.define(service, machine),
        lambda: account_service.write(service, machine),
        lambda: account_service.states([service], machine),
    ):
        with pytest.raises(PlatformUnsupportedError):
            call()


@pytest.mark.parametrize(
    "os_name, expected",
    [
        ("linux", ""),
        ("darwin", "/Library/Logs/Neutrino/agent/demo_ann.log"),
        ("windows", "C:\\state\\demo\\ann.log"),
    ],
)
def test_the_log_path_is_the_systems_own(os_name, expected):
    machine = ServiceMachine(
        os_name=os_name,
        module_dir="C:\\state\\demo" if os_name == "windows" else "/state/demo",
        record_dir="/config/demo",
        lookup_account=None,
    )

    assert account_service.log_path("demo", "ann", machine) == expected


def test_a_named_log_file_is_used_where_the_system_keeps_one():
    darwin = ServiceMachine(
        os_name="darwin", module_dir="/s", record_dir="/c", lookup_account=None
    )
    windows = ServiceMachine(
        os_name="windows", module_dir="C:\\s", record_dir="C:\\c", lookup_account=None
    )

    assert account_service.log_path("demo", "ann", darwin, "own.log") == (
        "/Library/Logs/Neutrino/agent/own.log"
    )
    assert account_service.log_path("demo", "ann", windows, "own.log") == (
        "C:\\s\\own.log"
    )


def test_only_linux_has_units(tmp_path):
    service = AccountService(name="demo", title="Demo", account="ann", command=("x",))

    assert account_service.units([service], machine_for("linux", tmp_path)) == [
        "neutrino_demo@ann.service"
    ]
    assert account_service.units([service], machine_for("darwin", tmp_path)) == []
    assert account_service.units([service], machine_for("windows", tmp_path)) == []
