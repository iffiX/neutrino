"""One program run as a person's account, as every system's service manager takes it.

A module describes an instance's service once, as an :class:`AccountService`,
and names nothing of the system. The functions here write that definition,
start and enable, stop and disable, remove and query the service, each
dispatched to the system's own file: a systemd unit with ``User=`` on Linux,
a LaunchDaemon with ``UserName`` on macOS, a scheduled task registered with
the account's login on Windows. A stopped instance stays stopped across a
reboot. A file the program reads that its account must not change is
root's, SYSTEM's on Windows, in a folder root owns that the account alone
reads beside root.

Not pure: the system files write definitions and drive the service manager.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import stat
from dataclasses import dataclass, field

from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_DARWIN_LOG_DIR,
    ACCOUNT_SERVICE_LAUNCHD_DIR,
    ACCOUNT_SERVICE_LAUNCHD_PREFIX,
    ACCOUNT_SERVICE_READ_LIMIT,
    ACCOUNT_SERVICE_STAGED_SUFFIX,
    ACCOUNT_SERVICE_SYSTEMD_DIR,
    ACCOUNT_SERVICE_TASK_PREFIX,
    ACCOUNT_SERVICE_UNIT_PREFIX,
    ACCOUNT_SERVICE_UNIT_SUFFIX,
)
from neutrino_agent.modules.shared.subprocess_run import run as run_command

# How a file in root's folder is read: no link followed and no wait on a
# pipe.
ROOT_FILE_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
)
# How a file in root's folder is made: afresh, no link followed.
ROOT_FILE_WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
)
# How an account's directory in root's folder is opened to take it back: a
# folder, no link followed.
ROOT_DIR_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)
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
            each is written whole, mode 0600, the account's own, in a
            folder root owns.
        read_files: ``(path, text)`` pairs the program reads and the
            account must not change: each is written whole and kept
            root's, SYSTEM's on Windows, in a folder root owns that the
            account alone reads beside root.
        directories: Directories the account owns: made mode 0700 before
            the service starts, deleted with it.
        is_output_discarded: Whether stdout and stderr are discarded: the
            unit's output goes to systemd's null on Linux, and no log file
            is written on macOS or Windows.
        is_process_group_abandoned: macOS: whether launchd leaves the
            processes the program started running when the job stops; the
            plist's ``AbandonProcessGroup``. Unread elsewhere.
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
    read_files: tuple = ()
    directories: tuple = ()
    is_output_discarded: bool = False
    is_process_group_abandoned: bool = False


@dataclass(frozen=True)
class ServiceMachine:
    """This machine as the layer reaches it, for one module's services.

    Attributes:
        os_name: ``linux``, ``darwin`` or ``windows``.
        module_dir: The module's directory under the state root.
        record_dir: Where the instances' records and environment files
            live, the module's directory under the state root.
        lookup_account: Returns an account's :class:`AccountEntry`, or
            raises KeyError for one the machine does not have.
        run: Runs one command as :func:`subprocess_run.run` does.
        chown: Changes a file's owner as :func:`os.chown` does.
        powershell: Windows: the agent's PowerShell host, asked as
            :meth:`WindowsPowerShellHost.call` is; None elsewhere.
        processes: Windows: the machine's processes, read and ended as
            :class:`WindowsProcessTable` does; None elsewhere.
        batch_logon: Windows: the batch logon right of the accounts, held
            and released as :class:`WindowsBatchLogonRight` does; None elsewhere.
        folders: Windows: folders' access lists set on handles, as
            :class:`WindowsFolderAccess` sets them; None sets them.
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
    batch_logon: object = None
    folders: object = None
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


def read_regular(path: str, limit: int = ACCOUNT_SERVICE_READ_LIMIT) -> "bytes | None":
    """The first bytes of one regular file, read through no link and waiting on no pipe.

    Args:
        path: The file.
        limit: How many bytes are read at most.

    Returns:
        Its bytes; None for a path that is missing, a link, no regular file
        or unreadable.
    """
    try:
        descriptor = os.open(path, ROOT_FILE_READ_FLAGS)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        parts = []
        left = limit
        while left > 0:
            part = os.read(descriptor, left)
            if not part:
                break
            parts.append(part)
            left -= len(part)
        return b"".join(parts)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def write_root_file(
    path: str, data: bytes, mode: int, *, owner: tuple, chown, staged=None
) -> bool:
    """Write one file of root's whole, beside its place and renamed in, unless it holds these bytes.

    The new file is made afresh, following no link, and given its mode and
    its owner on the open file; the file it replaces is never opened for
    writing.

    Args:
        path: The file, in a folder root owns.
        data: What it holds afterwards.
        mode: Its permission bits.
        owner: ``(uid, gid)`` it is given.
        chown: Changes an open file's owner as :func:`os.chown` does with a
            descriptor.
        staged: Called with the new file's path before it is renamed in;
            None calls nothing.

    Returns:
        Whether it was written.

    Raises:
        OSError: When the file cannot be made, written or renamed in.
    """
    if read_regular(path, len(data) + 1) == data:
        return False
    new = path + ACCOUNT_SERVICE_STAGED_SUFFIX
    with contextlib.suppress(FileNotFoundError):
        os.unlink(new)
    descriptor = os.open(new, ROOT_FILE_WRITE_FLAGS, 0o600)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view) :]
            chown(descriptor, owner[0], owner[1])
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)
        if staged is not None:
            staged(new)
        os.replace(new, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(new)
        raise
    return True


def clear_files(descriptor: int) -> list:
    """Delete every name an open folder holds that is no folder, following no link.

    Args:
        descriptor: The open folder, one of root's.

    Returns:
        The names deleted.

    Raises:
        OSError: When a name cannot be deleted.
    """
    cleared = []
    for name in os.listdir(descriptor):
        try:
            status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(status.st_mode):
            continue
        os.unlink(name, dir_fd=descriptor)
        cleared.append(name)
    return cleared


def make_read_dir(directory: str, account: str, machine) -> None:
    """Make a folder root owns that one account alone reads beside root, or take one back.

    A folder an earlier version gave the account is taken back on its open
    descriptor, following no link, before anything is written in it, and
    every file the account had in it is deleted once it is root's.

    Args:
        directory: The folder.
        account: The account that reads it.
        machine: The machine.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        KeyError: When the machine does not have the account.
        OSError: When the folder cannot be made or given.
    """
    _system(machine).make_read_dir(directory, account, machine)


def write_read_file(path: str, text: str, account: str, machine) -> bool:
    """Write one file root keeps that one account alone reads, unless it holds this text.

    Args:
        path: The file, in a folder :func:`make_read_dir` made.
        text: What it holds afterwards.
        account: The account that reads it.
        machine: The machine.

    Returns:
        Whether it was written.

    Raises:
        PlatformUnsupportedError: On a system the layer has no file for.
        KeyError: When the machine does not have the account.
        OSError: When the file cannot be written.
    """
    return _system(machine).write_read_file(path, text, account, machine)


def write_read_files(service: AccountService, machine) -> bool:
    """Write the files a service's program reads and its account must not change.

    Args:
        service: The service.
        machine: The machine.

    Returns:
        Whether a file's text changed.

    Raises:
        KeyError: When the machine does not have the account.
        OSError: When a folder or a file cannot be written.
    """
    is_changed = False
    for directory in read_dirs(service, _system(machine).dirname):
        make_read_dir(directory, service.account, machine)
    for path, text in service.read_files:
        is_changed |= write_read_file(path, text, service.account, machine)
    return is_changed


def remove_read_files(service: AccountService, dirname=os.path.dirname) -> None:
    """Delete the folders of a service's read files, with every file in them.

    Only names in root's folder are deleted, and no folder in it is
    entered: a folder that holds one stays.

    Args:
        service: The service.
        dirname: How the system takes a path's folder.
    """
    for directory in read_dirs(service, dirname):
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            with contextlib.suppress(OSError):
                if not entry.is_dir(follow_symlinks=False):
                    os.unlink(entry.path)
        with contextlib.suppress(OSError):
            os.rmdir(directory)


def read_dirs(service: AccountService, dirname=os.path.dirname) -> list:
    """The folders of a service's read files, each once, in their order. Pure."""
    directories: list = []
    for path, _text in service.read_files:
        directory = dirname(path)
        if directory not in directories:
            directories.append(directory)
    return directories


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


def remove_account_files(service: AccountService, chown=None) -> None:
    """Delete the files and the directories a service's account owned.

    Each directory, in a folder of root's, is taken back to root on its
    open descriptor, following no link, before what it holds is deleted:
    the account changes nothing in it from then on. A directory that
    cannot be taken back stays.

    Args:
        service: The service.
        chown: Changes an open directory's owner as :func:`os.chown` does
            with a descriptor; None is :func:`os.chown`.
    """
    chown = chown if chown is not None else getattr(os, "chown", _no_chown)
    for path, _text in service.files:
        try:
            os.unlink(path)
        except OSError:
            pass
    for directory in service.directories:
        try:
            descriptor = os.open(directory, ROOT_DIR_FLAGS)
        except OSError:
            continue
        try:
            chown(descriptor, 0, 0)
            os.fchmod(descriptor, 0o700)
        except OSError:
            continue
        finally:
            os.close(descriptor)
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
        OSError: When a file cannot be written, the PowerShell host fails,
            or Windows will not grant the account the batch logon right.
    """
    return _system(machine).write(service, machine)


def start(
    service: AccountService, machine: ServiceMachine, *, is_restart: bool
) -> None:
    """Enable and start one instance, or start it again when it must take a change.

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
    """Stop and disable one instance. Its definition stays, and it stays stopped across a reboot.

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
        OSError: When the PowerShell host fails, or Windows will not take
            the batch logon right away.
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
        OSError: When the system's reading fails.
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
