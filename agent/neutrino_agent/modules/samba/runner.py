"""The file share as a module: package, configuration, verbs, details.

The package comes from the distribution, so the install rides the
system-package runner. What makes the package this hub's file share, the
rendered ``smb.conf``, the accounts and the share directories, is applied
here from the hub's desired configuration; what the machine actually
serves, read back from Samba itself, is what the hub imports the first
time it configures a share somebody set up by hand.

On Windows and macOS the same module drives the system's own SMB server
through the platform's applier instead.

Not pure: drives Samba, or the system's SMB server, through its applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
import threading
import time

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import ModuleRunner, command_outcome
from neutrino_agent.modules.samba.applier import (
    SambaConfigApplier,
    SambaConfigReader,
    SambaStatusReader,
    SambaUserManager,
    ensure_share_group,
    testparm,
)
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_ACCOUNT_REFUSALS,
    SAMBA_BINARY_NAME,
    SAMBA_COMMAND_SET_PASSWORD,
    SAMBA_CONF_PATH,
    SAMBA_NATIVE_RECORD_NAME,
    SAMBA_NATIVE_STATUS_TTL_S,
    samba_unit,
)
from neutrino_agent.modules.samba.renderer import SambaConfigRenderer
from neutrino_agent.modules.subprocess_run import command_detail, unit_state
from neutrino_agent.modules.system_package import SystemPackageModuleRunner
from neutrino_agent.platforms.detect import platform_tuple


class SambaModuleRunner(SystemPackageModuleRunner):
    """Installs Samba by package and keeps it serving what the hub says."""

    name = "samba"
    binary = SAMBA_BINARY_NAME

    def __init__(self, *, platform, log=print, publish=None, family: str = ""):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            family: The distribution family; detected when empty.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._unit = samba_unit(family or platform_tuple().get("family", ""))
        self._config: "SambaConfig | None" = None

    @property
    def unit(self) -> str:
        """The unit this machine's Samba runs as."""
        return self._unit

    def install(self, resolved: dict) -> None:
        """Install the package and the group every share account joins.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        super().install(resolved)
        ensure_share_group()

    def validate(self, config: dict) -> None:
        """Parse, check and render a configuration, then have Samba check it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = SambaConfig.from_dict(config)
        parsed.validate()
        testparm(SambaConfigRenderer(config=parsed).render())

    def apply(self, config: dict) -> None:
        """Render the configuration, converge accounts, and load it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or Samba
                will not take it.
        """
        parsed = SambaConfig.from_dict(config)
        parsed.validate()
        ensure_share_group()
        rendered = SambaConfigRenderer(config=parsed).render()
        try:
            note = SambaConfigApplier(unit=self._unit).apply(rendered, config=parsed)
            changes = SambaUserManager().converge(parsed.users)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        self._config = parsed
        self._log("samba: " + "; ".join([note] + changes))

    def stop(self) -> None:
        """Take the server down, leaving the shares' files in place."""
        SambaConfigApplier(unit=self._unit).stop()

    def remove_configuration(self) -> None:
        """Delete the rendered ``smb.conf``; the share directories stay."""
        self._config = None
        with contextlib.suppress(OSError):
            os.unlink(SAMBA_CONF_PATH)

    def is_active(self) -> bool:
        """Whether this machine's Samba unit is active."""
        return unit_state(self._unit) == "active"

    def journal_units(self) -> list:
        """This machine's Samba unit."""
        return [self._unit]

    def details(self, resolved: dict) -> dict:
        """What Samba serves, who it serves, and each account's state.

        The global section and the shares are what ``testparm -s`` prints
        for the live file, whoever wrote it; the users are every account
        the hub configures or Samba holds a credential for.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"is_active", "global", "shares", "users", "sessions",
            "disk_usage"}``, each user ``{"name", "is_present",
            "has_password"}`` and each share ``{"name", "path", "params"}``.
        """
        config = self._config or SambaConfig()
        reader = SambaStatusReader()
        accounts = SambaUserManager()
        names = list(config.users)
        names += [name for name in accounts.credentialed_users() if name not in names]
        try:
            users = accounts.survey(names)
        except (OSError, subprocess.SubprocessError):
            users = []
        global_section, shares = SambaConfigReader().read()
        return {
            "is_active": unit_state(self._unit) == "active",
            "global": global_section,
            "shares": shares,
            "users": [vars(state) for state in users],
            "sessions": reader.sessions(),
            "disk_usage": reader.disk_usage(config),
        }

    def command(self, verb: str, args: dict, on_line=None) -> dict:
        """Run one of the file share's verbs.

        Args:
            verb: ``set_password``, or ``validate``.
            args: ``{"name", "password"}``.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        if verb != SAMBA_COMMAND_SET_PASSWORD:
            return super().command(verb, args, on_line)
        name = str(args.get("name", ""))
        config = self._config or SambaConfig()
        if name not in config.users:
            return command_outcome(1, "user_unknown", {"user": name})
        try:
            SambaUserManager().set_password(name, str(args.get("password", "")))
        except (OSError, subprocess.SubprocessError) as error:
            return command_outcome(
                1, "command_failed", {"detail": command_detail(error)[:500]}
            )
        return command_outcome(0, output=f"password set for {name}\n")


class SambaNativeServerRunner(ModuleRunner):
    """Keeps the system's own SMB server serving what the hub says.

    Windows and macOS carry the server, so there is nothing to install or
    uninstall; the platform's applier converges the shares, the accounts
    and the fence, and loads the fence again when the runner is built. A
    root-only record under the agent's work root lists what the module
    made and which accounts were given a password. The server's state is
    read at most every 30 seconds and again after every change.
    """

    name = "samba"
    kind = "system_package"

    def __init__(self, *, platform, log=print, publish=None, clock=time.monotonic):
        """
        Args:
            platform: The machine's platform; it has ``smb_server``.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            clock: The monotonic clock the status reading ages on.

        Raises:
            PlatformUnsupportedError: When the platform has no SMB server.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = platform.smb_server_applier()
        self._record_path = os.path.join(
            platform.agent_var_dir(), SAMBA_NATIVE_RECORD_NAME
        )
        self._clock = clock
        self._config: "SambaConfig | None" = None
        self._lock = threading.Lock()
        self._status: "dict | None" = None
        self._status_at = 0.0
        try:
            self._applier.reload_fence()
        except (OSError, subprocess.SubprocessError) as error:
            self._log(f"samba: the fence did not load: {error}")

    def verify(self, resolved: dict) -> bool:
        """Whether the system's SMB server is there.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the server answers for itself.
        """
        return bool(self._read_status().get("is_present"))

    def install(self, resolved: dict) -> None:
        """Install nothing: the system carries the server.

        Args:
            resolved: The module as the hub resolved it.
        """

    def uninstall(self, resolved: dict) -> None:
        """Remove nothing: the server stays with the system.

        Args:
            resolved: The module as the hub resolved it.
        """

    def validate(self, config: dict) -> None:
        """Parse and check a configuration for this system.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        SambaConfig.from_dict(config).validate(os_name=self._platform.os_name)

    def apply(self, config: dict) -> None:
        """Converge the server with the configuration and serve it.

        The record lists the configured shares before the server is
        touched, so a share made by an apply that then failed is still the
        module's to change.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or the
                server will not take it.
        """
        parsed = SambaConfig.from_dict(config)
        parsed.validate(os_name=self._platform.os_name)
        record = self._read_record()
        shares = dict(record["shares"])
        shares.update({share.name: share.path for share in parsed.shares})
        self._write_record(dict(record, shares=shares))
        refusal = None
        try:
            notes = self._applier.apply(parsed, dict(record, shares=shares))
        except ModuleApplyError as error:
            if error.code not in SAMBA_ACCOUNT_REFUSALS:
                raise
            refusal = error
            notes = [f"passed over account {error.params.get('user', '')}"]
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        finally:
            self._forget_status()
        accounts = list(record["accounts"])
        accounts += [name for name in parsed.users if name not in accounts]
        self._write_record(
            {
                "shares": {share.name: share.path for share in parsed.shares},
                "accounts": accounts,
                "passworded": [
                    name
                    for name in self._read_record()["passworded"]
                    if name in parsed.users
                ],
                "is_served": True,
            }
        )
        self._config = parsed
        self._log("samba: " + "; ".join(notes or ["unchanged"]))
        if refusal is not None:
            raise refusal

    def stop(self) -> None:
        """Take the module's shares off the server; accounts and fence stay.

        Raises:
            OSError: When the server will not let them go.
        """
        record = self._read_record()
        try:
            self._applier.withdraw(record, is_removed=False)
        finally:
            self._forget_status()
        self._write_record(dict(record, shares={}, is_served=False))

    def remove_configuration(self) -> None:
        """Take the shares and the fence away and disable the accounts.

        Raises:
            OSError: When the server will not let them go.
        """
        record = self._read_record()
        self._config = None
        try:
            self._applier.withdraw(record, is_removed=True)
        finally:
            self._forget_status()
        self._write_record(dict(record, shares={}, passworded=[], is_served=False))

    def is_active(self) -> bool:
        """Whether the server runs and serves the module's shares."""
        is_running = bool(self._read_status().get("is_running"))
        return is_running and bool(self._read_record()["is_served"])

    def details(self, resolved: dict) -> dict:
        """What the server serves of the module's, and who uses it.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"is_active", "global", "shares", "users", "sessions",
            "disk_usage", "fence"}`` in the shapes the Linux module
            reports, ``global`` empty and ``fence`` ``{"is_present",
            "is_enabled", "blocked"}``.
        """
        status = self._read_status()
        return {
            "is_active": self.is_active(),
            "global": {},
            "shares": list(status.get("shares") or []),
            "users": list(status.get("users") or []),
            "sessions": list(status.get("sessions") or []),
            "disk_usage": SambaStatusReader().disk_usage(self._config or SambaConfig()),
            "fence": dict(status.get("fence") or {}),
        }

    def journal_text(self, lines: int) -> list:
        """The server's own log, then the agent's lines about the module.

        Args:
            lines: How many lines to return at most.

        Returns:
            The server's latest lines followed by the agent's, oldest
            first within each.
        """
        own = self._read_source(
            "the SMB server's events", lambda: self._applier.read_server_log(lines)
        )
        return self._with_agent_lines(own, lines)

    def command(self, verb: str, args: dict, on_line=None) -> dict:
        """Run one of the file share's verbs.

        Args:
            verb: ``set_password``, or ``validate``.
            args: ``{"name", "password"}``.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        if verb != SAMBA_COMMAND_SET_PASSWORD:
            return super().command(verb, args, on_line)
        name = str(args.get("name", ""))
        config = self._config or SambaConfig()
        record = self._read_record()
        if name not in config.users or name not in record["accounts"]:
            return command_outcome(1, "user_unknown", {"user": name})
        try:
            self._applier.set_password(name, str(args.get("password", "")))
        except ModuleApplyError as error:
            return command_outcome(1, error.code, dict(error.params))
        except (OSError, subprocess.SubprocessError) as error:
            return command_outcome(
                1, "command_failed", {"detail": command_detail(error)[:500]}
            )
        finally:
            self._forget_status()
        record = self._read_record()
        if name not in record["passworded"]:
            self._write_record(dict(record, passworded=record["passworded"] + [name]))
        return command_outcome(0, output=f"password set for {name}\n")

    def _read_status(self) -> dict:
        """The server's state, read again once the last reading is stale."""
        with self._lock:
            now = self._clock()
            if (
                self._status is not None
                and now - self._status_at < SAMBA_NATIVE_STATUS_TTL_S
            ):
                return self._status
        status = self._applier.read_status(self._read_record())
        with self._lock:
            self._status, self._status_at = status, self._clock()
        return status

    def _forget_status(self) -> None:
        with self._lock:
            self._status = None

    def _read_record(self) -> dict:
        """The record, ``{"shares", "accounts", "passworded", "is_served"}``.

        Empty when none.
        """
        try:
            with open(self._record_path, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            held = {}
        held = held if isinstance(held, dict) else {}
        shares = held.get("shares")
        return {
            "shares": dict(shares) if isinstance(shares, dict) else {},
            "accounts": [str(name) for name in held.get("accounts") or []],
            "passworded": [str(name) for name in held.get("passworded") or []],
            "is_served": bool(held.get("is_served", False)),
        }

    def _write_record(self, record: dict) -> None:
        """Keep the record, root-only, whole or not at all."""
        directory = os.path.dirname(self._record_path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".samba_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(record, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._record_path)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
