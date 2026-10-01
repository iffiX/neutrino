"""VS Code's servers on Windows: one scheduled task per account.

LocalSystem cannot start a process as another account without that
account's password, so each instance is a task registered with the
account's login: it starts at boot, runs with the account's limited token,
has no time limit, and restarts when it stops. The task's description
carries a digest of what it runs and with which login, so an unchanged
instance is left running and a changed one is registered again. A task
Windows cannot sign in reads ``credential_invalid``. The task runs the CLI
through ``cmd.exe``, its output appended to the account's log file beside
the CLI. The token file and the log file are reachable by their account,
SYSTEM and the administrators alone. Every operation is one PowerShell
script, the passwords on its standard input.

Not pure: runs PowerShell.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import json
import ntpath
import re
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.powershell_run import listed, run_powershell
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.constants import (
    VSCODE_CLI_NAMES,
    VSCODE_DIR_NAME,
    VSCODE_LOGON_FAILURES,
    VSCODE_LOG_SUFFIX,
    VSCODE_SERVE_ARGUMENTS,
    VSCODE_TASK_MARKER,
    VSCODE_TASK_PREFIX,
    VSCODE_TOKEN_DIR_NAME,
    VSCODE_WINDOWS_SHELL,
)

# The port an instance's arguments name.
PORT_PATTERN = re.compile(r"--port (\d+)")

# Writes the token files, registers the tasks that changed, starts them,
# and unregisters the module's tasks no instance names.
APPLY_SCRIPT = """
$notes = @()
foreach ($i in @($d.instances)) {
  $dir = Split-Path -Parent $i.token_file
  if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  [IO.File]::WriteAllText($i.token_file, $i.token)
  $code = Invoke-Icacls $i.token_file /inheritance:r /grant:r "$($i.account):R" `
    '*S-1-5-18:F' '*S-1-5-32-544:F'
  if ($code -ne 0) { throw "icacls refused the token file of $($i.account)" }
  if (-not (Test-Path -LiteralPath $i.log_file)) {
    [IO.File]::WriteAllText($i.log_file, '')
  }
  $code = Invoke-Icacls $i.log_file /inheritance:r /grant:r "$($i.account):M" `
    '*S-1-5-18:F' '*S-1-5-32-544:F'
  if ($code -ne 0) { throw "icacls refused the log file of $($i.account)" }
  $task = Get-ScheduledTask -TaskName $i.task -ErrorAction SilentlyContinue
  if (-not $task -or "$($task.Description)" -ne $i.description) {
    if ($task) { Stop-ScheduledTask -TaskName $i.task -ErrorAction SilentlyContinue }
    $action = New-ScheduledTaskAction -Execute $d.program -Argument $i.arguments
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
      -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
      -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    try {
      Register-ScheduledTask -TaskName $i.task -Description $i.description `
        -Action $action -Trigger $trigger -Settings $settings `
        -User $i.account -Password $i.password -RunLevel Limited -Force | Out-Null
    } catch {
      if ("$($_.Exception.Message)" -match '0x8007052E') {
        Send-Refusal 'credential_invalid' @{account = $i.account}
      }
      throw
    }
    $notes += "registered the server of $($i.account)"
  }
  if ((Get-ScheduledTask -TaskName $i.task).State -ne 'Running') {
    Start-ScheduledTask -TaskName $i.task
  }
}
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  if (@($d.tasks) -notcontains $task.TaskName) {
    Stop-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false
    $account = $task.TaskName.Substring($d.prefix.Length)
    $log = Join-Path $d.log_dir "$account$($d.log_suffix)"
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
    $notes += "removed $($task.TaskName)"
  }
}
@{notes = $notes} | ConvertTo-Json -Compress -Depth 4
"""

# Stops the module's tasks; with ``is_removed`` also unregisters them and
# deletes the token files.
WITHDRAW_SCRIPT = """
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  Stop-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue
  if ($d.is_removed) { Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false }
}
if ($d.is_removed -and (Test-Path -LiteralPath $d.token_dir)) {
  Remove-Item -LiteralPath $d.token_dir -Recurse -Force
}
'{}'
"""

# Each of the module's tasks: its state, its last result and its arguments.
STATUS_SCRIPT = """
$tasks = @()
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
  $tasks += @{name = $task.TaskName; state = "$($task.State)";
    last_result = [int64]$info.LastTaskResult;
    arguments = "$(@($task.Actions)[0].Arguments)"}
}
@{tasks = $tasks} | ConvertTo-Json -Compress -Depth 4
"""


def task_name(account: str) -> str:
    """The task one account's server runs as.

    Args:
        account: The account.

    Returns:
        ``neutrino_vscode_<account>``.
    """
    return VSCODE_TASK_PREFIX + account


def task_arguments(cli_path: str, serve_arguments: list, log_file: str) -> str:
    """What ``cmd.exe`` is handed to run the CLI with its output in a log.

    Args:
        cli_path: Where the CLI is.
        serve_arguments: The CLI's own arguments.
        log_file: The file its output and its errors are appended to.

    Returns:
        ``/s /c "<cli> <arguments> >> <log> 2>&1"``.
    """
    command = subprocess.list2cmdline([cli_path, *serve_arguments])
    log = subprocess.list2cmdline([log_file])
    return f'/s /c "{command} >> {log} 2>&1"'


def _digest(program: str, arguments: str, instance) -> str:
    """What a task runs and with which login, in 16 hex digits."""
    material = json.dumps(
        [program, arguments, instance.account, instance.password, instance.token]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _port_of(entry: dict) -> int:
    match = PORT_PATTERN.search(str(entry.get("arguments", "")))
    return int(match.group(1)) if match else 0


class VscodeWindowsApplier:
    """Runs each instance as a scheduled task signed in with its account."""

    def __init__(self, *, root: str, powershell=None):
        """
        Args:
            root: The platform's root for software the hub sends; the CLI
                and the token files live under it.
            powershell: Called with ``(script, document)``; returns the JSON
                object the script printed. None runs PowerShell.
        """
        self.cli_dir = ntpath.join(root, VSCODE_DIR_NAME)
        self._token_dir = ntpath.join(self.cli_dir, VSCODE_TOKEN_DIR_NAME)
        self._powershell = powershell if powershell is not None else run_powershell

    @property
    def cli_path(self) -> str:
        """Where the CLI is."""
        return ntpath.join(self.cli_dir, VSCODE_CLI_NAMES["windows"])

    def log_path(self, account: str) -> str:
        """The file one account's server writes its output to.

        Args:
            account: The account.

        Returns:
            ``<cli dir>\\<account>.log``.
        """
        return ntpath.join(self.cli_dir, account + VSCODE_LOG_SUFFIX)

    def apply(self, config: VscodeConfig) -> list:
        """Register and start one task per instance; remove the ones gone.

        Args:
            config: The validated configuration.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``credential_invalid`` when Windows refuses an
                account's login.
            OSError: When PowerShell fails.
        """
        instances = []
        for instance in config.instances:
            token_file = ntpath.join(self._token_dir, instance.account + ".token")
            log_file = self.log_path(instance.account)
            arguments = task_arguments(
                self.cli_path,
                [
                    *VSCODE_SERVE_ARGUMENTS,
                    "--host",
                    config.host,
                    "--port",
                    str(instance.port),
                    "--connection-token-file",
                    token_file,
                ],
                log_file,
            )
            instances.append(
                {
                    "account": instance.account,
                    "password": instance.password,
                    "token": instance.token,
                    "token_file": token_file,
                    "log_file": log_file,
                    "task": task_name(instance.account),
                    "arguments": arguments,
                    "description": VSCODE_TASK_MARKER
                    + _digest(VSCODE_WINDOWS_SHELL, arguments, instance),
                }
            )
        answer = self._powershell(
            APPLY_SCRIPT,
            {
                "program": VSCODE_WINDOWS_SHELL,
                "log_dir": self.cli_dir,
                "log_suffix": VSCODE_LOG_SUFFIX,
                "prefix": VSCODE_TASK_PREFIX,
                "tasks": [entry["task"] for entry in instances],
                "instances": instances,
            },
        )
        return [str(note) for note in listed(answer.get("notes"))]

    def stop(self) -> None:
        """Stop every instance's task; each starts again at boot.

        Raises:
            OSError: When PowerShell fails.
        """
        self._withdraw(is_removed=False)

    def remove(self) -> None:
        """Stop and unregister every instance's task and delete the tokens.

        Raises:
            OSError: When PowerShell fails.
        """
        self._withdraw(is_removed=True)

    def states(self, config: "VscodeConfig | None") -> list:
        """Each instance, whether its task runs, and whether it can sign in.

        Args:
            config: The applied configuration; None reads the instances
                from the tasks.

        Returns:
            ``[{"account", "port", "url", "is_running", "code"}]``.
        """
        try:
            read = self._powershell(STATUS_SCRIPT, {"prefix": VSCODE_TASK_PREFIX})
        except (OSError, subprocess.SubprocessError, ModuleApplyError):
            read = {}
        tasks = {
            str(entry.get("name", "")): entry
            for entry in listed(read.get("tasks"))
            if isinstance(entry, dict)
        }
        if config is not None:
            held = [(item.account, item.port) for item in config.instances]
            host = config.host
        else:
            held = [
                (name[len(VSCODE_TASK_PREFIX) :], _port_of(entry))
                for name, entry in sorted(tasks.items())
            ]
            host = VscodeConfig().host
        states = []
        for account, port in held:
            entry = tasks.get(task_name(account)) or {}
            result = int(entry.get("last_result", 0) or 0) & 0xFFFFFFFF
            states.append(
                {
                    "account": account,
                    "port": port,
                    "url": f"http://{host}:{port}/" if port else "",
                    "is_running": str(entry.get("state", "")) == "Running",
                    "code": (
                        "credential_invalid" if result in VSCODE_LOGON_FAILURES else ""
                    ),
                }
            )
        return states

    def units(self) -> list:
        """No journal: a task keeps none."""
        return []

    def log_paths(self, config: "VscodeConfig | None") -> list:
        """Each instance's log file.

        Args:
            config: The applied configuration; None reads the instances
                from the tasks.

        Returns:
            ``[(account, path)]``, in the instances' order.
        """
        return [
            (state["account"], self.log_path(state["account"]))
            for state in self.states(config)
        ]

    def _withdraw(self, *, is_removed: bool) -> None:
        self._powershell(
            WITHDRAW_SCRIPT,
            {
                "prefix": VSCODE_TASK_PREFIX,
                "is_removed": is_removed,
                "token_dir": self._token_dir,
            },
        )
