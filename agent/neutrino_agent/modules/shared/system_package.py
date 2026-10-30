"""Installing and uninstalling the packages of a ``system`` entry.

A ``system`` recipe names distro packages, never a download: its install
asks the hub for no bytes and the platform installs the names with its own
tooling, one operation at a time under the step lock ``package_manager``.
:func:`run_package_manager` is the one helper every such run goes through:
it waits up to 300 seconds for the system's own lock, which unattended
upgrades and PackageKit take without asking the agent, names the process
that holds it as the running step's wait, and runs ``dpkg --configure -a``
once after a cut dpkg run. A recipe may name ``pre_install`` shell
steps, run before the packages, for a repository the distribution keeps the
software in. Whether the software is there is the recipe's ``verify``; the
runner's own check, its binary on the path, answers only for a module the
state does not name, so software somebody installed by hand is observed.

Not pure: runs the package manager.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time

from neutrino_agent.constants import (
    AGENT_MODULE_OUTPUT_LIMIT_BYTES,
    AGENT_PACKAGE_LOCK_RETRY_S,
    AGENT_UPDATE_DNF_LOCK_TEXT,
    AGENT_UPDATE_LOCK_TIMEOUT_S,
    AGENT_WAIT_PACKAGE_MANAGER,
)
from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.shared.package import params_of

# What apt prints while another process holds dpkg's lock, and that
# process's id and name in it.
APT_LOCK_TEXT = "Could not get lock"
APT_LOCK_HOLDER = re.compile(r"held by process (\d+) \(([^)]*)\)")
# The files dnf 4 names the process that holds each of its own locks in,
# the rpm database's and the metadata's.
DNF_LOCK_PATHS = ("/var/lib/dnf/rpmdb_lock.pid", "/var/cache/dnf/metadata_lock.pid")
# Where the kernel shows each process: its name, cut at 15 characters, and
# its command line.
PROC_DIR = "/proc"
# What apt prints after a dpkg run was cut.
DPKG_INTERRUPTED_TEXT = "dpkg was interrupted"
# The code a step fails with once the system's lock stayed held.
CODE_PACKAGE_MANAGER_BUSY = "package_manager_busy"
# The wait sink of the task running on each thread.
_sinks = threading.local()


def set_wait_sink(on_wait) -> None:
    """Hand the waits of the package runs on this thread to a task's row.

    Args:
        on_wait: Called with ``{code, params}`` while the system's lock is
            held, and with ``{}`` once the run goes on; None tells nobody.
    """
    _sinks.on_wait = on_wait


def run_package_manager(
    command: list, *, timeout_s: int = installers.INSTALL_TIMEOUT_S
) -> str:
    """Run one ``apt-get``, ``dnf`` or ``yum`` command, waiting for the system's own lock.

    apt waits up to 300 seconds through ``DPkg::Lock::Timeout`` and names
    the process that holds the lock; dnf runs once no process holds dnf 4's
    own locks, and again every few seconds while its output names the rpm
    transaction lock, up to 300 seconds in all. A run
    apt refuses because a dpkg run was cut runs ``dpkg --configure -a``
    once, then the command again.

    Args:
        command: The argument vector, the package manager first.
        timeout_s: How long one run of the command may take.

    Returns:
        Standard output.

    Raises:
        ModuleApplyError: ``package_manager_busy {holder}`` when the system's
            lock stayed held past the wait.
        InstallError: When the package manager refuses or cannot run.
    """
    program = os.path.basename(command[0])
    if program in ("dnf", "yum"):
        return _run_dnf(command, timeout_s)
    if program != "apt-get":
        return installers.run_checked(command, timeout_s=timeout_s)
    apt = [
        command[0],
        "-o",
        f"DPkg::Lock::Timeout={AGENT_UPDATE_LOCK_TIMEOUT_S}",
        *command[1:],
    ]
    code, output, holder = _run_apt(apt, timeout_s)
    if code != 0 and DPKG_INTERRUPTED_TEXT in output:
        installers.run_checked(["dpkg", "--configure", "-a"], timeout_s=timeout_s)
        code, output, holder = _run_apt(apt, timeout_s)
    if code == 0:
        return output
    if APT_LOCK_TEXT in output:
        raise ModuleApplyError(CODE_PACKAGE_MANAGER_BUSY, {"holder": holder})
    raise InstallError(
        f"{command[0]} failed: {output[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:]}",
        exit_code=code,
    )


def holder_name(pid: int, named: str = "") -> str:
    """The whole name of a process that holds a package manager's lock.

    The kernel's name of a process, the one apt prints, is cut at 15
    characters, such as ``unattended-upgr``; the command line holds it
    whole, after an interpreter's own words where the program is a script.

    Args:
        pid: The process.
        named: The name already known of it; empty reads the kernel's.

    Returns:
        The last part of the first word of the command line that begins
        with the kernel's name; that name where none does, or the command
        line cannot be read.
    """
    base = os.path.join(PROC_DIR, str(pid))
    if not named:
        try:
            with open(os.path.join(base, "comm"), encoding="utf-8") as stream:
                named = stream.read().strip()
        except (OSError, UnicodeDecodeError):
            return ""
    try:
        with open(os.path.join(base, "cmdline"), "rb") as stream:
            words = stream.read().split(b"\0")
    except OSError:
        return named
    for word in words:
        name = os.path.basename(word.decode("utf-8", "replace"))
        if named and name.startswith(named):
            return name
    return named


def _tell_wait(wait: dict) -> None:
    """Hand one wait to the sink of this thread's task."""
    on_wait = getattr(_sinks, "on_wait", None)
    if on_wait is not None:
        on_wait(wait)


def _package_wait(holder: str) -> dict:
    """``waiting_for_package_manager {holder}``."""
    return {"code": AGENT_WAIT_PACKAGE_MANAGER, "params": {"holder": holder}}


def _run_apt(command: list, timeout_s: int) -> tuple:
    """Run apt, reading its output as it comes, so a wait for dpkg's lock is named.

    Returns:
        ``(exit_code, output, holder)``, ``holder`` the process apt named as
        holding dpkg's lock, empty when it named none.

    Raises:
        InstallError: When apt cannot run.
    """
    environment = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=environment,
        )
    except OSError as error:
        raise InstallError(f"{command[0]} could not run: {error}")
    killer = threading.Timer(timeout_s, process.kill)
    killer.daemon = True
    killer.start()
    held = []
    holder = ""
    is_waiting = False
    try:
        for line in _lines(process.stdout):
            held.append(line)
            if APT_LOCK_TEXT in line:
                found = APT_LOCK_HOLDER.search(line)
                if found:
                    holder = holder_name(int(found.group(1)), found.group(2))
                if not is_waiting:
                    is_waiting = True
                    _tell_wait(_package_wait(holder))
            elif is_waiting and line.strip():
                is_waiting = False
                _tell_wait({})
        code = process.wait()
    finally:
        killer.cancel()
        if is_waiting:
            _tell_wait({})
    return code, "\n".join(held), holder


def _run_dnf(command: list, timeout_s: int) -> str:
    """Run dnf or yum once no other run holds its lock, up to the wait.

    dnf 4 and yum wait for their own lock without a word, so the files
    their locks name the holder in are read before each run, and the wait
    for a holder they name ends before dnf runs; dnf 5 refuses at once, and
    runs again while its output names the rpm transaction lock.
    """
    waited = 0
    told = None
    try:
        while True:
            pid = _dnf_lock_pid()
            if not pid:
                if told:
                    told = None
                    _tell_wait({})
                try:
                    return installers.run_checked(command, timeout_s=timeout_s)
                except InstallError as error:
                    if AGENT_UPDATE_DNF_LOCK_TEXT not in str(error):
                        raise
            holder = holder_name(pid) if pid else ""
            if waited >= AGENT_UPDATE_LOCK_TIMEOUT_S:
                raise ModuleApplyError(CODE_PACKAGE_MANAGER_BUSY, {"holder": holder})
            if told != holder:
                told = holder
                _tell_wait(_package_wait(holder))
            time.sleep(AGENT_PACKAGE_LOCK_RETRY_S)
            waited += AGENT_PACKAGE_LOCK_RETRY_S
    finally:
        if told is not None:
            _tell_wait({})


def _dnf_lock_pid() -> int:
    """The process that holds one of dnf 4's own locks; 0 when none does.

    A file that names this process or a process that has ended holds
    nothing.
    """
    for path in DNF_LOCK_PATHS:
        try:
            with open(path, encoding="utf-8") as stream:
                pid = int(stream.read().strip() or "0")
        except (OSError, ValueError):
            continue
        if pid > 0 and pid != os.getpid():
            if os.path.exists(os.path.join(PROC_DIR, str(pid))):
                return pid
    return 0


def _lines(stream):
    """The lines of a stream as they come, a carriage return ending one too."""
    pending = ""
    while True:
        chunk = stream.read(1)
        if not chunk:
            break
        if chunk in "\r\n":
            yield pending
            pending = ""
            continue
        pending += chunk
    if pending:
        yield pending


def _recipe_packages(recipe: dict) -> list:
    """The package names a recipe installs."""
    return [str(name) for name in params_of(recipe).get("packages") or []]


def _recipe_steps(recipe: dict) -> list:
    """The shell steps a recipe runs before its packages."""
    return [str(step) for step in params_of(recipe).get("pre_install") or []]


def _removed_packages(recipe: dict) -> list:
    """The package names a recipe's uninstall removes."""
    removal = params_of(recipe).get("uninstall")
    if not isinstance(removal, dict):
        return []
    return [str(name) for name in removal.get("packages") or []]


class SystemPackageModuleRunner(ModuleRunner):
    """Installs named distro packages and removes them.

    Attributes:
        binary: The program that says the software is there for a module
            the state does not name; empty for a runner with none of its own.
    """

    binary = ""

    def verify(self, recipe: dict) -> bool:
        """Whether the runner's own program is on the path.

        Args:
            recipe: The module's recipe, empty for a module the state does
                not name.

        Returns:
            True when the binary is found.
        """
        return bool(self.binary) and shutil.which(self.binary) is not None

    def install(self, recipe: dict) -> None:
        """Run the recipe's steps, then install its packages with the machine's own tooling.

        Args:
            recipe: The module's recipe.

        Raises:
            InstallError: If a step or the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        for step in _recipe_steps(recipe):
            self._log(step)
            output = installers.run_shell(step)
            if output.strip():
                self._log(output.strip())
        output = self._platform.install_system_packages(_recipe_packages(recipe))
        if output.strip():
            self._log(output.strip())

    def uninstall(self, recipe: dict) -> None:
        """Take the packages the recipe's uninstall names off this machine.

        Args:
            recipe: The module's recipe.

        Raises:
            InstallError: If the uninstall refuses.
            PlatformUnsupportedError: If this platform removes nothing.
        """
        output = self._platform.remove_system_packages(_removed_packages(recipe))
        if output.strip():
            self._log(output.strip())
