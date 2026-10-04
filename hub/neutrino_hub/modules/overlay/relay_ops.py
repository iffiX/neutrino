"""Running the relay's ssh, and reading where it stands.

The applier makes the stored relay true: the key file from the vault, the
start line, and the process under the controller's name ``relay``, which is
the unit ``neutrino_hub_relay.service`` on Linux and a child of the hub's
service on macOS and Windows. The monitor reads the process every second
and checks the public address from outside, and its view is the relay's
state. Neither ever prints the key.
"""

import base64
import datetime
import hashlib
import os
import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import asyncssh

from neutrino_hub.exceptions import KeyMaterialError, VaultLockedError
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.constants import DEVICE_KEY_ERROR_UNREADABLE
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_RELAY_CHANGE_STARTED,
    OVERLAY_RELAY_CHANGE_STOPPED,
    OVERLAY_RELAY_CHECK_FIRST_S,
    OVERLAY_RELAY_CHECK_FOREIGN,
    OVERLAY_RELAY_CHECK_INTERVAL_S,
    OVERLAY_RELAY_CHECK_NO_ANSWER,
    OVERLAY_RELAY_CHECK_TIMEOUT_S,
    OVERLAY_RELAY_DIR_MODE,
    OVERLAY_RELAY_DIR_NAME,
    OVERLAY_RELAY_FILE_MODE,
    OVERLAY_RELAY_KEY_NAME,
    OVERLAY_RELAY_KNOWN_HOSTS_NAME,
    OVERLAY_RELAY_LOG_LINES,
    OVERLAY_RELAY_SERVICE_NAME,
    OVERLAY_RELAY_SSH_NAME,
    OVERLAY_RELAY_STATE_CONNECTED,
    OVERLAY_RELAY_STATE_CONNECTING,
    OVERLAY_RELAY_STATE_DISABLED,
    OVERLAY_RELAY_STATE_NOT_CONFIGURED,
    OVERLAY_RELAY_STATE_PORT_CLOSED,
    OVERLAY_RELAY_STATE_VAULT_LOCKED,
    OVERLAY_RELAY_TICK_S,
    OVERLAY_RELAY_UNIT,
    OVERLAY_RELAY_WINDOWS_ROOT_DEFAULT,
    OVERLAY_RELAY_WINDOWS_ROOT_ENV,
    OVERLAY_RELAY_WINDOWS_SSH,
)
from neutrino_hub.modules.overlay.relay_config import OverlayRelayConfig, read_relay
from neutrino_hub.modules.overlay.relay_renderer import (
    OverlayRelayRenderer,
    judge_exit,
)
from neutrino_hub.platforms.constants import PLATFORM_OS_WINDOWS
from neutrino_hub.platforms.detect import hub_os, is_linux
from neutrino_hub.system.constants import (
    SYSTEM_SERVICES_STATE_PATH,
    SYSTEM_START_LINE_DROPIN_NAME,
    SYSTEM_SYSTEMD_DIR,
)
from neutrino_hub.system.process_control import read_services_state
from neutrino_hub.system.systemd_ctl import start_line_dropin
from neutrino_hub.utils.constants import (
    UTILS_DATA_DIR,
    UTILS_STATE_ROOT,
    is_dev_root_set,
)
from neutrino_hub.utils.json_file import write_generated

# One apply at a time, each on the file as it stands when it runs.
OVERLAY_RELAY_APPLY_LOCK = threading.Lock()


def relay_dir() -> Path:
    """The directory holding what the relay's ssh reads."""
    return UTILS_STATE_ROOT / OVERLAY_RELAY_DIR_NAME


def key_path() -> Path:
    """The key file the relay's ssh is given."""
    return relay_dir() / OVERLAY_RELAY_KEY_NAME


def known_hosts_path() -> Path:
    """The file ssh records the server's host key in."""
    return relay_dir() / OVERLAY_RELAY_KNOWN_HOSTS_NAME


def ssh_path() -> str:
    """Where the system's OpenSSH client is.

    Returns:
        Its absolute path; empty when this machine has none.
    """
    if hub_os() == PLATFORM_OS_WINDOWS:
        root = os.environ.get(
            OVERLAY_RELAY_WINDOWS_ROOT_ENV, OVERLAY_RELAY_WINDOWS_ROOT_DEFAULT
        )
        path = Path(root).joinpath(*OVERLAY_RELAY_WINDOWS_SSH)
        return str(path) if path.is_file() else ""
    return shutil.which(OVERLAY_RELAY_SSH_NAME) or ""


def forget_host_key() -> bool:
    """Delete the recorded host key.

    Returns:
        Whether one was recorded.
    """
    try:
        known_hosts_path().unlink()
    except FileNotFoundError:
        return False
    return True


def host_key_fingerprint() -> str:
    """The recorded host key's fingerprint, in OpenSSH's own form.

    Returns:
        ``SHA256:<base64>`` of the first key the file holds; empty when none
        is recorded or the file cannot be read.
    """
    try:
        text = known_hosts_path().read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        words = line.split()
        if len(words) < 3 or line.startswith("#"):
            continue
        try:
            blob = base64.b64decode(words[2], validate=True)
        except ValueError:
            continue
        digest = base64.b64encode(hashlib.sha256(blob).digest()).decode()
        return f"SHA256:{digest.rstrip('=')}"
    return ""


def is_key_stored(key_id: str) -> bool:
    """Whether the vault holds an SSH key under this id.

    Args:
        key_id: The key's id.

    Returns:
        True when it does.
    """
    if not key_id:
        return False
    try:
        return KeyRegistry().has_key(key_id)
    except (OSError, ValueError):
        return False


def is_relay_configured(config: OverlayRelayConfig) -> bool:
    """Whether the relay names a host, an account and a key the vault holds.

    Args:
        config: The stored relay.

    Returns:
        True when it does.
    """
    return config.has_settings and is_key_stored(config.key_id)


def openssh_key_text(key_id: str) -> str:
    """One stored key in OpenSSH form, without its passphrase.

    Args:
        key_id: The key's id.

    Returns:
        The private key text ssh reads.

    Raises:
        VaultLockedError: If the vault cannot be opened.
        KeyMaterialError: If the key is not there or does not open.
    """
    text, passphrase = KeyRegistry().material_for(key_id)
    try:
        loaded = asyncssh.import_private_key(text, passphrase=passphrase)
    except (asyncssh.KeyImportError, asyncssh.KeyEncryptionError) as error:
        raise KeyMaterialError(
            DEVICE_KEY_ERROR_UNREADABLE, {"detail": str(error)}
        ) from error
    return loaded.export_private_key("openssh").decode()


def check_public_address(host: str, port: int, *, timeout_s: float) -> str:
    """Complete a TLS handshake at the public address and read its certificate.

    Args:
        host: The server's name or address.
        port: The public port.
        timeout_s: How long the dial and the handshake may take together.

    Returns:
        The SHA-256 hex of the certificate met there; empty when nothing
        answered with one in time.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout_s) as raw:
            raw.settimeout(timeout_s)
            with context.wrap_socket(raw, server_hostname=host) as wrapped:
                der = wrapped.getpeercert(binary_form=True)
    except (OSError, ValueError):
        return ""
    return hashlib.sha256(der).hexdigest() if der else ""


class OverlayRelayApplier:
    """Makes the stored relay the one that runs."""

    def __init__(self, *, controller, agent_port: int):
        """
        Args:
            controller: The process controller the hub runs its daemons with.
            agent_port: The port the agent channel listens on.
        """
        self._controller = controller
        self._agent_port = agent_port

    def apply(self, config: OverlayRelayConfig, *, is_restarted: bool = False) -> str:
        """Run the relay when it is on and configured, and stop it otherwise.

        Nothing is restarted when the key file and the start line are what
        the configuration renders and the process runs, unless asked.

        Args:
            config: The stored relay.
            is_restarted: Whether a running relay is started again anyway.

        Returns:
            ``relay_started`` or ``relay_stopped`` for what changed, empty
            when nothing did.

        Raises:
            OSError: If a file cannot be written.
            subprocess.CalledProcessError: If the system refuses the unit.
        """
        with OVERLAY_RELAY_APPLY_LOCK:
            program = ssh_path()
            if not (config.is_enabled and program and is_relay_configured(config)):
                return self._stop()
            try:
                key_text = openssh_key_text(config.key_id)
            except VaultLockedError:
                if key_path().is_file():
                    return ""
                return self._stop()
            except KeyMaterialError:
                return self._stop()
            argv = OverlayRelayRenderer(
                ssh_path=program,
                key_path=str(key_path()),
                known_hosts_path=str(known_hosts_path()),
                agent_port=self._agent_port,
            ).render(config)
            is_changed = self._write_key(key_text)
            if not self._is_start_line_current(argv):
                is_changed = True
            if not self._is_unit_owned():
                return ""
            if not is_changed and not is_restarted and self._is_running():
                return ""
            self._start(argv)
            return OVERLAY_RELAY_CHANGE_STARTED

    def _write_key(self, text: str) -> bool:
        """Write the key file root-only, telling whether it changed.

        The file is kept when it holds the same key: OpenSSH's form carries
        a random check number, so two writes of one key differ as text.
        """
        path = key_path()
        relay_dir().mkdir(mode=OVERLAY_RELAY_DIR_MODE, parents=True, exist_ok=True)
        wanted = asyncssh.import_private_key(text).get_fingerprint()
        try:
            held = asyncssh.import_private_key(path.read_text(encoding="utf-8"))
            if held.get_fingerprint() == wanted:
                return False
        except (OSError, asyncssh.KeyImportError):
            pass
        write_generated(path, text, mode=OVERLAY_RELAY_FILE_MODE)
        return True

    def _start(self, argv: list) -> None:
        """Hand the start line over and run the process on it."""
        if is_linux():
            self._refresh_unit()
        self._controller.set_start_line(OVERLAY_RELAY_SERVICE_NAME, argv, {}, None)
        if self._controller.is_enabled(OVERLAY_RELAY_SERVICE_NAME):
            self._controller.restart(OVERLAY_RELAY_SERVICE_NAME)
            return
        self._controller.enable(OVERLAY_RELAY_SERVICE_NAME)
        if is_linux():
            self._controller.restart(OVERLAY_RELAY_SERVICE_NAME)

    def _stop(self) -> str:
        """Stop the process, forget its start line and delete the key file."""
        note = ""
        if self._is_unit_owned() and self._is_standing():
            try:
                self._controller.stop(OVERLAY_RELAY_SERVICE_NAME)
            except (RuntimeError, subprocess.SubprocessError, KeyError):
                pass
            self._controller.disable(OVERLAY_RELAY_SERVICE_NAME)
            self._controller.set_start_line(OVERLAY_RELAY_SERVICE_NAME, None, {}, None)
            note = OVERLAY_RELAY_CHANGE_STOPPED
        key_path().unlink(missing_ok=True)
        return note

    def _is_standing(self) -> bool:
        """Whether the relay runs or would start with the machine."""
        try:
            status = self._controller.status(OVERLAY_RELAY_SERVICE_NAME)
        except (KeyError, OSError):
            return False
        return status.is_active or status.is_enabled

    def _is_running(self) -> bool:
        """Whether the relay's process runs now."""
        try:
            return self._controller.is_active(OVERLAY_RELAY_SERVICE_NAME)
        except (KeyError, OSError):
            return False

    def _is_start_line_current(self, argv: list) -> bool:
        """Whether the held start line is this one."""
        if not is_linux():
            held = read_services_state(SYSTEM_SERVICES_STATE_PATH)["start_lines"]
            line = held.get(OVERLAY_RELAY_SERVICE_NAME) or {}
            return line.get("argv") == argv
        path = SYSTEM_SYSTEMD_DIR / f"{OVERLAY_RELAY_UNIT}.d"
        try:
            text = (path / SYSTEM_START_LINE_DROPIN_NAME).read_text(encoding="utf-8")
        except OSError:
            return False
        return text == start_line_dropin(argv, {}, None)

    def _is_unit_owned(self) -> bool:
        """Whether this hub drives the relay's process; a development root
        on Linux drives no units."""
        return not (is_linux() and is_dev_root_set())

    def _refresh_unit(self) -> None:
        """Install or update the relay's unit."""
        text = (UTILS_DATA_DIR / "services" / OVERLAY_RELAY_UNIT).read_text(
            encoding="utf-8"
        )
        path = SYSTEM_SYSTEMD_DIR / OVERLAY_RELAY_UNIT
        try:
            if path.read_text(encoding="utf-8") == text:
                return
        except OSError:
            pass
        path.write_text(text, encoding="utf-8")
        self._controller.reload()


class OverlayRelayMonitor:
    """Reads the relay's process and checks its public address.

    One thread ticks every ``OVERLAY_RELAY_TICK_S``. A process with a new id
    is a new run: its first check comes ``OVERLAY_RELAY_CHECK_FIRST_S``
    after it is seen and the next ones every
    ``OVERLAY_RELAY_CHECK_INTERVAL_S``.
    """

    def __init__(
        self,
        *,
        controller,
        fingerprint_of: Callable[[], str],
        check=check_public_address,
        clock=time.monotonic,
    ):
        """
        Args:
            controller: The process controller the hub runs its daemons with.
            fingerprint_of: Returns the hub's own agent certificate's
                SHA-256 hex.
            check: ``check(host, port, timeout_s=...)`` returns the
                fingerprint met at the public address, empty for none.
            clock: The monotonic clock.
        """
        self._controller = controller
        self._fingerprint_of = fingerprint_of
        self._check = check
        self._clock = clock
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._process_id = 0
        self._started_at = 0.0
        self._checked_at = 0.0
        self._checked_at_text = ""
        # None before the first check of a run; then whether it met the
        # hub's own certificate.
        self._is_check_matched: "bool | None" = None
        self._check_error = ""

    def start(self) -> None:
        """Tick on a thread of its own until :meth:`stop`."""
        threading.Thread(target=self._run, name="relay_monitor", daemon=True).start()

    def stop(self) -> None:
        """End the thread."""
        self._stopping.set()

    def restart_checks(self) -> None:
        """Forget the last check; the next run is checked afresh."""
        with self._lock:
            self._process_id = 0
            self._is_check_matched = None
            self._check_error = ""

    def tick(self) -> None:
        """Read the process once, and check the public address when due."""
        config = read_relay()
        process_id = self._read_process_id()
        now = self._clock()
        with self._lock:
            if process_id and process_id != self._process_id:
                self._started_at = now
                self._is_check_matched = None
                self._check_error = ""
            self._process_id = process_id
            is_due = bool(process_id) and (
                (
                    self._is_check_matched is None
                    and now - self._started_at >= OVERLAY_RELAY_CHECK_FIRST_S
                )
                or (
                    self._is_check_matched is not None
                    and now - self._checked_at >= OVERLAY_RELAY_CHECK_INTERVAL_S
                )
            )
        if not is_due or not config.host:
            return
        self._run_check(config)

    def view(self) -> dict:
        """Where the relay stands now.

        Returns:
            ``{state, last_error, host_key_fingerprint, checked_at}``.
        """
        config = read_relay()
        state, last_error = self._state(config)
        with self._lock:
            checked_at = self._checked_at_text
        return {
            "state": state,
            "last_error": last_error,
            "host_key_fingerprint": host_key_fingerprint(),
            "checked_at": checked_at,
        }

    def _state(self, config: OverlayRelayConfig) -> tuple:
        """The state code and its last error."""
        if not config.is_enabled:
            return OVERLAY_RELAY_STATE_DISABLED, ""
        if not is_relay_configured(config):
            return OVERLAY_RELAY_STATE_NOT_CONFIGURED, ""
        if not key_path().is_file():
            try:
                is_locked = SecretVault().is_locked()
            except (OSError, ValueError):
                is_locked = False
            if is_locked:
                return OVERLAY_RELAY_STATE_VAULT_LOCKED, ""
        process_id = self._read_process_id()
        with self._lock:
            is_same_run = process_id and process_id == self._process_id
            matched = self._is_check_matched if is_same_run else None
            error = self._check_error
        if process_id:
            if matched is None:
                return OVERLAY_RELAY_STATE_CONNECTING, ""
            if matched:
                return OVERLAY_RELAY_STATE_CONNECTED, ""
            return OVERLAY_RELAY_STATE_PORT_CLOSED, error
        try:
            lines = self._controller.run_output(
                OVERLAY_RELAY_SERVICE_NAME, line_count=OVERLAY_RELAY_LOG_LINES
            )
        except (KeyError, OSError):
            lines = []
        if not lines:
            return OVERLAY_RELAY_STATE_CONNECTING, ""
        return judge_exit(lines)

    def _run_check(self, config: OverlayRelayConfig) -> None:
        """Dial the public address and compare what answers with the hub."""
        address = f"{config.host}:{config.public_port}"
        met = self._check(
            config.host, config.public_port, timeout_s=OVERLAY_RELAY_CHECK_TIMEOUT_S
        )
        try:
            own = self._fingerprint_of()
        except (OSError, ValueError):
            own = ""
        if not met:
            error = OVERLAY_RELAY_CHECK_NO_ANSWER.format(address=address)
        elif met != own:
            error = OVERLAY_RELAY_CHECK_FOREIGN.format(address=address)
        else:
            error = ""
        with self._lock:
            self._checked_at = self._clock()
            self._checked_at_text = (
                datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
            self._is_check_matched = not error
            self._check_error = error

    def _read_process_id(self) -> int:
        """The relay's process id now, 0 when none runs."""
        try:
            return self._controller.process_id(OVERLAY_RELAY_SERVICE_NAME)
        except (KeyError, OSError, NotImplementedError):
            return 0

    def _run(self) -> None:
        """Tick until stopped; a tick that fails waits for the next."""
        while not self._stopping.wait(OVERLAY_RELAY_TICK_S):
            try:
                self.tick()
            except (OSError, ValueError, RuntimeError):
                continue
