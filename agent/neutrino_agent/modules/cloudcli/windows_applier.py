"""CloudCLI on Windows: one scheduled task per account.

LocalSystem cannot start a process as another account without that
account's password, so each instance is a task registered with the
account's login, as VS Code's are: it starts at boot, runs with the
account's limited token, has no time limit, and restarts when it stops. It
runs a script that sets the instance's environment and starts the Node.js
the agent unpacked with the server script of the account's own app
directory, its output appended to the account's log file; the script puts
Node's directory before the account's own ``PATH``, so ``node`` and the
``claude`` the account installed are the ones CloudCLI finds. The script holds the instance's secrets and is reachable by its
account, SYSTEM and the administrators alone. An account's install runs
once as a task of its own with the same login, left running: each apply
reads the task, and while it runs the module is installing and no instance
is started. A task that has ended is judged by its result and by the app
directory, then unregistered. Every operation is one PowerShell script, the
passwords on its standard input.

Not pure: runs PowerShell.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import json
import ntpath
import subprocess

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.cloudcli import installer
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_INSTALL_TASK_PREFIX,
    CLOUDCLI_LOG_SUFFIX,
    CLOUDCLI_LOGON_FAILURES,
    CLOUDCLI_NODE_PARTS,
    CLOUDCLI_NPM_PARTS,
    CLOUDCLI_TASK_MARKER,
    CLOUDCLI_TASK_PREFIX,
    CLOUDCLI_WINDOWS_NPM_PATH,
    CLOUDCLI_WINDOWS_INSTALL_LIMIT_S,
    CLOUDCLI_WINDOWS_RULE_PREFIX,
    CLOUDCLI_WINDOWS_RULE_TITLE,
    CLOUDCLI_WINDOWS_SCRIPT_DIR_NAME,
    CLOUDCLI_WINDOWS_SHELL,
)
from neutrino_agent.modules.powershell_run import listed, run_powershell
from neutrino_agent.modules.vscode.windows_applier import task_arguments

# What an install script exits with when npm failed; a native module's
# failure exits with the native check's own status.
NPM_FAILED_EXIT = 1
# The task states of an install that has not ended.
INSTALL_RUNNING_STATES = ("Running", "Queued")
# What one account's install step found: CloudCLI already there, installed
# by a task that just ended, or a task still running.
INSTALL_READY = "ready"
INSTALL_FINISHED = "finished"
INSTALL_RUNNING = "running"

# Writes an account's install script and starts it as a task with the
# account's login, leaving it to run.
INSTALL_SCRIPT = """
$dir = Split-Path -Parent $d.script
if (-not (Test-Path -LiteralPath $dir)) {
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
[IO.File]::WriteAllText($d.script, $d.script_text)
[IO.File]::WriteAllText($d.log, '')
foreach ($file in @($d.script, $d.log)) {
  $code = Invoke-Icacls $file /inheritance:r /grant:r "$($d.account):M" `
    '*S-1-5-18:F' '*S-1-5-32-544:F'
  if ($code -ne 0) { throw "icacls refused $file" }
}
$action = New-ScheduledTaskAction -Execute $d.program -Argument $d.arguments
$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Seconds $d.timeout_s) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
try {
  Register-ScheduledTask -TaskName $d.task -Action $action -Settings $settings `
    -User $d.account -Password $d.password -RunLevel Limited -Force | Out-Null
} catch {
  if ("$($_.Exception.Message)" -match '0x8007052E') {
    Send-Refusal 'credential_invalid' @{account = $d.account}
  }
  throw
}
Start-ScheduledTask -TaskName $d.task
'{}'
"""

# Unregisters an account's ended install task, deletes its script, and
# answers the end of its output.
FINISH_INSTALL_SCRIPT = """
Unregister-ScheduledTask -TaskName $d.task -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $d.script -Force -ErrorAction SilentlyContinue
$output = ''
if (Test-Path -LiteralPath $d.log) { $output = [IO.File]::ReadAllText($d.log) }
if ($output.Length -gt 8000) { $output = $output.Substring($output.Length - 8000) }
@{output = $output} | ConvertTo-Json -Compress -Depth 4
"""

# Writes each instance's script, registers the tasks that changed, starts
# them, restarts one whose script changed, opens each instance's port in the
# firewall, and unregisters the module's tasks no instance names, closing
# their ports.
APPLY_SCRIPT = """
$notes = @()
foreach ($i in @($d.instances)) {
  $dir = Split-Path -Parent $i.script
  if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  $held = ''
  if (Test-Path -LiteralPath $i.script) { $held = [IO.File]::ReadAllText($i.script) }
  $is_changed = $held -ne $i.script_text
  [IO.File]::WriteAllText($i.script, $i.script_text)
  $code = Invoke-Icacls $i.script /inheritance:r /grant:r "$($i.account):R" `
    '*S-1-5-18:F' '*S-1-5-32-544:F'
  if ($code -ne 0) { throw "icacls refused the script of $($i.account)" }
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
    $notes += "registered CloudCLI of $($i.account)"
  } elseif ($is_changed) {
    Stop-ScheduledTask -TaskName $i.task -ErrorAction SilentlyContinue
    $notes += "restarted CloudCLI of $($i.account)"
  }
  if ((Get-ScheduledTask -TaskName $i.task).State -ne 'Running') {
    Start-ScheduledTask -TaskName $i.task
  }
  $rule = Get-NetFirewallRule -Name $i.rule -ErrorAction SilentlyContinue
  if (-not $rule) {
    New-NetFirewallRule -Name $i.rule -DisplayName $i.rule_title `
      -Direction Inbound -Action Allow -Protocol TCP -LocalPort $i.port `
      -Profile Any | Out-Null
    $notes += "opened port $($i.port) for $($i.account)"
  } elseif ("$(($rule | Get-NetFirewallPortFilter).LocalPort)" -ne "$($i.port)") {
    $rule | Set-NetFirewallRule -LocalPort $i.port
    $notes += "moved the port of $($i.account) to $($i.port)"
  }
}
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  if (@($d.tasks) -notcontains $task.TaskName) {
    Stop-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false
    $account = $task.TaskName.Substring($d.prefix.Length)
    foreach ($file in @((Join-Path $d.script_dir "$account.cmd"),
        (Join-Path $d.log_dir "$account$($d.log_suffix)"))) {
      Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
    }
    Remove-NetFirewallRule -Name "$($d.rule_prefix)$account" -ErrorAction SilentlyContinue
    $notes += "removed $($task.TaskName)"
  }
}
@{notes = $notes} | ConvertTo-Json -Compress -Depth 4
"""

# Stops the module's tasks; with ``is_removed`` also unregisters them,
# deletes their scripts and closes their ports.
WITHDRAW_SCRIPT = """
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  Stop-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue
  if ($d.is_removed) { Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false }
}
if ($d.is_removed -and (Test-Path -LiteralPath $d.script_dir)) {
  Remove-Item -LiteralPath $d.script_dir -Recurse -Force
}
if ($d.is_removed) {
  Remove-NetFirewallRule -Name "$($d.rule_prefix)*" -ErrorAction SilentlyContinue
}
'{}'
"""

# Each of the module's tasks: its state and its last result.
STATUS_SCRIPT = """
$tasks = @()
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
  $tasks += @{name = $task.TaskName; state = "$($task.State)";
    last_result = [int64]$info.LastTaskResult}
}
@{tasks = $tasks} | ConvertTo-Json -Compress -Depth 4
"""


def task_name(account: str) -> str:
    """The task one account's CloudCLI runs as.

    Args:
        account: The account.

    Returns:
        ``neutrino_cloudcli_<account>``.
    """
    return CLOUDCLI_TASK_PREFIX + account


def render_script(environment: dict, *, node: str, server: str) -> str:
    """The script one instance's task runs.

    Args:
        environment: What it sets before it starts CloudCLI.
        node: The Node.js interpreter.
        server: The server script of the account's app directory.

    Returns:
        The ``.cmd`` text, CRLF line ends.
    """
    lines = ["@echo off"]
    lines += [f'set "{name}={value}"' for name, value in environment.items()]
    lines += ['cd /d "%USERPROFILE%"', subprocess.list2cmdline([node, server])]
    return "\r\n".join(lines) + "\r\n"


def render_install_script(*, app: str, node: str, npm: str, registry: str = "") -> str:
    """The script an account's install task runs.

    Args:
        app: The account's app directory.
        node: The Node.js interpreter.
        npm: npm's script.
        registry: The registry npm installs from; empty for npm's own.

    Returns:
        The ``.cmd`` text, CRLF line ends: the app directory and the empty
        npm configuration made, Node's directory leading ``PATH``, npm run,
        then the native check, exiting with npm's failure or the check's.
    """
    environment = {
        "PATH": ";".join([ntpath.dirname(node), *CLOUDCLI_WINDOWS_NPM_PATH]),
        **installer.npm_environment(app, join=ntpath.join, registry=registry),
    }
    lines = ["@echo off", f'if not exist "{app}" mkdir "{app}"']
    lines.append(f'type nul > "{environment["npm_config_userconfig"]}"')
    lines += [f'set "{name}={value}"' for name, value in environment.items()]
    lines.append(
        subprocess.list2cmdline([node, npm, *installer.npm_arguments(app)])
        + f" || exit /b {NPM_FAILED_EXIT}"
    )
    lines.append(f'cd /d "{app}"')
    lines.append(f'"{node}" -e "{installer.NATIVE_CHECK_SCRIPT}"')
    return "\r\n".join(lines) + "\r\n"


def _digest(program: str, arguments: str, account: str, password: str) -> str:
    """What a task runs and with which login, in 16 hex digits."""
    material = json.dumps([program, arguments, account, password])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class CloudcliWindowsApplier:
    """Runs each instance as a scheduled task signed in with its account."""

    def __init__(
        self, *, module_dir: str, record_dir: str, account_home, powershell=None
    ):
        """
        Args:
            module_dir: Where Node.js is unpacked, under the root every
                account reads; the scripts and the logs live under it.
            record_dir: Where the records live, under the agent's own
                state root.
            account_home: Returns an account's profile directory or raises
                KeyError.
            powershell: Called with ``(script, document, timeout_s=)``;
                returns the JSON object the script printed. None runs
                PowerShell.
        """
        self.module_dir = module_dir
        self.record_dir = record_dir
        self._script_dir = ntpath.join(module_dir, CLOUDCLI_WINDOWS_SCRIPT_DIR_NAME)
        self._account_home = account_home
        self._powershell = powershell if powershell is not None else run_powershell
        # The accounts whose install task the last apply found running.
        self.installing: frozenset = frozenset()

    @property
    def node(self) -> str:
        """The Node.js interpreter, empty when none is unpacked."""
        directory = installer.node_dir(self.module_dir)
        return (
            ntpath.join(directory, *CLOUDCLI_NODE_PARTS["windows"]) if directory else ""
        )

    def log_path(self, account: str) -> str:
        """The file one account's CloudCLI writes its output to.

        Args:
            account: The account.

        Returns:
            ``<module dir>\\<account>.log``.
        """
        return ntpath.join(self.module_dir, account + CLOUDCLI_LOG_SUFFIX)

    def install_log_path(self, account: str) -> str:
        """The file one account's install task writes its output to.

        Args:
            account: The account.

        Returns:
            ``<module dir>\\run\\install_<account>.log``.
        """
        return ntpath.join(self._script_dir, f"install_{account}{CLOUDCLI_LOG_SUFFIX}")

    def apply(self, config, upstream_ports: dict) -> list:
        """Install CloudCLI for each account, register and start one task per instance, remove the rest.

        Args:
            config: The validated :class:`CloudcliConfig`.
            upstream_ports: Account to the loopback port its CloudCLI
                listens on.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``account_unknown`` for an account with no
                profile, ``cloudcli_node_download_failed`` with no Node.js,
                ``credential_invalid`` when Windows refuses an account's
                login, and an install's ``cloudcli_npm_install_failed`` or
                ``cloudcli_native_module_failed``.
            ModuleInstallPending: While an account's install task runs; no
                instance is started then.
            OSError: When PowerShell fails.
        """
        node = self.node
        if not node:
            raise ModuleApplyError("cloudcli_node_download_failed", {})
        homes = {}
        for instance in config.instances:
            try:
                homes[instance.account] = self._account_home(instance.account)
            except KeyError:
                raise ModuleApplyError(
                    "account_unknown", {"account": instance.account}
                ) from None
        notes = []
        tasks = self._install_tasks()
        running = []
        try:
            for instance in config.instances:
                step = self._install_app(
                    instance,
                    homes[instance.account],
                    node,
                    tasks.get(CLOUDCLI_INSTALL_TASK_PREFIX + instance.account),
                    registry=config.npm_registry,
                )
                if step == INSTALL_RUNNING:
                    running.append(instance.account)
                elif step == INSTALL_FINISHED:
                    notes.append(f"installed CloudCLI for {instance.account}")
        finally:
            self.installing = frozenset(running)
        if running:
            raise ModuleInstallPending(", ".join(running))
        instances = []
        for instance in config.instances:
            home = homes[instance.account]
            script = ntpath.join(self._script_dir, instance.account + ".cmd")
            log_file = self.log_path(instance.account)
            arguments = task_arguments(script, [], log_file)
            environment = installer.service_environment(
                config,
                instance,
                upstream_port=upstream_ports[instance.account],
                home=home,
                os_name="windows",
                node_dir=ntpath.dirname(node),
                join=ntpath.join,
            )
            server = installer.server_path(
                installer.app_dir(home, "windows", join=ntpath.join), join=ntpath.join
            )
            instances.append(
                {
                    "account": instance.account,
                    "password": instance.password,
                    "script": script,
                    "script_text": render_script(environment, node=node, server=server),
                    "log_file": log_file,
                    "task": task_name(instance.account),
                    "port": instance.port,
                    "rule": CLOUDCLI_WINDOWS_RULE_PREFIX + instance.account,
                    "rule_title": CLOUDCLI_WINDOWS_RULE_TITLE.format(
                        account=instance.account
                    ),
                    "arguments": arguments,
                    "description": CLOUDCLI_TASK_MARKER
                    + _digest(
                        CLOUDCLI_WINDOWS_SHELL,
                        arguments,
                        instance.account,
                        instance.password,
                    ),
                }
            )
        answer = self._powershell(
            APPLY_SCRIPT,
            {
                "program": CLOUDCLI_WINDOWS_SHELL,
                "script_dir": self._script_dir,
                "log_dir": self.module_dir,
                "log_suffix": CLOUDCLI_LOG_SUFFIX,
                "prefix": CLOUDCLI_TASK_PREFIX,
                "rule_prefix": CLOUDCLI_WINDOWS_RULE_PREFIX,
                "tasks": [entry["task"] for entry in instances],
                "instances": instances,
            },
        )
        return notes + [str(note) for note in listed(answer.get("notes"))]

    def stop(self) -> None:
        """Stop every instance's task; each starts again at boot.

        Raises:
            OSError: When PowerShell fails.
        """
        self._withdraw(is_removed=False)

    def remove(self) -> None:
        """Stop and unregister every instance's task and delete the scripts.

        Raises:
            OSError: When PowerShell fails.
        """
        self._withdraw(is_removed=True)

    def states(self, accounts: list) -> dict:
        """Whether each account's task runs, and whether it can sign in.

        Args:
            accounts: The accounts asked about.

        Returns:
            Account to ``{"is_running", "code"}``, ``code`` being
            ``credential_invalid`` for a task Windows cannot sign in.
        """
        try:
            read = self._powershell(STATUS_SCRIPT, {"prefix": CLOUDCLI_TASK_PREFIX})
        except (OSError, subprocess.SubprocessError, ModuleApplyError):
            read = {}
        tasks = {
            str(entry.get("name", "")): entry
            for entry in listed(read.get("tasks"))
            if isinstance(entry, dict)
        }
        states = {}
        for account in accounts:
            entry = tasks.get(task_name(account)) or {}
            result = int(entry.get("last_result", 0) or 0) & 0xFFFFFFFF
            states[account] = {
                "is_running": str(entry.get("state", "")) == "Running",
                "code": (
                    "credential_invalid" if result in CLOUDCLI_LOGON_FAILURES else ""
                ),
            }
        return states

    def units(self) -> list:
        """No journal: a task keeps none."""
        return []

    def log_paths(self, accounts: list) -> list:
        """Each instance's log file, or its install's while that runs.

        Args:
            accounts: The accounts asked about.

        Returns:
            ``[(account, path)]``, in that order.
        """
        return [
            (
                account,
                (
                    self.install_log_path(account)
                    if account in self.installing
                    else self.log_path(account)
                ),
            )
            for account in accounts
        ]

    def _install_tasks(self) -> dict:
        """Each account's install task as Windows holds it, by its name."""
        read = self._powershell(STATUS_SCRIPT, {"prefix": CLOUDCLI_INSTALL_TASK_PREFIX})
        return {
            str(entry.get("name", "")): entry
            for entry in listed(read.get("tasks"))
            if isinstance(entry, dict)
        }

    def _install_app(
        self,
        instance,
        home: str,
        node: str,
        task: "dict | None",
        *,
        registry: str = "",
    ) -> str:
        """Judge an account's install task, or start one when CloudCLI is not there.

        Returns:
            ``INSTALL_READY``, ``INSTALL_FINISHED`` or ``INSTALL_RUNNING``.

        Raises:
            ModuleApplyError: The step an ended install failed at.
        """
        account = instance.account
        app = installer.app_dir(home, "windows", join=ntpath.join)
        script = ntpath.join(self._script_dir, f"install_{account}.cmd")
        log_file = self.install_log_path(account)
        name = CLOUDCLI_INSTALL_TASK_PREFIX + account
        if task is not None:
            if str(task.get("state", "")) in INSTALL_RUNNING_STATES:
                return INSTALL_RUNNING
            self._judge_install(task, app, name, script, log_file, account)
            return INSTALL_FINISHED
        if installer.is_app_ready(app):
            return INSTALL_READY
        directory = ntpath.dirname(node)
        npm = ntpath.join(directory, *CLOUDCLI_NPM_PARTS["windows"])
        self._powershell(
            INSTALL_SCRIPT,
            {
                "account": account,
                "password": instance.password,
                "task": name,
                "script": script,
                "script_text": render_install_script(
                    app=app, node=node, npm=npm, registry=registry
                ),
                "log": log_file,
                "program": CLOUDCLI_WINDOWS_SHELL,
                "arguments": task_arguments(script, [], log_file),
                "timeout_s": CLOUDCLI_WINDOWS_INSTALL_LIMIT_S,
            },
        )
        return INSTALL_RUNNING

    def _judge_install(
        self, task: dict, app: str, name: str, script: str, log_file: str, account: str
    ) -> None:
        """Unregister an ended install task and raise the step it failed at."""
        answer = self._powershell(
            FINISH_INSTALL_SCRIPT, {"task": name, "script": script, "log": log_file}
        )
        output = str(answer.get("output", "") or "")
        result = int(task.get("last_result", 0) or 0) & 0xFFFFFFFF
        if result in CLOUDCLI_LOGON_FAILURES:
            raise ModuleApplyError("credential_invalid", {"account": account})
        if result == installer.NATIVE_CHECK_EXIT:
            lines = output.strip().splitlines()
            raise ModuleApplyError(
                "cloudcli_native_module_failed",
                {"account": account, "module": lines[-1] if lines else ""},
            )
        if result != 0 or not installer.is_app_ready(app):
            raise installer.npm_failure(output, account)

    def _withdraw(self, *, is_removed: bool) -> None:
        self._powershell(
            WITHDRAW_SCRIPT,
            {
                "prefix": CLOUDCLI_TASK_PREFIX,
                "rule_prefix": CLOUDCLI_WINDOWS_RULE_PREFIX,
                "is_removed": is_removed,
                "script_dir": self._script_dir,
            },
        )
