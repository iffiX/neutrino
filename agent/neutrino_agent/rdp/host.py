"""Sharing this machine's desktop, as the hub's switch orders.

The Remote desktop module's switch is the one place a share is decided.
On, the host takes the machine's RustDesk over: it keeps aside what is
registered under RustDesk's names and is not the agent's, stops and ends
every RustDesk host but a viewer, writes the options and the seat password
into the settings files while nothing runs, and registers and starts the
agent's own copy under RustDesk's names. Off, it removes what it registered,
ends its copy and puts back what it kept, settings files included. Each
system's registration is its applier's (``modules/remote_desktop/``).

The seat password is the hub's: it arrives in the state's ``desktop``
section, is written into ``RustDesk.toml`` whenever it changed, and is kept
in a root-only file. It enters neither the store nor any report.

**A share is declared only once it listens.** The host reads the system's
socket table for its copy on the direct port; it opens no connection to it.
A share an agent of an earlier version recorded is taken over the same way
when the agent starts, and kept and reported until the first state names
the module.

Who is at the screen, how many peers are connected, and what a peer would
wait on are each platform's own, read through the seat
(:func:`~neutrino_agent.rdp.seat.seat_for`).

Not pure: writes RustDesk's settings, drives its registration through the
applier, and reads the socket table.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
import time
import uuid

from neutrino_agent.exceptions import (
    InstallError,
    ModuleApplyError,
    PlatformUnsupportedError,
)
from neutrino_agent.modules import rustdesk
from neutrino_agent.modules.remote_desktop.constants import (
    REMOTE_DESKTOP_DIR_NAME,
    REMOTE_DESKTOP_DIRECT_PORT,
    REMOTE_DESKTOP_KEPT_DIR_NAME,
    REMOTE_DESKTOP_KEPT_SETTINGS_DIR_NAME,
    REMOTE_DESKTOP_LISTEN_TTL_S,
    REMOTE_DESKTOP_OPTIONS,
    REMOTE_DESKTOP_OPTIONS_FILE,
    REMOTE_DESKTOP_PASSWORD_FILE,
    REMOTE_DESKTOP_REGISTERED_NAME,
)
from neutrino_agent.modules.remote_desktop.records import read_json, write_json
from neutrino_agent.modules.subprocess_run import command_detail
from neutrino_agent.rdp.constants import (
    RDP_ATTENTION_NOBODY_SEATED,
    RDP_ATTENTION_TTL_S,
    RDP_GREETER_ACCOUNTS,
    RDP_PASSWORD_FILE,
    RDP_STATE_NOT_SHARED,
    RDP_STATE_SHARING,
    RDP_STATE_STARTING,
)
from neutrino_agent.rdp.seat import seat_for

# Where a declared share came from: the switch, or the record an old
# ``nagent rdp start`` left, the only share a hub adopts.
DESKTOP_ORIGIN_SWITCH = "switch"
DESKTOP_ORIGIN_COMMAND = "command"
# The codes a failed step of the switch reports.
CODE_TAKEOVER_FAILED = "rdp_takeover_failed"
CODE_RESTORE_FAILED = "rdp_restore_failed"
# The steps they name.
STEP_COPY = "copy"
STEP_KEEP = "keep"
STEP_STOP = "stop"
STEP_SETTINGS = "settings"
STEP_REGISTER = "register"
STEP_START = "start"
STEP_RESTORE = "restore"
# What a step that failed may have raised.
STEP_ERRORS = (OSError, subprocess.SubprocessError, InstallError, ValueError)


def applier_for(os_name: str, kept_dir: str):
    """The registration of one operating system.

    Args:
        os_name: ``linux``, ``windows`` or ``darwin``.
        kept_dir: Where what is kept aside goes.

    Returns:
        That system's applier.
    """
    if os_name == "windows":
        from neutrino_agent.modules.remote_desktop.windows_applier import (
            RemoteDesktopWindowsApplier,
        )

        return RemoteDesktopWindowsApplier(kept_dir=kept_dir)
    if os_name == "darwin":
        from neutrino_agent.modules.remote_desktop.darwin_applier import (
            RemoteDesktopDarwinApplier,
        )

        return RemoteDesktopDarwinApplier(kept_dir=kept_dir)
    from neutrino_agent.modules.remote_desktop.linux_applier import (
        RemoteDesktopLinuxApplier,
    )

    return RemoteDesktopLinuxApplier(kept_dir=kept_dir)


class RdpShareHost:
    """Shares this machine's desktop as the switch says, and says where the
    share stands."""

    def __init__(
        self,
        *,
        platform,
        store,
        credentials_dir: str,
        state_dir: str,
        log=print,
        seat=None,
        applier=None,
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`MachineStateStore` holding the share record.
            credentials_dir: Where the seat password file lives.
            state_dir: The state root, under which ``remote_desktop/``
                keeps what was registered and what was kept aside.
            log: Callable used for progress messages.
            seat: Who is at the screen and what a peer would wait on; None
                is the platform's own.
            applier: The system's registration; None is the platform's own.
        """
        self._platform = platform
        self._seat = seat if seat is not None else seat_for(platform.os_name)
        self._store = store
        self._credentials_dir = credentials_dir
        self._dir = os.path.join(state_dir, REMOTE_DESKTOP_DIR_NAME)
        self._kept_dir = os.path.join(self._dir, REMOTE_DESKTOP_KEPT_DIR_NAME)
        self._applier = (
            applier
            if applier is not None
            else applier_for(platform.os_name, self._kept_dir)
        )
        self._log = log
        self._lock = threading.Lock()
        self._seat_password = ""
        self._listened_at = 0.0
        self._listeners: list = []
        self._attention_at = 0.0
        self._attention = ""

    def take_seat_password(self, password: str) -> None:
        """Keep the seat password the hub holds, for the next write.

        Args:
            password: The seat password from the state's ``desktop``
                section.
        """
        if password:
            self._seat_password = password

    def set_switch(self, is_enabled: bool) -> None:
        """Make the switch true on this machine.

        The first call ends a share an earlier agent recorded: from here on
        the switch alone decides.

        Args:
            is_enabled: Whether the desktop is shared.

        Raises:
            ModuleApplyError: ``rdp_takeover_failed {step, detail}`` or
                ``rdp_restore_failed {step, detail}`` naming the step that
                failed.
        """
        with self._lock:
            record = self._store.rdp_share()
            if not record.get("is_ordered"):
                self._store.set_rdp_share(
                    {
                        "is_ordered": True,
                        "share_id": str(record.get("share_id", "") or ""),
                    }
                )
            if is_enabled:
                self._take_over()
            else:
                self._give_back()
            self._listened_at = 0.0

    def resume_old_share(self) -> None:
        """Take RustDesk over for a share an earlier agent's command made.

        The upgrade took that agent's RustDesk away, so the share runs again
        on the agent's copy until the first state names the module. A
        failure is logged: the state that follows tries again.
        """
        with self._lock:
            record = self._store.rdp_share()
            if record.get("is_ordered") or not record.get("is_shared"):
                return
            try:
                self._take_over()
            except ModuleApplyError as error:
                said = " ".join(f"{key}={value}" for key, value in error.params.items())
                self._log(f"remote_desktop: {error.code} {said}"[:500])

    def settle_at_start(self) -> None:
        """What the agent does about RustDesk when it starts.

        A share an earlier agent's command made is taken over; a host the
        switch runs whose program the package has since replaced is
        started again, so it runs the copy on disk.
        """
        self.resume_old_share()
        self.renew_if_replaced()

    def renew_if_replaced(self) -> None:
        """Start the host again when its running program is not the copy on
        disk: an upgrade replaced the copy under a host that kept running.

        Not an apply of the state: the settings and the registration stay
        as they are. A failure is logged.
        """
        with self._lock:
            if not os.path.isfile(self._registered_path()):
                return
            applier = self._applier
            try:
                if not applier.is_copy_present() or not applier.stale_pids():
                    return
                self._log("remote_desktop: the copy was replaced; starting it again")
                _, _, uid = self._seat_of()
                applier.stop_hosts()
                applier.start(uid)
            except STEP_ERRORS as error:
                self._log(f"remote_desktop: {command_detail(error)}"[:500])
            self._listened_at = 0.0

    def leave_hub(self) -> None:
        """Cut the share off and give RustDesk back: the machine left the hub
        or was removed from it. An old command's record ends with it, so the
        next hub adopts nothing. A failure is logged.
        """
        with self._lock:
            try:
                self._give_back()
            except ModuleApplyError as error:
                said = " ".join(f"{key}={value}" for key, value in error.params.items())
                self._log(f"remote_desktop: {error.code} {said}"[:500])
            self._store.set_rdp_share({"is_ordered": True})
            self._listened_at = 0.0

    def is_service_running(self) -> bool:
        """Whether the agent's RustDesk service runs, the switch on, whoever
        sits at the screen."""
        if not os.path.isfile(self._registered_path()):
            return False
        try:
            return bool(self._applier.is_service_running())
        except STEP_ERRORS:
            return False

    def turn_off(self) -> None:
        """Give RustDesk back, whatever the switch says: the agent is leaving.

        Raises:
            ModuleApplyError: ``rdp_restore_failed {step, detail}``.
        """
        with self._lock:
            self._give_back()

    def is_running(self) -> bool:
        """Whether the agent's copy listens on the direct port."""
        program = self._applier.program
        return any(_is_same(program, listener) for listener in self._listening())

    def has_copy_processes(self) -> bool:
        """Whether any process of the agent's copy runs."""
        try:
            return bool(self._applier.copy_pids())
        except STEP_ERRORS:
            return False

    def state(self) -> dict:
        """What the control channel reads about this machine's share.

        Returns:
            ``{"is_shared", "state", "port", "account", "attention",
            "has_password"}``. The seat password itself is in none of it.
        """
        is_on = self._is_on()
        account = self._account() if is_on else ""
        return {
            "is_shared": is_on,
            "state": self._state(is_on),
            "port": REMOTE_DESKTOP_DIRECT_PORT,
            "account": account,
            "attention": self.attention(account) if is_on else "",
            "has_password": self._read_password() != "",
        }

    def declaration(self) -> dict:
        """What the heartbeat carries up about this machine's share.

        Returns:
            ``{"is_shared", "origin", "account", "share_id", "port",
            "attention", "connected_count"}``. ``is_shared`` is true only
            while the share listens, so a fleet list never offers a desktop
            that cannot be reached; ``origin`` is ``switch`` for the switch's
            share, ``command`` for one an old command's record keeps running,
            empty while nothing is shared; ``account`` is whoever sits at the
            screen and decides nothing; ``attention`` names what a peer would
            wait on if it dialed now. The seat password is in none of it.
        """
        is_on = self._is_on()
        account = self._account() if is_on else ""
        port = REMOTE_DESKTOP_DIRECT_PORT
        is_shared = is_on and self._state(is_on) == RDP_STATE_SHARING
        return {
            "is_shared": is_shared,
            "origin": self._origin() if is_shared else "",
            "account": account,
            "share_id": self._share_id() if is_on else "",
            "port": port,
            "attention": self.attention(account) if is_on else "",
            "connected_count": self._seat.connected_count(port) if is_on else 0,
        }

    def attention(self, account: str) -> str:
        """What somebody has to do at this machine before a peer sees it.

        Believed for :data:`RDP_ATTENTION_TTL_S`: the heartbeat asks every
        few seconds and the answer costs the session table and a file.

        Args:
            account: The account at the screen.

        Returns:
            A typed code, empty when a peer would be shown the desktop.
        """
        now = time.monotonic()
        if now - self._attention_at < RDP_ATTENTION_TTL_S:
            return self._attention
        self._attention = self._read_attention(account)
        self._attention_at = now
        return self._attention

    def _take_over(self) -> None:
        """Turn the share on, or leave it alone when it already stands.

        Raises:
            ModuleApplyError: ``rdp_takeover_failed {step, detail}``.
        """
        applier = self._applier
        if not applier.is_copy_present():
            raise ModuleApplyError(
                CODE_TAKEOVER_FAILED,
                {"step": STEP_COPY, "detail": f"{applier.program} is missing"},
            )
        account, home, uid = self._seat_of()
        password = self._seat_password or self._read_password()
        paths = self._settings_paths(home)
        # The password goes into the service's own file alone: the session's
        # host takes it from the service and stores it in its own form.
        service_password = paths[1] if password else ""
        written = [
            path
            for path in paths
            if not _is_password_file(path) or path == service_password
        ]
        registered = read_json(self._registered_path())
        is_changed = any(
            rustdesk.would_change(path, self._render(path, password))
            for path in written
        )
        if (
            registered
            and not is_changed
            and applier.is_registered()
            and applier.copy_pids()
        ):
            return
        was_on = bool(registered)
        step = STEP_KEEP
        try:
            if not registered:
                applier.keep_aside()
                registered = {"share_id": self._share_id() or uuid.uuid4().hex}
                registered["settings"] = {}
                write_json(self._registered_path(), registered)
            step = STEP_STOP
            applier.stop_hosts()
            step = STEP_SETTINGS
            for path in paths:
                self._keep_settings(registered, path)
            write_json(self._registered_path(), registered)
            for path in written:
                rustdesk.write_settings(path, self._render(path, password))
            step = STEP_REGISTER
            applier.register()
            step = STEP_START
            applier.start(uid)
        except STEP_ERRORS as error:
            raise ModuleApplyError(
                CODE_TAKEOVER_FAILED, {"step": step, "detail": command_detail(error)}
            )
        if password:
            self._write_password(password)
        self._log("remote_desktop: the agent's RustDesk runs")
        if not was_on and account:
            self._seat.ask_for_permissions(account)

    def _give_back(self) -> None:
        """Turn the share off and put back what was there before.

        Raises:
            ModuleApplyError: ``rdp_restore_failed {step, detail}``.
        """
        applier = self._applier
        registered = read_json(self._registered_path())
        if not registered and not applier.is_registered() and not applier.copy_pids():
            return
        step = STEP_STOP
        try:
            applier.unregister()
            step = STEP_SETTINGS
            self._restore_settings(registered)
            step = STEP_RESTORE
            applier.restore()
        except STEP_ERRORS as error:
            raise ModuleApplyError(
                CODE_RESTORE_FAILED, {"step": step, "detail": command_detail(error)}
            )
        with contextlib.suppress(OSError):
            os.unlink(self._registered_path())
        shutil.rmtree(self._kept_dir, ignore_errors=True)
        self._log("remote_desktop: RustDesk is given back")

    def _render(self, path: str, password: str):
        """What one settings file is written through."""
        if _is_password_file(path):
            return lambda existing: rustdesk.render_password(existing, password)
        return lambda existing: rustdesk.render_config(existing, REMOTE_DESKTOP_OPTIONS)

    def _settings_paths(self, home: str) -> list:
        """Every settings file the share keeps aside: the service's options
        and password first, then the seat's."""
        return [
            os.path.join(directory, name)
            for directory in self._applier.settings_dirs(home)
            for name in (REMOTE_DESKTOP_OPTIONS_FILE, REMOTE_DESKTOP_PASSWORD_FILE)
        ]

    def _keep_settings(self, registered: dict, path: str) -> None:
        """Copy one settings file aside before its first write.

        Args:
            registered: The record, whose ``settings`` maps each path to its
                kept copy, empty for a file that was not there.
            path: The file.

        Raises:
            OSError: When the copy cannot be made.
        """
        settings = registered.setdefault("settings", {})
        if path in settings:
            return
        if not os.path.isfile(path):
            settings[path] = ""
            return
        kept_dir = os.path.join(self._kept_dir, REMOTE_DESKTOP_KEPT_SETTINGS_DIR_NAME)
        os.makedirs(kept_dir, mode=0o700, exist_ok=True)
        kept = os.path.join(kept_dir, f"{len(settings)}.toml")
        shutil.copy2(path, kept)
        status = os.stat(path)
        settings[path] = kept
        registered.setdefault("owners", {})[path] = [
            status.st_uid,
            status.st_gid,
            status.st_mode & 0o777,
        ]

    def _restore_settings(self, registered: dict) -> None:
        """Put every settings file back as it was before the first write.

        Raises:
            OSError: When a file cannot be put back.
        """
        owners = registered.get("owners") or {}
        for path, kept in (registered.get("settings") or {}).items():
            if not kept:
                if os.path.isfile(path):
                    os.unlink(path)
                continue
            if not os.path.isfile(kept):
                continue
            shutil.copy2(kept, path)
            owner = owners.get(path)
            if owner and hasattr(os, "chown"):
                os.chown(path, int(owner[0]), int(owner[1]))
                os.chmod(path, int(owner[2]))

    def _is_on(self) -> bool:
        """Whether the switch, or before the first state an earlier agent's
        record, says the desktop is shared."""
        record = self._store.rdp_share()
        if record.get("is_ordered"):
            return os.path.isfile(self._registered_path())
        return bool(record.get("is_shared"))

    def _origin(self) -> str:
        """Where the share came from: the switch, or an old command's record."""
        if self._store.rdp_share().get("is_ordered"):
            return DESKTOP_ORIGIN_SWITCH
        return DESKTOP_ORIGIN_COMMAND

    def _share_id(self) -> str:
        record = self._store.rdp_share()
        if record.get("is_ordered"):
            registered = read_json(self._registered_path())
            return str(registered.get("share_id", "") or record.get("share_id", ""))
        return str(record.get("share_id", "") or "")

    def _account(self) -> str:
        """Whoever sits at the screen, for the report alone."""
        seated = self._seat.graphical_accounts()
        if seated:
            return str(seated[0])
        record = self._store.rdp_share()
        return "" if record.get("is_ordered") else str(record.get("account", "") or "")

    def _seat_of(self) -> tuple:
        """The account at the screen, its home and its uid.

        Returns:
            ``(account, home, uid)``; empty, empty and None for nobody.
        """
        seated = self._seat.graphical_accounts() or []
        account = str(seated[0]) if seated else ""
        if not account or account.split("@")[0] in RDP_GREETER_ACCOUNTS:
            return "", "", None
        home = self._account_home(account)
        uid = None
        try:
            import pwd

            uid = pwd.getpwnam(account).pw_uid
        except (ImportError, KeyError):
            uid = None
        return account, home, uid

    def _read_attention(self, account: str) -> str:
        """Ask the machine what a peer would wait on, without the cache."""
        seated = self._seat.graphical_accounts()
        if seated is not None and not seated:
            return RDP_ATTENTION_NOBODY_SEATED
        if account and account.split("@")[0] in RDP_GREETER_ACCOUNTS:
            return RDP_ATTENTION_NOBODY_SEATED
        return self._seat.screen_attention(self._account_home(account))

    def _account_home(self, account: str) -> str:
        """One account's home, empty when it cannot be resolved."""
        if not account:
            return ""
        try:
            return self._platform.account_home(account)
        except (KeyError, OSError, PlatformUnsupportedError):
            return ""

    def _state(self, is_on: bool) -> str:
        """Where the share stands, by what listens on the direct port."""
        if not is_on:
            return RDP_STATE_NOT_SHARED
        return RDP_STATE_SHARING if self.is_running() else RDP_STATE_STARTING

    def _listening(self) -> list:
        """The programs on the direct port, read again at most every few
        seconds."""
        now = time.monotonic()
        if self._listened_at and now - self._listened_at <= REMOTE_DESKTOP_LISTEN_TTL_S:
            return self._listeners
        try:
            self._listeners = list(
                self._applier.listening_programs(REMOTE_DESKTOP_DIRECT_PORT)
            )
        except STEP_ERRORS:
            self._listeners = []
        self._listened_at = now
        return self._listeners

    def _registered_path(self) -> str:
        return os.path.join(self._dir, REMOTE_DESKTOP_REGISTERED_NAME)

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


def _is_same(program: str, listener: str) -> bool:
    """Whether a listener's program is the given one; Windows paths ignore
    case."""
    if not listener:
        return False
    if os.name == "nt" or "\\" in program:
        return program.lower() == listener.lower()
    return program == listener


def _is_password_file(path: str) -> bool:
    """Whether a settings file is the one the permanent password is in."""
    return os.path.basename(path) == REMOTE_DESKTOP_PASSWORD_FILE
