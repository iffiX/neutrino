"""The keeper: what starts the account's Podman machine at boot and again when it stops.

The keeper is an account service of the module's own name: the scheduled
task ``neutrino_podman_<account>`` under the account's login on Windows,
the LaunchDaemon ``com.neutrino.podman.<account>`` with ``UserName`` on
macOS. Its script loops by itself, since Task Scheduler did not start a
task again after its program exited: every 30 seconds it reads the
machine's state and starts the machine when it is not running. A state it
cannot read is unknown, and the keeper waits for the next round. On Windows
each start first deletes the socket file a restart with the machine running
leaves behind, and a start that fails is followed by a stop and one more
start, so Podman moves an ssh port that fell into a range Windows reserved
at boot.

Pure: the script's text and the service's description.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ntpath
import posixpath

from neutrino_agent.modules.podman.constants import (
    PODMAN_DARWIN_TEMP_DIR_COMMAND,
    PODMAN_DARWIN_TEMP_DIR_VARIABLE,
    PODMAN_GENERATED_MARKER,
    PODMAN_MACHINE_KEEPER_INTERVAL_S,
    PODMAN_MACHINE_KEEPER_NAMES,
    PODMAN_MACHINE_KEEPER_TITLE,
    PODMAN_MACHINE_NAME,
    PODMAN_MACHINE_PROVIDER_VARIABLE,
    PODMAN_MACHINE_WINDOWS_SOCKET,
    PODMAN_MODULE_NAME,
)
from neutrino_agent.modules.shared.account_service import AccountService

# The keeper on Windows. The program's folder goes first on PATH so the
# state is read through ``for /f`` with no quoted program path in it.
_WINDOWS_SCRIPT = """@echo off
rem {marker}
cd /d "%USERPROFILE%"
set "{variable}={provider}"
set "PATH={program_dir};%PATH%"
set "SOCKET={socket}"
:loop
set "STATE="
for /f "usebackq delims=" %%s in (`podman machine inspect --format "{{{{.State}}}}" {machine} 2^>nul`) do set "STATE=%%s"
if "%STATE%"=="" goto wait
if /i "%STATE%"=="running" goto wait
echo %date% %time% the machine is "%STATE%", starting it
if exist "%SOCKET%" del /q "%SOCKET%"
podman machine start {machine}
if not errorlevel 1 goto wait
echo %date% %time% the start failed, stopping the machine and starting it once more
podman machine stop {machine}
if exist "%SOCKET%" del /q "%SOCKET%"
podman machine start {machine}
:wait
ping -n {pings} 127.0.0.1 >nul
goto loop
"""

# The keeper on macOS. Podman keeps the machine's sockets under
# ``$TMPDIR/podman``, and ``TMPDIR`` is the account's own temporary
# directory, the one its sessions and the agent's machine commands have.
_DARWIN_SCRIPT = """#!/bin/sh
{marker}
export {variable}={provider}
temp=$({temp_dir_command}) && export {temp_dir_variable}="$temp"
PATH="{program_dir}:$PATH"
while :; do
    state=$(podman machine inspect --format '{{{{.State}}}}' {machine} 2>/dev/null)
    if [ -n "$state" ] && [ "$state" != running ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') the machine is \\"$state\\", starting it"
        if ! podman machine start {machine}; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') the start failed, stopping the machine and starting it once more"
            podman machine stop {machine}
            podman machine start {machine}
        fi
    fi
    sleep {interval}
done
"""


def keeper_script(*, os_name: str, binary: str, provider: str) -> str:
    """The keeper's script on one system.

    Args:
        os_name: ``windows`` or ``darwin``.
        binary: Podman's program on the computer.
        provider: The machine provider the script names to Podman.

    Returns:
        The ``.cmd`` text with CRLF line ends on Windows, the sh text on
        macOS.

    Raises:
        ValueError: For a system with no keeper.
    """
    if os_name == "windows":
        text = _WINDOWS_SCRIPT.format(
            marker=PODMAN_GENERATED_MARKER.lstrip("# "),
            variable=PODMAN_MACHINE_PROVIDER_VARIABLE,
            provider=provider,
            program_dir=ntpath.dirname(binary),
            socket=PODMAN_MACHINE_WINDOWS_SOCKET,
            machine=PODMAN_MACHINE_NAME,
            # ping waits about a second between its echoes, after the first.
            pings=PODMAN_MACHINE_KEEPER_INTERVAL_S + 1,
        )
        return text.replace("\n", "\r\n")
    if os_name == "darwin":
        return _DARWIN_SCRIPT.format(
            marker=PODMAN_GENERATED_MARKER,
            variable=PODMAN_MACHINE_PROVIDER_VARIABLE,
            provider=provider,
            temp_dir_command=" ".join(PODMAN_DARWIN_TEMP_DIR_COMMAND),
            temp_dir_variable=PODMAN_DARWIN_TEMP_DIR_VARIABLE,
            program_dir=posixpath.dirname(binary),
            machine=PODMAN_MACHINE_NAME,
            interval=PODMAN_MACHINE_KEEPER_INTERVAL_S,
        )
    raise ValueError(f"no keeper on {os_name!r}")


def keeper_path(*, os_name: str, module_dir: str) -> str:
    """Where the keeper's script is written: in the module's directory under the state root.

    Args:
        os_name: ``windows`` or ``darwin``.
        module_dir: The module's directory under the state root.

    Returns:
        ``keeper.cmd`` on Windows, ``keeper.sh`` on macOS, in that directory.

    Raises:
        ValueError: For a system with no keeper.
    """
    name = PODMAN_MACHINE_KEEPER_NAMES.get(os_name)
    if name is None:
        raise ValueError(f"no keeper on {os_name!r}")
    join = ntpath.join if os_name == "windows" else posixpath.join
    return join(module_dir, name)


def keeper_service(
    *,
    os_name: str,
    module_dir: str,
    account: str,
    password: str,
    binary: str,
    provider: str,
) -> AccountService:
    """The keeper as the account service layer runs it.

    Args:
        os_name: ``windows`` or ``darwin``.
        module_dir: The module's directory under the state root.
        account: The account whose machine it keeps.
        password: The account's login, which the Windows task is registered
            with; empty elsewhere.
        binary: Podman's program on the computer.
        provider: The machine provider.

    Returns:
        The service: the script as the account's file, run by the task's
        ``cmd.exe`` on Windows and by ``/bin/sh`` on macOS, its output in
        the module's log of the account. On macOS launchd leaves the
        machine's processes running when the keeper's job stops.

    Raises:
        ValueError: For a system with no keeper.
    """
    path = keeper_path(os_name=os_name, module_dir=module_dir)
    command = (path,) if os_name == "windows" else ("/bin/sh", path)
    return AccountService(
        name=PODMAN_MODULE_NAME,
        title=PODMAN_MACHINE_KEEPER_TITLE,
        account=account,
        command=command,
        password=password,
        files=(
            (
                path,
                keeper_script(os_name=os_name, binary=binary, provider=provider),
            ),
        ),
        is_process_group_abandoned=True,
    )
