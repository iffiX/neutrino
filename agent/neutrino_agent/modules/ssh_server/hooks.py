"""What the SSH server adds to the shared runner: the host key and each instance's run directory.

The agent carries ``neutrino_ssh_server`` in its own package, so nothing is
installed. The first apply makes the machine's Ed25519 host key with that
program, kept root's alone under the module's directory. Each instance runs
the program as its account on ``127.0.0.1`` at the port the shared runner
takes for it from 22000 up and keeps in its record, reading a copy of the
host key and its one authorized key from its run directory, which the
account owns. No forwarder stands in front of it: the hub reaches it
through the agent's ``connect`` stream.

Not pure: makes the host key.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ntpath
import os
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
)
from neutrino_agent.modules.shared.instances import InstanceHooks
from neutrino_agent.modules.shared.subprocess_run import command_detail
from neutrino_agent.modules.ssh_server.config import (
    SshServerConfig,
    SshServerInstance,
)
from neutrino_agent.modules.ssh_server.constants import (
    SSH_SERVER_AUTHORIZED_KEY_NAME,
    SSH_SERVER_BASE_PORT,
    SSH_SERVER_BINARY_NAME,
    SSH_SERVER_DARWIN_PATH,
    SSH_SERVER_FALLBACK_SHELL,
    SSH_SERVER_HOST_KEY_NAME,
    SSH_SERVER_LISTEN_HOST,
    SSH_SERVER_MAKE_HOST_KEY_TIMEOUT_S,
    SSH_SERVER_NAME,
    SSH_SERVER_PORT_VARIABLE,
    SSH_SERVER_RECORD_FIELDS,
    SSH_SERVER_RUN_DIR_NAME,
    SSH_SERVER_RUNNER,
    SSH_SERVER_SHELL_VARIABLE,
    SSH_SERVER_TITLE,
    SSH_SERVER_WINDOWS_BINARY_NAME,
    SSH_SERVER_WINDOWS_POWERSHELL_PARTS,
    SSH_SERVER_WINDOWS_SYSTEM_ROOT_DEFAULT,
)
from neutrino_agent.modules.ssh_server.openssh_key import (
    fingerprint,
    public_line_of_private,
)


def binary_path(platform) -> str:
    """The ``neutrino_ssh_server`` the agent's package carries.

    Args:
        platform: The machine's platform.

    Returns:
        The program under the platform's ``agent_bin_dir()``.
    """
    if platform.os_name == "windows":
        return ntpath.join(platform.agent_bin_dir(), SSH_SERVER_WINDOWS_BINARY_NAME)
    return os.path.join(platform.agent_bin_dir(), SSH_SERVER_BINARY_NAME)


def windows_powershell() -> str:
    """Windows PowerShell under the system root.

    Returns:
        ``%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe``.
    """
    root = os.environ.get("SystemRoot", "") or SSH_SERVER_WINDOWS_SYSTEM_ROOT_DEFAULT
    return ntpath.join(root, *SSH_SERVER_WINDOWS_POWERSHELL_PARTS)


class SshServerHooks(InstanceHooks):
    """The SSH server's part of the shared runner."""

    name = SSH_SERVER_NAME
    title = SSH_SERVER_TITLE
    runner = SSH_SERVER_RUNNER
    instance_class = SshServerInstance
    record_fields = SSH_SERVER_RECORD_FIELDS
    is_forwarded = False
    base_port = SSH_SERVER_BASE_PORT

    def __init__(self, *, platform, log=print, binary: str = ""):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            binary: The ``neutrino_ssh_server`` run; empty is the one the
                agent's package carries.
        """
        super().__init__(platform=platform, log=log)
        self._os_name = platform.os_name
        self._join = ntpath.join if self._os_name == "windows" else os.path.join
        self.binary = binary or binary_path(platform)

    @property
    def host_key_path(self) -> str:
        """The machine's host key, root's alone, under the module's directory."""
        return self._join(self.machine.module_dir, SSH_SERVER_HOST_KEY_NAME)

    def run_dir(self, account: str) -> str:
        """One account's run directory, which its instance reads.

        Args:
            account: The account.

        Returns:
            ``run/<account>`` under the module's directory.
        """
        return self._join(self.machine.module_dir, SSH_SERVER_RUN_DIR_NAME, account)

    def parse(self, config: dict) -> SshServerConfig:
        """The configuration parsed and checked for this system.

        Args:
            config: The module's desired configuration.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: ``account_invalid``, ``account_duplicate``,
                ``key_missing`` or, on Windows, ``credential_missing``,
                naming the first problem found.
        """
        parsed = SshServerConfig.from_dict(config)
        parsed.validate(os_name=self._os_name)
        return parsed

    def verify(self) -> bool:
        """Whether the module is on the machine.

        Returns:
            True: the agent carries it.
        """
        return True

    def prepare_module(self) -> list:
        """Make the machine's host key once, and open the way to the run directories.

        Returns:
            ``made the host key`` when this apply made it.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when the program
                cannot make the key.
            OSError: When the module's directory cannot be written.
        """
        module_dir = self.machine.module_dir
        run_root = self._join(module_dir, SSH_SERVER_RUN_DIR_NAME)
        os.makedirs(run_root, exist_ok=True)
        if self._os_name != "windows":
            os.chmod(module_dir, 0o755)
            os.chmod(run_root, 0o755)
        if os.path.isfile(self.host_key_path):
            return []
        self._make_host_key()
        return ["made the host key"]

    def service(
        self, instance: SshServerInstance, entry: AccountEntry, record: dict
    ) -> AccountService:
        """One account's SSH server on its loopback port, with its keys in its run directory.

        Args:
            instance: The instance; ``%i`` for the Linux template.
            entry: Its account, whose login shell is the default.
            record: Its record, whose ``port`` it listens on.

        Returns:
            The service.
        """
        run_dir = self.run_dir(instance.account)
        host_key = self._join(run_dir, SSH_SERVER_HOST_KEY_NAME)
        authorized_key = self._join(run_dir, SSH_SERVER_AUTHORIZED_KEY_NAME)
        port = int(record.get("port", 0) or 0)
        shell = self._shell(instance, entry)
        if self._os_name == "linux":
            listen = f"{SSH_SERVER_LISTEN_HOST}:${{{SSH_SERVER_PORT_VARIABLE}}}"
            shell_argument = f"${{{SSH_SERVER_SHELL_VARIABLE}}}"
            environment = {
                SSH_SERVER_PORT_VARIABLE: str(port),
                SSH_SERVER_SHELL_VARIABLE: shell,
            }
        else:
            listen = f"{SSH_SERVER_LISTEN_HOST}:{port}"
            shell_argument = shell
            environment = {}
        if self._os_name == "darwin":
            environment = {
                "HOME": entry.home,
                "USER": instance.account,
                "LOGNAME": instance.account,
                "SHELL": shell,
                "PATH": SSH_SERVER_DARWIN_PATH,
            }
        return AccountService(
            name=self.name,
            title=self.title,
            account=instance.account,
            command=(
                self.binary,
                "--listen",
                listen,
                "--host-key",
                host_key,
                "--authorized-key",
                authorized_key,
                "--shell",
                shell_argument,
            ),
            environment=environment,
            working_directory="" if self._os_name == "windows" else "~",
            log_name=self._log_name(instance.account),
            password=instance.password,
            listen_port=port,
            files=(
                (host_key, self._host_key_text()),
                (authorized_key, instance.authorized_key + "\n"),
            ),
            directories=(run_dir,),
        )

    def module_details(self) -> dict:
        """The machine's host public key and its fingerprint.

        Returns:
            ``{"host_key", "host_key_fingerprint"}``, both empty before the
            key is made.
        """
        try:
            line = public_line_of_private(self._host_key_text())
            return {"host_key": line, "host_key_fingerprint": fingerprint(line)}
        except ValueError:
            return {"host_key": "", "host_key_fingerprint": ""}

    def _shell(self, instance: SshServerInstance, entry: AccountEntry) -> str:
        """The shell a session starts: the row's, else the login shell, else PowerShell on Windows."""
        if instance.shell_path:
            return instance.shell_path
        if self._os_name == "windows":
            return windows_powershell()
        return entry.shell or SSH_SERVER_FALLBACK_SHELL

    def _log_name(self, account: str) -> str:
        """Windows: the instance's log under the agent's log root; elsewhere the layer's own."""
        log_path = self._platform.agent_log_path()
        if self._os_name != "windows" or not log_path:
            return ""
        return ntpath.join(ntpath.dirname(log_path), f"{self.name}_{account}.log")

    def _host_key_text(self) -> str:
        """The host key file's text, empty before it is made."""
        try:
            with open(self.host_key_path, "r", encoding="ascii") as stream:
                return stream.read()
        except (OSError, ValueError):
            return ""

    def _make_host_key(self) -> None:
        """Run the program to write a new host key beside the kept path, then move it in place."""
        path = self.host_key_path
        made = path + ".new"
        with contextlib.suppress(OSError):
            os.unlink(made)
        try:
            self.machine.run(
                [self.binary, "--make-host-key", made],
                timeout_s=SSH_SERVER_MAKE_HOST_KEY_TIMEOUT_S,
            )
            if self._os_name != "windows":
                os.chmod(made, 0o600)
            os.replace(made, path)
        except (OSError, subprocess.SubprocessError) as error:
            with contextlib.suppress(OSError):
                os.unlink(made)
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            ) from None
        self._log(f"{self.name}: made the host key")
