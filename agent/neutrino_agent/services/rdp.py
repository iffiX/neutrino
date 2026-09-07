"""Sharing this machine's desktop, and reaching one that is shared.

Two halves of one type. **Share** is a decision made on the machine and
nowhere else: a person sets an access password, the agent configures
RustDesk for direct connection and declares the share upward, and every
other machine's Services shows it. **Connect** launches the local RustDesk
client at an address another machine declared.

**One share per machine, owned by its account.** An ordinary caller shares
their own seat and stops their own share; the privileged scope — root, or
the hub's drawer — controls anyone's. The access password travels only
inside the one ask that sets it (the local socket, or the hub's pinned
wire, the way a mount's credentials do), is set into RustDesk salted, and
is kept in a root-only file so the owner can read back what they set. It
enters neither the service store nor any heartbeat.

**A machine with no desktop is refused before anything is configured.**
RustDesk on a box with no graphical session answers nothing, and the share
says so rather than passing the connection refusal on raw.

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

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

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

# How long the answer to "what would a peer wait on" is believed. Reading it
# asks the session table and a file, and the heartbeat asks every few
# seconds; nothing about a seat changes faster than this.
RDP_ATTENTION_TTL_S = 15.0

# What a session's type has to be for there to be a desktop to share, and how
# long the machine's own session list is waited for.
RDP_GRAPHICAL_SESSION_TYPES = ("x11", "wayland", "mir")
RDP_SESSION_TIMEOUT_S = 5

# What a window needs to open on the seat's screen, read from the session's
# own processes — the same place RustDesk's service reads it before spawning
# its screen server into the session. Injectable for the tests.
RDP_SESSION_ENVIRONMENT_KEYS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
)
RDP_PROC_DIR = "/proc"

# The option RustDesk stores the screen-capture permission under once a
# person has granted it. Wayland asks for that permission on the shared
# machine's own screen, so until it is there every connection waits on a
# dialog only somebody sitting at that machine can answer.
RDP_WAYLAND_TOKEN_OPTION = "wayland-restore-token"

# The greeter's session owns a home on a tmpfs, so it can hold no such
# permission and a peer would wait for a dialog nobody is there to answer.
RDP_GREETER_ACCOUNTS = ("gdm", "gdm-greeter", "sddm", "lightdm", "greetd")


class RdpServiceHandler(ServiceTypeHandler):
    """Shares this machine's desktop, and opens a client at another's."""

    service_type = "rdp"

    def __init__(
        self, *, platform, store, credentials_dir: str, accounts=None, log=print
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`MachineServiceStore` holding the share record.
            credentials_dir: Where the access password file lives.
            accounts: Callable answering the machine's human accounts, for
                judging the account a share names.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._store = store
        self._credentials_dir = credentials_dir
        self._accounts = accounts
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
        # One share per machine. An ordinary caller shares their own seat
        # and stops their own share; the privileged scope controls anyone's.
        record = self._store.rdp_share()
        held = str(record.get("account", ""))
        if action == RDP_ACTION_SHARE:
            named = self._share_account(str(body.get("account", "")), account)
            if not is_privileged:
                if named != account:
                    return {"code": "control_scope_refused", "params": {}}
                if bool(record.get("is_shared")) and held and held != account:
                    return {"code": "control_scope_refused", "params": {}}
            return self._share(named, str(body.get("password", "")))
        if action == RDP_ACTION_UNSHARE:
            if not is_privileged and held and held != account:
                return {"code": "control_scope_refused", "params": {}}
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
                # Whose desktop the share means, and who is actually at the
                # screen — the page preselects from the latter, because the
                # seat decides what a peer is shown.
                "account": str(record.get("account", "")),
                "desktop_accounts": graphical_accounts() or [],
            }
        }

    def summary(self) -> dict:
        """The share at a glance, for the hub's drawer to draw.

        The cheap fields only — no id read, no seat listing — because this
        rides every beat.

        Returns:
            ``{"is_shared", "state", "port", "account"}``.
        """
        record = self._store.rdp_share()
        is_shared = bool(record.get("is_shared"))
        return {
            "is_shared": is_shared,
            "state": self._state(is_shared),
            "port": int(record.get("port") or rustdesk.RUSTDESK_DIRECT_PORT),
            "account": str(record.get("account", "")),
        }

    def declaration(self) -> dict:
        """What the heartbeat carries up about this machine's share.

        Returns:
            ``{"is_shared", "share_id", "port", "attention"}``. ``is_shared``
            is true only while the share actually answers, so a fleet list
            never offers a desktop that cannot be reached; ``attention``
            names what a peer would wait on if it dialed now, so the machine
            dialing can say why rather than sit in "connecting". The access
            password is in neither and never crosses the wire.
        """
        record = self._store.rdp_share()
        is_shared = bool(record.get("is_shared"))
        return {
            "is_shared": is_shared and self._state(is_shared) == RDP_STATE_SHARING,
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
        cannot see, and the honest thing is to say so before it dials.

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

    def _read_attention(self, account: str) -> str:
        """Ask the machine what a peer would wait on, without the cache."""
        seated = graphical_accounts()
        if seated is not None and not seated:
            return "rdp_nobody_seated"
        if account and account.split("@")[0] in RDP_GREETER_ACCOUNTS:
            return "rdp_nobody_seated"
        if not self._is_wayland_seat():
            return ""
        home = self._account_home(account)
        return "" if self._has_wayland_permission(home) else "rdp_screen_not_allowed"

    def _is_wayland_seat(self) -> bool:
        """Whether this machine's screen is handed out through a portal."""
        if os.name == "nt" or _is_darwin():
            return False
        if os.environ.get("WAYLAND_DISPLAY"):
            return True
        shown = _loginctl(["show-session", "--property=Type", "self"])
        if shown is None:
            return _session_types() == ["wayland"]
        return "wayland" in (shown or "")

    def _account_home(self, account: str) -> str:
        """One account's home, empty when it cannot be resolved."""
        if not account:
            return ""
        try:
            return self._platform.account_home(account)
        except (KeyError, PlatformUnsupportedError):
            return ""

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
        paths = rustdesk.config_paths(account_home)
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    if RDP_WAYLAND_TOKEN_OPTION in stream.read():
                        return True
            except OSError:
                continue
        return False

    def reveal_password(self, *, account: str, is_privileged: bool) -> str:
        """The access password this machine shares with, for its owner.

        Args:
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.

        Returns:
            The password, for the privileged scope and the share's own
            account; empty for anyone else or when none is set.
        """
        if is_privileged:
            return self._read_password()
        held = str(self._store.rdp_share().get("account", ""))
        return self._read_password() if held and held == account else ""

    def _share_account(self, named: str, caller: str) -> str:
        """The account whose desktop a share means.

        Args:
            named: What the body names, empty for none.
            caller: The asking account.

        Returns:
            The named account; with none named, the one account at the
            machine's screen when there is exactly one, else the caller.
        """
        if named:
            return named
        seated = graphical_accounts()
        if seated is not None and len(seated) == 1:
            return seated[0]
        return caller

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
        reported = self._accounts() if self._accounts is not None else []
        if account in reported:
            return {}
        return {"code": "no_target_user", "params": {}}

    def _share(self, account: str, password: str):
        """Configure RustDesk for direct connection and declare the share."""
        if not password:
            return {"code": "rdp_password_missing", "params": {}}
        status = self._module_states().get(RDP_MODULE) or {}
        if status.get("state") != "installed":
            return {"code": "module_missing", "params": {"module": RDP_MODULE}}
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
        """Open the local RustDesk client at one shared desktop.

        The client is a window, and this runs in a daemon that owns no
        display — a plain spawn starts a process nobody can see. So on
        Linux it is stepped down into the seat session with that session's
        own display environment, the way RustDesk's service spawns its
        screen server; where no seat can be found the ask is refused
        rather than silently opening nothing.
        """
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
            invocation, environment = client_invocation(binary, peer)
        except LookupError:
            return {"code": "rdp_no_desktop", "params": {}}
        try:
            subprocess.Popen(
                invocation,
                env=environment,
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


def client_invocation(binary: str, peer: str) -> tuple:
    """How to start the client so its window lands on the machine's screen.

    Args:
        binary: The RustDesk binary.
        peer: What to dial.

    Returns:
        ``(argv, environment)``; environment None keeps the caller's own.

    Raises:
        LookupError: When this daemon owns no display and no seat session's
            can be borrowed, so a spawn would open a window nobody sees.
    """
    connect = [binary, "--connect", peer]
    if os.name == "nt" or _is_darwin():
        return connect, None
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return connect, None
    if pwd is None or os.geteuid() != 0:
        raise LookupError("no display and no way to borrow a session's")
    seated = graphical_accounts() or []
    environment = session_environment(seated[0]) if seated else None
    if not seated or environment is None:
        raise LookupError("no seat session to open a window in")
    account = seated[0]
    return (
        ["runuser", "-u", account, "--"] + connect,
        {
            "HOME": pwd.getpwnam(account).pw_dir,
            "USER": account,
            "LOGNAME": account,
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            **environment,
        },
    )


def session_environment(account: str) -> "dict | None":
    """One seated account's display environment, off its own processes.

    Args:
        account: The seated account.

    Returns:
        The display variables, or None when no process of that account
        carries a display.
    """
    if pwd is None:
        return None
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
        True on any machine that cannot be asked, so only one that positively
        has no graphical session is refused.
    """
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    seated = graphical_accounts()
    return True if seated is None else bool(seated)


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


def graphical_accounts() -> "list | None":
    """The accounts signed in at this machine's screen.

    ``loginctl`` lists each session with its owner, and answers the type of
    every session it is asked about in the order it was asked.

    Returns:
        The owning accounts of the graphical sessions, or None on a machine
        that cannot be asked — Windows and macOS say nothing this way, and a
        box without ``loginctl`` says nothing at all.
    """
    if os.name == "nt" or _is_darwin():
        return None
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


def _is_darwin() -> bool:
    """Whether this machine is macOS."""
    return os.uname().sysname == "Darwin" if hasattr(os, "uname") else False
