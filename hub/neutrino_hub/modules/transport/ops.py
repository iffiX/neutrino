"""Running the hub's transport, and reading what it keeps.

The applier makes the stored settings true: the directories the transport
writes, the local channel's secret, ``generated/transport.json``, and the
process under the controller's name ``transport``, which is the unit
``neutrino_hub_transport.service`` on Linux and a child of the hub's service
on macOS and Windows (privilege.md, "The transport holds the agent port, and
is not root"). The probe runs ``neutrino_transport probe`` for the relay's
and the frp vendors' checks. The key helpers read the public half, and seal
or restore the private half for a backup; nothing here prints either.
"""

import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
from pathlib import Path

# Unix's alone; the account the unit runs as is Linux's.
try:
    import grp
except ImportError:
    grp = None

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.channel.constants import CHANNEL_SETTING_LEGACY
from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.transport.constants import (
    TRANSPORT_ACCOUNT,
    TRANSPORT_BINARY_PATH,
    TRANSPORT_CHANGE_RESTARTED,
    TRANSPORT_CHANGE_STARTED,
    TRANSPORT_COMMAND_HUB,
    TRANSPORT_COMMAND_PROBE,
    TRANSPORT_GENERATED_MODE,
    TRANSPORT_GENERATED_NAME,
    TRANSPORT_KEY_AAD,
    TRANSPORT_KEY_DIR,
    TRANSPORT_CONFIG_ROOT_MODE,
    TRANSPORT_KEY_DIR_MODE,
    TRANSPORT_KEY_HEX_CHARS,
    TRANSPORT_PRIVATE_KEY_MODE,
    TRANSPORT_PRIVATE_KEY_NAME,
    TRANSPORT_PROBE_TIMEOUT_S,
    TRANSPORT_PUBLIC_KEY_NAME,
    TRANSPORT_RUN_DIR,
    TRANSPORT_RUN_DIR_MODE,
    TRANSPORT_SEALED_KEY_NAME,
    TRANSPORT_SECRET_BYTES,
    TRANSPORT_SECRET_MODE,
    TRANSPORT_SECRET_NAME,
    TRANSPORT_SERVICE_NAME,
    TRANSPORT_SOCKET_NAME,
    TRANSPORT_STATE_DIR,
    TRANSPORT_STATE_DIR_MODE,
    TRANSPORT_WINDOWS_PIPE,
)
from neutrino_hub.modules.transport.renderer import TransportConfigRenderer
from neutrino_hub.platforms.constants import PLATFORM_OS_WINDOWS
from neutrino_hub.platforms.detect import hub_os, is_linux
from neutrino_hub.system.child_supervisor import ChildStartLine
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.web.constants import WEB_DEFAULT_AGENT_LISTEN_PORT

LOGGER = logging.getLogger(__name__)


class TransportSecretHolder:
    """The local channel's secret the supervisor made for the transport's
    current run, on macOS and Windows; empty while no run was started."""

    def __init__(self):
        self._lock = threading.Lock()
        self._secret = ""

    def set(self, secret: str) -> None:
        """Keep the secret the child was just handed."""
        with self._lock:
            self._secret = secret

    def get(self) -> str:
        """The secret the current run holds, empty for none."""
        with self._lock:
            return self._secret


SECRET_HOLDER = TransportSecretHolder()


def control_socket_address() -> str:
    """Where the transport listens for the hub's Python.

    Returns:
        The socket's path, or the pipe's name on Windows.
    """
    if hub_os() == PLATFORM_OS_WINDOWS:
        return TRANSPORT_WINDOWS_PIPE
    return str(TRANSPORT_RUN_DIR / TRANSPORT_SOCKET_NAME)


def secret_path() -> Path:
    """The file the secret lives in on Linux."""
    return TRANSPORT_STATE_DIR / TRANSPORT_SECRET_NAME


def transport_secret() -> str:
    """The secret every local connection opens with.

    Returns:
        The supervisor's secret for the current run where the transport is
        the service's child; else the file's, empty when it is not there.
    """
    held = SECRET_HOLDER.get()
    if held:
        return held
    try:
        return secret_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def make_secret() -> str:
    """A fresh local channel secret, 32 random bytes in hex."""
    return secrets.token_hex(TRANSPORT_SECRET_BYTES)


def ensure_secret_file() -> bool:
    """Write the secret file when it is missing, root's with the transport's group.

    Returns:
        True when the file was written.

    Raises:
        OSError: When the state directory or the file cannot be written.
    """
    path = secret_path()
    ensure_state_dir()
    if path.is_file() and path.read_text(encoding="utf-8").strip():
        return False
    path.write_text(make_secret() + "\n", encoding="utf-8")
    _own_by_group(path, TRANSPORT_SECRET_MODE)
    return True


def ensure_state_dir() -> None:
    """Make the transport's state directory, root's with the transport's group.

    Raises:
        OSError: When it cannot be made.
    """
    TRANSPORT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _own_by_group(TRANSPORT_STATE_DIR, TRANSPORT_STATE_DIR_MODE)


def ensure_key_dir() -> bool:
    """Make the key directory the transport's own, mode 0700, under a
    configuration root the account passes.

    Returns:
        True when the directory was made.

    Raises:
        OSError: When it cannot be made or handed over.
    """
    is_made = not TRANSPORT_KEY_DIR.is_dir()
    TRANSPORT_KEY_DIR.mkdir(parents=True, exist_ok=True)
    if is_linux():
        os.chmod(TRANSPORT_KEY_DIR.parent, TRANSPORT_CONFIG_ROOT_MODE)
    _own_by_account(TRANSPORT_KEY_DIR, TRANSPORT_KEY_DIR_MODE)
    return is_made


def ensure_run_dir() -> None:
    """Make the transport's run directory, its own, mode 0700.

    Raises:
        OSError: When it cannot be made or handed over.
    """
    if hub_os() == PLATFORM_OS_WINDOWS:
        return
    TRANSPORT_RUN_DIR.mkdir(parents=True, exist_ok=True)
    _own_by_account(TRANSPORT_RUN_DIR, TRANSPORT_RUN_DIR_MODE)


def ensure_account() -> bool:
    """Make the transport's system account on Linux.

    Returns:
        True when the account was made; False when it was there, or the hub
        is not on Linux.

    Raises:
        subprocess.CalledProcessError: When ``useradd`` fails.
    """
    if not is_linux() or has_account():
        return False
    run(
        [
            "useradd",
            "--system",
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            TRANSPORT_ACCOUNT,
        ]
    )
    return True


def has_account() -> bool:
    """Whether the transport's account exists on this Linux box."""
    if not is_linux() or grp is None:
        return False
    try:
        grp.getgrnam(TRANSPORT_ACCOUNT)
    except KeyError:
        return False
    return True


def read_public_key() -> str:
    """The hub's static public key, as the transport wrote it.

    Returns:
        64 lowercase hex characters.

    Raises:
        FileNotFoundError: While the transport has made no key yet.
        ValueError: When the file holds no key.
    """
    text = (TRANSPORT_KEY_DIR / TRANSPORT_PUBLIC_KEY_NAME).read_text("utf-8").strip()
    key = text.lower()
    if len(key) != TRANSPORT_KEY_HEX_CHARS or any(
        char not in "0123456789abcdef" for char in key
    ):
        raise ValueError("the public key file holds no key")
    return key


def sealed_private_key() -> bytes:
    """The private half sealed under the vault's data key, for a backup.

    Returns:
        The sealed record as JSON bytes.

    Raises:
        FileNotFoundError: While the transport has made no key yet.
        VaultLockedError: While the vault is locked.
    """
    private = (TRANSPORT_KEY_DIR / TRANSPORT_PRIVATE_KEY_NAME).read_bytes()
    try:
        sealed = seal_bytes(private, TRANSPORT_KEY_AAD)
    except (OSError, ValueError) as error:
        raise VaultLockedError() from error
    return json.dumps(sealed).encode("utf-8")


def restore_private_key(sealed_json: bytes) -> None:
    """Put a backup's private half back as the transport's own.

    Args:
        sealed_json: What :func:`sealed_private_key` produced.

    Raises:
        VaultLockedError: While the vault cannot open it.
        ValueError: When the archive member is not a sealed record.
        OSError: When the key cannot be written.
    """
    sealed = json.loads(sealed_json.decode("utf-8"))
    if not isinstance(sealed, dict):
        raise ValueError("the sealed key is not a record")
    try:
        private = unseal_bytes(sealed, TRANSPORT_KEY_AAD)
    except (OSError, ValueError) as error:
        raise VaultLockedError() from error
    ensure_key_dir()
    path = TRANSPORT_KEY_DIR / TRANSPORT_PRIVATE_KEY_NAME
    path.write_bytes(private)
    _own_by_account(path, TRANSPORT_PRIVATE_KEY_MODE)
    public = TRANSPORT_KEY_DIR / TRANSPORT_PUBLIC_KEY_NAME
    if public.exists():
        public.unlink()


def generated_path() -> Path:
    """Where ``transport.json`` is written."""
    return UTILS_GENERATED_DIR / TRANSPORT_GENERATED_NAME


def render_settings(settings: dict) -> dict:
    """The transport's document for the panel's settings.

    Args:
        settings: ``config/web/settings.json`` as read.

    Returns:
        What :class:`TransportConfigRenderer` renders.
    """
    return TransportConfigRenderer(
        listen_port=int(
            settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
        ),
        control_socket=control_socket_address(),
        is_legacy_enabled=settings.get(CHANNEL_SETTING_LEGACY) is True,
    ).render()


def start_line() -> ChildStartLine:
    """How the hub's service starts the transport as its child.

    Returns:
        The start line, its secret written to the child's standard input at
        each start.
    """
    return ChildStartLine(
        argv=[
            str(TRANSPORT_BINARY_PATH),
            TRANSPORT_COMMAND_HUB,
            "--config",
            str(generated_path()),
            "--key-dir",
            str(TRANSPORT_KEY_DIR),
        ],
        is_secret_on_stdin=True,
    )


def unit_argv() -> list:
    """How the Linux unit, and ``nhub run --only-transport``, start it."""
    return [
        str(TRANSPORT_BINARY_PATH),
        TRANSPORT_COMMAND_HUB,
        "--config",
        str(generated_path()),
        "--key-dir",
        str(TRANSPORT_KEY_DIR),
        "--secret-file",
        str(secret_path()),
    ]


class TransportApplier:
    """Makes the stored transport settings the ones that run."""

    def __init__(self, *, controller):
        """
        Args:
            controller: The process controller the hub runs its daemons with.
        """
        self._controller = controller

    def prepare(self) -> list:
        """Make the directories, the account and the secret the transport needs.

        Returns:
            What was made, as words for the log.

        Raises:
            OSError: When a directory or the secret cannot be written.
            subprocess.CalledProcessError: When the account cannot be made.
        """
        made = []
        if ensure_account():
            made.append("account")
        if ensure_key_dir():
            made.append("key directory")
        ensure_run_dir()
        if is_linux() and ensure_secret_file():
            made.append("secret")
        return made

    def apply(self, settings: dict, *, is_restarted: bool = False) -> str:
        """Render ``transport.json`` and run the transport on it.

        Args:
            settings: The panel's settings.
            is_restarted: Whether a running transport is started again anyway.

        Returns:
            ``transport_started`` or ``transport_restarted``, empty when
            nothing changed.

        Raises:
            OSError: If a file cannot be written.
            subprocess.SubprocessError: If the system refuses the unit.
        """
        self.prepare()
        rendered = render_settings(settings)
        path = generated_path()
        is_changed = self._write(path, rendered)
        if not TRANSPORT_BINARY_PATH.is_file():
            LOGGER.warning(
                "the transport is not installed at %s", TRANSPORT_BINARY_PATH
            )
            return ""
        status = self._controller.status(TRANSPORT_SERVICE_NAME)
        if not status.is_installed:
            return ""
        if not status.is_active:
            self._controller.control(TRANSPORT_SERVICE_NAME, "restart")
            return TRANSPORT_CHANGE_STARTED
        if is_changed or is_restarted:
            self._controller.control(TRANSPORT_SERVICE_NAME, "restart")
            return TRANSPORT_CHANGE_RESTARTED
        return ""

    def _write(self, path: Path, rendered: dict) -> bool:
        """Write the document when it differs from the file; the transport's
        account reads it."""
        text = json.dumps(rendered, indent=2, sort_keys=True) + "\n"
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
        write_generated(path, text, mode=TRANSPORT_GENERATED_MODE)
        return True


def probe(
    host: str, port: int, *, timeout_s: float = TRANSPORT_PROBE_TIMEOUT_S
) -> bool:
    """Whether an address reaches this hub, by a handshake under its key.

    Args:
        host: The address or name to dial.
        port: The port.
        timeout_s: How long the dial and the handshake may take.

    Returns:
        True when ``neutrino_transport probe`` completed message 2 under the
        hub's own public key within the time; False otherwise, and when the
        transport or its key is not there.
    """
    try:
        key = read_public_key()
    except (OSError, ValueError):
        return False
    if not TRANSPORT_BINARY_PATH.is_file():
        return False
    address = f"tcp://[{host}]:{port}" if ":" in host else f"tcp://{host}:{port}"
    try:
        result = subprocess.run(
            [
                str(TRANSPORT_BINARY_PATH),
                TRANSPORT_COMMAND_PROBE,
                "--key",
                key,
                address,
            ],
            capture_output=True,
            timeout=timeout_s + 2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def forget_key() -> None:
    """Delete the static key, for ``nhub reset all``; the transport makes a
    new pair at ``keys_reload``."""
    shutil.rmtree(TRANSPORT_KEY_DIR, ignore_errors=True)


def settings_or_empty() -> dict:
    """The panel's settings, empty when the box is not set up."""
    try:
        return read_config("web/settings.json")
    except (FileNotFoundError, ValueError):
        return {}


def _own_by_account(path: Path, mode: int) -> None:
    """Give one path to the transport's account, where it exists."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    if is_linux() and has_account():
        shutil.chown(path, user=TRANSPORT_ACCOUNT, group=TRANSPORT_ACCOUNT)


def _own_by_group(path: Path, mode: int) -> None:
    """Keep one path root's with the transport's group, where it exists."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    if is_linux() and has_account():
        shutil.chown(path, group=TRANSPORT_ACCOUNT)
