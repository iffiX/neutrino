"""Making the share configuration true on the box.

Three effects live here, kept apart from the pure renderer: converging system
accounts with the configured user list, installing a rendered ``smb.conf``,
and reading what the server is doing right now.

Accounts are converged, not scripted: apply looks at what exists and closes
the gap, so applying twice does nothing twice. A user removed from the
configuration loses share access — credential and group membership — but the
unix account itself is left standing, because deleting accounts is how files
end up owned by a recycled uid.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.system.machine import distribution_family
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.constants import (
    SAMBA_CONF_LINK_PATH,
    SAMBA_GENERATED_NAME,
    SAMBA_GROUP,
    SAMBA_UNIT,
)

# The include file an earlier installer wrote next to smb.conf. The rendered
# file replaces the whole configuration, so the leftover would only confuse
# whoever reads the directory.
LEGACY_INCLUDE_PATH = Path("/etc/samba/neutrino_share.conf")

# Debian names the unit after the binary; RHEL and Arch ship one smb.service.
SMBD_SERVICE = SAMBA_UNIT.removesuffix(".service")


@dataclass
class SambaUserState:
    """One configured user, as the box actually has them.

    Attributes:
        name: The account name.
        is_present: Whether the unix account exists yet.
        has_password: Whether Samba holds a credential for it. False after a
            rebuild from backup — passwords are never in ``config/`` — and the
            page says so instead of letting the login just fail.
    """

    name: str
    is_present: bool
    has_password: bool


class SambaUserManager:
    """Converges accounts with the configured user list."""

    def survey(self, users: list[str]) -> list[SambaUserState]:
        """Read each configured user's actual state.

        Args:
            users: The configured user names.

        Returns:
            One entry per configured user, in the given order.
        """
        credentialed = self._credentialed_users()
        return [
            SambaUserState(
                name=name,
                is_present=self._account_exists(name),
                has_password=name in credentialed,
            )
            for name in users
        ]

    def converge(self, users: list[str]) -> list[str]:
        """Make the system match the configured user list.

        Args:
            users: The configured user names.

        Returns:
            Human-readable notes on what was changed, empty when nothing was.

        Raises:
            CommandError: If an account cannot be created or retired.
        """
        changes = []
        for name in users:
            if not self._account_exists(name):
                # No home and no shell: the account exists to own files on
                # shares and to hold a Samba credential, not to log in.
                run(
                    [
                        "useradd",
                        "--no-create-home",
                        "--shell",
                        "/usr/sbin/nologin",
                        name,
                    ]
                )
                changes.append(f"created account {name}")
            result = run(["id", "-nG", name])
            if SAMBA_GROUP not in result.stdout.split():
                run(["usermod", "-aG", SAMBA_GROUP, name])
                changes.append(f"added {name} to {SAMBA_GROUP}")

        for name in self._credentialed_users():
            if name not in users:
                run(["smbpasswd", "-x", name])
                run(["gpasswd", "-d", name, SAMBA_GROUP], is_checked=False)
                changes.append(f"retired {name}")
        return changes

    def set_password(self, name: str, password: str) -> None:
        """Set one user's share password.

        Args:
            name: A configured user whose unix account exists.
            password: The new password, which goes to Samba's credential store
                and nowhere else.

        Raises:
            CommandError: If Samba refuses — most often because the account
                does not exist yet, which apply is what fixes.
        """
        run(
            ["smbpasswd", "-s", "-a", name],
            input_text=f"{password}\n{password}\n",
        )
        # A freshly added credential can arrive disabled; make sure it is not.
        run(["smbpasswd", "-e", name])

    def _account_exists(self, name: str) -> bool:
        return run(["id", "-u", name], is_checked=False).is_success

    def _credentialed_users(self) -> set[str]:
        result = run(["pdbedit", "-L"], is_checked=False)
        if not result.is_success:
            return set()
        return {
            line.split(":", 1)[0] for line in result.stdout.splitlines() if ":" in line
        }


class SambaConfigApplier:
    """Installs a rendered ``smb.conf`` and puts it into effect."""

    def apply(self, rendered: str, *, config: SambaConfig) -> str:
        """Validate, install and load the rendered configuration.

        Validation happens against the generated copy before the live path
        moves, so a bad render can never take the running server's
        configuration with it.

        Args:
            rendered: The full ``smb.conf`` text.
            config: The configuration it was rendered from, for the share
                directories to create.

        Returns:
            A short summary of what changed.

        Raises:
            CommandError: If Samba rejects the configuration.
        """
        generated_path = UTILS_GENERATED_DIR / SAMBA_GENERATED_NAME
        write_generated(generated_path, rendered)
        result = run(["testparm", "-s", str(generated_path)], is_checked=False)
        if not result.is_success:
            raise CommandError(
                f"Samba rejected the configuration: {result.stderr.strip()}"
            )

        self._ensure_share_directories(config)
        self._link_config(generated_path)
        LEGACY_INCLUDE_PATH.unlink(missing_ok=True)

        # Reload rather than restart: shares appear and disappear without
        # dropping the connections that are moving files right now. Nothing to
        # do when the service is stopped; the file is in place for when it
        # starts.
        is_active = run(
            ["systemctl", "is-active", SMBD_SERVICE], is_checked=False
        ).stdout.strip()
        if is_active == "active":
            run(["systemctl", "reload", SMBD_SERVICE])
            return "reloaded smbd"
        return "smbd not running; configuration staged"

    def _ensure_share_directories(self, config: SambaConfig) -> None:
        for share in config.shares:
            path = Path(share.path)
            path.mkdir(parents=True, exist_ok=True)
            shutil.chown(path, group=SAMBA_GROUP)
            # Setgid, so files created over the share inherit the shared group
            # rather than each creator's own.
            path.chmod(0o2775)

    def _link_config(self, generated_path: Path) -> None:
        if (
            SAMBA_CONF_LINK_PATH.is_symlink()
            and SAMBA_CONF_LINK_PATH.readlink() == generated_path
        ):
            return
        SAMBA_CONF_LINK_PATH.unlink(missing_ok=True)
        SAMBA_CONF_LINK_PATH.symlink_to(generated_path)


class SambaStatusReader:
    """Reads what the server is doing right now."""

    def sessions(self) -> list[dict]:
        """List who is connected and to what.

        Returns:
            One entry per session: user, machine, and the shares it has open.
            Empty when the server is down or has no visitors.
        """
        result = run(["smbstatus", "--json"], is_checked=False)
        if not result.is_success:
            return []
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        shares_by_session: dict[str, list[str]] = {}
        for tcon in (status.get("tcons") or {}).values():
            session_id = str(tcon.get("session_id", ""))
            shares_by_session.setdefault(session_id, []).append(tcon.get("service", ""))
        sessions = []
        for session_id, session in (status.get("sessions") or {}).items():
            sessions.append(
                {
                    "username": session.get("username", ""),
                    "hostname": session.get("hostname", ""),
                    "remote_address": _strip_port(session.get("remote_machine", "")),
                    "shares": sorted(shares_by_session.get(str(session_id), [])),
                }
            )
        return sessions

    def disk_usage(self, config: SambaConfig) -> list[dict]:
        """Read how full each share's filesystem is.

        Returns:
            One entry per share that exists on disk.
        """
        usage = []
        for share in config.shares:
            try:
                measured = shutil.disk_usage(share.path)
            except OSError:
                continue
            usage.append(
                {
                    "share": share.name,
                    "total_bytes": measured.total,
                    "free_bytes": measured.free,
                }
            )
        return usage


def _strip_port(machine: str) -> str:
    # smbstatus reports the peer as ipv4:192.168.100.2:44510.
    if machine.startswith("ipv4:"):
        machine = machine[len("ipv4:") :]
    return machine.rsplit(":", 1)[0] if ":" in machine else machine
