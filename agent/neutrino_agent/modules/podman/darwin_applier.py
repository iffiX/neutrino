"""The macOS part of a Podman machine: Podman's pkg, the computer's size, the machine's resources.

Podman's pkg goes in through the system's installer and puts Podman under
``/opt/podman``. The machine is applehv's, and Podman itself sets its
processors, memory and disk with ``podman machine set`` on the stopped
machine. Every machine command runs with the account's own temporary
directory as ``TMPDIR``, under which Podman keeps the machine's sockets.

Not pure: runs the installer, ``pkgutil``, ``sysctl`` and ``getconf``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import shutil
import subprocess

from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.podman.constants import (
    PODMAN_DARWIN_BINARY,
    PODMAN_DARWIN_COMMAND_TIMEOUT_S,
    PODMAN_DARWIN_INSTALLED_PATHS,
    PODMAN_DARWIN_PKG_ID,
    PODMAN_DARWIN_SYSCTL_COMMAND,
    PODMAN_DARWIN_TEMP_DIR_COMMAND,
    PODMAN_DARWIN_TEMP_DIR_VARIABLE,
    PODMAN_GIB,
    PODMAN_MACHINE_PROVIDER_APPLEHV,
)
from neutrino_agent.modules.podman.machine import PodmanMachine
from neutrino_agent.modules.podman.machine_runner import PodmanSystemApplier
from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared.subprocess_run import run as run_command


class PodmanDarwinApplier(PodmanSystemApplier):
    """Installs Podman's pkg and sizes an applehv machine through Podman."""

    provider = PODMAN_MACHINE_PROVIDER_APPLEHV
    binary = PODMAN_DARWIN_BINARY

    def __init__(
        self,
        *,
        platform,
        run=run_command,
        install_pkg=installers.install_pkg,
        installed_paths: tuple = PODMAN_DARWIN_INSTALLED_PATHS,
    ):
        """
        Args:
            platform: The computer's platform, whose ``run_as_account``
                reads an account's temporary directory.
            run: Runs one command as the agent itself, as
                :func:`subprocess_run.run` does.
            install_pkg: Installs one pkg, as :func:`installers.install_pkg`
                does.
            installed_paths: What the pkg and its scripts put on the
                computer, removed by the uninstall.
        """
        self._platform = platform
        self._run = run
        self._install_pkg = install_pkg
        self._installed_paths = tuple(installed_paths)
        self._temp_dirs: dict = {}

    def install_artifact(self, artifact: dict, path: str) -> None:
        """Install Podman's pkg with the system's installer.

        Args:
            artifact: ``{name, kind, digest, directory}``.
            path: The kept file.

        Raises:
            ModuleApplyError: ``install_failed`` for an artifact that is not
                a pkg; ``podman_install_failed {artifact, exit_code}`` when
                the installer fails, 1 when it did not start.
        """
        name = str(artifact.get("name", "") or "")
        if artifact.get("kind") != "pkg":
            raise ModuleApplyError(
                "install_failed", {"detail": f"artifact {name!r} is not a pkg"}
            )
        try:
            self._install_pkg(path)
        except InstallError as error:
            exit_code = error.exit_code if error.exit_code is not None else 1
            raise ModuleApplyError(
                "podman_install_failed", {"artifact": name, "exit_code": exit_code}
            ) from error

    def uninstall(self) -> None:
        """Delete what the pkg put on the computer and forget its receipt.

        Raises:
            OSError: When a file cannot be deleted or ``pkgutil`` cannot run.
            subprocess.SubprocessError: When ``pkgutil`` does not finish.
        """
        for path in self._installed_paths:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.unlink(path)
        self._run(
            ["pkgutil", "--forget", PODMAN_DARWIN_PKG_ID],
            is_checked=False,
            timeout_s=PODMAN_DARWIN_COMMAND_TIMEOUT_S,
        )

    def host_facts(self) -> tuple:
        """The computer's logical processors and its memory, from ``sysctl``.

        Returns:
            ``(cpus, memory_gib)``; the base's reading when ``sysctl`` does
            not answer.
        """
        try:
            result = self._run(
                list(PODMAN_DARWIN_SYSCTL_COMMAND),
                is_checked=False,
                timeout_s=PODMAN_DARWIN_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return super().host_facts()
        values = result.stdout.split() if result.is_success else []
        try:
            cpus, memory = int(values[0]), int(values[1])
        except (IndexError, ValueError):
            return super().host_facts()
        return cpus, memory // PODMAN_GIB

    def disk_gib(self, machine: PodmanMachine) -> int:
        """The machine's disk as Podman sized it, ``Resources.DiskSize`` in its settings file.

        Args:
            machine: The machine.

        Returns:
            The size in GiB; 0 when it cannot be read.
        """
        try:
            with open(machine.settings_path(), "r", encoding="utf-8") as stream:
                settings = json.load(stream)
            return int((settings.get("Resources") or {}).get("DiskSize") or 0)
        except (OSError, ValueError, AttributeError, TypeError, KeyError):
            return 0

    def halt(self, machine: PodmanMachine) -> None:
        """Stop the machine; a stopped one stays stopped.

        Args:
            machine: The machine.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when Podman cannot stop
                it.
        """
        machine.stop()

    def write_resources(
        self, machine: PodmanMachine, *, cpus: int, memory_gib: int
    ) -> None:
        """Give the stopped machine its processors and memory through Podman.

        Args:
            machine: The machine.
            cpus: Its processors.
            memory_gib: Its memory in GiB.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when Podman refuses.
        """
        machine.set_resources(cpus=cpus, memory_gib=memory_gib)

    def resize_disk(self, machine: PodmanMachine, *, disk_gib: int) -> None:
        """Grow the stopped machine's disk through Podman, which refuses to shrink it.

        Args:
            machine: The machine.
            disk_gib: The size in GiB.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when Podman refuses.
        """
        machine.set_resources(disk_gib=disk_gib)

    def machine_environment(self, account: str) -> dict:
        """``TMPDIR`` as the account's own temporary directory, read once per account.

        Args:
            account: The machine's account.

        Returns:
            ``{"TMPDIR": <directory>}``; empty when the account's directory
            cannot be read.
        """
        found = self._temp_dirs.get(account)
        if found is None:
            try:
                done = self._platform.run_as_account(
                    account,
                    list(PODMAN_DARWIN_TEMP_DIR_COMMAND),
                    timeout_s=PODMAN_DARWIN_COMMAND_TIMEOUT_S,
                )
            except (KeyError, OSError, subprocess.SubprocessError):
                return {}
            found = (done.stdout or "").strip() if done.returncode == 0 else ""
            if not found:
                return {}
            self._temp_dirs[account] = found
        return {PODMAN_DARWIN_TEMP_DIR_VARIABLE: found}
