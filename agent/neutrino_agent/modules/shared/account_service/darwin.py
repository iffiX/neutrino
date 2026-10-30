"""A module's instances on macOS: one LaunchDaemon per account.

Each instance is a LaunchDaemon whose plist names the account in
``UserName``, so root's launchd starts the program as that account with no
password, its output appended to the instance's file under the agents' log
directory. The log file belongs to the account, mode 0600. A plist that
changed, or a job launchd does not hold, is loaded again.

Not pure: writes under ``/Library`` and drives launchd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import plistlib
import subprocess

from neutrino_agent.modules.shared.account_service import (
    label,
    remove_account_files,
    write_account_files,
    write_if_changed,
)
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_LOG_SUFFIX,
    ACCOUNT_SERVICE_PLIST_SUFFIX,
)


def render_plist(service, *, home: str, log_path: str) -> bytes:
    """One instance's LaunchDaemon.

    Args:
        service: The service.
        home: The account's home, where a service that starts in ``~`` runs.
        log_path: The file its output and its errors are appended to; unread
            for a service whose output is discarded.

    Returns:
        The plist, as XML.
    """
    document = {
        "Label": label(service.name, service.account),
        "UserName": service.account,
        "ProgramArguments": list(service.command),
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    if not service.is_output_discarded:
        document["StandardOutPath"] = log_path
        document["StandardErrorPath"] = log_path
    if service.environment:
        document["EnvironmentVariables"] = dict(service.environment)
    if service.working_directory:
        document["WorkingDirectory"] = (
            home if service.working_directory == "~" else service.working_directory
        )
    if service.umask:
        document["Umask"] = int(service.umask, 8)
    if service.is_process_group_abandoned:
        document["AbandonProcessGroup"] = True
    return plistlib.dumps(document)


def plist_path(service, machine) -> str:
    """Where one instance's plist is written."""
    return os.path.join(
        machine.launchd_dir,
        label(service.name, service.account) + ACCOUNT_SERVICE_PLIST_SUFFIX,
    )


def define(template, machine) -> bool:
    """Nothing is shared: each instance has its own plist."""
    return False


def write(service, machine) -> bool:
    """Write the account's files, its log and its plist; whether one changed."""
    entry = machine.lookup_account(service.account)
    is_changed = write_account_files(service, entry, machine)
    log = log_path(service.name, service.account, machine, service.log_name)
    if not service.is_output_discarded:
        os.makedirs(machine.log_dir, mode=0o755, exist_ok=True)
        with open(log, "a", encoding="utf-8"):
            pass
        os.chmod(log, 0o600)
        machine.chown(log, entry.uid, entry.gid)
    plist = render_plist(service, home=entry.home, log_path=log)
    return (
        write_if_changed(
            plist_path(service, machine),
            plist.decode("utf-8"),
            0o600 if service.is_environment_secret else 0o644,
        )
        or is_changed
    )


def start(service, machine, *, is_restart: bool) -> None:
    """Enable the job, then load it, booting it out first when it changed or is not held."""
    name = label(service.name, service.account)
    machine.run(["launchctl", "enable", f"system/{name}"], is_checked=False)
    if is_restart or not _is_loaded(name, machine):
        machine.run(["launchctl", "bootout", f"system/{name}"], is_checked=False)
        machine.run(["launchctl", "bootstrap", "system", plist_path(service, machine)])


def stop(service, machine) -> None:
    """Disable the job and boot it out, so it stays stopped across a reboot."""
    name = label(service.name, service.account)
    machine.run(["launchctl", "disable", f"system/{name}"], is_checked=False)
    machine.run(["launchctl", "bootout", f"system/{name}"], is_checked=False)


def remove(service, machine) -> None:
    """Boot the job out and delete its plist, its log and the account's files."""
    stop(service, machine)
    paths = [plist_path(service, machine)]
    if not service.is_output_discarded:
        paths.append(log_path(service.name, service.account, machine, service.log_name))
    for path in paths:
        with contextlib.suppress(OSError):
            os.unlink(path)
    remove_account_files(service)


def states(services: list, machine) -> dict:
    """Whether launchd runs each instance's job."""
    return {
        service.account: {
            "is_running": _is_running(label(service.name, service.account), machine),
            "code": "",
        }
        for service in services
    }


def forget(name: str, machine) -> None:
    """Nothing is shared: each instance's plist went with it."""


def units(services: list, machine) -> list:
    """No journal: launchd keeps none."""
    return []


def log_path(name: str, account: str, machine, log_name: str) -> str:
    """The file one instance's output goes to under the agents' log directory."""
    return os.path.join(
        machine.log_dir, log_name or f"{name}_{account}{ACCOUNT_SERVICE_LOG_SUFFIX}"
    )


def _is_loaded(name: str, machine) -> bool:
    result = machine.run(["launchctl", "print", f"system/{name}"], is_checked=False)
    return result.is_success


def _is_running(name: str, machine) -> bool:
    try:
        result = machine.run(["launchctl", "print", f"system/{name}"], is_checked=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.is_success and "state = running" in result.stdout
