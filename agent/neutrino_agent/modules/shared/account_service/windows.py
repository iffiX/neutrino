"""A module's instances on Windows: one scheduled task per account.

LocalSystem cannot start a process as another account without that
account's password, so each instance is a task registered with the
account's login: it starts at boot, runs with the account's limited token,
has no time limit, and restarts when it stops. The task's description
carries a digest of what it runs and with which login, so an unchanged
instance is left running and a changed one is registered again. The task
runs the program through ``cmd.exe`` with its output appended to the
account's log file beside the program, or sent to the null device for a
service that discards it; a service with an environment, a working directory
or a discarded output runs a script that sets them first. The files the task
reads are reachable by their account, SYSTEM and the administrators alone.
An instance's processes are the ones whose command line names its log file,
or its script where the output is discarded, and every process they
started; a stop ends all of them, and an instance with a port runs while
one of them listens on it. The account holds the batch logon right from
its first task's write until its last task is removed. The task goes
through the agent's PowerShell host, the password on its standard input;
the files, their access lists and the processes are the agent's own work.

Not pure: writes files, runs icacls, drives the Task Scheduler, changes
the local security policy and ends processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import shutil
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.account_service import task_name
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_LOG_SUFFIX,
    ACCOUNT_SERVICE_LOGON_FAILURES,
    ACCOUNT_SERVICE_TASK_MARKER,
    ACCOUNT_SERVICE_TASK_PREFIX,
    ACCOUNT_SERVICE_WINDOWS_NULL_DEVICE,
    ACCOUNT_SERVICE_WINDOWS_RULE_INFIX,
    ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME,
    ACCOUNT_SERVICE_WINDOWS_SCRIPT_SUFFIX,
    ACCOUNT_SERVICE_WINDOWS_SHELL,
    ACCOUNT_SERVICE_WINDOWS_TASK_RUNNING,
)
from neutrino_agent.modules.shared.windows_acl import grant_account_alone
from neutrino_agent.platforms.windows_processes import lineage, process_tree


def task_arguments(program: str, arguments: list, log_file: str) -> str:
    """What ``cmd.exe`` is handed to run a program with its output in a log.

    Args:
        program: The program, or the script that starts it.
        arguments: The program's own arguments.
        log_file: The file its output and its errors are appended to; empty
            sends both to the null device.

    Returns:
        ``/s /c "<program> <arguments> >> <log> 2>&1"``, or with ``> NUL``
        in place of the log.
    """
    command = subprocess.list2cmdline([program, *arguments])
    if not log_file:
        return f'/s /c "{command} > {ACCOUNT_SERVICE_WINDOWS_NULL_DEVICE} 2>&1"'
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


def output_mark(service, machine) -> str:
    """What an instance's processes are found by on their command line.

    Args:
        service: The service.
        machine: The machine.

    Returns:
        The instance's log file, or its script where the output is discarded.
    """
    if service.is_output_discarded:
        return script_path(service, machine)
    return log_path(service.name, service.account, machine, service.log_name)


def rule_prefix(name: str) -> str:
    """The name an older build gave the module's firewall rules, without the port."""
    return f"{ACCOUNT_SERVICE_TASK_PREFIX}{name}{ACCOUNT_SERVICE_WINDOWS_RULE_INFIX}"


def define(template, machine) -> bool:
    """Nothing is shared: each instance has its own task."""
    return False


def task_files(service, machine) -> list:
    """The files one instance's task reads: the account's, and its script when it has one.

    Args:
        service: The service.
        machine: The machine.

    Returns:
        ``[{"path", "text"}]``.
    """
    files = [{"path": path, "text": text} for path, text in service.files]
    if _is_scripted(service):
        files.append(
            {"path": script_path(service, machine), "text": render_script(service)}
        )
    return files


def arguments_of(service, machine) -> str:
    """What ``cmd.exe`` is handed for one instance: its script, or the program itself.

    Args:
        service: The service.
        machine: The machine.

    Returns:
        The task's arguments, the output appended to the instance's log, or
        discarded where the service says.
    """
    log = _output_log(service, machine)
    if _is_scripted(service):
        return task_arguments(script_path(service, machine), [], log)
    return task_arguments(service.command[0], list(service.command[1:]), log)


def write(service, machine) -> bool:
    """Write the account's files and its log, and register the task when it changed.

    The account is granted the batch logon right first where it needs it.
    Every firewall rule an older build opened for an instance's port goes.

    Returns:
        Whether the task was registered.
    """
    log = _output_log(service, machine)
    files = task_files(service, machine)
    for file in files:
        write_text(file["path"], file["text"])
        grant_account_alone(
            machine.run, file["path"], service.account, "R", is_tree=False
        )
    for directory in service.directories:
        os.makedirs(directory, exist_ok=True)
        grant_account_alone(machine.run, directory, service.account, "M", is_tree=True)
    if log:
        if not os.path.exists(log):
            write_text(log, "")
        grant_account_alone(machine.run, log, service.account, "M", is_tree=False)
    arguments = arguments_of(service, machine)
    description = task_description(arguments, service, [file["text"] for file in files])
    task = task_name(service.name, service.account)
    if machine.batch_logon is not None:
        machine.batch_logon.hold(service.account, task, service.password)
    held = machine.powershell.call("task_read", {"task": task})
    is_registered = False
    if not held.get("is_present") or held.get("description") != description:
        if held.get("is_present"):
            _stop_instance(task, output_mark(service, machine), machine)
        machine.powershell.call(
            "task_write",
            {
                "task": task,
                "description": description,
                "program": ACCOUNT_SERVICE_WINDOWS_SHELL,
                "arguments": arguments,
                "account": service.account,
                "password": service.password,
            },
        )
        is_registered = True
    machine.powershell.call("rules_forget", {"prefix": rule_prefix(service.name)})
    return is_registered


def start(service, machine, *, is_restart: bool) -> None:
    """Start the task unless it runs, ending what is left of the instance first."""
    task = task_name(service.name, service.account)
    held = machine.powershell.call("task_read", {"task": task})
    if held.get("state") == ACCOUNT_SERVICE_WINDOWS_TASK_RUNNING:
        return
    _stop_instance(task, output_mark(service, machine), machine)
    machine.powershell.call("task_start", {"task": task})


def stop(service, machine) -> None:
    """Stop the task and end the instance's process tree; it starts again at boot."""
    _stop_instance(
        task_name(service.name, service.account),
        output_mark(service, machine),
        machine,
    )


def remove(service, machine) -> None:
    """Stop the instance, unregister its task and delete what it ran from.

    The account's batch logon right goes with its last task, where the
    agent granted it.
    """
    task = task_name(service.name, service.account)
    _stop_instance(task, output_mark(service, machine), machine)
    machine.powershell.call("task_remove", {"task": task})
    if machine.batch_logon is not None:
        machine.batch_logon.release(service.account, task)
    paths = [path for path, _text in service.files]
    paths.append(script_path(service, machine))
    if not service.is_output_discarded:
        paths.append(log_path(service.name, service.account, machine, service.log_name))
    paths += list(service.directories)
    for path in paths:
        remove_path(path)


def states(services: list, machine) -> dict:
    """Whether each instance runs, and whether its task can sign in.

    An instance whose service names a port runs while its process tree
    listens on it; any other runs while its task does.
    """
    if not services:
        return {}
    name = services[0].name
    try:
        read = machine.powershell.call(
            "task_states", {"prefix": f"{ACCOUNT_SERVICE_TASK_PREFIX}{name}_"}
        )
    except (OSError, ModuleApplyError):
        read = {}
    tasks = {
        str(entry.get("name", "")): entry
        for entry in read.get("tasks") or []
        if isinstance(entry, dict)
    }
    entries = None
    held = {}
    for service in services:
        entry = tasks.get(task_name(name, service.account))
        result = int((entry or {}).get("last_result", 0) or 0) & 0xFFFFFFFF
        if entry is None:
            is_running = False
        elif service.listen_port:
            if entries is None:
                entries = _process_entries(machine)
            is_running = _is_listening(
                output_mark(service, machine), service.listen_port, entries, machine
            )
        else:
            is_running = (
                str(entry.get("state", "")) == ACCOUNT_SERVICE_WINDOWS_TASK_RUNNING
            )
        held[service.account] = {
            "is_running": is_running,
            "code": (
                "credential_invalid" if result in ACCOUNT_SERVICE_LOGON_FAILURES else ""
            ),
        }
    return held


def forget(name: str, machine) -> None:
    """Remove the firewall rules an older build opened for the module."""
    machine.powershell.call("rules_forget", {"prefix": rule_prefix(name)})


def units(services: list, machine) -> list:
    """No journal: a task keeps none."""
    return []


def log_path(name: str, account: str, machine, log_name: str) -> str:
    """The file one instance's output goes to, beside the program."""
    return ntpath.join(
        machine.module_dir, log_name or account + ACCOUNT_SERVICE_LOG_SUFFIX
    )


def write_text(path: str, text: str) -> None:
    """Write one file whole as UTF-8 without a byte order mark, its folder made.

    Args:
        path: The file.
        text: What it holds afterwards, line ends as given.

    Raises:
        OSError: When the file cannot be written.
    """
    os.makedirs(ntpath.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(text.encode("utf-8"))


def remove_path(path: str) -> None:
    """Delete a file or a tree; what cannot be deleted stays.

    Args:
        path: The file or the directory.
    """
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _stop_instance(task: str, mark: str, machine) -> None:
    """Take the instance's process tree, stop its task, and end what is left."""
    entries = machine.processes.entries()
    roots = [
        entry.pid
        for entry in entries
        if entry.pid and mark in machine.processes.command_line(entry.pid)
    ]
    tree = process_tree(entries, roots)
    machine.powershell.call("task_stop", {"task": task})
    machine.processes.end(tree)


def _process_entries(machine) -> list:
    """The process table, empty when the kernel refuses it."""
    try:
        return machine.processes.entries()
    except OSError:
        return []


def _is_listening(mark: str, port: int, entries: list, machine) -> bool:
    """Whether a process of the instance's tree listens on its port."""
    for pid in machine.processes.listener_pids(port):
        for member in lineage(entries, pid):
            if mark in machine.processes.command_line(member):
                return True
    return False


def _is_scripted(service) -> bool:
    return bool(
        service.environment or service.working_directory or service.is_output_discarded
    )


def _output_log(service, machine) -> str:
    """The file a task's output is appended to; empty for a discarded output."""
    if service.is_output_discarded:
        return ""
    return log_path(service.name, service.account, machine, service.log_name)
