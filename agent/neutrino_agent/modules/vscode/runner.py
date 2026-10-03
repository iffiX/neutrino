"""VS Code as a module: Microsoft's standalone CLI serving each account.

The CLI is the archive the hub caches, down a package stream, unpacked into
the module's own directory. Each instance is one account's ``code
serve-web`` on its own port, reached with the token the hub generated,
started the way the system starts a process as an account: a systemd unit
with ``User=`` on Linux, a LaunchDaemon with ``UserName`` on macOS, a
scheduled task with the account's login on Windows.

Not pure: drives the platform's applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess
import threading
import time

from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.log_tail import file_tail
from neutrino_agent.modules.subprocess_run import command_detail
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.constants import (
    VSCODE_CLI_NAMES,
    VSCODE_DIR_NAME,
    VSCODE_KIND,
    VSCODE_NAME,
    VSCODE_STATUS_TTL_S,
    VSCODE_TOKEN_DIR_NAME,
)
from neutrino_agent.modules.vscode.darwin_applier import VscodeDarwinApplier
from neutrino_agent.modules.vscode.installer import remove_cli, unpack_cli
from neutrino_agent.modules.vscode.linux_applier import VscodeLinuxApplier
from neutrino_agent.modules.vscode.windows_applier import VscodeWindowsApplier


def vscode_applier_for(platform):
    """The applier that starts a server as an account on this system.

    Args:
        platform: The machine's platform.

    Returns:
        The Linux, macOS or Windows applier.

    Raises:
        PlatformUnsupportedError: On a system with none.
    """
    if platform.os_name == "linux":
        cli_dir = os.path.join(platform.agent_var_dir(), VSCODE_DIR_NAME)
        return VscodeLinuxApplier(
            cli_dir=cli_dir, token_dir=os.path.join(cli_dir, VSCODE_TOKEN_DIR_NAME)
        )
    if platform.os_name == "darwin":
        return VscodeDarwinApplier(root=platform.agent_var_dir())
    if platform.os_name == "windows":
        return VscodeWindowsApplier(root=platform.agent_var_dir())
    raise PlatformUnsupportedError("no VS Code here")


class VscodeModuleRunner(ModuleRunner):
    """Installs the CLI from the hub's bytes and runs a server per account."""

    kind = VSCODE_KIND
    name = VSCODE_NAME

    def __init__(
        self, *, platform, log=print, publish=None, applier=None, clock=time.monotonic
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            applier: The system's applier; None picks the platform's own.
            clock: The monotonic clock the instances' reading ages on.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = applier if applier is not None else vscode_applier_for(platform)
        self._clock = clock
        self._config: "VscodeConfig | None" = None
        self._lock = threading.Lock()
        self._states: "list | None" = None
        self._states_at = 0.0

    def verify(self, resolved: dict) -> bool:
        """Whether the CLI is on the machine.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the CLI's file exists.
        """
        return os.path.isfile(self._applier.cli_path)

    def install(self, resolved: dict, package_path: str) -> None:
        """Unpack the CLI the hub handed down.

        Args:
            resolved: The module as the hub resolved it; its entry names
                ``package_kind``, ``tar`` or ``zip``.
            package_path: The archive on local disk.

        Raises:
            InstallError: When the archive is not one the CLI comes in.
            OSError: When the CLI's directory cannot be opened to every
                account.
        """
        entry = resolved.get("entry") or {}
        unpack_cli(
            package_path,
            package_kind=str(entry.get("package_kind", "")),
            directory=self._applier.cli_dir,
            name=VSCODE_CLI_NAMES[self._platform.os_name],
        )
        self._platform.open_to_accounts(self._applier.cli_dir)
        self._forget_states()

    def uninstall(self, resolved: dict) -> None:
        """Delete the CLI.

        Args:
            resolved: The module as the hub resolved it.
        """
        remove_cli(self._applier.cli_dir)

    def validate(self, config: dict) -> None:
        """Parse and check a configuration for this system.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        VscodeConfig.from_dict(config).validate(os_name=self._platform.os_name)

    def apply(self, config: dict) -> None:
        """Run a server per instance and none for an account no longer named.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or the
                system will not run it.
        """
        parsed = VscodeConfig.from_dict(config)
        parsed.validate(os_name=self._platform.os_name)
        try:
            notes = self._applier.apply(parsed)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        finally:
            self._forget_states()
        self._config = parsed
        self._log("vscode: " + "; ".join(notes or ["unchanged"]))

    def stop(self) -> None:
        """Stop every server; the CLI and the configuration stay.

        Raises:
            OSError: When the system will not stop one.
        """
        try:
            self._applier.stop()
        finally:
            self._forget_states()

    def remove_configuration(self) -> None:
        """Stop every server and delete what the applies wrote.

        Raises:
            OSError: When the system will not let one go.
        """
        self._config = None
        try:
            self._applier.remove()
        finally:
            self._forget_states()

    def is_active(self) -> bool:
        """Whether there is a server and every one of them runs."""
        states = self._read_states()
        return bool(states) and all(state["is_running"] for state in states)

    def journal_units(self) -> list:
        """Every server's unit, on Linux."""
        return self._applier.units()

    def journal_text(self, lines: int) -> list:
        """Every server's output: the units' journal, or each log file's tail.

        Where no unit keeps the output, the agent's own lines that name the
        module follow the log files' lines.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first within each server; a log file's lines
            start with its account's name.
        """
        logs = self._applier.log_paths(self._config)
        if not logs and self.journal_units():
            return super().journal_text(lines)
        share = max(1, lines // len(logs)) if logs else 0
        own = []
        for account, path in logs:
            read = self._read_source(path, lambda path=path: file_tail(path, share))
            own += [f"{account}: {line}" for line in read]
        return self._with_agent_lines(own, lines)

    def details(self, resolved: dict) -> dict:
        """Each server, where it answers and whether it runs.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"instances": [{"account", "port", "url", "is_running",
            "code"}]}``, ``code`` being ``credential_invalid`` for a
            Windows task that cannot sign its account in.
        """
        return {"instances": [dict(state) for state in self._read_states()]}

    def _read_states(self) -> list:
        """The servers' states, read again once the last reading is stale."""
        with self._lock:
            if (
                self._states is not None
                and self._clock() - self._states_at < VSCODE_STATUS_TTL_S
            ):
                return self._states
        states = self._applier.states(self._config)
        with self._lock:
            self._states, self._states_at = states, self._clock()
        return states

    def _forget_states(self) -> None:
        with self._lock:
            self._states = None
