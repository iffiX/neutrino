"""Putting the agent on a device over SSH.

SSH exists here for one thing: installing or reinstalling the agent on a
machine that has none. Every other device operation rides the agent's own
channel. The sudo password an install needs is typed for that install,
fed to ``sudo`` over stdin, and kept nowhere.

Output is streamed rather than collected, because an install takes minutes
and the panel shows it live.

A device's host key is recorded the first time it is reached and checked on
every connection after that, because what travels over these sessions is the
sudo password somebody just typed. See
:mod:`neutrino_hub.modules.devices.host_keys`.
"""

import asyncio
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncssh

from neutrino_hub.modules.credentials.vault import SecretVault, VaultError
from neutrino_hub.modules.devices.agent_package import (
    AgentPackageCache,
    AgentPackageFetchError,
)
from neutrino_hub.modules.devices.constants import (
    SSH_UNREACHABLE_STATUS,
    SSH_UNSUPPORTED_OS_STATUS,
)
from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore
from neutrino_hub.modules.devices.key_registry import KeyRegistry

LOGIN_KIND = "login"

CONNECT_TIMEOUT_S = 15
# Room for apt to fetch python3 on a minimal image before the tiny package.
INSTALL_TIMEOUT_S = 300
# Room for a full package list on a slow mirror.
REFRESH_TIMEOUT_S = 300

# Shown when a device answers with a key other than the recorded one. It says
# what to do because the honest answer — reinstalled, or something else is on
# the address — is not one the gateway can tell apart on its own.
HOST_KEY_CHANGED_MESSAGE = (
    "this device is presenting a different host key than the one recorded for "
    "it. That happens when a machine is rebuilt, and it also happens when "
    "something else has taken its address. Remove the device and add it again "
    "to accept the new key."
)
# uname -m to the architecture names dpkg and arch.json use.
MACHINE_TO_ARCH = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "armv7l": "armhf",
    "armv6l": "armhf",
}


def _os_family(os_release: str) -> str:
    text = os_release.lower()
    if any(name in text for name in ("rhel", "fedora", "centos", "rocky", "alma")):
        return "rhel"
    return "debian"


def _normalise_machine(machine: str) -> str:
    return MACHINE_TO_ARCH.get(machine, machine)


def _password_material(login_id: str | None) -> str | None:
    """Open one referenced login's password.

    Args:
        login_id: The vault object's id, or None when the device names
            none.

    Returns:
        The password, or None when the id is absent, stale, or names another
        kind — the same stance as a stale ``key_id``.
    """
    if not login_id:
        return None
    vault = SecretVault()
    record = vault.get(login_id)
    if record is None or record.kind != LOGIN_KIND:
        return None
    try:
        return vault.open(login_id).get("password")
    except VaultError:
        return None


@dataclass
class SshCredentials:
    """How to reach and authenticate to one device.

    Attributes:
        host: Address or hostname.
        port: SSH port.
        username: Login user.
        private_key: Private key text, opened from the vault for the device's
            ``key_id``.
        private_key_path: Path to a private key file, for a device whose config
            names one directly.
        private_key_passphrase: Passphrase, when the key is encrypted.
        password: Login password, opened from the vault for the device's
            ``login_id`` or typed for one install.
    """

    host: str
    port: int
    username: str
    private_key: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = None
    password: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "SshCredentials":
        """Build from a device's ``ssh`` block in ``config/devices``.

        A device references its key by ``key_id`` and its password by
        ``login_id``; the material is opened from the vault here, so the
        device config never holds any. A stale reference yields no material
        rather than an error. A ``private_key_path`` naming a file is still
        honoured.

        Args:
            data: The stored SSH settings.

        Returns:
            The parsed credentials.
        """
        private_key = None
        passphrase = data.get("private_key_passphrase")
        key_id = data.get("key_id")
        if key_id:
            registry = KeyRegistry()
            if registry.has_key(key_id):
                private_key, passphrase = registry.material_for(key_id)
        return cls(
            host=data["host"],
            port=data.get("port", 22),
            username=data["username"],
            private_key=private_key,
            private_key_path=data.get("private_key_path"),
            private_key_passphrase=passphrase,
            password=_password_material(data.get("login_id")),
        )


class DeviceSshOperator:
    """Runs commands and deployments on one device."""

    def __init__(
        self,
        *,
        credentials: SshCredentials,
        host_keys: "DeviceHostKeyStore | None" = None,
    ):
        """
        Args:
            credentials: How to reach the device.
            host_keys: Where the device's host key is remembered. The default
                store is the gateway's own; tests pass their own file.
        """
        self._credentials = credentials
        self._host_keys = host_keys or DeviceHostKeyStore()
        # Whether sudo on the device prompts, learned once from sudo itself
        # (``sudo -n true``); None until asked.
        self._is_sudo_passwordless: "bool | None" = None

    async def check_connection(self) -> tuple[bool, str]:
        """Try to connect and report the result.

        Returns:
            A pair of success flag and a message: the remote uname on success,
            the failure reason otherwise.
        """
        try:
            async with self._connect() as connection:
                result = await connection.run("uname -sr", check=False)
                return True, (result.stdout or "").strip()
        except asyncssh.HostKeyNotVerifiable:
            return False, HOST_KEY_CHANGED_MESSAGE
        except (OSError, asyncssh.Error) as error:
            return False, str(error)

    async def run_once(
        self, command: str, *, timeout_s: int = 20, input_text: str | None = None
    ) -> tuple[int, str]:
        """Run one command and collect its output.

        For quick status probes, where streaming would be overkill. A UTF-8
        locale is forced, since an SSH session carries none by default.

        Args:
            command: Shell command to run on the device.
            timeout_s: How long to wait before giving up.
            input_text: Written to the command's stdin, which is then closed.

        Returns:
            The exit code and the combined output. A connection failure is
            reported as exit 255 with the reason as output, rather than raising,
            so a caller probing several things is not derailed by one failure.
        """
        try:
            async with self._connect() as connection:
                result = await connection.run(
                    f"LANG=C.UTF-8 LC_ALL=C.UTF-8 {command}",
                    check=False,
                    timeout=timeout_s,
                    input=input_text,
                )
                output = (result.stdout or "") + (result.stderr or "")
                return result.exit_status or 0, output.strip()
        except (OSError, asyncssh.Error, asyncio.TimeoutError) as error:
            return SSH_UNREACHABLE_STATUS, str(error)

    async def run_privileged_once(
        self,
        command: str,
        *,
        timeout_s: int = 30,
        input_text: str | None = None,
        sudo_password: str | None = None,
    ) -> tuple[int, str]:
        """Run one command through sudo and collect its output.

        The streaming :meth:`run_privileged_stream` is for output the panel
        shows live; this is for a quick privileged step, like starting a
        service, whose result the caller only needs to check.

        Args:
            command: Shell command to run as root on the device.
            timeout_s: How long to wait before giving up.
            input_text: What the command itself reads from stdin, after the
                sudo password line when one is needed.
            sudo_password: What sudo is fed when it prompts; None when the
                account is expected not to be asked.

        Returns:
            The exit code and combined output.
        """
        plan, refusal = await self._sudo_plan(command, input_text, sudo_password)
        if plan is None:
            return 1, refusal
        wrapped, payload = plan
        return await self.run_once(wrapped, timeout_s=timeout_s, input_text=payload)

    async def detect_system(self) -> tuple[str, str]:
        """Read the device's OS family and architecture.

        Args:
            None.

        Returns:
            A pair of ``os_family`` (``debian`` or ``rhel``, defaulting to
            ``debian``) and normalised ``arch`` (``amd64`` / ``arm64`` /
            ``armhf`` / ``x86_64``), matching the keys in a product's
            ``arch.json``. Unknown values come back empty so the caller treats
            the device as unsupported rather than guessing.
        """
        _, os_release = await self.run_once(
            '. /etc/os-release 2>/dev/null; echo "$ID $ID_LIKE"'
        )
        os_family = _os_family(os_release)
        code, arch = await self.run_once("dpkg --print-architecture 2>/dev/null")
        if code == 0 and arch.strip():
            return os_family, arch.strip()
        _, machine = await self.run_once("uname -m")
        return os_family, _normalise_machine(machine.strip())

    async def upload(self, local_path: Path, remote_path: str) -> None:
        """Copy a local file to the device.

        Args:
            local_path: The file to send.
            remote_path: Where to put it on the device.

        Raises:
            OSError: If the connection or transfer fails.
            asyncssh.Error: If SFTP fails.
        """
        async with self._connect() as connection:
            async with connection.start_sftp_client() as sftp:
                await sftp.put(str(local_path), remote_path)

    async def run_stream(
        self, command: str, *, input_text: str | None = None
    ) -> AsyncIterator[str]:
        """Run a command and yield its output as it arrives.

        Args:
            command: Shell command to run on the device.
            input_text: Written to the command's stdin, which is then closed.

        Yields:
            Chunks of combined stdout and stderr, then a final status line.
        """
        try:
            async with self._connect() as connection:
                process = await connection.create_process(
                    command, stderr=asyncssh.STDOUT, input=input_text
                )
                async for chunk in process.stdout:
                    yield chunk
                await process.wait()
                yield f"\n[exit {process.exit_status}]\n"
        except (OSError, asyncssh.Error) as error:
            yield f"\n[connection failed: {error}]\n"

    async def run_privileged_stream(
        self,
        command: str,
        *,
        input_text: str | None = None,
        sudo_password: str | None = None,
    ) -> AsyncIterator[str]:
        """Run a command through sudo and yield its output.

        Args:
            command: Shell command to run as root on the device.
            input_text: What the command itself reads from stdin, after the
                sudo password line when one is needed.
            sudo_password: What sudo is fed when it prompts; None when the
                account is expected not to be asked.

        Yields:
            Chunks of combined output, then a final status line.
        """
        plan, refusal = await self._sudo_plan(command, input_text, sudo_password)
        if plan is None:
            yield f"{refusal}\n"
            yield "\n[exit 1]\n"
            return
        wrapped, payload = plan
        async for chunk in self.run_stream(wrapped, input_text=payload):
            yield chunk

    async def install_client(
        self,
        *,
        packages: AgentPackageCache,
        enrollment_link: str,
        sudo_password: str | None = None,
    ) -> AsyncIterator[str]:
        """Deliver the agent as a native package and join it to this hub.

        The same acts a person performs by hand — refresh the package lists,
        install the package, run ``nagent connect`` — so there is one install
        story and one enrollment path. The link goes on the command line,
        which it was shaped for: a single-use ticket bound to this device's
        record, no different from a person pasting it into a terminal. Stdin
        stays the sudo password's alone — sudo reads it only when it prompts,
        so nothing else may need lines counted behind it.

        Args:
            packages: The agent packages this hub can deliver, asked once the
                machine and its package manager are known.
            enrollment_link: The ticket the panel generated for this device.
            sudo_password: What sudo is fed when it prompts, typed for this
                install; None when the account is expected not to be asked.

        Yields:
            Progress lines and the remote tools' output. A device that is not
            Linux, or whose package manager or machine the hub carries no
            package for, ends the task before anything lands on it.
        """
        family = None
        package_path = None
        try:
            async with self._connect() as connection:
                result = await connection.run("uname -s", check=False)
                kernel = (result.stdout or "").strip()
                if kernel != "Linux":
                    yield (
                        f"[unsupported OS {kernel or 'unknown'}; the agent "
                        f"installs over SSH on Linux devices]\n"
                    )
                    yield f"\n[exit {SSH_UNSUPPORTED_OS_STATUS}]\n"
                    return
                # The package carries an interpreter, so the machine decides
                # which file as much as the package manager does.
                result = await connection.run("uname -m", check=False)
                machine = (result.stdout or "").strip()
                architecture = _normalise_machine(machine)
                for candidate, tool in (("deb", "dpkg"), ("rpm", "rpm")):
                    if not packages.serves(family=candidate, architecture=architecture):
                        continue
                    probe = await connection.run(f"command -v {tool}", check=False)
                    if (probe.exit_status or 0) != 0:
                        continue
                    # The bytes may still have to be fetched, which is a
                    # download and not something to hold the loop for.
                    package_path = await asyncio.to_thread(
                        packages.package,
                        family=candidate,
                        architecture=architecture,
                    )
                    family = candidate
                    break
                if package_path is None:
                    yield (
                        "[the hub carries no agent package this machine can "
                        f"install (dpkg or rpm, {machine or 'unknown machine'}); "
                        "join this machine with an enrollment link instead]\n"
                    )
                    yield f"\n[exit {SSH_UNSUPPORTED_OS_STATUS}]\n"
                    return
                remote_package = f"/tmp/{package_path.name}"
                yield f"[uploading {package_path.name}]\n"
                async with connection.start_sftp_client() as sftp:
                    await sftp.put(str(package_path), remote_package)
        except AgentPackageFetchError as error:
            platform = error.params.get("platform", "this machine")
            yield f"\n[the agent package for {platform} could not be produced: "
            yield f"{error.code}]\n"
            yield f"\n[exit {SSH_UNSUPPORTED_OS_STATUS}]\n"
            return
        except (OSError, asyncssh.Error) as error:
            yield f"\n[upload failed: {error}]\n"
            return

        if family == "deb":
            # The package names dependencies apt resolves from the device's
            # lists, and an image's lists are empty until they are fetched.
            # dnf refreshes its own metadata, so only apt is asked to.
            yield "[refreshing the package lists]\n"
            code, output = await self.run_privileged_once(
                "DEBIAN_FRONTEND=noninteractive apt-get update",
                timeout_s=REFRESH_TIMEOUT_S,
                sudo_password=sudo_password,
            )
            if output:
                yield output + "\n"
            if code != 0:
                yield (
                    "[the package lists could not be refreshed; the install "
                    "continues with the lists this device already has]\n"
                )
            # --reinstall, because a reinstall of the same version is this
            # action's whole meaning on a managed device — plain install
            # answers "already newest" and changes nothing.
            install_command = (
                "DEBIAN_FRONTEND=noninteractive apt-get install -y "
                "--reinstall "
                f"--allow-downgrades {shlex.quote(remote_package)}"
            )
        else:
            install_command = (
                f"dnf reinstall -y {shlex.quote(remote_package)} || "
                f"dnf install -y {shlex.quote(remote_package)} || "
                f"rpm -Uvh --oldpackage --force {shlex.quote(remote_package)}"
            )
        yield f"[installing the {family} package]\n"
        code, output = await self.run_privileged_once(
            install_command, timeout_s=INSTALL_TIMEOUT_S, sudo_password=sudo_password
        )
        if output:
            yield output + "\n"
        if code != 0:
            yield f"\n[exit {code}]\n"
            return

        yield "[joining this hub]\n"
        code, output = await self.run_privileged_once(
            f"nagent connect --yes {shlex.quote(enrollment_link)}",
            sudo_password=sudo_password,
        )
        if output:
            yield output + "\n"
        yield f"\n[exit {code}]\n"

    async def _sudo_plan(
        self,
        command: str,
        input_text: str | None = None,
        sudo_password: str | None = None,
    ) -> "tuple[tuple[str, str | None] | None, str]":
        """Compose a privileged run so stdin is never shared by accident.

        Sudo itself is asked first — ``sudo -n true``, once per operator —
        whether it would prompt. The password line is then sent exactly when
        sudo is going to consume it (``-k`` discards a cached timestamp so it
        must), and a password the account does not need never leaves the hub
        at all. Nothing behind sudo ever has to count stdin lines.

        Args:
            command: The command to run as root.
            input_text: What the command itself reads from stdin, when
                anything.
            sudo_password: What sudo is fed when it prompts.

        Returns:
            The plan — the command to send and its stdin payload — and an
            empty string; or None and the line saying why there is no plan.
        """
        if self._credentials.username == "root":
            return (command, input_text), ""
        if self._is_sudo_passwordless is None:
            code, _ = await self.run_once("sudo -n true")
            self._is_sudo_passwordless = code == 0
        if self._is_sudo_passwordless:
            return (f"sudo -n bash -lc {shlex.quote(command)}", input_text), ""
        if not sudo_password:
            return None, (
                "[sudo on this device wants a password and none was given; "
                "type one in the install dialog]"
            )
        return (
            f"sudo -S -p '' -k bash -lc {shlex.quote(command)}",
            f"{sudo_password}\n{input_text or ''}",
        ), ""

    @asynccontextmanager
    async def _connect(self):
        """Open a connection, recording the host key the first time."""
        async with asyncssh.connect(**self._connect_options()) as connection:
            self._remember_host_key(connection)
            yield connection

    def _remember_host_key(self, connection) -> None:
        """Write down the key this device presented, the first time it does.

        Later connections are checked against it by asyncssh, so nothing is
        recorded here after the first: a key that has changed must reach a
        person as a refusal, not as an update.
        """
        if self._host_keys.has(self._credentials.host, self._credentials.port):
            return
        key = connection.get_server_host_key()
        if key is None:
            return
        try:
            self._host_keys.learn(
                self._credentials.host,
                self._credentials.port,
                key.export_public_key().decode().strip(),
            )
        except OSError:
            # A key that cannot be written is a problem with the disk, not
            # with the device. Failing the session over it would take every
            # device offline in the panel; the next connection tries again.
            pass

    def _connect_options(self) -> dict:
        # None means "take this one on trust", which is only ever the first
        # connection to a device. Once a key is on file asyncssh checks it and
        # refuses a mismatch, so a sudo password somebody typed cannot be
        # handed to something that merely answered on the address.
        options: dict = {
            "host": self._credentials.host,
            "port": self._credentials.port,
            "username": self._credentials.username,
            "known_hosts": self._host_keys.known_hosts_for(
                self._credentials.host, self._credentials.port
            ),
            "connect_timeout": CONNECT_TIMEOUT_S,
        }
        if self._credentials.private_key:
            options["client_keys"] = [
                asyncssh.import_private_key(
                    self._credentials.private_key,
                    passphrase=self._credentials.private_key_passphrase,
                )
            ]
        elif self._credentials.private_key_path:
            options["client_keys"] = [self._credentials.private_key_path]
            if self._credentials.private_key_passphrase:
                options["passphrase"] = self._credentials.private_key_passphrase
        if self._credentials.password:
            options["password"] = self._credentials.password
        return options
