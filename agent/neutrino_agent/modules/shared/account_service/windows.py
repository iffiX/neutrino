"""A module's instances on Windows: one scheduled task per account.

LocalSystem cannot start a process as another account without that
account's password, so each instance is a task registered with the
account's login: it starts at boot, runs with the account's limited token,
has no time limit, and restarts when it stops. The task's description
carries a digest of what it runs and with which login, so an unchanged
instance is left running and a changed one is registered again. The task
runs the program through ``cmd.exe`` with its output appended to the
account's log file beside the program; a service with an environment or a
working directory runs a script that sets them first. The files the task
reads are reachable by their account, SYSTEM and the administrators alone.
An instance's processes are the ones whose command line names its log file
and every process they started; a stop ends all of them. Every operation is
one PowerShell script, the password on its standard input.

Not pure: runs PowerShell.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import json
import ntpath
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.account_service import task_name
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_LOG_SUFFIX,
    ACCOUNT_SERVICE_LOGON_FAILURES,
    ACCOUNT_SERVICE_TASK_MARKER,
    ACCOUNT_SERVICE_TASK_PREFIX,
    ACCOUNT_SERVICE_WINDOWS_RULE_INFIX,
    ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME,
    ACCOUNT_SERVICE_WINDOWS_SCRIPT_SUFFIX,
    ACCOUNT_SERVICE_WINDOWS_SHELL,
)
from neutrino_agent.modules.shared.powershell_run import listed

# An instance's process tree: every process whose command line names the
# instance's log file, and their descendants by parent process id, a child
# never older than its parent. A stop takes the tree before the task stops
# and ends what is left of it after.
TREE_FUNCTIONS = """
function Get-InstanceTree($mark) {
  $all = @(Get-CimInstance Win32_Process)
  $tree = @($all | Where-Object { "$($_.CommandLine)".Contains($mark) })
  for ($n = 0; $n -lt $tree.Count; $n++) {
    $parent = $tree[$n]
    foreach ($child in $all) {
      if ($child.ParentProcessId -eq $parent.ProcessId -and
          $child.CreationDate -ge $parent.CreationDate -and
          @($tree | ForEach-Object { $_.ProcessId }) -notcontains $child.ProcessId) {
        $tree += $child
      }
    }
  }
  ,$tree
}
function Stop-Instance($task, $mark) {
  $tree = Get-InstanceTree $mark
  Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
  foreach ($process in $tree) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
  }
}
function Test-InstanceListening($mark, $port) {
  $owners = @(Get-NetTCPConnection -State Listen -LocalPort $port `
    -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess })
  if ($owners.Count -eq 0) { return $false }
  $tree = Get-InstanceTree $mark
  return (@($tree | Where-Object { $owners -contains $_.ProcessId }).Count -gt 0)
}
"""

# Writes the account's files and its log, registers the task when it is
# missing or runs something else, and removes every firewall rule an older
# build opened for an instance's port.
REGISTER_SCRIPT = TREE_FUNCTIONS + """
foreach ($file in @($d.files)) {
  $dir = Split-Path -Parent $file.path
  if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  [IO.File]::WriteAllText($file.path, $file.text)
  $code = Invoke-Icacls $file.path /inheritance:r /grant:r "$($d.account):R" `
    '*S-1-5-18:F' '*S-1-5-32-544:F'
  if ($code -ne 0) { throw "icacls refused $($file.path)" }
}
foreach ($dir in @($d.directories)) {
  if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  $code = Invoke-Icacls $dir /inheritance:r /grant:r "$($d.account):(OI)(CI)M" `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'
  if ($code -ne 0) { throw "icacls refused $dir" }
}
if (-not (Test-Path -LiteralPath $d.log_file)) {
  [IO.File]::WriteAllText($d.log_file, '')
}
$code = Invoke-Icacls $d.log_file /inheritance:r /grant:r "$($d.account):M" `
  '*S-1-5-18:F' '*S-1-5-32-544:F'
if ($code -ne 0) { throw "icacls refused the log file of $($d.account)" }
$is_registered = $false
$task = Get-ScheduledTask -TaskName $d.task -ErrorAction SilentlyContinue
if (-not $task -or "$($task.Description)" -ne $d.description) {
  if ($task) { Stop-Instance $d.task $d.mark }
  $action = New-ScheduledTaskAction -Execute $d.program -Argument $d.arguments
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
  try {
    Register-ScheduledTask -TaskName $d.task -Description $d.description `
      -Action $action -Trigger $trigger -Settings $settings `
      -User $d.account -Password $d.password -RunLevel Limited -Force | Out-Null
  } catch {
    if (Test-LogonRefused $_) {
      Send-Refusal 'credential_invalid' @{account = $d.account}
    }
    throw
  }
  $is_registered = $true
}
$stale = @(Get-NetFirewallRule -Name "$($d.rule_prefix)*" -ErrorAction SilentlyContinue)
if ($stale.Count -gt 0) { $stale | Remove-NetFirewallRule }
@{is_registered = $is_registered} | ConvertTo-Json -Compress -Depth 4
"""

# Starts the task unless it runs, ending what is left of the instance first.
START_SCRIPT = TREE_FUNCTIONS + """
if ((Get-ScheduledTask -TaskName $d.task).State -ne 'Running') {
  Stop-Instance $d.task $d.mark
  Start-ScheduledTask -TaskName $d.task
}
'{}'
"""

# Stops the task and ends the instance's whole process tree.
STOP_SCRIPT = TREE_FUNCTIONS + """
Stop-Instance $d.task $d.mark
'{}'
"""

# Stops the instance, unregisters its task and deletes what it ran from.
REMOVE_SCRIPT = TREE_FUNCTIONS + """
Stop-Instance $d.task $d.mark
Unregister-ScheduledTask -TaskName $d.task -Confirm:$false -ErrorAction SilentlyContinue
foreach ($path in @($d.paths)) {
  Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
}
'{}'
"""

# Each of the module's tasks: its state, its last result, and whether its
# process tree listens on the port the service names.
STATUS_SCRIPT = TREE_FUNCTIONS + """
$tasks = @()
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
  $listening = $false
  $port = $d.ports.($task.TaskName)
  if ($port) {
    $listening = Test-InstanceListening $d.marks.($task.TaskName) ([int]$port)
  }
  $tasks += @{name = $task.TaskName; state = "$($task.State)";
    last_result = [int64]$info.LastTaskResult; is_listening = $listening}
}
@{tasks = $tasks} | ConvertTo-Json -Compress -Depth 4
"""

# Removes every firewall rule an older build opened for the module's ports.
FORGET_SCRIPT = """
Remove-NetFirewallRule -Name "$($d.rule_prefix)*" -ErrorAction SilentlyContinue
'{}'
"""


def task_arguments(program: str, arguments: list, log_file: str) -> str:
    """What ``cmd.exe`` is handed to run a program with its output in a log.

    Args:
        program: The program, or the script that starts it.
        arguments: The program's own arguments.
        log_file: The file its output and its errors are appended to.

    Returns:
        ``/s /c "<program> <arguments> >> <log> 2>&1"``.
    """
    command = subprocess.list2cmdline([program, *arguments])
    log = subprocess.list2cmdline([log_file])
    return f'/s /c "{command} >> {log} 2>&1"'


def render_script(service) -> str:
    """The script one instance's task runs.

    Args:
        service: The service, with an environment or a working directory.

    Returns:
        The ``.cmd`` text, CRLF line ends: the environment set, the
        working directory entered, the command run.
    """
    lines = ["@echo off"]
    lines += [f'set "{name}={value}"' for name, value in service.environment.items()]
    if service.working_directory:
        directory = (
            "%USERPROFILE%"
            if service.working_directory == "~"
            else service.working_directory
        )
        lines.append(f'cd /d "{directory}"')
    lines.append(subprocess.list2cmdline(list(service.command)))
    return "\r\n".join(lines) + "\r\n"


def task_description(arguments: str, service, texts: list) -> str:
    """The description a task carries: a digest of what it runs and with which login.

    Args:
        arguments: What ``cmd.exe`` is handed.
        service: The service.
        texts: The texts of every file the task reads.

    Returns:
        ``neutrino:`` and 16 hex digits.
    """
    material = json.dumps(
        [
            ACCOUNT_SERVICE_WINDOWS_SHELL,
            arguments,
            service.account,
            service.password,
            *texts,
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return ACCOUNT_SERVICE_TASK_MARKER + digest


def script_path(service, machine) -> str:
    """Where one instance's script is written, under ``run`` beside the program."""
    return ntpath.join(
        machine.module_dir,
        ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME,
        service.account + ACCOUNT_SERVICE_WINDOWS_SCRIPT_SUFFIX,
    )


def rule_prefix(name: str) -> str:
    """The name an older build gave the module's firewall rules, without the port."""
    return f"{ACCOUNT_SERVICE_TASK_PREFIX}{name}{ACCOUNT_SERVICE_WINDOWS_RULE_INFIX}"


def define(template, machine) -> bool:
    """Nothing is shared: each instance has its own task."""
    return False


def write(service, machine) -> bool:
    """Write the account's files and register the task; whether it was registered."""
    log = log_path(service.name, service.account, machine, service.log_name)
    files = [{"path": path, "text": text} for path, text in service.files]
    if _is_scripted(service):
        files.append(
            {"path": script_path(service, machine), "text": render_script(service)}
        )
        arguments = task_arguments(script_path(service, machine), [], log)
    else:
        arguments = task_arguments(service.command[0], list(service.command[1:]), log)
    answer = machine.powershell(
        REGISTER_SCRIPT,
        {
            "account": service.account,
            "password": service.password,
            "task": task_name(service.name, service.account),
            "program": ACCOUNT_SERVICE_WINDOWS_SHELL,
            "arguments": arguments,
            "description": task_description(
                arguments, service, [file["text"] for file in files]
            ),
            "log_file": log,
            "mark": log,
            "files": files,
            "directories": list(service.directories),
            "rule_prefix": rule_prefix(service.name),
        },
    )
    return answer.get("is_registered") is True


def start(service, machine, *, is_restart: bool) -> None:
    """Start the task unless it runs; a changed task was registered again."""
    machine.powershell(START_SCRIPT, _task_document(service, machine))


def stop(service, machine) -> None:
    """Stop the task and end the instance's process tree; it starts again at boot."""
    machine.powershell(STOP_SCRIPT, _task_document(service, machine))


def remove(service, machine) -> None:
    """Stop the instance, unregister its task and delete its files."""
    log = log_path(service.name, service.account, machine, service.log_name)
    paths = [path for path, _text in service.files]
    paths += [script_path(service, machine), log, *service.directories]
    machine.powershell(
        REMOVE_SCRIPT, dict(_task_document(service, machine), paths=paths)
    )


def states(services: list, machine) -> dict:
    """Whether each instance runs, and whether its task can sign in.

    An instance whose service names a port runs while its process tree
    listens on it; any other runs while its task does.
    """
    if not services:
        return {}
    name = services[0].name
    document = {
        "prefix": f"{ACCOUNT_SERVICE_TASK_PREFIX}{name}_",
        "ports": {
            task_name(name, service.account): service.listen_port
            for service in services
            if service.listen_port
        },
        "marks": {
            task_name(name, service.account): log_path(
                name, service.account, machine, service.log_name
            )
            for service in services
        },
    }
    try:
        read = machine.powershell(STATUS_SCRIPT, document)
    except (OSError, subprocess.SubprocessError, ModuleApplyError):
        read = {}
    tasks = {
        str(entry.get("name", "")): entry
        for entry in listed(read.get("tasks"))
        if isinstance(entry, dict)
    }
    held = {}
    for service in services:
        entry = tasks.get(task_name(name, service.account)) or {}
        result = int(entry.get("last_result", 0) or 0) & 0xFFFFFFFF
        if service.listen_port:
            is_running = entry.get("is_listening") is True
        else:
            is_running = str(entry.get("state", "")) == "Running"
        held[service.account] = {
            "is_running": is_running,
            "code": (
                "credential_invalid" if result in ACCOUNT_SERVICE_LOGON_FAILURES else ""
            ),
        }
    return held


def forget(name: str, machine) -> None:
    """Remove the firewall rules an older build opened for the module."""
    machine.powershell(FORGET_SCRIPT, {"rule_prefix": rule_prefix(name)})


def units(services: list, machine) -> list:
    """No journal: a task keeps none."""
    return []


def log_path(name: str, account: str, machine, log_name: str) -> str:
    """The file one instance's output goes to, beside the program."""
    return ntpath.join(
        machine.module_dir, log_name or account + ACCOUNT_SERVICE_LOG_SUFFIX
    )


def _is_scripted(service) -> bool:
    return bool(service.environment or service.working_directory)


def _task_document(service, machine) -> dict:
    log = log_path(service.name, service.account, machine, service.log_name)
    return {"task": task_name(service.name, service.account), "mark": log}
