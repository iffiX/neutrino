"""Driving LAN devices over SSH.

Everything the panel does to another machine goes through here: opening an
interactive shell, running a privileged command with the stored sudo password,
and the one-click deployments (remote desktop clients, and the neutrino_agent
agent itself).

Output is streamed rather than collected, because these operations take minutes
and the panel shows them live.

A device's host key is recorded the first time it is reached and checked on
every connection after that, because what travels over these sessions is the
sudo password the panel holds for the machine. See
:mod:`neutrino_hub.modules.devices.host_keys`.
"""

import asyncio
import posixpath
import shlex
import stat
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncssh

from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore
from neutrino_hub.modules.devices.key_registry import KeyRegistry

CONNECT_TIMEOUT_S = 15

# Shown when a device answers with a key other than the recorded one. It says
# what to do because the honest answer — reinstalled, or something else is on
# the address — is not one the gateway can tell apart on its own.
HOST_KEY_CHANGED_MESSAGE = (
    "this device is presenting a different host key than the one recorded for "
    "it. That happens when a machine is rebuilt, and it also happens when "
    "something else has taken its address. Remove the device and add it again "
    "to accept the new key."
)
AGENT_INSTALL_DIR = "/tmp/neutrino_agent_install"
READ_CHUNK_BYTES = 4096
SFTP_CHUNK_BYTES = 256 * 1024

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


@dataclass
class SshCredentials:
    """How to reach and authenticate to one device.

    Attributes:
        host: Address or hostname.
        port: SSH port.
        username: Login user.
        private_key_path: Path to a private key, when key authentication is
            used. Written by the panel from a pasted key, not chosen by hand.
        private_key_passphrase: Passphrase, when the key is encrypted.
        password: Login password, when password authentication is used.
        sudo_password: Password piped to ``sudo -S`` for privileged steps. None
            means the account has passwordless sudo.
    """

    host: str
    port: int
    username: str
    private_key_path: str | None = None
    private_key_passphrase: str | None = None
    password: str | None = None
    sudo_password: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "SshCredentials":
        """Build from a device's ``ssh`` block in ``config/devices``.

        A device references a key by ``key_id``; the path and passphrase are
        resolved here from the key registry, so the device config never holds
        key material. An older ``private_key_path`` is still honoured for a
        device configured before the registry existed.

        Args:
            data: The stored SSH settings.

        Returns:
            The parsed credentials.
        """
        key_path = data.get("private_key_path")
        passphrase = data.get("private_key_passphrase")
        key_id = data.get("key_id")
        if key_id:
            registry = KeyRegistry()
            if registry.has_key(key_id):
                key_path = str(registry.path_for(key_id))
                passphrase = registry.passphrase_for(key_id)
        return cls(
            host=data["host"],
            port=data.get("port", 22),
            username=data["username"],
            private_key_path=key_path,
            private_key_passphrase=passphrase,
            password=data.get("password"),
            sudo_password=data.get("sudo_password"),
        )

    @property
    def has_sudo_password(self) -> bool:
        """Whether a sudo password was supplied."""
        return bool(self.sudo_password)


@dataclass
class RemoteFileEntry:
    """One name in a remote directory listing.

    Attributes:
        name: Base name within its directory.
        is_dir: Whether it is a directory.
        is_link: Whether it is a symlink. A link is offered as a directory to
            step into, and stepping into one that points at a file simply
            fails with the server's message.
        size_bytes: Size, zero for directories.
        modified_at: Modification time as Unix seconds.
    """

    name: str
    is_dir: bool = False
    is_link: bool = False
    size_bytes: int = 0
    modified_at: int = 0


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

    async def run_once(self, command: str, *, timeout_s: int = 20) -> tuple[int, str]:
        """Run one command and collect its output.

        For quick status probes, where streaming would be overkill. A locale is
        forced because some tools (AnyDesk among them) refuse to run without a
        UTF-8 one, and an SSH session carries none by default.

        Args:
            command: Shell command to run on the device.
            timeout_s: How long to wait before giving up.

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
                )
                output = (result.stdout or "") + (result.stderr or "")
                return result.exit_status or 0, output.strip()
        except (OSError, asyncssh.Error, asyncio.TimeoutError) as error:
            return SSH_UNREACHABLE_STATUS, str(error)

    async def run_privileged_once(
        self, command: str, *, timeout_s: int = 30
    ) -> tuple[int, str]:
        """Run one command through sudo and collect its output.

        The streaming :meth:`run_privileged_stream` is for output the panel
        shows live; this is for a quick privileged step, like starting a
        service, whose result the caller only needs to check. The stored sudo
        password is supplied, so it works without passwordless sudo.

        Args:
            command: Shell command to run as root on the device.
            timeout_s: How long to wait before giving up.

        Returns:
            The exit code and combined output.
        """
        return await self.run_once(self._sudo_wrap(command), timeout_s=timeout_s)

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

    async def run_stream(self, command: str) -> AsyncIterator[str]:
        """Run a command and yield its output as it arrives.

        Args:
            command: Shell command to run on the device.

        Yields:
            Chunks of combined stdout and stderr, then a final status line.
        """
        try:
            async with self._connect() as connection:
                process = await connection.create_process(
                    command, stderr=asyncssh.STDOUT
                )
                async for chunk in process.stdout:
                    yield chunk
                await process.wait()
                yield f"\n[exit {process.exit_status}]\n"
        except (OSError, asyncssh.Error) as error:
            yield f"\n[connection failed: {error}]\n"

    async def run_privileged_stream(self, command: str) -> AsyncIterator[str]:
        """Run a command through sudo and yield its output.

        Args:
            command: Shell command to run as root on the device.

        Yields:
            Chunks of combined output, then a final status line.
        """
        async for chunk in self.run_stream(self._sudo_wrap(command)):
            yield chunk

    async def install_client(
        self,
        *,
        package_path: Path,
        gateway_url: str,
        token: str,
    ) -> AsyncIterator[str]:
        """Upload and install the neutrino_agent agent.

        Args:
            package_path: Local path to the client tarball.
            gateway_url: Base URL the agent reports back to.
            token: Per-device token the agent authenticates with.

        Yields:
            Progress lines and the remote installer's output.
        """
        if not package_path.is_file():
            yield (
                f"[client package missing at {package_path}; build it in the "
                f"neutrino_agent repo with scripts/build_package/main.py]\n"
            )
            return
        remote_archive = f"{AGENT_INSTALL_DIR}/client.tar.gz"
        try:
            async with self._connect() as connection:
                yield f"[creating {AGENT_INSTALL_DIR}]\n"
                await connection.run(f"mkdir -p {AGENT_INSTALL_DIR}", check=False)
                yield f"[uploading {package_path.name}]\n"
                async with connection.start_sftp_client() as sftp:
                    await sftp.put(str(package_path), remote_archive)
                yield "[unpacking]\n"
                await connection.run(
                    f"tar -xzf {shlex.quote(remote_archive)} "
                    f"-C {shlex.quote(AGENT_INSTALL_DIR)}",
                    check=False,
                )
        except (OSError, asyncssh.Error) as error:
            yield f"\n[upload failed: {error}]\n"
            return

        # NO_COLOR keeps the installer's ANSI codes out of the panel's plain
        # log, where they would show as literal escape sequences.
        install_command = (
            f"cd {shlex.quote(AGENT_INSTALL_DIR)} && NO_COLOR=1 bash install.sh "
            f"--gateway-url {shlex.quote(gateway_url)} --token {shlex.quote(token)}"
        )
        async for chunk in self.run_privileged_stream(install_command):
            yield chunk

    async def open_shell(
        self,
        *,
        on_output: Callable[[str], None],
        term_size: tuple[int, int] = (80, 24),
    ) -> "SshShellSession":
        """Open an interactive shell for the terminal view.

        Args:
            on_output: Called with each chunk the remote shell writes.
            term_size: Initial columns and rows.

        Returns:
            A live session the caller writes keystrokes into.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH negotiation fails.
        """
        connection = await self._open_connection()
        process = await connection.create_process(
            term_type="xterm-256color",
            term_size=term_size,
            stderr=asyncssh.STDOUT,
        )
        return SshShellSession(
            connection=connection, process=process, on_output=on_output
        )

    async def list_dir(self, path: str) -> tuple[str, list[RemoteFileEntry]]:
        """List a remote directory for the file-transfer view.

        Args:
            path: Directory to list; empty means the login user's home.

        Returns:
            The resolved absolute path and its entries, unsorted.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH fails or the path is not a listable
                directory.
        """
        async with self._connect() as connection:
            async with connection.start_sftp_client() as sftp:
                resolved = await sftp.realpath(path or ".")
                entries = []
                for item in await sftp.readdir(resolved):
                    if item.filename in (".", ".."):
                        continue
                    mode = item.attrs.permissions or 0
                    entries.append(
                        RemoteFileEntry(
                            name=item.filename,
                            is_dir=stat.S_ISDIR(mode),
                            is_link=stat.S_ISLNK(mode),
                            size_bytes=item.attrs.size or 0,
                            modified_at=item.attrs.mtime or 0,
                        )
                    )
                return resolved, entries

    async def open_download(self, path: str) -> "SftpDownload":
        """Open a remote file for streaming to the browser.

        Args:
            path: The file to read.

        Returns:
            A live download; the caller must drain or close it.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH fails or the file cannot be opened.
        """
        connection = await self._open_connection()
        try:
            sftp = await connection.start_sftp_client()
            attrs = await sftp.stat(path)
            file = await sftp.open(path, "rb")
        except (OSError, asyncssh.Error):
            connection.close()
            raise
        return SftpDownload(
            connection=connection, file=file, size_bytes=attrs.size or 0
        )

    async def upload_stream(self, path: str, chunks: AsyncIterator[bytes]) -> None:
        """Write a browser upload to a remote file.

        Missing parent directories are created, which is what lets a whole
        folder upload arrive as a stream of files with relative paths.

        Args:
            path: Destination file, overwritten if present.
            chunks: The request body as it arrives.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH fails or the file cannot be written.
        """
        async with self._connect() as connection:
            async with connection.start_sftp_client() as sftp:
                parent = posixpath.dirname(path)
                if parent not in ("", "/"):
                    await sftp.makedirs(parent, exist_ok=True)
                async with sftp.open(path, "wb") as file:
                    async for chunk in chunks:
                        await file.write(chunk)

    async def open_archive_download(self, path: str) -> "SshArchiveDownload":
        """Pack a remote directory or file into a tar.gz stream.

        The archive is built by ``tar`` on the device and streamed as it is
        produced, so nothing is staged on either side.

        Args:
            path: The directory or file to pack.

        Returns:
            A live download; the caller must drain or close it.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH fails.
        """
        parent, name = posixpath.split(path.rstrip("/"))
        connection = await self._open_connection()
        try:
            process = await connection.create_process(
                f"tar -czf - -C {shlex.quote(parent or '/')} {shlex.quote(name)}",
                encoding=None,
            )
        except (OSError, asyncssh.Error):
            connection.close()
            raise
        return SshArchiveDownload(connection=connection, process=process)

    async def make_dir(self, path: str) -> None:
        """Create a remote directory.

        Args:
            path: The directory to create.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH fails or the directory cannot be made.
        """
        async with self._connect() as connection:
            async with connection.start_sftp_client() as sftp:
                await sftp.mkdir(path)

    async def rename_path(self, path: str, new_path: str) -> None:
        """Rename or move a remote file or directory.

        Args:
            path: The current path.
            new_path: The new path.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH fails or the rename is refused.
        """
        async with self._connect() as connection:
            async with connection.start_sftp_client() as sftp:
                await sftp.rename(path, new_path)

    async def delete_path(self, path: str) -> None:
        """Delete a remote file, or a directory with everything in it.

        Args:
            path: The path to delete.

        Raises:
            OSError: If the connection cannot be established.
            asyncssh.Error: If SSH fails or something cannot be removed.
        """
        async with self._connect() as connection:
            async with connection.start_sftp_client() as sftp:
                attrs = await sftp.lstat(path)
                if stat.S_ISDIR(attrs.permissions or 0):
                    await sftp.rmtree(path)
                else:
                    await sftp.remove(path)

    def _sudo_wrap(self, command: str) -> str:
        if self._credentials.username == "root":
            return command
        if self._credentials.has_sudo_password:
            password = shlex.quote(self._credentials.sudo_password or "")
            return f"echo {password} | sudo -S -p '' bash -lc {shlex.quote(command)}"
        return f"sudo -n bash -lc {shlex.quote(command)}"

    @asynccontextmanager
    async def _connect(self):
        """Open a connection, recording the host key the first time."""
        async with asyncssh.connect(**self._connect_options()) as connection:
            self._remember_host_key(connection)
            yield connection

    async def _open_connection(self) -> asyncssh.SSHClientConnection:
        connection = await asyncssh.connect(**self._connect_options())
        self._remember_host_key(connection)
        return connection

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
        # refuses a mismatch, so the sudo password this operator carries
        # cannot be handed to something that merely answered on the address.
        options: dict = {
            "host": self._credentials.host,
            "port": self._credentials.port,
            "username": self._credentials.username,
            "known_hosts": self._host_keys.known_hosts_for(
                self._credentials.host, self._credentials.port
            ),
            "connect_timeout": CONNECT_TIMEOUT_S,
        }
        if self._credentials.private_key_path:
            options["client_keys"] = [self._credentials.private_key_path]
            if self._credentials.private_key_passphrase:
                options["passphrase"] = self._credentials.private_key_passphrase
        if self._credentials.password:
            options["password"] = self._credentials.password
        return options


class SshShellSession:
    """One live interactive shell behind the terminal websocket."""

    def __init__(
        self,
        *,
        connection: asyncssh.SSHClientConnection,
        process: asyncssh.SSHClientProcess,
        on_output: Callable[[str], None],
    ):
        """
        Args:
            connection: The open SSH connection, closed with the session.
            process: The remote shell process.
            on_output: Called with each chunk of remote output.
        """
        self._connection = connection
        self._process = process
        self._on_output = on_output

    async def pump_output(self) -> int:
        """Forward remote output until the shell exits.

        Reads with ``read()`` rather than iterating the stream. Iterating an
        asyncssh reader yields one line at a time, which for an interactive
        shell means a typed character never reaches the browser until Enter is
        pressed — the whole point of a terminal is to echo each keystroke as it
        is typed. ``read()`` returns whatever bytes are available immediately.

        Returns:
            The shell's exit status.
        """
        while True:
            chunk = await self._process.stdout.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            self._on_output(chunk)
        await self._process.wait_closed()
        return self._process.exit_status or 0

    def write(self, data: str) -> None:
        """Send keystrokes to the remote shell.

        Args:
            data: Raw terminal input.
        """
        self._process.stdin.write(data)

    def resize(self, columns: int, rows: int) -> None:
        """Tell the remote shell its terminal size changed.

        Args:
            columns: New column count.
            rows: New row count.
        """
        self._process.change_terminal_size(columns, rows)

    def close(self) -> None:
        """Close the shell and the underlying connection."""
        self._process.close()
        self._connection.close()


class SftpDownload:
    """One remote file being streamed to the browser."""

    def __init__(
        self,
        *,
        connection: asyncssh.SSHClientConnection,
        file,
        size_bytes: int,
    ):
        """
        Args:
            connection: The open SSH connection, closed when the stream ends.
            file: The open remote file.
            size_bytes: The file's size, for the response headers.
        """
        self._connection = connection
        self._file = file
        self.size_bytes = size_bytes

    async def chunks(self) -> AsyncIterator[bytes]:
        """Yield the file's content, closing everything when done.

        The connection is closed in ``finally`` so a browser cancelling the
        download mid-stream still tears the SSH session down.
        """
        try:
            while True:
                chunk = await self._file.read(SFTP_CHUNK_BYTES)
                if not chunk:
                    return
                yield chunk
        finally:
            self._connection.close()


class SshArchiveDownload:
    """One remote directory being packed and streamed to the browser."""

    def __init__(
        self,
        *,
        connection: asyncssh.SSHClientConnection,
        process: asyncssh.SSHClientProcess,
    ):
        """
        Args:
            connection: The open SSH connection, closed when the stream ends.
            process: The remote ``tar`` writing the archive to stdout.
        """
        self._connection = connection
        self._process = process

    async def chunks(self) -> AsyncIterator[bytes]:
        """Yield the archive as ``tar`` produces it.

        The connection is closed in ``finally`` so a cancelled download also
        stops the remote ``tar``.
        """
        try:
            while True:
                chunk = await self._process.stdout.read(SFTP_CHUNK_BYTES)
                if not chunk:
                    return
                yield chunk
        finally:
            self._connection.close()
