"""What the SSH server adds to the shared runner: the host key and each instance's run directory.

The agent carries ``neutrino_ssh_server`` in its own package, so nothing is
installed. The first apply makes the machine's Ed25519 host key with that
program, kept root's alone under the module's directory. Each instance runs
the program as its account on ``127.0.0.1`` at the port the shared runner
takes for it from 22000 up and keeps in its record, reading a copy of the
host key and its one authorized key from its run directory, which the
account owns. Beside them ``path_folders`` names the launcher folders of
the command line programs the account is enabled in, which the program
reads as each session starts; a change of them rewrites that file alone.
No forwarder stands in front of it: the hub reaches it through the agent's
``connect`` stream.

Not pure: makes the host key and writes the path folders file.
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
    SSH_SERVER_PATH_FOLDERS_NAME,
    SSH_SERVER_PATH_FOLDERS_STAGED_SUFFIX,
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

# How the path folders file is read and written: no link followed, no wait
# on a pipe, and the new file made afresh.
PATH_FOLDERS_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
)
PATH_FOLDERS_WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
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


def write_swapped(path: str, text: str) -> bool:
    """Write one file whole beside its place and rename it in, unless it holds this text.

    The new file is made afresh, mode 0644, following no link; the file it
    replaces is never opened for writing.

    Args:
        path: The file.
        text: What it holds afterwards.

    Returns:
        Whether it changed.

    Raises:
        OSError: When the file cannot be written or renamed into place.
    """
    data = text.encode("utf-8")
    try:
        descriptor = os.open(path, PATH_FOLDERS_READ_FLAGS)
    except OSError:
        held = None
    else:
        try:
            with os.fdopen(descriptor, "rb") as stream:
                held = stream.read(len(data) + 1)
        except OSError:
            held = None
    if held == data:
        return False
    staged = path + SSH_SERVER_PATH_FOLDERS_STAGED_SUFFIX
    with contextlib.suppress(FileNotFoundError):
        os.unlink(staged)
    descriptor = os.open(staged, PATH_FOLDERS_WRITE_FLAGS, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(staged, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(staged)
        raise
    return True


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

    def prepare(
        self, parsed: SshServerConfig, instance: SshServerInstance, entry: AccountEntry
    ) -> list:
        """Write the launcher folders of the account's programs into its ``path_folders``.

        Args:
            parsed: The parsed configuration.
            instance: The instance, whose ``programs`` name the folders.
            entry: Its account.

        Returns:
            ``wrote the path folders of <account>`` when the file changed.

        Raises:
            OSError: When the run directory or the file cannot be written.
        """
        run_dir = self.run_dir(instance.account)
        os.makedirs(run_dir, mode=0o700, exist_ok=True)
        folders = launcher_folders(
            self._platform.agent_var_dir(), self._os_name, instance.programs
        )
        text = "".join(folder + "\n" for folder in folders)
        path = self._join(run_dir, SSH_SERVER_PATH_FOLDERS_NAME)
        if not write_swapped(path, text):
            return []
        return [f"wrote the path folders of {instance.account}"]

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
