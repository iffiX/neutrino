"""Bringing this machine's own agent to the version of the hub's package.

Every install of the hub's package ends with the panel started on the new
version, and at each start the panel compares what ``nagent --version``
prints with the version of this machine's package in the hub's agent cache.
When they differ, the panel writes a script beside the update's script and
starts it apart from itself: a transient unit on Linux, a job given to
``launchctl submit`` on macOS, a PowerShell with no window on Windows. The
script waits while the hub's own update runs, since its health gate can put
the previous hub back. It ends when the hub moved to another version or the
agent reached the package's version meanwhile. Otherwise it installs the
package with the command the hub's update installs with, which waits for the
lock of the install that started the panel.

Not pure: reads the agent's version, writes the script and starts it.
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from neutrino_hub import HUB_VERSION
from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices.agent_package import (
    AGENT_PACKAGE_FAMILY_OF_OS,
    AGENT_PACKAGE_FAMILY_OF_PLATFORM,
    AgentPackageCache,
)
from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_DIR_MODE,
    HUB_UPDATE_DIR_NAME,
    HUB_UPDATE_LAUNCH_TIMEOUT_S,
    HUB_UPDATE_LOCAL_AGENT_LOG_NAME,
    HUB_UPDATE_LOCAL_AGENT_PID_NAME,
    HUB_UPDATE_LOCAL_AGENT_POLL_S,
    HUB_UPDATE_LOCAL_AGENT_SCRIPT_NAME,
    HUB_UPDATE_LOCAL_AGENT_SCRIPT_NAME_WINDOWS,
    HUB_UPDATE_LOCAL_AGENT_UNIT,
    HUB_UPDATE_LOCAL_AGENT_VERSION_NAME,
    HUB_UPDATE_LOCAL_AGENT_VERSION_TIMEOUT_S,
    HUB_UPDATE_LOCAL_AGENT_WAIT_S,
    HUB_UPDATE_MSI_BUSY_CODE,
    HUB_UPDATE_MSI_INSTALLED_CODES,
    HUB_UPDATE_MSI_MUTEX,
    HUB_UPDATE_NHUB_DARWIN,
    HUB_UPDATE_NHUB_NAME_WINDOWS,
    HUB_UPDATE_PID_NAME,
    HUB_UPDATE_SCRIPT_MODE,
    HUB_UPDATE_UNIT,
    HUB_UPDATE_UNIT_ENVIRONMENT,
    HUB_UPDATE_UNIT_MEMORY_HIGH,
)
from neutrino_hub.modules.hub_update.installer import (
    MANAGER_NAMES,
    SCRIPT_ENCODINGS,
    agent_install_command,
    launchd_job_state,
    lock_step,
    powershell_list,
    powershell_quote,
    start_detached_process,
    update_family,
    windows_script_state,
)
from neutrino_hub.platforms.detect import hub_os, hub_platform
from neutrino_hub.system.machine import distribution_family, machine_architecture
from neutrino_hub.system.systemd_ctl import held_unit_state
from neutrino_hub.utils import constants
from neutrino_hub.utils.subprocess_run import run

UNIT_ACTIVE_STATES = ("active", "activating")
# Where each family's script is written, where it is not ``local_agent.sh``.
SCRIPT_NAMES = {"msi": HUB_UPDATE_LOCAL_AGENT_SCRIPT_NAME_WINDOWS}

SCRIPT = r"""#!/bin/sh
# Written by neutrino_hub.modules.hub_update; runs as the transient unit
# @UNIT@. Do not edit.
umask 022
LOG=@LOG@
HUB=@HUB@
WANTED=@WANTED@
AGENT=@AGENT@
AGENT_COMMAND=@AGENT_COMMAND@
WAIT=@WAIT@
POLL=@POLL@
UNITS=@UNITS@
MANAGER=@MANAGER@
PACE='nice -n 10'
command -v ionice >/dev/null 2>&1 && PACE="ionice -c 2 -n 7 $PACE"

step() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $1" >> "$LOG"
}

is_running() {
    systemctl list-units --all --plain --no-legend --full "$1.service" 2>/dev/null \
        | awk -v unit="$1.service" '{ for (i = 1; i + 2 <= NF; i++) if ($i == unit) state = $(i + 2) }
            END { exit !(state == "active" || state == "activating" || state == "reloading" || state == "deactivating") }'
}

is_busy() {
    for unit in $UNITS; do
        is_running "$unit" && return 0
    done
    return 1
}

version_of() {
    "$1" --version 2>/dev/null | tail -n 1
}

: > "$LOG"
seen=$(version_of "$AGENT_COMMAND")
step "agent ${seen:-none}, package $WANTED, hub $HUB"
deadline=$(( $(date +%s) + WAIT ))
while is_busy && [ "$(date +%s)" -lt "$deadline" ]; do
    sleep "$POLL"
done
seen=$(version_of nhub)
if [ "$seen" != "$HUB" ]; then
    step "hub ${seen:-gone} now; nothing installed"
    exit 0
fi
if ! command -v "$AGENT_COMMAND" >/dev/null 2>&1; then
    step 'no agent on this machine'
    exit 0
fi
if [ "$(version_of "$AGENT_COMMAND")" = "$WANTED" ]; then
    step "agent already $WANTED"
    exit 0
fi
step "installing $AGENT"
@LOCK_STEP@
( @INSTALL@ ) >> "$LOG" 2>&1
code=$?
seen=$(version_of "$AGENT_COMMAND")
if [ "$seen" = "$WANTED" ]; then
    step "agent updated to $WANTED"
    exit 0
fi
step "agent update failed: $MANAGER exited $code, found version ${seen:-none}"
exit 1
"""

SCRIPT_DARWIN = r"""#!/bin/sh
# Written by neutrino_hub.modules.hub_update; runs as the launchd job
# @UNIT@. Do not edit. launchd runs a submitted job again whenever it
# exits, so every end removes the job.
umask 022
LOG=@LOG@
HUB=@HUB@
WANTED=@WANTED@
AGENT=@AGENT@
AGENT_COMMAND=@AGENT_COMMAND@
NHUB=@NHUB@
JOB=@UNIT@
JOBS=@JOBS@
WAIT=@WAIT@
POLL=@POLL@

step() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $1" >> "$LOG"
}

finish() {
    launchctl remove "$JOB"
    exit "$1"
}

is_busy() {
    for job in $JOBS; do
        launchctl print "$job" 2>/dev/null | grep -q 'state = running' && return 0
    done
    pgrep -x installer >/dev/null 2>&1
}

version_of() {
    "$1" --version 2>/dev/null | tail -n 1
}

: > "$LOG"
seen=$(version_of "$AGENT_COMMAND")
step "agent ${seen:-none}, package $WANTED, hub $HUB"
deadline=$(( $(date +%s) + WAIT ))
while is_busy && [ "$(date +%s)" -lt "$deadline" ]; do
    sleep "$POLL"
done
seen=$(version_of "$NHUB")
if [ "$seen" != "$HUB" ]; then
    step "hub ${seen:-gone} now; nothing installed"
    finish 0
fi
if [ ! -x "$AGENT_COMMAND" ]; then
    step 'no agent on this machine'
    finish 0
fi
if [ "$(version_of "$AGENT_COMMAND")" = "$WANTED" ]; then
    step "agent already $WANTED"
    finish 0
fi
step "installing $AGENT"
( @INSTALL@ ) >> "$LOG" 2>&1
code=$?
seen=$(version_of "$AGENT_COMMAND")
if [ "$seen" = "$WANTED" ]; then
    step "agent updated to $WANTED"
    finish 0
fi
step "agent update failed: installer exited $code, found version ${seen:-none}"
finish 1
"""

SCRIPT_WINDOWS = r"""# Written by neutrino_hub.modules.hub_update; runs apart from the hub's
# service. Do not edit.
$ErrorActionPreference = 'Continue'
$Log = @LOG@
$Hub = @HUB@
$Wanted = @WANTED@
$Agent = @AGENT@
$AgentCommand = @AGENT_COMMAND@
$Nhub = @NHUB@
$UpdatePid = @UPDATE_PID@
$Wait = @WAIT@
$Poll = @POLL@
$Installed = @INSTALLED_CODES@

function Add-Step($Line) {
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    Add-Content -LiteralPath $Log -Value "$stamp $Line"
}

function Get-Version($Command) {
    try {
        return [string](& $Command --version 2>$null | Select-Object -Last 1)
    } catch {
        return ''
    }
}

function Test-Update {
    try {
        $id = [int]((Get-Content -LiteralPath $UpdatePid -Raw).Trim())
    } catch {
        return $false
    }
    if ($id -eq $PID) { return $false }
    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    return [bool]($process -and $process.ProcessName -like 'powershell*')
}

function Test-Installer {
    $held = $null
    try {
        if (-not [Threading.Mutex]::TryOpenExisting(@MSI_MUTEX@, [ref]$held)) { return $false }
        $held.Dispose()
    } catch [UnauthorizedAccessException] {
    }
    return $true
}

function Wait-Busy {
    $deadline = (Get-Date).AddSeconds($Wait)
    while (((Get-Date) -lt $deadline) -and ((Test-Update) -or (Test-Installer))) {
        Start-Sleep -Seconds $Poll
    }
}

function Invoke-Msi($Arguments) {
    $run = Start-Process -FilePath msiexec.exe -Wait -PassThru -WindowStyle Hidden `
        -ArgumentList $Arguments
    Add-Content -LiteralPath $Log -Value "msiexec $Arguments exited $($run.ExitCode)"
    return $run.ExitCode
}

[IO.File]::WriteAllText($Log, '')
$seen = Get-Version $AgentCommand
if (-not $seen) { $seen = 'none' }
Add-Step "agent $seen, package $Wanted, hub $Hub"
Wait-Busy
$seen = Get-Version $Nhub
if ($seen -ne $Hub) {
    if (-not $seen) { $seen = 'gone' }
    Add-Step "hub $seen now; nothing installed"
    exit 0
}
if (-not (Test-Path -LiteralPath $AgentCommand)) {
    Add-Step 'no agent on this machine'
    exit 0
}
if ((Get-Version $AgentCommand) -eq $Wanted) {
    Add-Step "agent already $Wanted"
    exit 0
}
Add-Step "installing $Agent"
$arguments = "/i `"$Agent`" /qn /norestart"
$code = Invoke-Msi $arguments
if ($code -eq @MSI_BUSY@) {
    Wait-Busy
    if ((Get-Version $AgentCommand) -eq $Wanted) {
        Add-Step "agent already $Wanted"
        exit 0
    }
    $code = Invoke-Msi $arguments
}
$seen = Get-Version $AgentCommand
if ($seen -eq $Wanted) {
    Add-Step "agent updated to $Wanted"
    exit 0
}
if (-not $seen) { $seen = 'none' }
Add-Step "agent update failed: msiexec exited $code, found version $seen"
exit 1
"""


def package_version(name: str) -> str:
    """The version an agent package's file name names.

    Args:
        name: The file name, as a release publishes it.

    Returns:
        The version, empty when the name is no agent package's.
    """
    found = re.match(HUB_UPDATE_LOCAL_AGENT_VERSION_NAME, name)
    return found.group(1) if found else ""


def local_agent_package() -> str:
    """This machine's own agent package, as the hub's cache holds it.

    Returns:
        The file's path; empty when the cache holds none for this machine or
        it cannot be had.
    """
    family = AGENT_PACKAGE_FAMILY_OF_OS.get(hub_os(), "")
    family = family or AGENT_PACKAGE_FAMILY_OF_PLATFORM.get(distribution_family(), "")
    architecture = machine_architecture()
    cache = AgentPackageCache()
    if not family or not cache.serves(family=family, architecture=architecture):
        return ""
    try:
        return str(cache.package(family=family, architecture=architecture))
    except (OSError, ValueError, AgentArtifactFetchError):
        return ""


def local_agent_script_name(family: str) -> str:
    """What the local agent's script of a family is called.

    Args:
        family: The distribution family, or ``pkg`` or ``msi``.

    Returns:
        ``local_agent.ps1`` for ``msi``, ``local_agent.sh`` for every other.
    """
    return SCRIPT_NAMES.get(family, HUB_UPDATE_LOCAL_AGENT_SCRIPT_NAME)


def render_local_agent_script(
    *,
    family: str,
    hub_version: str,
    wanted: str,
    package: Path,
    directory: Path,
    agent_command: str,
    wait_s: int = HUB_UPDATE_LOCAL_AGENT_WAIT_S,
    poll_s: float = HUB_UPDATE_LOCAL_AGENT_POLL_S,
) -> str:
    """The script that installs this machine's agent package. Pure.

    It waits at most ``wait_s`` while the hub's own update runs, on macOS
    also while ``installer`` runs and on Windows while the Windows Installer
    runs. It installs nothing when the hub is no longer ``hub_version`` or
    the agent is ``wanted`` by then. Each turn is a line in its log.

    Args:
        family: The distribution family, or ``pkg`` on macOS and ``msi`` on
            Windows.
        hub_version: The hub's version the script is written for.
        wanted: The version the package installs.
        package: The agent package file.
        directory: Where the log is written.
        agent_command: The agent's command.
        wait_s: How long the hub's own update and another install are
            waited out.
        poll_s: How often the script looks.

    Returns:
        The script's text.

    Raises:
        ValueError: If no package manager is known for the family.
    """
    log = directory / HUB_UPDATE_LOCAL_AGENT_LOG_NAME
    if family == "msi":
        quote = powershell_quote
        template = SCRIPT_WINDOWS
        values = {
            "@NHUB@": quote(
                str(constants.UTILS_STATIC_ROOT / HUB_UPDATE_NHUB_NAME_WINDOWS)
            ),
            "@UPDATE_PID@": quote(str(directory / HUB_UPDATE_PID_NAME)),
            "@INSTALLED_CODES@": powershell_list(
                str(code) for code in HUB_UPDATE_MSI_INSTALLED_CODES
            ),
            "@MSI_MUTEX@": quote(HUB_UPDATE_MSI_MUTEX),
            "@MSI_BUSY@": str(HUB_UPDATE_MSI_BUSY_CODE),
        }
    elif family == "pkg":
        quote = shlex.quote
        template = SCRIPT_DARWIN
        values = {
            "@NHUB@": quote(HUB_UPDATE_NHUB_DARWIN),
            "@JOBS@": quote(f"system/{HUB_UPDATE_UNIT}"),
            "@INSTALL@": agent_install_command(family),
        }
    else:
        if family not in MANAGER_NAMES:
            raise ValueError(f"no package manager is known for {family}")
        quote = shlex.quote
        template = SCRIPT
        values = {
            "@UNITS@": quote(HUB_UPDATE_UNIT),
            "@MANAGER@": quote(MANAGER_NAMES[family]),
            "@LOCK_STEP@": lock_step(family),
            "@INSTALL@": agent_install_command(family),
        }
    values.update(
        {
            "@UNIT@": HUB_UPDATE_LOCAL_AGENT_UNIT,
            "@LOG@": quote(str(log)),
            "@HUB@": quote(hub_version),
            "@WANTED@": quote(wanted),
            "@AGENT@": quote(str(package)),
            "@AGENT_COMMAND@": quote(agent_command),
            "@WAIT@": str(int(wait_s)),
            "@POLL@": str(poll_s),
        }
    )
    text = template
    for token, value in values.items():
        text = text.replace(token, value)
    return text


class HubLocalAgentInstaller:
    """Hands the install of this machine's agent at the hub package's version
    to the system."""

    def __init__(
        self,
        *,
        directory: Path | None = None,
        family: str | None = None,
        hub_version: str = HUB_VERSION,
        agent_command: str | None = None,
        package_of: Callable[[], str] = local_agent_package,
        run_command: Callable[..., object] = run,
        job_state_of: Callable[[], str] | None = None,
        start_detached: Callable[[list], int] | None = None,
    ):
        """Set up an installer.

        Args:
            directory: Where the script, its process id and its log live;
                None is the update directory under the state root.
            family: The distribution family, or ``pkg`` or ``msi``; None
                reads the machine's.
            hub_version: The hub's own version.
            agent_command: The agent's command; None is the platform's.
            package_of: Returns this machine's agent package in the cache,
                empty when there is none.
            run_command: How the agent's version is read and the unit or
                the launchd job is started.
            job_state_of: How the script's state is read, in systemd's
                words; None reads it from systemd, launchd or the Windows
                script's process, by the family.
            start_detached: How the Windows script is started apart from the
                service, answering its process id; None starts it with no
                window and outside the service's job.
        """
        self._directory = directory
        self._family = family
        self._hub_version = hub_version
        self._agent_command = agent_command
        self._package_of = package_of
        self._run = run_command
        self._job_state_of = job_state_of
        self._start_detached = start_detached or start_detached_process

    @property
    def directory(self) -> Path:
        """Where the script, its process id and its log live."""
        return self._directory or constants.UTILS_STATE_ROOT / HUB_UPDATE_DIR_NAME

    def follow(self) -> str:
        """Start the install when this machine's agent is not the package's version.

        Returns:
            One line naming both versions and the script started, or saying
            why none started; empty when the machine has no agent, or its
            agent is the package's version.

        Raises:
            OSError: When the script cannot be written or started.
            subprocess.SubprocessError: When ``systemd-run`` or ``launchctl``
                refuses.
            ValueError: If no package manager is known for the family.
        """
        command = self._agent_command or hub_platform().agent_command()
        if not _is_installed(command):
            return ""
        installed = self._version_of(command)
        if installed == self._hub_version:
            return ""
        package = self._package_of()
        if not package:
            return f"agent {installed or 'unknown'}: no agent package for this machine"
        wanted = package_version(Path(package).name) or self._hub_version
        if installed == wanted:
            return ""
        if self._job_state() in UNIT_ACTIVE_STATES:
            return f"agent {installed or 'unknown'}: {HUB_UPDATE_LOCAL_AGENT_UNIT} runs"
        family = self._family or update_family()
        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, HUB_UPDATE_DIR_MODE)
        script = directory / local_agent_script_name(family)
        script.write_text(
            render_local_agent_script(
                family=family,
                hub_version=self._hub_version,
                wanted=wanted,
                package=Path(package),
                directory=directory,
                agent_command=command,
            ),
            encoding=SCRIPT_ENCODINGS.get(family, "utf-8"),
        )
        os.chmod(script, HUB_UPDATE_SCRIPT_MODE)
        self._start(family, script)
        return (
            f"agent {installed or 'unknown'} goes to {wanted}: "
            f"{HUB_UPDATE_LOCAL_AGENT_UNIT} started"
        )

    def _version_of(self, command: str) -> str:
        """The last line the agent's ``--version`` prints, empty when none."""
        try:
            result = self._run(
                [command, "--version"],
                is_checked=False,
                timeout_s=HUB_UPDATE_LOCAL_AGENT_VERSION_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        lines = str(getattr(result, "stdout", "") or "").strip().splitlines()
        return lines[-1].strip() if lines else ""

    def _job_state(self) -> str:
        """The script's state, read the way the family's system keeps it."""
        if self._job_state_of is not None:
            return self._job_state_of()
        family = self._family or update_family()
        if family == "pkg":
            return launchd_job_state(f"system/{HUB_UPDATE_LOCAL_AGENT_UNIT}")
        if family == "msi":
            return windows_script_state(
                self.directory / HUB_UPDATE_LOCAL_AGENT_PID_NAME
            )
        return held_unit_state(HUB_UPDATE_LOCAL_AGENT_UNIT)

    def _start(self, family: str, script: Path) -> None:
        """Start the script apart from the panel, the way the system does it."""
        if family == "msi":
            pid = self._start_detached(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ]
            )
            (self.directory / HUB_UPDATE_LOCAL_AGENT_PID_NAME).write_text(
                str(pid), encoding="utf-8"
            )
            return
        if family == "pkg":
            # A job that ended without removing itself keeps its label.
            try:
                self._run(
                    ["launchctl", "remove", HUB_UPDATE_LOCAL_AGENT_UNIT],
                    is_checked=False,
                    timeout_s=HUB_UPDATE_LAUNCH_TIMEOUT_S,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            self._run(
                ["launchctl", "submit", "-l", HUB_UPDATE_LOCAL_AGENT_UNIT, "--"]
                + ["/bin/sh", str(script)],
                timeout_s=HUB_UPDATE_LAUNCH_TIMEOUT_S,
            )
            return
        self._run(
            [
                "systemd-run",
                "--unit",
                HUB_UPDATE_LOCAL_AGENT_UNIT,
                "--collect",
                f"--property=MemoryHigh={HUB_UPDATE_UNIT_MEMORY_HIGH}",
                *(f"--setenv={pair}" for pair in HUB_UPDATE_UNIT_ENVIRONMENT),
                "/bin/sh",
                str(script),
            ],
            timeout_s=HUB_UPDATE_LAUNCH_TIMEOUT_S,
        )


def _is_installed(command: str) -> bool:
    """Whether the agent's command is on ``PATH`` or at its absolute path."""
    if os.path.isabs(command):
        return os.path.isfile(command)
    return shutil.which(command) is not None
