"""One program run as a person's account, as every system's service manager takes it.

A module describes an instance's service once, as an :class:`AccountService`,
and names nothing of the system. The functions here write that definition,
start, stop, remove and query the service, each dispatched to the system's
own file: a systemd unit with ``User=`` on Linux, a LaunchDaemon with
``UserName`` on macOS, a scheduled task registered with the account's login
on Windows.

Not pure: the system files write definitions and drive the service manager.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import importlib
import os
import shutil
from dataclasses import dataclass, field

from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_DARWIN_LOG_DIR,
    ACCOUNT_SERVICE_LAUNCHD_DIR,
    ACCOUNT_SERVICE_LAUNCHD_PREFIX,
    ACCOUNT_SERVICE_SYSTEMD_DIR,
    ACCOUNT_SERVICE_TASK_PREFIX,
    ACCOUNT_SERVICE_UNIT_PREFIX,
    ACCOUNT_SERVICE_UNIT_SUFFIX,
)
from neutrino_agent.modules.shared.subprocess_run import run as run_command

# The systems the layer has a file for, by the platform's name.
SYSTEM_MODULES = {
    "linux": "neutrino_agent.modules.shared.account_service.linux",
    "darwin": "neutrino_agent.modules.shared.account_service.darwin",
    "windows": "neutrino_agent.modules.shared.account_service.windows",
}


def _no_chown(path: str, uid: int, gid: int) -> None:
    """What ``chown`` is on a system without one."""


@dataclass(frozen=True)
class AccountEntry:
    """One account as the account database describes it.

    Attributes:
        uid: The account's user id; 0 where the system has none.
        gid: Its group id; 0 where the system has none.
        home: Its home directory.
        shell: Its login shell; empty where the system has none.
    """

    uid: int
    gid: int
    home: str
    shell: str = ""


@dataclass(frozen=True)
class AccountService:
    """One instance's service, the same description on every system.

    Attributes:
        name: The module's name, which names the unit
            ``neutrino_<name>@<account>.service``, the LaunchDaemon
            ``com.neutrino.<name>.<account>`` and the task
            ``neutrino_<name>_<account>``.
        title: What the unit's description calls the program.
        account: The account the program runs as.
        command: The argument vector.
        environment: What the program runs with, name to value, written
            from scratch; empty inherits nothing and writes no file.
        working_directory: Where the program starts: ``~`` is the account's
            home; empty is the service manager's own.
        log_name: The file the output goes to on macOS, under the agents'
            log directory, and on Windows, beside the program; empty is
            ``<name>_<account>.log`` there and ``<account>.log`` here.
        umask: The umask the program runs under, as octal digits; empty
            keeps the service manager's.
        password: The account's login, which a Windows task is registered
            with; unread elsewhere.
        listen_port: The loopback port the program answers on; Windows
            reads a running instance off it, and 0 reads the task's state.
        environment_dir: Linux: where the environment file is written,
            ``<account>.env`` under it; empty is the module's record
            directory.
        is_environment_secret: Whether the environment holds a secret: the
            file that carries it is root-only and every value is quoted.
        files: ``(path, text)`` pairs the program reads as the account:
            each is written whole, mode 0600, the account's own.
        directories: Directories the account owns: made mode 0700 before
            the service starts, deleted with it.
        is_output_discarded: Whether stdout and stderr are discarded: the
            unit's output goes to systemd's null on Linux, and no log file
            is written on macOS or Windows.
    """

    name: str
    title: str
    account: str
    command: tuple
    environment: dict = field(default_factory=dict)
    working_directory: str = ""
    log_name: str = ""
    umask: str = ""
    password: str = ""
    listen_port: int = 0
    environment_dir: str = ""
    is_environment_secret: bool = False
    files: tuple = ()
    directories: tuple = ()
    is_output_discarded: bool = False


@dataclass(frozen=True)
class ServiceMachine:
    """This machine as the layer reaches it, for one module's services.

    Attributes:
        os_name: ``linux``, ``darwin`` or ``windows``.
        module_dir: The module's directory under the state root.
        record_dir: The module's directory under the configuration root.
        lookup_account: Returns an account's :class:`AccountEntry`, or
            raises KeyError for one the machine does not have.
        run: Runs one command as :func:`subprocess_run.run` does.
        chown: Changes a file's owner as :func:`os.chown` does.
        powershell: Windows: the agent's PowerShell host, asked as
            :meth:`WindowsPowerShellHost.call` is; None elsewhere.
        processes: Windows: the machine's processes, read and ended as
            :class:`WindowsProcessTable` does; None elsewhere.
        systemd_dir: Where the template unit is written.
        launchd_dir: Where the plists are written.
        log_dir: Where the macOS log files are.
    """

    os_name: str
    module_dir: str
    record_dir: str
    lookup_account: object
    run: object = run_command
    chown: object = getattr(os, "chown", _no_chown)
    powershell: object = None
    processes: object = None
    systemd_dir: str = ACCOUNT_SERVICE_SYSTEMD_DIR
    launchd_dir: str = ACCOUNT_SERVICE_LAUNCHD_DIR
    log_dir: str = ACCOUNT_SERVICE_DARWIN_LOG_DIR


def write_if_changed(path: str, text: str, mode: int) -> bool:
    """Write a file whole unless it already holds this text.

    Args:
        path: The file.
        text: What it holds afterwards.
        mode: Its permission bits.

    Returns:
        Whether it changed.

    Raises:
        OSError: When the file cannot be written.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            if stream.read() == text:
                return False
    except OSError:
        pass
    temporary = path + ".new"
    with open(temporary, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    return True


def write_account_files(service: AccountService, entry: AccountEntry, machine) -> bool:
    """Write the files and make the directories a service's account owns.

    Args:
        service: The service.
        entry: Its account.
        machine: The machine, whose ``chown`` hands each over.

    Returns:
        Whether a file's text changed.

    Raises:
        OSError: When a file or a directory cannot be written.
    """
    is_changed = False
    for path, text in service.files:
        os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
        is_changed |= write_if_changed(path, text, 0o600)
        machine.chown(path, entry.uid, entry.gid)
    for directory in service.directories:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        machine.chown(directory, entry.uid, entry.gid)
    return is_changed


def remove_account_files(service: AccountService) -> None:
    """Delete the files and the directories a service's account owned.

    Args:
        service: The service.
    """
    for path, _text in service.files:
        try:
            os.unlink(path)
        except OSError:
            pass
    for directory in service.directories:
        shutil.rmtree(directory, ignore_errors=True)


def unit_name(name: str, account: str) -> str:
    """The unit one instance runs as on Linux: ``neutrino_<name>@<account>.service``."""
    return f"{ACCOUNT_SERVICE_UNIT_PREFIX}{name}@{account}{ACCOUNT_SERVICE_UNIT_SUFFIX}"


def label(name: str, account: str) -> str:
    """The LaunchDaemon one instance runs as on macOS: ``com.neutrino.<name>.<account>``."""
    return f"{ACCOUNT_SERVICE_LAUNCHD_PREFIX}{name}.{account}"


def task_name(name: str, account: str) -> str:
    """The task one instance runs as on Windows: ``neutrino_<name>_<account>``."""
    return f"{ACCOUNT_SERVICE_TASK_PREFIX}{name}_{account}"


def define(template: AccountService, machine: ServiceMachine) -> bool:
    """Write what every instance of one module shares.

    Args:
        template: The service of the instance whose account is systemd's
            ``%i``; on Linux the template unit is rendered from it.
        machine: The machine.

    Returns:
        Whether the shared definition changed, so every instance restarts.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        OSError: When the definition cannot be written.
        subprocess.CalledProcessError: When the service manager refuses.
    """
    return _system(machine).define(template, machine)


def write(service: AccountService, machine: ServiceMachine) -> bool:
    """Write one instance's definition, its environment and its account's files.

    Args:
        service: The service.
        machine: The machine.

    Returns:
        Whether something the instance runs from changed.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        ModuleApplyError: ``credential_invalid`` when Windows refuses the
            account's login.
        KeyError: When the machine does not have the account.
        OSError: When a file cannot be written, or the PowerShell host fails.
    """
    return _system(machine).write(service, machine)


def start(
    service: AccountService, machine: ServiceMachine, *, is_restart: bool
) -> None:
    """Start one instance, or start it again when it must take a change.

    Args:
        service: The service.
        machine: The machine.
        is_restart: Whether a running instance is started again.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        OSError: When the PowerShell host fails.
        subprocess.CalledProcessError: When the service manager refuses.
    """
    _system(machine).start(service, machine, is_restart=is_restart)


def stop(service: AccountService, machine: ServiceMachine) -> None:
    """Stop one instance; its definition stays and starts it again at boot.

    Args:
        service: The service.
        machine: The machine.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        OSError: When the PowerShell host fails.
    """
    _system(machine).stop(service, machine)


def remove(service: AccountService, machine: ServiceMachine) -> None:
    """Stop one instance and delete its definition, its environment and its files.

    Args:
        service: The service.
        machine: The machine.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        OSError: When the PowerShell host fails.
    """
    _system(machine).remove(service, machine)


def states(services: list, machine: ServiceMachine) -> dict:
    """Whether each instance runs, and why it cannot.

    Args:
        services: The services asked about.
        machine: The machine.

    Returns:
        Account to ``{"is_running", "code"}``, ``code`` being
        ``credential_invalid`` for a Windows task that cannot sign its
        account in, else empty.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
    """
    return _system(machine).states(services, machine)


def forget(name: str, machine: ServiceMachine) -> None:
    """Delete what every instance of one module shared, once none is left.

    Args:
        name: The module's name.
        machine: The machine.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        OSError: When the PowerShell host fails.
    """
    _system(machine).forget(name, machine)


def units(services: list, machine: ServiceMachine) -> list:
    """The units whose journal is the instances' output: Linux's alone.

    Args:
        services: The services.
        machine: The machine.

    Returns:
        The unit names, empty where no unit keeps the output.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
    """
    return _system(machine).units(services, machine)


def log_path(
    name: str, account: str, machine: ServiceMachine, log_name: str = ""
) -> str:
    """The file one instance's output goes to, where no unit keeps it.

    Args:
        name: The module's name.
        account: The account.
        machine: The machine.
        log_name: The file's name when the service names one.

    Returns:
        The path, empty on Linux.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
    """
    return _system(machine).log_path(name, account, machine, log_name)


def _system(machine: ServiceMachine):
    """The system's own file of the layer."""
    module = SYSTEM_MODULES.get(machine.os_name)
    if module is None:
        raise PlatformUnsupportedError(f"no account services on {machine.os_name!r}")
    return importlib.import_module(module)
