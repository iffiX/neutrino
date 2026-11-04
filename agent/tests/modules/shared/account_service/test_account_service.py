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

from neutrino_agent.modules.shared.subprocess_run import CommandResult

from tests.conftest import chowned_path, fd_owners


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
    remove_account_files(service, chown=lambda target, uid, gid: None)
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


# --- a folder of root's the account reads ---


def test_on_linux_a_read_file_is_roots_in_roots_folder_and_the_accounts_group_reads(
    tmp_path, monkeypatch
):
    owners = fd_owners(monkeypatch, {})
    machine = machine_for(
        "linux", tmp_path, chown=lambda target, uid, gid: os.fchown(target, uid, gid)
    )
    run_dir = str(tmp_path / "run" / "ann")
    key = run_dir + "/host_key"
    service = AccountService(
        name="demo",
        title="Demo",
        account="ann",
        command=("/bin/demo",),
        read_files=((key, "secret\n"),),
    )

    assert account_service.write_read_files(service, machine) is True
    assert account_service.write_read_files(service, machine) is False

    assert open(key).read() == "secret\n"
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o640
    assert stat.S_IMODE(os.stat(run_dir).st_mode) == 0o750
    assert (run_dir, 0, 1000) in owners
    assert (key, 0, 1000) in owners
    account_service.remove_read_files(service)
    assert not os.path.exists(run_dir)


@pytest.mark.parametrize("planted", ["host_key", "host_key.new"])
def test_a_link_in_a_read_folder_turns_no_write_mode_or_owner_onto_another_file(
    tmp_path, planted
):
    owners = []
    machine = machine_for(
        "linux",
        tmp_path,
        chown=lambda target, uid, gid: owners.append((chowned_path(target), uid, gid)),
    )
    run_dir = tmp_path / "run" / "ann"
    run_dir.mkdir(parents=True)
    held = tmp_path / "held"
    held.write_text("kept\n")
    os.chmod(held, 0o600)
    (run_dir / planted).symlink_to(held)

    account_service.write_read_file(str(run_dir / "host_key"), "key\n", "ann", machine)

    assert held.read_text() == "kept\n"
    assert stat.S_IMODE(held.stat().st_mode) == 0o600
    assert str(held) not in [path for path, _uid, _gid in owners]
    assert (run_dir / "host_key").read_text() == "key\n"


def test_on_a_mac_a_read_file_is_roots_alone_with_an_entry_for_the_account(
    tmp_path,
):
    ran = []

    def run(command, *, is_checked=True, **_):
        ran.append(list(command))
        return CommandResult(list(command), 0, "drwx------ 2 root wheel /x\n", "")

    machine = machine_for(
        "darwin", tmp_path, run=run, chown=lambda target, uid, gid: None
    )
    run_dir = str(tmp_path / "run" / "ann")
    key = run_dir + "/host_key"

    account_service.make_read_dir(run_dir, "ann", machine)
    account_service.write_read_file(key, "secret\n", "ann", machine)

    assert stat.S_IMODE(os.stat(run_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    assert ran == [
        ["/bin/ls", "-led", run_dir],
        ["/bin/chmod", "-N", run_dir],
        [
            "/bin/chmod",
            "+a",
            "user:ann allow list,search,readattr,readextattr,readsecurity",
            run_dir,
        ],
        [
            "/bin/chmod",
            "+a",
            "user:ann allow read,readattr,readextattr,readsecurity",
            key + ".new",
        ],
    ]


def test_an_earlier_versions_folder_is_taken_back_and_its_files_cleared(
    tmp_path, monkeypatch
):
    owners = fd_owners(monkeypatch, {})
    machine = machine_for(
        "linux", tmp_path, chown=lambda target, uid, gid: os.fchown(target, uid, gid)
    )
    run_dir = tmp_path / "run" / "ann"
    run_dir.mkdir(parents=True)
    (run_dir / "host_key").write_text("the machine's key")
    (run_dir / "authorized_key.new").symlink_to("/etc/passwd")
    (run_dir / "kept").mkdir()

    account_service.make_read_dir(str(run_dir), "ann", machine)
    (run_dir / "authorized_key").write_text("key")
    account_service.make_read_dir(str(run_dir), "ann", machine)

    assert sorted(os.listdir(run_dir)) == ["authorized_key", "kept"]
    assert owners[0] == (str(run_dir), 0, 1000)
