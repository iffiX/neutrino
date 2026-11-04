"""What the SSH server adds to the shared runner: each instance's host key and run directory.

The agent carries ``neutrino_ssh_server`` in its own package, so nothing is
installed. Each instance runs the program as its account on ``127.0.0.1`` at
the port the shared runner takes for it from 22000 up and keeps in its
record, reading its own Ed25519 host key, which the agent makes with that
program at the instance's first apply, and its one authorized key from its
run directory. The directory and its files are root's, SYSTEM's on Windows,
and the account alone reads them beside root. Beside the keys ``path_folders`` names the
launcher folders of the command line programs the account is enabled in,
which the program reads as each session starts; a change of them rewrites
that file alone. No forwarder stands in front of it: the hub reaches it
through the agent's ``connect`` stream.

Not pure: makes the host keys and writes the run directories.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ntpath
import os
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
    read_regular,
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
    SSH_SERVER_INSTANCE_KEY_NAME,
    SSH_SERVER_LISTEN_HOST,
    SSH_SERVER_MAKE_HOST_KEY_TIMEOUT_S,
    SSH_SERVER_NAME,
    SSH_SERVER_MADE_HOST_KEY_SUFFIX,
    SSH_SERVER_PATH_FOLDERS_NAME,
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
from neutrino_agent.platforms.base import launcher_folders


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

    def run_dir(self, account: str) -> str:
        """One account's run directory, root's, which its instance reads.

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
        """Open the way to the run directories, and delete the one host key of an earlier version.

        Returns:
            ``removed the machine's host key`` when this apply deleted it.

        Raises:
            OSError: When the module's directory cannot be written.
        """
        module_dir = self.machine.module_dir
        run_root = self._join(module_dir, SSH_SERVER_RUN_DIR_NAME)
        os.makedirs(run_root, exist_ok=True)
        if self._os_name != "windows":
            os.chmod(module_dir, 0o755)
            os.chmod(run_root, 0o755)
        machine_key = self._join(module_dir, SSH_SERVER_HOST_KEY_NAME)
        if not os.path.isfile(machine_key):
            return []
        os.unlink(machine_key)
        return ["removed the machine's host key"]

    def prepare(
        self, parsed: SshServerConfig, instance: SshServerInstance, entry: AccountEntry
    ) -> list:
        """Make the account's run directory and its host key, and write its ``path_folders``.

        The directory is root's, SYSTEM's on Windows, and the account alone
        reads it beside root; one an earlier version gave the account is
        taken back first, and the copy of the machine's host key it held
        deleted once it is root's. The host key is made once, at the
        instance's first apply.

        Args:
            parsed: The parsed configuration.
            instance: The instance, whose ``programs`` name the folders.
            entry: Its account.

        Returns:
            ``made the host key of <account>`` and ``wrote the path folders
            of <account>``, each when this apply did it.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when the program
                cannot make the key.
            KeyError: When the machine does not have the account.
            OSError: When the run directory or a file cannot be written.
        """
        account = instance.account
        run_dir = self.run_dir(account)
        account_service.make_read_dir(run_dir, account, self.machine)
        notes = []
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._join(run_dir, SSH_SERVER_HOST_KEY_NAME))
            notes.append(
                f"removed the machine's host key from the run folder of {account}"
            )
        if not self._host_key_line(account):
            self._make_host_key(account)
            notes.append(f"made the host key of {account}")
        folders = launcher_folders(
            self._platform.agent_var_dir(), self._os_name, instance.programs
        )
        text = "".join(folder + "\n" for folder in folders)
        path = self._join(run_dir, SSH_SERVER_PATH_FOLDERS_NAME)
        if account_service.write_read_file(path, text, account, self.machine):
            notes.append(f"wrote the path folders of {account}")
        return notes

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
        host_key = self._join(run_dir, SSH_SERVER_INSTANCE_KEY_NAME)
        authorized_key = self._join(run_dir, SSH_SERVER_AUTHORIZED_KEY_NAME)
        path_folders = self._join(run_dir, SSH_SERVER_PATH_FOLDERS_NAME)
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
                "--path-folders",
                path_folders,
            ),
            environment=environment,
            working_directory="" if self._os_name == "windows" else "~",
            log_name=self._log_name(instance.account),
            password=instance.password,
            listen_port=port,
            read_files=(
                (host_key, self._host_key_text(instance.account)),
                (authorized_key, instance.authorized_key + "\n"),
            ),
        )

    def details_extra(self, record: dict) -> dict:
        """One instance's host public key and its fingerprint.

        Args:
            record: The instance's record.

        Returns:
            ``{"host_key", "host_key_fingerprint"}``, both empty before the
            key is made.
        """
        line = self._host_key_line(str(record.get("account", "") or ""))
        return {
            "host_key": line,
            "host_key_fingerprint": fingerprint(line) if line else "",
        }

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

    def _host_key_text(self, account: str) -> str:
        """One instance's host key file's text, empty before it is made."""
        held = read_regular(
            self._join(self.run_dir(account), SSH_SERVER_INSTANCE_KEY_NAME)
        )
        try:
            return (held or b"").decode("ascii")
        except ValueError:
            return ""

    def _host_key_line(self, account: str) -> str:
        """One instance's host public key in OpenSSH form, empty before it is made or when it does not read."""
        text = self._host_key_text(account)
        if not text:
            return ""
        try:
            return public_line_of_private(text)
        except ValueError:
            return ""

    def _make_host_key(self, account: str) -> None:
        """Run the program to make a new host key in the account's run directory, then write it there as a read file."""
        run_dir = self.run_dir(account)
        made = self._join(
            run_dir, SSH_SERVER_INSTANCE_KEY_NAME + SSH_SERVER_MADE_HOST_KEY_SUFFIX
        )
        with contextlib.suppress(OSError):
            os.unlink(made)
        try:
            self.machine.run(
                [self.binary, "--make-host-key", made],
                timeout_s=SSH_SERVER_MAKE_HOST_KEY_TIMEOUT_S,
            )
            text = (read_regular(made) or b"").decode("ascii")
            public_line_of_private(text)
            account_service.write_read_file(
                self._join(run_dir, SSH_SERVER_INSTANCE_KEY_NAME),
                text,
                account,
                self.machine,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            ) from None
        finally:
            with contextlib.suppress(OSError):
                os.unlink(made)
        self._log(f"{self.name}: made the host key of {account}")
