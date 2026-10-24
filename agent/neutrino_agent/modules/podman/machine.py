"""One account's Podman machine, driven through ``podman machine`` and read through its ssh port.

Every ``podman machine`` command runs as the account through the platform's
``run_as_account``: WSL refuses SYSTEM, and ``podman machine`` refuses root
on macOS. The root script that writes into the machine goes in on standard
input through ``podman machine ssh --username root``, as the account too.
The agent reads the machine itself, as SYSTEM or root, with ``podman
--url ssh://root@127.0.0.1:<port>/run/podman/podman.sock --identity <key>``:
the port from the machine's settings file, read again at each read since a
start can move it, and the key read where it is in the account's home.

Not pure: runs commands.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import ntpath
import os
import posixpath
import subprocess
from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.podman.constants import (
    PODMAN_MACHINE_COMMAND_TIMEOUT_S,
    PODMAN_MACHINE_DETAIL_CHARS,
    PODMAN_MACHINE_INIT_TIMEOUT_S,
    PODMAN_MACHINE_KEY_PATH,
    PODMAN_MACHINE_NAME,
    PODMAN_MACHINE_PROVIDER_VARIABLE,
    PODMAN_MACHINE_PROVIDER_WSL,
    PODMAN_MACHINE_READ_HOST,
    PODMAN_MACHINE_SCRIPT_TIMEOUT_S,
    PODMAN_MACHINE_SETTINGS_DIR,
    PODMAN_MACHINE_SOCKET_PATH,
)
from neutrino_agent.modules.shared.subprocess_run import command_detail
from neutrino_agent.modules.shared.subprocess_run import run as run_command


def _resource_flags(*, cpus: int, memory_gib: int, disk_gib: int) -> list:
    """``--cpus``, ``--memory`` in MiB and ``--disk-size`` for each size above 0."""
    flags = []
    if cpus > 0:
        flags += ["--cpus", str(cpus)]
    if memory_gib > 0:
        flags += ["--memory", str(memory_gib * 1024)]
    if disk_gib > 0:
        flags += ["--disk-size", str(disk_gib)]
    return flags


@dataclass(frozen=True)
class PodmanMachineState:
    """What ``podman machine inspect`` says of the machine.

    Attributes:
        state: Podman's word, ``running``, ``stopped`` or ``starting``.
        is_rootful: Whether the machine's API is root's.
    """

    state: str
    is_rootful: bool

    @property
    def is_running(self) -> bool:
        """Whether the machine runs."""
        return self.state == "running"


class PodmanMachine:
    """One account's default Podman machine."""

    def __init__(
        self,
        *,
        platform,
        account: str,
        password: str,
        binary: str,
        provider: str,
        environment: "dict | None" = None,
        run=run_command,
    ):
        """
        Args:
            platform: The computer's platform, whose ``run_as_account`` and
                ``account_home`` the machine's commands go through.
            account: The account whose machine it is.
            password: The account's login, which Windows runs its commands
                with; empty elsewhere.
            binary: Podman's program on the computer.
            provider: The machine provider, ``wsl`` or ``applehv``.
            environment: Variables every command run as the account gets
                beside the provider, such as macOS's ``TMPDIR``; None is
                none.
            run: Runs one command as the agent itself, as
                :func:`subprocess_run.run` does.
        """
        self._platform = platform
        self.account = account
        self._password = password
        self.binary = binary
        self.provider = provider
        self._environment = dict(environment or {})
        self._run = run
        self._join = ntpath.join if platform.os_name == "windows" else posixpath.join

    @property
    def is_sized_at_init(self) -> bool:
        """Whether ``podman machine init`` takes the machine's size.

        WSL reads the processors and the memory from the account's
        ``.wslconfig`` and creates its own disk, so a WSL machine is sized
        after the init.
        """
        return self.provider != PODMAN_MACHINE_PROVIDER_WSL

    def settings_path(self) -> str:
        """The machine's settings file in the account's home.

        Raises:
            KeyError: When the computer does not have the account.
        """
        return self._join(
            self._platform.account_home(self.account),
            *PODMAN_MACHINE_SETTINGS_DIR,
            self.provider,
            f"{PODMAN_MACHINE_NAME}.json",
        )

    def identity_path(self) -> str:
        """The machine's key in the account's home, read where it is.

        Raises:
            KeyError: When the computer does not have the account.
        """
        return self._join(
            self._platform.account_home(self.account), *PODMAN_MACHINE_KEY_PATH
        )

    def is_present(self) -> bool:
        """Whether the account has its default machine: its settings file is there.

        Raises:
            KeyError: When the computer does not have the account.
        """
        return os.path.isfile(self.settings_path())

    def ssh_port(self) -> int:
        """The ssh port the machine forwards to the computer's loopback, now.

        Returns:
            ``SSH.Port`` from the machine's settings file.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when the file names no
                port.
            KeyError: When the computer does not have the account.
        """
        path = self.settings_path()
        try:
            with open(path, "r", encoding="utf-8") as stream:
                settings = json.load(stream)
            port = int((settings.get("SSH") or {}).get("Port") or 0)
        except (OSError, ValueError, AttributeError, TypeError) as error:
            raise ModuleApplyError(
                "machine_unreachable",
                {"detail": f"{path}: {error}"[:PODMAN_MACHINE_DETAIL_CHARS]},
            ) from error
        if port <= 0:
            raise ModuleApplyError(
                "machine_unreachable", {"detail": f"{path} names no ssh port"}
            )
        return port

    def read_command(self) -> tuple:
        """The program and the options that reach root's Podman in the machine.

        The port is read again on every call.

        Returns:
            ``(binary, "--url", "ssh://root@127.0.0.1:<port>/run/podman/podman.sock",
            "--identity", <key>)``.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when the settings file
                names no port.
            KeyError: When the computer does not have the account.
        """
        url = (
            f"ssh://root@{PODMAN_MACHINE_READ_HOST}:{self.ssh_port()}"
            f"{PODMAN_MACHINE_SOCKET_PATH}"
        )
        return (self.binary, "--url", url, "--identity", self.identity_path())

    def info(self, read_command: "tuple | None" = None) -> dict:
        """What ``podman info`` says of the machine, read as the agent itself.

        Args:
            read_command: The read's command from :meth:`read_command`; None
                reads the port now.

        Returns:
            The parsed ``podman info --format json``.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when the machine does
                not answer.
            KeyError: When the computer does not have the account.
        """
        command = read_command if read_command is not None else self.read_command()
        try:
            result = self._run(
                [*command, "info", "--format", "json"],
                is_checked=False,
                timeout_s=30,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "machine_unreachable",
                {"detail": command_detail(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
            ) from error
        if not result.is_success:
            detail = (result.stderr or result.stdout).strip()
            raise ModuleApplyError(
                "machine_unreachable", {"detail": detail[-PODMAN_MACHINE_DETAIL_CHARS:]}
            )
        try:
            info = json.loads(result.stdout or "{}")
        except ValueError as error:
            raise ModuleApplyError(
                "machine_unreachable",
                {"detail": str(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
            ) from error
        return info if isinstance(info, dict) else {}

    def control(self, name: str, action: str) -> None:
        """Start, stop or restart a container somebody started by hand, as the agent itself.

        Args:
            name: The container's name.
            action: ``start``, ``stop`` or ``restart``.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when the settings file
                names no port.
            subprocess.CalledProcessError: If the container refuses.
            OSError: When Podman cannot start.
        """
        self._run([*self.read_command(), action, name], timeout_s=120)

    def inspect(self) -> PodmanMachineState:
        """What the machine is now, as the account's Podman says.

        Returns:
            Its state and whether it is rootful.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when Podman cannot say;
                ``credential_invalid`` when Windows refuses the login.
        """
        output = self._machine(
            ["inspect", PODMAN_MACHINE_NAME],
            code="machine_unreachable",
            timeout_s=PODMAN_MACHINE_COMMAND_TIMEOUT_S,
        )
        try:
            found = json.loads(output or "[]")
        except ValueError as error:
            raise ModuleApplyError(
                "machine_unreachable",
                {"detail": str(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
            ) from error
        entry = found[0] if isinstance(found, list) and found else {}
        if not isinstance(entry, dict):
            entry = {}
        return PodmanMachineState(
            state=str(entry.get("State", "") or ""),
            is_rootful=bool(entry.get("Rootful", False)),
        )

    def init(
        self, image_path: str, *, cpus: int, memory_gib: int, disk_gib: int
    ) -> None:
        """Create the account's default machine, rootful, from the kept image.

        Args:
            image_path: The machine image the hub sent.
            cpus: Its processors, passed where the provider takes them.
            memory_gib: Its memory in GiB, passed where the provider takes it.
            disk_gib: Its disk in GiB, passed where the provider takes it.

        Raises:
            ModuleApplyError: ``machine_init_failed`` when Podman refuses;
                ``credential_invalid`` when Windows refuses the login.
        """
        arguments = ["init", "--rootful", "--image", image_path]
        if self.is_sized_at_init:
            arguments += _resource_flags(
                cpus=cpus, memory_gib=memory_gib, disk_gib=disk_gib
            )
        arguments.append(PODMAN_MACHINE_NAME)
        self._machine(
            arguments,
            code="machine_init_failed",
            timeout_s=PODMAN_MACHINE_INIT_TIMEOUT_S,
        )

    def set_rootful(self) -> None:
        """Make the stopped machine's API root's.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when Podman refuses;
                ``credential_invalid`` when Windows refuses the login.
        """
        self._machine(
            ["set", "--rootful", PODMAN_MACHINE_NAME],
            code="machine_set_failed",
            timeout_s=PODMAN_MACHINE_COMMAND_TIMEOUT_S,
        )

    def set_resources(
        self, *, cpus: int = 0, memory_gib: int = 0, disk_gib: int = 0
    ) -> None:
        """Change the stopped machine's size, where Podman sets it itself (macOS).

        Args:
            cpus: Its processors; 0 leaves them.
            memory_gib: Its memory in GiB; 0 leaves it.
            disk_gib: Its disk in GiB; 0 leaves it.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when Podman refuses;
                ``credential_invalid`` when Windows refuses the login.
        """
        flags = _resource_flags(cpus=cpus, memory_gib=memory_gib, disk_gib=disk_gib)
        if not flags:
            return
        self._machine(
            ["set", *flags, PODMAN_MACHINE_NAME],
            code="machine_set_failed",
            timeout_s=PODMAN_MACHINE_COMMAND_TIMEOUT_S,
        )

    def start(self) -> None:
        """Start the machine.

        Raises:
            ModuleApplyError: ``machine_unreachable`` when Podman cannot;
                ``credential_invalid`` when Windows refuses the login.
        """
        self._machine(
            ["start", PODMAN_MACHINE_NAME],
            code="machine_unreachable",
            timeout_s=PODMAN_MACHINE_COMMAND_TIMEOUT_S,
        )

    def stop(self) -> None:
        """Stop the machine; its disk, images and volumes stay.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when Podman cannot;
                ``credential_invalid`` when Windows refuses the login.
        """
        self._machine(
            ["stop", PODMAN_MACHINE_NAME],
            code="machine_set_failed",
            timeout_s=PODMAN_MACHINE_COMMAND_TIMEOUT_S,
        )

    def run_as_account(self, argv: list, *, stdin: str = "", timeout_s: int):
        """Run one command as the machine's account, with the provider and the machine's variables.

        Args:
            argv: The argument vector.
            stdin: What the command reads on its standard input.
            timeout_s: How long it may take.

        Returns:
            The completed process.

        Raises:
            ModuleApplyError: ``credential_invalid`` when Windows refuses the
                login.
            OSError: When the platform cannot start it.
            PlatformUnsupportedError: When the platform cannot step down.
        """
        return self._platform.run_as_account(
            self.account,
            list(argv),
            stdin=stdin,
            timeout_s=timeout_s,
            password=self._password,
            environment={
                **self._environment,
                PODMAN_MACHINE_PROVIDER_VARIABLE: self.provider,
            },
        )

    def as_account(self, step, *arguments):
        """Run one step of the agent's own code as the machine's account.

        Args:
            step: Called with ``arguments``; what it reaches, it reaches
                with the account's rights.
            *arguments: What the step is called with.

        Returns:
            What the step returned.

        Raises:
            ModuleApplyError: ``credential_invalid`` when Windows refuses the
                login.
            OSError: When the platform cannot act as the account.
            PlatformUnsupportedError: When the platform cannot act as an
                account inside the agent's own process.
        """
        return self._platform.as_account(
            self.account, step, *arguments, password=self._password
        )

    def shell(self, script: str) -> "subprocess.CompletedProcess":
        """Run one root script in the machine, read by ``sh -s`` on standard input.

        Args:
            script: The POSIX sh text.

        Returns:
            The completed process; its output is the script's, errors after.

        Raises:
            ModuleApplyError: ``credential_invalid`` when Windows refuses the
                login; ``machine_unreachable`` when the platform cannot run it.
        """
        argv = [
            self.binary,
            "machine",
            "ssh",
            "--username",
            "root",
            PODMAN_MACHINE_NAME,
            "sh",
            "-s",
        ]
        try:
            return self.run_as_account(
                argv, stdin=script, timeout_s=PODMAN_MACHINE_SCRIPT_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "machine_unreachable",
                {"detail": command_detail(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
            ) from error

    def _machine(self, arguments: list, *, code: str, timeout_s: int) -> str:
        """Run one ``podman machine`` verb as the account.

        Returns:
            Its standard output.

        Raises:
            ModuleApplyError: ``code`` with Podman's own words when it exits
                non-zero or cannot start; ``credential_invalid`` when
                Windows refuses the login.
        """
        try:
            done = self.run_as_account(
                [self.binary, "machine", *arguments], timeout_s=timeout_s
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                code, {"detail": command_detail(error)[:PODMAN_MACHINE_DETAIL_CHARS]}
            ) from error
        if done.returncode != 0:
            said = f"{done.stdout or ''}{done.stderr or ''}".strip()
            detail = said or f"podman machine {arguments[0]} exited {done.returncode}"
            raise ModuleApplyError(
                code, {"detail": detail[-PODMAN_MACHINE_DETAIL_CHARS:]}
            )
        return done.stdout or ""
