"""Sharing this machine's desktop.

Sharing is decided on the machine and nowhere else: a person sets an access
password, the agent configures RustDesk for direct connection and declares
the share upward, and every other machine's fleet list shows it. The access
password travels only inside the one ask that sets it, is set into RustDesk
salted, and is kept in a root-only file so the owner can read back what they
set. It enters neither the store nor any heartbeat.

**A machine with no desktop is refused before anything is configured.**
RustDesk on a box with no graphical session answers nothing, and the share
says so rather than passing the connection refusal on raw.

**A share is declared only once it answers.** Configuring is not sharing:
the share probes the direct port and says ``starting`` until it opens.

Not pure: writes RustDesk's configuration, drives its service, and opens a
local socket to see whether it answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import pwd
import socket
import subprocess
import time
import uuid

from neutrino_agent.modules import rustdesk
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.rdp.constants import (
    RDP_ATTENTION_NOBODY_SEATED,
    RDP_ATTENTION_SCREEN_NOT_ALLOWED,
    RDP_ATTENTION_TTL_S,
    RDP_GRAPHICAL_SESSION_TYPES,
    RDP_GREETER_ACCOUNTS,
    RDP_MODULE_NAME,
    RDP_PASSWORD_FILE,
    RDP_PROBE_HOST,
    RDP_PROBE_TIMEOUT_S,
    RDP_PROBE_TTL_S,
    RDP_PROC_DIR,
    RDP_SESSION_ENVIRONMENT_KEYS,
    RDP_SESSION_TIMEOUT_S,
    RDP_STATE_NOT_SHARED,
    RDP_STATE_SHARING,
    RDP_STATE_STARTING,
    RDP_WAYLAND_TOKEN_OPTION,
)


def session_environment(account: str) -> "dict | None":
    """One seated account's display environment, off its own processes.

    Args:
        account: The seated account.

    Returns:
        The display variables, or None when no process of that account
        carries a display.
    """
    try:
        uid = pwd.getpwnam(account).pw_uid
    except KeyError:
        return None
    try:
        pids = sorted((p for p in os.listdir(RDP_PROC_DIR) if p.isdigit()), key=int)
    except OSError:
        return None
    for pid in pids:
        path = os.path.join(RDP_PROC_DIR, pid)
        try:
            if os.stat(path).st_uid != uid:
                continue
            with open(os.path.join(path, "environ"), "rb") as stream:
                raw = stream.read()
        except OSError:
            continue
        pairs = dict(
            item.split("=", 1)
            for item in raw.decode("utf-8", "replace").split("\0")
            if "=" in item
        )
        if not (pairs.get("DISPLAY") or pairs.get("WAYLAND_DISPLAY")):
            continue
        return {key: pairs[key] for key in RDP_SESSION_ENVIRONMENT_KEYS if key in pairs}
    return None


def has_desktop_session() -> bool:
    """Whether this machine has a desktop for RustDesk to share.

    Returns:
        True on a machine that cannot be asked, so only one that positively
        has no graphical session is refused.
    """
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    seated = graphical_accounts()
    return True if seated is None else bool(seated)


def graphical_accounts() -> "list | None":
    """The accounts signed in at this machine's screen.

    ``loginctl`` lists each session with its owner, and answers the type of
    every session it is asked about in the order it was asked.

    Returns:
        The owning accounts of the graphical sessions, or None on a box
        without ``loginctl``, which says nothing at all.
    """
    listed = _loginctl(["list-sessions", "--no-legend"])
    if listed is None:
        return None
    rows = [line.split() for line in listed.splitlines() if line.split()]
    if not rows:
        return []
    sessions = [row[0] for row in rows]
    owners = {row[0]: row[2] for row in rows if len(row) > 2}
    shown = _loginctl(["show-session", "--property=Type"] + sessions)
    if shown is None:
        return None
    types = [
        line.strip()[len("Type=") :]
        for line in shown.splitlines()
        if line.strip().startswith("Type=")
    ]
    named = []
    for session, kind in zip(sessions, types):
        owner = owners.get(session, "")
        if kind in RDP_GRAPHICAL_SESSION_TYPES and owner and owner not in named:
            named.append(owner)
    return named


def _loginctl(arguments: list):
    """What ``loginctl`` printed, or None when this machine cannot be asked."""
    try:
        result = subprocess.run(
            ["loginctl"] + arguments,
            capture_output=True,
            text=True,
            timeout=RDP_SESSION_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _session_types() -> list:
    """The types of this machine's graphical sessions.

    Returns:
        The types, empty where none is graphical or the machine cannot be
        asked.
    """
    listed = _loginctl(["list-sessions", "--no-legend"])
    if listed is None:
        return []
    sessions = [line.split()[0] for line in listed.splitlines() if line.split()]
    if not sessions:
        return []
    shown = _loginctl(["show-session", "--property=Type"] + sessions)
    if shown is None:
        return []
    return [
        line.strip()[len("Type=") :]
        for line in shown.splitlines()
        if line.strip().startswith("Type=")
        and line.strip()[len("Type=") :] in RDP_GRAPHICAL_SESSION_TYPES
    ]


class RdpShareHost:
    """Shares this machine's desktop, and says where the share stands."""

    def __init__(self, *, platform, store, credentials_dir: str, log=print):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`MachineStateStore` holding the share record.
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
        self._attention_at = 0.0
        self._attention = ""

    def bind_modules(self, reader) -> None:
        """Say where the machine's module states are read from.

        Args:
            reader: Called with no arguments for the module report, so the
                share flow can refuse before it configures anything.
        """
        self._module_reader = reader

    def share(self, account: str, password: str) -> dict:
        """Configure RustDesk for direct connection and declare the share.

        Args:
            account: The account sitting at the machine's screen.
            password: The access password a peer connects with.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if not account:
            return {"code": "rdp_no_seat", "params": {}}
        if not password:
            return {"code": "rdp_password_missing", "params": {}}
        status = self._module_states().get(RDP_MODULE_NAME) or {}
        if status.get("state") != "installed":
            return {"code": "module_missing", "params": {"module": RDP_MODULE_NAME}}
        if not has_desktop_session():
            return {"code": "rdp_no_desktop", "params": {}}
        refusal = self._seat_refusal(account)
        if refusal:
            return refusal
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

    def unshare(self) -> dict:
        """Close the direct server, drop the record, and stop declaring.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
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

    def state(self) -> dict:
        """What the control channel reads about this machine's share.

        Returns:
            ``{"is_shared", "state", "port", "account", "attention",
            "rustdesk_id", "has_password"}``. The access password itself is
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
            ``{"is_shared", "account", "share_id", "port", "attention"}``.
            ``is_shared`` is true only while the share actually answers, so
            a fleet list never offers a desktop that cannot be reached;
            ``attention`` names what a peer would wait on if it dialed now.
            The access password is in none of it and never crosses the wire.
        """
        record = self._store.rdp_share()
        is_shared = bool(record.get("is_shared"))
        return {
            "is_shared": is_shared and self._state(is_shared) == RDP_STATE_SHARING,
            "account": str(record.get("account", "") or ""),
            "share_id": str(record.get("share_id", "")),
            "port": int(record.get("port") or rustdesk.RUSTDESK_DIRECT_PORT),
            # Only a share has anything for a peer to wait on, and only a
            # sharing machine should pay for asking.
            "attention": (
                self.attention(str(record.get("account", ""))) if is_shared else ""
            ),
        }

    def attention(self, account: str) -> str:
        """What somebody has to do at this machine before a peer sees it.

        Wayland hands screen capture out through a dialog on the shared
        machine's own screen. RustDesk remembers the answer, so this is
        once per person; until then a peer that dials waits on a dialog it
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
        seated = graphical_accounts()
        if seated is not None and not seated:
            return RDP_ATTENTION_NOBODY_SEATED
        if account and account.split("@")[0] in RDP_GREETER_ACCOUNTS:
            return RDP_ATTENTION_NOBODY_SEATED
        if not self._is_wayland_seat():
            return ""
        home = self._account_home(account)
        if self._has_wayland_permission(home):
            return ""
        return RDP_ATTENTION_SCREEN_NOT_ALLOWED

    @staticmethod
    def _is_wayland_seat() -> bool:
        """Whether this machine's screen is handed out through a portal."""
        if os.environ.get("WAYLAND_DISPLAY"):
            return True
        shown = _loginctl(["show-session", "--property=Type", "self"])
        if shown is None:
            return _session_types() == ["wayland"]
        return "wayland" in (shown or "")

    @staticmethod
    def _has_wayland_permission(account_home: str) -> bool:
        """Whether RustDesk already holds this machine's screen permission.

        Args:
            account_home: The home of the account the share is for.

        Returns:
            True when the option is in a configuration RustDesk reads, and
            on a machine whose files cannot be read, which is not an
            invitation to nag.
        """
        for path in rustdesk.config_paths(account_home):
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    if RDP_WAYLAND_TOKEN_OPTION in stream.read():
                        return True
            except OSError:
                continue
        return False

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
        seated = graphical_accounts()
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
        """Keep the access password where only root reads it."""
        path = self._password_path()
        try:
            os.makedirs(self._credentials_dir, exist_ok=True)
            os.chmod(self._credentials_dir, 0o700)
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
