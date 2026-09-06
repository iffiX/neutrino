"""Sharing this machine's desktop, and reaching one that is shared.

Two halves of one type. **Share** is a decision made on the machine and
nowhere else: a person sets an access password, the agent configures
RustDesk for direct connection and declares the share upward, and every
other machine's Services shows it. **Connect** launches the local RustDesk
client at an address another machine declared.

The access password never leaves this machine. It is set into RustDesk,
which stores it salted, and kept in a root-only file beside the mount
credentials so a person can read back what they set — it enters neither the
service store nor any heartbeat, and the hub is never told it.

**A share is declared only once it answers.** Configuring is not sharing:
the handler probes the direct port and says ``starting`` until it opens.
macOS says ``waiting_for_approval`` instead, because screen recording there
takes one person at the machine allowing it in System Settings and no
amount of configuration substitutes for that.

Not pure: writes RustDesk's configuration, drives its service, and opens a
local socket to see whether it answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import socket
import subprocess
import time
import uuid

from neutrino_agent.modules import rustdesk
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.services.base import ServiceTypeHandler, find_entry

# The module a share cannot work without, named the way every other
# dependency is.
RDP_MODULE = "rustdesk"

RDP_ACTION_SHARE = "share"
RDP_ACTION_UNSHARE = "unshare"
RDP_ACTION_CONNECT = "connect"

# What sharing looks like from here. ``starting`` and ``waiting_for_approval``
# are the two ways a configured share is not yet answering.
RDP_STATE_NOT_SHARED = "not_shared"
RDP_STATE_SHARING = "sharing"
RDP_STATE_STARTING = "starting"
RDP_STATE_WAITING_APPROVAL = "waiting_for_approval"

# Where the access password is kept, mode 0600 under the agent's own root.
RDP_PASSWORD_FILE = "rdp_access_password"

# How long a probe of the direct port is believed. The page polls and the
# heartbeat reads, and neither wants a connect attempt each time.
RDP_PROBE_TTL_S = 3.0
RDP_PROBE_TIMEOUT_S = 1.0

RDP_PROBE_HOST = "127.0.0.1"


class RdpServiceHandler(ServiceTypeHandler):
    """Shares this machine's desktop, and opens a client at another's."""

    service_type = "rdp"

    def __init__(self, *, platform, store, credentials_dir: str, log=print):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`MachineServiceStore` holding the share record.
            credentials_dir: Where the access password file lives.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._store = store
        self._credentials_dir = credentials_dir
        self._log = log
        self._module_reader = None
        self._probed_at = 0.0
        self._is_answering = False

    def bind_modules(self, reader) -> None:
        """Say where the machine's module states are read from.

        Args:
            reader: Called with no arguments for the module report, so the
                share flow can refuse before it configures anything.
        """
        self._module_reader = reader

    def _module_states(self) -> dict:
        """What each module on this machine is, empty until that is bound."""
        return {} if self._module_reader is None else self._module_reader()

    def act(self, *, entries: list, account: str, is_privileged: bool, body: dict):
        """Share this desktop, stop sharing it, or open a client.

        Args:
            entries: The catalog's service list.
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            body: ``action`` plus that action's own fields.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        action = str(body.get("action", ""))
        if action == RDP_ACTION_CONNECT:
            return self._connect(entries, str(body.get("id", "")))
        # Sharing writes root-owned configuration and drives a system
        # service, and what it opens is the whole machine rather than one
        # account's files.
        if not is_privileged:
            return {"code": "control_scope_refused", "params": {}}
        if action == RDP_ACTION_SHARE:
            return self._share(account, str(body.get("password", "")))
        if action == RDP_ACTION_UNSHARE:
            return self._unshare()
        return {"code": "unknown_request", "params": {}}

    def state(self) -> dict:
        """What the page and the heartbeat read about this machine's share.

        Returns:
            ``{"rdp": {...}}`` — the state, the port, RustDesk's id, and
            the share id the declaration rides up under.
        """
        record = self._store.rdp_share()
        is_shared = bool(record.get("is_shared"))
        return {
            "rdp": {
                "is_shared": is_shared,
                "share_id": str(record.get("share_id", "")),
                "port": int(record.get("port") or rustdesk.RUSTDESK_DIRECT_PORT),
                "state": self._state(is_shared),
                "rustdesk_id": rustdesk.read_id(),
                "has_password": self._read_password() != "",
            }
        }

    def declaration(self) -> dict:
        """What the heartbeat carries up about this machine's share.

        Returns:
            ``{"is_shared", "share_id", "port"}``. ``is_shared`` is true
            only while the share actually answers, so a fleet list never
            offers a desktop that cannot be reached. The access password is
            not here and never crosses the wire.
        """
        record = self._store.rdp_share()
        is_shared = bool(record.get("is_shared"))
        return {
            "is_shared": is_shared and self._state(is_shared) == RDP_STATE_SHARING,
            "share_id": str(record.get("share_id", "")),
            "port": int(record.get("port") or rustdesk.RUSTDESK_DIRECT_PORT),
        }

    def reveal_password(self, *, is_privileged: bool) -> str:
        """The access password this machine shares with, for its owner.

        Args:
            is_privileged: Whether the caller holds the privileged scope.

        Returns:
            The password, empty for an ordinary caller or when none is set.
        """
        return self._read_password() if is_privileged else ""

    def _share(self, account: str, password: str):
        """Configure RustDesk for direct connection and declare the share."""
        if not password:
            return {"code": "rdp_password_missing", "params": {}}
        status = self._module_states().get(RDP_MODULE) or {}
        if status.get("state") != "installed":
            return {"code": "module_missing", "params": {"module": RDP_MODULE}}
        record = self._store.rdp_share()
        share_id = str(record.get("share_id", "")) or uuid.uuid4().hex
        try:
            self._configure(account, rustdesk.RUSTDESK_SHARE_OPTIONS)
            rustdesk.set_password(password)
        except InstallError as error:
            return {"code": "rdp_configure_failed", "params": {"detail": str(error)}}
        self._write_password(password)
        self._store.set_rdp_share(
            {
                "share_id": share_id,
                "is_shared": True,
                "port": rustdesk.RUSTDESK_DIRECT_PORT,
                # Whose session copy was written, so unsharing closes every
                # file sharing opened rather than only the service's own.
                "account": account,
            }
        )
        self._probed_at = 0.0
        return {}

    def _unshare(self):
        """Close the direct server, drop the record, and stop declaring."""
        closed = tuple(
            (key, value) if key != "direct-server" else (key, "N")
            for key, value in rustdesk.RUSTDESK_SHARE_OPTIONS
        )
        account = str(self._store.rdp_share().get("account", ""))
        try:
            self._configure(account, closed, is_restarted=False)
        except InstallError as error:
            return {"code": "rdp_configure_failed", "params": {"detail": str(error)}}
        self._store.clear_rdp_share()
        self._remove_password()
        self._probed_at = 0.0
        return {}

    def _configure(self, account: str, options: tuple, is_restarted: bool = True):
        """Write RustDesk's configuration everywhere it is read.

        The service is stopped first: it rewrites its own file as it exits,
        and a write underneath a running service is one it overwrites.

        Args:
            account: The account sitting at the machine, for the session's
                own copy; empty writes only the service's.
            options: The ``(key, value)`` pairs to set.
            is_restarted: Whether to bring the service back up afterwards.

        Raises:
            InstallError: If a file cannot be written.
        """
        rustdesk.control_service(rustdesk.RUSTDESK_ACTION_STOP)
        for path in rustdesk.config_paths(self._account_home(account)):
            rustdesk.write_config(path, options)
        if is_restarted:
            rustdesk.control_service(rustdesk.RUSTDESK_ACTION_START)

    def _account_home(self, account: str) -> str:
        """One account's home, empty when it cannot be resolved."""
        if not account:
            return ""
        try:
            return self._platform.account_home(account)
        except (KeyError, PlatformUnsupportedError):
            return ""

    def _state(self, is_shared: bool) -> str:
        """Where the share stands, by what the direct port actually does."""
        if not is_shared:
            return RDP_STATE_NOT_SHARED
        if self._answers():
            return RDP_STATE_SHARING
        if _is_darwin():
            # Screen recording on macOS is one person's allowance in System
            # Settings; nothing the agent does stands in for it.
            return RDP_STATE_WAITING_APPROVAL
        return RDP_STATE_STARTING

    def _answers(self) -> bool:
        """Whether the direct port is open, re-probed at most every few seconds."""
        now = time.monotonic()
        if now - self._probed_at <= RDP_PROBE_TTL_S:
            return self._is_answering
        port = int(self._store.rdp_share().get("port") or rustdesk.RUSTDESK_DIRECT_PORT)
        try:
            with socket.create_connection(
                (RDP_PROBE_HOST, port), timeout=RDP_PROBE_TIMEOUT_S
            ):
                self._is_answering = True
        except OSError:
            self._is_answering = False
        self._probed_at = now
        return self._is_answering

    def _connect(self, entries: list, entry_id: str):
        """Open the local RustDesk client at one shared desktop."""
        entry = find_entry(entries, self.service_type, entry_id)
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        binary = rustdesk.binary_path()
        if not binary:
            return {"code": "module_missing", "params": {"module": RDP_MODULE}}
        payload = entry.get("payload") or {}
        peer = connect_peer(
            str(payload.get("host", "")),
            int(payload.get("port") or rustdesk.RUSTDESK_DIRECT_PORT),
        )
        if not peer:
            return {"code": "rdp_no_address", "params": {}}
        try:
            subprocess.Popen(
                [binary, "--connect", peer],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return {"code": "rdp_launch_failed", "params": {"detail": str(error)}}
        return {}

    def _password_path(self) -> str:
        return os.path.join(self._credentials_dir, RDP_PASSWORD_FILE)

    def _read_password(self) -> str:
        try:
            with open(self._password_path(), "r", encoding="utf-8") as stream:
                return stream.read().strip()
        except OSError:
            return ""

    def _write_password(self, password: str) -> None:
        """Keep the access password where only root reads it."""
        path = self._password_path()
        try:
            os.makedirs(self._credentials_dir, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(password)
        except OSError as error:
            self._log(f"rdp: could not keep the access password: {error}")

    def _remove_password(self) -> None:
        try:
            os.unlink(self._password_path())
        except OSError:
            return


def connect_peer(host: str, port: int) -> str:
    """What the local client is told to connect to.

    RustDesk dials a bare address at its own default direct port, so a
    share on that port is named by address alone; a share on any other port
    is named ``host:port``, which the client's own domain-and-port path
    takes.

    Args:
        host: The address the sharing machine is reached at.
        port: The port its direct server answers on.

    Returns:
        The peer string, empty when there is no address to dial.
    """
    if not host:
        return ""
    if port == rustdesk.RUSTDESK_DIRECT_PORT:
        return host
    return f"{host}:{port}"


def _is_darwin() -> bool:
    """Whether this machine is macOS."""
    return os.uname().sysname == "Darwin" if hasattr(os, "uname") else False
