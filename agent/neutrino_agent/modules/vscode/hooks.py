"""What VS Code adds to the shared runner: each server's service.

The CLI comes from the hub's package stream as the archive Microsoft
publishes, with the one executable inside, and the shared unpack puts it
directly in the module's own directory. Each instance is one account's
``code serve-web`` on its port, reached with the connection token the hub
generated, which the CLI checks itself, so the module names no forwarder
rule. On Linux the server reads
its address, port and token file from an environment file beside the token;
on macOS and Windows the command line carries them.

Not pure: writes, on Linux, the inotify limits.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ntpath
import os
import subprocess

from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
    write_if_changed,
)
from neutrino_agent.modules.shared.instances import InstanceHooks
from neutrino_agent.modules.vscode.config import VscodeConfig, VscodeInstance
from neutrino_agent.modules.vscode.constants import (
    VSCODE_BASE_PORT,
    VSCODE_CLI_NAMES,
    VSCODE_RUNNER,
    VSCODE_LINUX_SYSCTL_FLOORS,
    VSCODE_LINUX_SYSCTL_PATH,
    VSCODE_LINUX_SYSCTL_PROC_DIR,
    VSCODE_LOOPBACK_ADDRESS,
    VSCODE_NAME,
    VSCODE_SERVE_ARGUMENTS,
    VSCODE_TITLE,
    VSCODE_TOKEN_DIR_NAME,
    VSCODE_VERSION_ARGUMENT,
    VSCODE_VERSION_PREFIX,
    VSCODE_VERSION_TIMEOUT_S,
)

TOKEN_SUFFIX = ".token"
# The variables the Linux unit reads its address, port and token file from.
HOST_VARIABLE = "VSCODE_HOST"
PORT_VARIABLE = "VSCODE_PORT"
TOKEN_FILE_VARIABLE = "VSCODE_TOKEN_FILE"


class VscodeHooks(InstanceHooks):
    """VS Code's part of the shared runner."""

    name = VSCODE_NAME
    title = VSCODE_TITLE
    runner = VSCODE_RUNNER
    instance_class = VscodeInstance
    record_fields = ("account", "port", "host")
    is_forwarded = False
    base_port = VSCODE_BASE_PORT

    def __init__(
        self,
        *,
        platform,
        log=print,
        sysctl_path: str = VSCODE_LINUX_SYSCTL_PATH,
        proc_dir: str = VSCODE_LINUX_SYSCTL_PROC_DIR,
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            sysctl_path: The drop-in that raises the inotify limits on Linux.
            proc_dir: Where the kernel shows the limits in force.
        """
        super().__init__(platform=platform, log=log)
        self._sysctl_path = sysctl_path
        self._proc_dir = proc_dir
        # The CLI's size and time, and the version it printed.
        self._version: tuple = ((), "")

    @property
    def cli_path(self) -> str:
        """Where the CLI is."""
        return self._join(self.machine.module_dir, VSCODE_CLI_NAMES[self._os_name])

    @property
    def token_dir(self) -> str:
        """Where each account's token file is, beside the CLI."""
        return self._join(self.machine.module_dir, VSCODE_TOKEN_DIR_NAME)

    def parse(self, config: dict) -> VscodeConfig:
        """The configuration parsed and checked for this system.

        Args:
            config: The module's desired configuration.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = VscodeConfig.from_dict(config)
        parsed.validate(os_name=self._os_name)
        return parsed

    def verify(self) -> bool:
        """Whether the CLI's file exists."""
        return os.path.isfile(self.cli_path)

    def prepare_module(self) -> list:
        """Raise a Linux machine's inotify limits to the module's floors.

        Returns:
            One note when a drop-in was written.

        Raises:
            OSError: When the drop-in cannot be written.
        """
        if self._os_name != "linux":
            return []
        return ["raised the inotify limits"] if self._raise_watch_limits() else []

    def record(
        self, parsed: VscodeConfig, instance: VscodeInstance, held: dict
    ) -> dict:
        """One instance's record: its account, its port and the address it listens on.

        Args:
            parsed: The configuration.
            instance: The instance.
            held: The record held before, with the port the runner took.

        Returns:
            ``{account, port, host}``.
        """
        return {
            "account": instance.account,
            "port": int(held.get("port") or 0),
            "host": parsed.host,
        }

    def service(
        self, instance: VscodeInstance, entry: AccountEntry, record: dict
    ) -> AccountService:
        """One account's ``code serve-web`` on its port with its token file.

        Args:
            instance: The instance.
            entry: Its account.
            record: Its record, whose ``host`` and ``port`` are where it
                listens.

        Returns:
            The service.
        """
        token_path = self._join(self.token_dir, instance.account + TOKEN_SUFFIX)
        host = str(record.get("host") or VSCODE_LOOPBACK_ADDRESS)
        port = int(record.get("port") or 0)
        if self._os_name == "linux":
            command = (
                self.cli_path,
                *VSCODE_SERVE_ARGUMENTS,
                "--host",
                f"${{{HOST_VARIABLE}}}",
                "--port",
                f"${{{PORT_VARIABLE}}}",
                "--connection-token-file",
                f"${{{TOKEN_FILE_VARIABLE}}}",
            )
            environment = {
                HOST_VARIABLE: host,
                PORT_VARIABLE: str(port),
                TOKEN_FILE_VARIABLE: token_path,
            }
        else:
            command = (
                self.cli_path,
                *VSCODE_SERVE_ARGUMENTS,
                "--host",
                host,
                "--port",
                str(port),
                "--connection-token-file",
                token_path,
            )
            environment = {}
        return AccountService(
            name=self.name,
            title=self.title,
            account=instance.account,
            command=command,
            environment=environment,
            password=instance.password,
            listen_port=port,
            environment_dir=self.token_dir,
            files=((token_path, instance.token),),
        )

    def details_extra(self, record: dict) -> dict:
        """Where the instance answers, without its token.

        Args:
            record: The instance's record.

        Returns:
            ``{"url": "http://<host>:<port>/"}``.
        """
        host = record.get("host") or VSCODE_LOOPBACK_ADDRESS
        return {"url": f"http://{host}:{record.get('port')}/"}

    def module_details(self) -> dict:
        """The CLI installed.

        Returns:
            ``{"version"}``, the version ``code --version`` prints, empty
            while the CLI does not answer.
        """
        return {"version": self._installed_version()}

    def forget_module(self) -> None:
        """Delete the inotify drop-in."""
        with contextlib.suppress(OSError):
            os.unlink(self._sysctl_path)

    @property
    def _os_name(self) -> str:
        return self._platform.os_name

    def _join(self, *parts: str) -> str:
        return (ntpath.join if self._os_name == "windows" else os.path.join)(*parts)

    def _installed_version(self) -> str:
        """The version the CLI prints, read once per CLI file."""
        cli = self.cli_path
        try:
            found = os.stat(cli)
        except OSError:
            return ""
        stamp = (found.st_mtime_ns, found.st_size)
        if self._version[0] != stamp:
            try:
                result = self.machine.run(
                    [cli, VSCODE_VERSION_ARGUMENT],
                    is_checked=False,
                    timeout_s=VSCODE_VERSION_TIMEOUT_S,
                )
                words = result.stdout.split() if result.is_success else []
            except (OSError, subprocess.SubprocessError):
                words = []
            is_named = len(words) > 1 and words[0] == VSCODE_VERSION_PREFIX
            self._version = (stamp, words[1] if is_named else "")
        return self._version[1]

    def _raise_watch_limits(self) -> bool:
        """Lift the inotify limits to the module's floors, never lower them.

        A limit the kernel does not report is left alone.

        Returns:
            Whether a drop-in was written and loaded.
        """
        wanted = {}
        for key, floor in VSCODE_LINUX_SYSCTL_FLOORS.items():
            current = self._read_limit(key)
            if current is not None and current < floor:
                wanted[key] = floor
        if not wanted:
            return False
        text = "".join(f"{key} = {value}\n" for key, value in wanted.items())
        os.makedirs(os.path.dirname(self._sysctl_path), exist_ok=True)
        if not write_if_changed(self._sysctl_path, text, 0o644):
            return False
        self.machine.run(["sysctl", "-p", self._sysctl_path], is_checked=False)
        return True

    def _read_limit(self, key: str) -> "int | None":
        path = os.path.join(self._proc_dir, *key.split("."))
        try:
            with open(path, encoding="utf-8") as handle:
                return int(handle.read().strip())
        except (OSError, ValueError):
            return None
