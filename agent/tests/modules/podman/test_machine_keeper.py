"""The keeper's script on each system, pinned byte for byte, and the service that runs it."""

import plistlib
from pathlib import Path

import pytest

from neutrino_agent.modules.podman.machine_keeper import (
    keeper_path,
    keeper_script,
    keeper_service,
)
from neutrino_agent.modules.shared.account_service import ServiceMachine
from neutrino_agent.modules.shared.account_service import darwin as darwin_service
from neutrino_agent.modules.shared.account_service import windows as windows_service

GOLDEN = Path(__file__).parent / "golden"
WINDOWS_BINARY = "C:\\Program Files\\Podman\\podman.exe"
DARWIN_BINARY = "/opt/podman/bin/podman"


def test_the_windows_keeper_is_the_golden_script_with_crlf_line_ends():
    script = keeper_script(os_name="windows", binary=WINDOWS_BINARY, provider="wsl")

    assert script.count("\r\n") == script.count("\n")
    assert script.replace("\r\n", "\n") == (GOLDEN / "keeper.cmd").read_text(
        encoding="utf-8"
    )


def test_the_windows_keeper_deletes_the_socket_before_each_start_and_retries_once():
    lines = keeper_script(
        os_name="windows", binary=WINDOWS_BINARY, provider="wsl"
    ).splitlines()

    starts = [i for i, line in enumerate(lines) if "machine start" in line]
    assert len(starts) == 2
    for start in starts:
        assert lines[start - 1] == 'if exist "%SOCKET%" del /q "%SOCKET%"'
    assert "machine stop" in lines[starts[1] - 2]
    assert lines[-2:] == ["ping -n 31 127.0.0.1 >nul", "goto loop"]


def test_the_mac_keeper_is_the_golden_script():
    script = keeper_script(os_name="darwin", binary=DARWIN_BINARY, provider="applehv")

    assert script == (GOLDEN / "keeper.sh").read_text(encoding="utf-8")


def test_no_keeper_on_linux():
    with pytest.raises(ValueError):
        keeper_script(os_name="linux", binary="/usr/bin/podman", provider="")
    with pytest.raises(ValueError):
        keeper_path(os_name="linux", module_dir="/var/lib/neutrino/agent/podman")


def test_the_windows_keeper_is_a_task_running_the_script_under_the_accounts_login():
    module_dir = "C:\\ProgramData\\Neutrino\\agent\\state\\podman"

    service = keeper_service(
        os_name="windows",
        module_dir=module_dir,
        account="lab",
        password="pw",
        binary=WINDOWS_BINARY,
        provider="wsl",
    )

    assert service.name == "podman"
    assert service.account == "lab"
    assert service.password == "pw"
    assert service.command == (f"{module_dir}\\keeper.cmd",)
    assert service.files == (
        (
            f"{module_dir}\\keeper.cmd",
            keeper_script(os_name="windows", binary=WINDOWS_BINARY, provider="wsl"),
        ),
    )
    assert service.listen_port == 0
    assert not service.environment
    assert not service.working_directory
    assert not service.is_output_discarded


def test_the_mac_keeper_is_a_launchdaemon_running_the_script_with_sh():
    module_dir = "/Library/Application Support/Neutrino/agent/state/podman"

    service = keeper_service(
        os_name="darwin",
        module_dir=module_dir,
        account="me",
        password="",
        binary=DARWIN_BINARY,
        provider="applehv",
    )

    assert service.command == ("/bin/sh", f"{module_dir}/keeper.sh")
    assert service.files[0][0] == f"{module_dir}/keeper.sh"


def test_the_task_runs_the_script_with_its_output_in_the_accounts_log():
    module_dir = "C:\\ProgramData\\Neutrino\\agent\\state\\podman"
    machine = ServiceMachine(
        os_name="windows",
        module_dir=module_dir,
        record_dir="C:\\ProgramData\\Neutrino\\agent\\config\\podman",
        lookup_account=lambda account: None,
    )
    service = keeper_service(
        os_name="windows",
        module_dir=module_dir,
        account="lab",
        password="pw",
        binary=WINDOWS_BINARY,
        provider="wsl",
    )

    assert windows_service.arguments_of(service, machine) == (
        f'/s /c "{module_dir}\\keeper.cmd >> {module_dir}\\lab.log 2>&1"'
    )
    assert windows_service.task_files(service, machine) == [
        {"path": path, "text": text} for path, text in service.files
    ]


def test_the_plist_runs_the_script_as_the_account_with_its_log():
    module_dir = "/Library/Application Support/Neutrino/agent/state/podman"
    service = keeper_service(
        os_name="darwin",
        module_dir=module_dir,
        account="me",
        password="",
        binary=DARWIN_BINARY,
        provider="applehv",
    )
    log = "/Library/Logs/Neutrino/agent/podman_me.log"

    plist = plistlib.loads(
        darwin_service.render_plist(service, home="/Users/me", log_path=log)
    )

    assert plist == {
        "Label": "com.neutrino.podman.me",
        "UserName": "me",
        "ProgramArguments": ["/bin/sh", f"{module_dir}/keeper.sh"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
