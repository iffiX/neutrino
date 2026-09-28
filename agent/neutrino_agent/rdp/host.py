"""Sharing this machine's desktop.

Which desktop is shared is decided on the machine: the agent configures
RustDesk for direct connection and declares the share upward, and every
other machine's fleet list shows it. The seat password a peer connects with
is the hub's — it arrives in the desired state, is set into RustDesk salted
whenever it changed, and is kept in a root-only file so the machine knows
what it already set. It enters neither the store nor any heartbeat.

**A machine with no desktop is refused before anything is configured.**
RustDesk on a box with no graphical session answers nothing, and the share
says so rather than passing the connection refusal on raw.

**A share is declared only once it answers.** Configuring is not sharing:
the share probes the direct port and says ``starting`` until it opens.

Who is at the screen, how many peers are connected, and what a peer would
wait on are each platform's own, read through the seat
(:func:`~neutrino_agent.rdp.seat.seat_for`).

Not pure: writes RustDesk's configuration, drives its service, and opens a
local socket to see whether it answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import socket
import time
import uuid

from neutrino_agent.exceptions import InstallError, PlatformUnsupportedError
from neutrino_agent.modules import rustdesk
from neutrino_agent.rdp.constants import (
    RDP_ATTENTION_NOBODY_SEATED,
    RDP_ATTENTION_TTL_S,
    RDP_GREETER_ACCOUNTS,
    RDP_MODULE_NAME,
    RDP_PASSWORD_FILE,
    RDP_PROBE_HOST,
    RDP_PROBE_TIMEOUT_S,
    RDP_PROBE_TTL_S,
    RDP_STATE_NOT_SHARED,
    RDP_STATE_SHARING,
    RDP_STATE_STARTING,
)
from neutrino_agent.rdp.seat import seat_for


def closed_options() -> tuple:
    """The share configuration with the direct server shut again.

    Returns:
        The ``(key, value)`` pairs to write.
    """
    return tuple(
        (key, value) if key != "direct-server" else (key, "N")
        for key, value in rustdesk.RUSTDESK_SHARE_OPTIONS
    )


class RdpShareHost:
    """Shares this machine's desktop, and says where the share stands."""

    def __init__(self, *, platform, store, credentials_dir: str, log=print, seat=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`MachineStateStore` holding the share record.
            credentials_dir: Where the seat password file lives.
            log: Callable used for progress messages.
            seat: Who is at the screen and what a peer would wait on; None
                is the platform's own.
        """
        self._platform = platform
        self._seat = seat if seat is not None else seat_for(platform.os_name)
        self._store = store
        self._credentials_dir = credentials_dir
        self._log = log
        self._module_reader = None
        self._probed_at = 0.0
        self._is_answering = False
        self._attention_at = 0.0
        self._attention = ""

    def bind_modules(self, reader) -> None:
        """Say where the machine's module states are read from.

        Args:
            reader: Called with no arguments for the module report, so the
                share flow can refuse before it configures anything.
        """
        self._module_reader = reader

    def share(self, account: str) -> dict:
        """Configure RustDesk for direct connection and declare the share.

        A machine shares one seat at a time: naming another account closes
        the copy the previous one was shared through.

        Args:
            account: The account sitting at the machine's screen.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if not account:
            return {"code": "rdp_no_seat", "params": {}}
        status = self._module_states().get(RDP_MODULE_NAME) or {}
        if status.get("state") != "installed":
            return {"code": "module_missing", "params": {"module": RDP_MODULE_NAME}}
        if not self._seat.has_desktop_session():
            return {"code": "rdp_no_desktop", "params": {}}
        refusal = self._seat_refusal(account)
        if refusal:
            return refusal
        record = self._store.rdp_share()
        share_id = str(record.get("share_id", "")) or uuid.uuid4().hex
        replaced = str(record.get("account", "") or "")
        try:
            if replaced and replaced != account:
                self._configure(replaced, closed_options(), is_restarted=False)
            self._configure(account, rustdesk.RUSTDESK_SHARE_OPTIONS)
            seat_password = self._read_password()
            if seat_password:
                rustdesk.set_password(seat_password)
        except InstallError as error:
            return {"code": "rdp_configure_failed", "params": {"detail": str(error)}}
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

    def unshare(self) -> dict:
        """Close the direct server, drop the record, and stop declaring.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        account = str(self._store.rdp_share().get("account", ""))
        try:
            self._configure(account, closed_options(), is_restarted=False)
        except InstallError as error:
            return {"code": "rdp_configure_failed", "params": {"detail": str(error)}}
        self._store.clear_rdp_share()
        self._probed_at = 0.0
        return {}

    def apply_baseline(self) -> None:
        """Point RustDesk at the LAN and nothing else, wherever it reads.

        A service already running reads its configuration once, so a
        baseline that changed anything is followed by a restart. Best
        effort: a machine that cannot take the write still runs.
        """
        is_changed = False
        for path in rustdesk.config_paths(""):
            try:
                if rustdesk.write_config(path, rustdesk.RUSTDESK_BASE_OPTIONS):
                    is_changed = True
            except InstallError as error:
                self._log(f"rdp: {error}")
        if not is_changed:
            return
        try:
            rustdesk.control_service(rustdesk.RUSTDESK_ACTION_RESTART)
        except InstallError as error:
            self._log(f"rdp: {error}")

    def apply_seat_password(self, password: str) -> dict:
        """Set the seat password the hub holds, when it is not the one set.

        RustDesk stores it salted, so the root-only file beside the store is
        the only record of what this machine already set.

        Args:
            password: The seat password from the desired state.

        Returns:
            Empty when it took or there was nothing to do,
            ``{"code", "params"}`` when RustDesk refused it.
        """
        if not password or password == self._read_password():
            return {}
        try:
            rustdesk.set_password(password)
        except InstallError as error:
            return {"code": "rdp_password_refused", "params": {"detail": str(error)}}
        self._write_password(password)
        return {}

    def state(self) -> dict:
        """What the control channel reads about this machine's share.

        Returns:
            ``{"is_shared", "state", "port", "account", "attention",
            "rustdesk_id", "has_password"}``. The seat password itself is
            in none of it.
        """
        record = self._store.rdp_share()
        is_shared = bool(record.get("is_shared"))
        account = str(record.get("account", ""))
        return {
            "is_shared": is_shared,
            "state": self._state(is_shared),
            "port": int(record.get("port") or rustdesk.RUSTDESK_DIRECT_PORT),
            "account": account,
            "attention": self.attention(account) if is_shared else "",
            "rustdesk_id": rustdesk.read_id(),
            "has_password": self._read_password() != "",
        }

    def declaration(self) -> dict:
        """What the heartbeat carries up about this machine's share.

        Returns:
            ``{"is_shared", "account", "share_id", "port", "attention",
            "connected_count"}``. ``is_shared`` is true only while the share
            actually answers, so a fleet list never offers a desktop that
            cannot be reached; ``attention`` names what a peer would wait on
            if it dialed now. The seat password is in none of it and never
            crosses the wire.
        """
        record = self._store.rdp_share()
        is_shared = bool(record.get("is_shared"))
        port = int(record.get("port") or rustdesk.RUSTDESK_DIRECT_PORT)
        return {
            "is_shared": is_shared and self._state(is_shared) == RDP_STATE_SHARING,
            "account": str(record.get("account", "") or ""),
            "share_id": str(record.get("share_id", "")),
            "port": port,
            # Only a share has anything for a peer to wait on, and only a
            # sharing machine should pay for asking.
            "attention": (
                self.attention(str(record.get("account", ""))) if is_shared else ""
            ),
            "connected_count": self._seat.connected_count(port) if is_shared else 0,
        }

    def attention(self, account: str) -> str:
        """What somebody has to do at this machine before a peer sees it.

        Wayland hands screen capture out through a dialog on the shared
        machine's own screen, and a Mac through two permissions granted in
        its settings. Until then a peer that dials waits on something it
        cannot see.

        Believed for :data:`RDP_ATTENTION_TTL_S`: the heartbeat asks every
        few seconds and the answer costs the session table and a file.

        Args:
            account: The account the share is for.

        Returns:
            A typed code, empty when a peer would be shown the desktop.
        """
        now = time.monotonic()
        if now - self._attention_at < RDP_ATTENTION_TTL_S:
            return self._attention
        self._attention = self._read_attention(account)
        self._attention_at = now
        return self._attention

    def _module_states(self) -> dict:
        """What each module on this machine is, empty until that is bound."""
        return {} if self._module_reader is None else self._module_reader()

    def _read_attention(self, account: str) -> str:
        """Ask the machine what a peer would wait on, without the cache."""
        seated = self._seat.graphical_accounts()
        if seated is not None and not seated:
            return RDP_ATTENTION_NOBODY_SEATED
        if account and account.split("@")[0] in RDP_GREETER_ACCOUNTS:
            return RDP_ATTENTION_NOBODY_SEATED
        return self._seat.screen_attention(self._account_home(account))

    def _seat_refusal(self, account: str) -> dict:
        """Why one account's desktop cannot be shared, empty when it can.

        The seat decides what a peer is shown — RustDesk's service spawns
        its screen server into the signed-in session, whoever asked for the
        share — so the account a share names must be the one at the screen.
        Where the machine cannot say who that is, the account only has to
        exist.

        Args:
            account: The account the share names.

        Returns:
            Empty when the account can be shared, ``{"code", "params"}``
            when it cannot.
        """
        seated = self._seat.graphical_accounts()
        if seated is not None:
            if account in seated:
                return {}
            return {"code": "rdp_wrong_seat", "params": {"account": account}}
        if account in self._human_accounts():
            return {}
        return {"code": "no_target_user", "params": {}}

    def _human_accounts(self) -> list:
        """The machine's human accounts, empty when it cannot be asked."""
        try:
            return self._platform.human_accounts()
        except PlatformUnsupportedError:
            return []

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
        return RDP_STATE_SHARING if self._answers() else RDP_STATE_STARTING

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

    def _password_path(self) -> str:
        return os.path.join(self._credentials_dir, RDP_PASSWORD_FILE)

    def _read_password(self) -> str:
        try:
            with open(self._password_path(), "r", encoding="utf-8") as stream:
                return stream.read().strip()
        except OSError:
            return ""

    def _write_password(self, password: str) -> None:
        """Keep the seat password where only root reads it."""
        path = self._password_path()
        try:
            os.makedirs(self._credentials_dir, exist_ok=True)
            os.chmod(self._credentials_dir, 0o700)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(password)
        except OSError as error:
            self._log(f"rdp: could not keep the seat password: {error}")
