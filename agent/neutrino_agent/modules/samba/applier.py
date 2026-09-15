"""Making the share configuration true on the machine.

Three effects, kept apart from the pure renderer: converging system
accounts with the configured user list, installing a rendered ``smb.conf``,
and reading what the server is doing right now.

Accounts are converged, not scripted: apply looks at what exists and closes
the gap. A user removed from the configuration loses share access, the
credential and the group membership, but the unix account stands, because
deleting accounts is how files end up owned by a recycled uid.

Not pure: writes ``/etc/samba``, runs Samba's tools and drives the unit.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import SAMBA_CONF_PATH, SAMBA_GROUP
from neutrino_agent.modules.subprocess_run import CommandResult, run, unit_state

# One row of ``smbstatus -p``: pid, user, group, then the client's name with
# its address in parentheses.
SESSION_ROW_PATTERN = re.compile(r"^(\S+)\s+(\S+)\s+\S+\s+(\S+) \(([^)]+)\)")
# A section header in what ``testparm -s`` prints.
SECTION_PATTERN = re.compile(r"^\[(.+)\]\s*$")
GLOBAL_SECTION = "global"
# The shares Samba serves for printing, which a file share never declares.
PRINTER_SECTIONS = ("printers", "print$")


@dataclass
class SambaUserState:
    """One configured user, as the machine actually has them.

    Attributes:
        name: The account name.
        is_present: Whether the unix account exists yet.
        has_password: Whether Samba holds a credential for it.
    """

    name: str
    is_present: bool
    has_password: bool


def ensure_share_group() -> None:
    """Make sure the group every share account joins exists."""
    if run(["getent", "group", SAMBA_GROUP], is_checked=False).is_success:
        return
    run(["groupadd", "--system", SAMBA_GROUP], is_checked=False)


def testparm(rendered: str) -> None:
    """Have Samba itself check a rendered file.

    Args:
        rendered: The full ``smb.conf`` text.

    Raises:
        ModuleApplyError: ``samba_config_rejected`` with Samba's own words,
            or ``samba_missing`` when testparm is not on the machine.
    """
    if shutil.which("testparm") is None:
        raise ModuleApplyError("samba_missing")
    handle, path = tempfile.mkstemp(prefix="smb_", suffix=".conf")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(rendered)
        result = run(["testparm", "-s", path], is_checked=False)
    finally:
        os.unlink(path)
    if not result.is_success:
        raise ModuleApplyError(
            "samba_config_rejected", {"detail": result.stderr.strip()[-500:]}
        )


def parse_smb_conf(text: str) -> tuple:
    """The global section and the shares in what ``testparm -s`` printed.

    Args:
        text: The normalized configuration, one ``key = value`` per line
            under ``[section]`` headers; comments and blank lines are
            skipped, and the printer sections are not shares.

    Returns:
        ``(global, shares)``: the global parameters by name, and one
        ``{"name", "path", "params"}`` per share in the order printed, the
        params being every parameter but the path.
    """
    sections: dict = {}
    order: list = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        header = SECTION_PATTERN.match(stripped)
        if header:
            current = header.group(1).strip()
            if current not in sections:
                sections[current] = {}
                order.append(current)
            continue
        if current is None or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        sections[current][key.strip()] = value.strip()
    shares = []
    for name in order:
        if name == GLOBAL_SECTION or name in PRINTER_SECTIONS:
            continue
        params = dict(sections[name])
        shares.append({"name": name, "path": params.pop("path", ""), "params": params})
    return dict(sections.get(GLOBAL_SECTION, {})), shares


class SambaConfigReader:
    """Reads the configuration Samba actually runs with."""

    def read(self) -> tuple:
        """Have Samba print its live configuration, normalized, and parse it.

        Returns:
            ``(global, shares)`` as :func:`parse_smb_conf` gives them; both
            empty when testparm is not there or refuses the file.
        """
        if shutil.which("testparm") is None or not os.path.isfile(SAMBA_CONF_PATH):
            return {}, []
        try:
            result = run(["testparm", "-s", SAMBA_CONF_PATH], is_checked=False)
        except (OSError, subprocess.SubprocessError):
            return {}, []
        if not result.is_success:
            return {}, []
        return parse_smb_conf(result.stdout)


def _json_object(text: str) -> "dict | None":
    try:
        status = json.loads(text)
    except ValueError:
        return None
    return status if isinstance(status, dict) else None


def _table_rows(text: str) -> list:
    # smbstatus prints a header, a rule of dashes, then one row per line
    # until a blank line.
    rows: list = []
    is_below_rule = False
    for line in text.splitlines():
        if not is_below_rule:
            is_below_rule = line.startswith("---")
        elif line.strip():
            rows.append(line)
        else:
            break
    return rows


def _session_entry(*, username: str, hostname: str, address: str, shares: list) -> dict:
    return {
        "username": username,
        "hostname": hostname,
        "remote_address": _strip_port(address),
        "shares": sorted(shares),
    }


def _strip_port(machine: str) -> str:
    # smbstatus reports the peer as ipv4:192.168.100.2:44510.
    if machine.startswith("ipv4:"):
        machine = machine[len("ipv4:") :]
    return machine.rsplit(":", 1)[0] if ":" in machine else machine


class SambaUserManager:
    """Converges accounts with the configured user list."""

    def survey(self, users: list) -> list:
        """Read each configured user's actual state.

        Args:
            users: The configured user names.

        Returns:
            One :class:`SambaUserState` per configured user, in order.
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

    def converge(self, users: list) -> list:
        """Make the system match the configured user list.

        Args:
            users: The configured user names.

        Returns:
            Notes on what was changed, empty when nothing was.

        Raises:
            subprocess.CalledProcessError: If an account cannot be created or retired.
        """
        changes = []
        for name in users:
            if not self._account_exists(name):
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
            password: The new password, which goes to Samba's credential
                store and nowhere else.

        Raises:
            subprocess.CalledProcessError: If Samba refuses.
        """
        run(["smbpasswd", "-s", "-a", name], input_text=f"{password}\n{password}\n")
        run(["smbpasswd", "-e", name])

    def credentialed_users(self) -> list:
        """Every account Samba holds a credential for, as ``pdbedit -L`` lists them.

        Returns:
            The names in the order listed; empty when Samba cannot be asked.
        """
        try:
            result = run(["pdbedit", "-L"], is_checked=False)
        except (OSError, subprocess.SubprocessError):
            return []
        if not result.is_success:
            return []
        return [
            line.split(":", 1)[0] for line in result.stdout.splitlines() if ":" in line
        ]

    def _account_exists(self, name: str) -> bool:
        return run(["id", "-u", name], is_checked=False).is_success

    def _credentialed_users(self) -> set:
        return set(self.credentialed_users())


class SambaConfigApplier:
    """Installs a rendered ``smb.conf`` and puts it into effect."""

    def __init__(self, *, unit: str):
        """
        Args:
            unit: The unit this machine's Samba runs as.
        """
        self._unit = unit

    def apply(self, rendered: str, *, config: SambaConfig) -> str:
        """Validate, install and load the rendered configuration.

        Validation runs on a copy before the live file moves, so a bad
        render never takes the running server's configuration with it.

        Args:
            rendered: The full ``smb.conf`` text.
            config: The configuration it was rendered from, for the share
                directories to create.

        Returns:
            A short summary of what changed.

        Raises:
            ModuleApplyError: If Samba rejects the configuration.
            subprocess.CalledProcessError: If the unit will not come up.
        """
        testparm(rendered)
        self._ensure_share_directories(config)
        self._write(rendered)
        if unit_state(self._unit) == "active":
            run(["systemctl", "reload", self._unit])
            return "reloaded"
        run(["systemctl", "enable", "--now", self._unit])
        return "started"

    def stop(self) -> None:
        """Take the server down until the next apply; the unit stays enabled."""
        run(["systemctl", "stop", self._unit], is_checked=False)

    def _ensure_share_directories(self, config: SambaConfig) -> None:
        for share in config.shares:
            os.makedirs(share.path, exist_ok=True)
            shutil.chown(share.path, group=SAMBA_GROUP)
            # Setgid, so files created over the share inherit the shared
            # group rather than each creator's own.
            os.chmod(share.path, 0o2775)

    def _write(self, rendered: str) -> None:
        directory = os.path.dirname(SAMBA_CONF_PATH)
        os.makedirs(directory, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".smb_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(rendered)
            os.chmod(temporary, 0o644)
            if os.path.islink(SAMBA_CONF_PATH):
                os.unlink(SAMBA_CONF_PATH)
            os.replace(temporary, SAMBA_CONF_PATH)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise


class SambaStatusReader:
    """Reads what the server is doing right now."""

    def sessions(self) -> list:
        """List who is connected and to what.

        ``smbstatus --json`` is asked first; a Samba that does not know the
        flag is read from the tables ``smbstatus -p`` and ``smbstatus -S``
        print.

        Returns:
            One entry per session: user, machine, and the shares it has
            open. Empty when the server is down or has no visitors.
        """
        result = self._smbstatus("--json")
        if result is None:
            return []
        status = _json_object(result.stdout) if result.is_success else None
        if status is not None:
            return self._sessions_from_json(status)
        return self._sessions_from_tables()

    def disk_usage(self, config: SambaConfig) -> list:
        """Read how full each share's filesystem is.

        Args:
            config: The applied configuration.

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

    def _smbstatus(self, flag: str) -> "CommandResult | None":
        try:
            return run(["smbstatus", flag], is_checked=False, timeout_s=15)
        except (OSError, subprocess.SubprocessError):
            return None

    def _sessions_from_json(self, status: dict) -> list:
        shares_by_session: dict = {}
        for tcon in (status.get("tcons") or {}).values():
            session_id = str(tcon.get("session_id", ""))
            shares_by_session.setdefault(session_id, []).append(tcon.get("service", ""))
        return [
            _session_entry(
                username=session.get("username", ""),
                hostname=session.get("remote_machine", ""),
                address=session.get("hostname", ""),
                shares=shares_by_session.get(str(session_id), []),
            )
            for session_id, session in (status.get("sessions") or {}).items()
        ]

    def _sessions_from_tables(self) -> list:
        processes = self._smbstatus("-p")
        if processes is None or not processes.is_success:
            return []
        rows = []
        for line in _table_rows(processes.stdout):
            match = SESSION_ROW_PATTERN.match(line)
            if match is not None:
                rows.append(match.groups())
        if not rows:
            return []
        shares_by_pid = self._shares_by_pid({row[0] for row in rows})
        return [
            _session_entry(
                username=username,
                hostname=machine,
                address=address,
                shares=shares_by_pid.get(pid, []),
            )
            for pid, username, machine, address in rows
        ]

    def _shares_by_pid(self, pids: set) -> dict:
        # A share name may hold spaces: the first token naming a live
        # session's pid ends the name, and the tokens before it are the name.
        connections = self._smbstatus("-S")
        if connections is None or not connections.is_success:
            return {}
        shares: dict = {}
        for line in _table_rows(connections.stdout):
            tokens = line.split()
            for index in range(1, len(tokens)):
                if tokens[index] in pids:
                    shares.setdefault(tokens[index], []).append(
                        " ".join(tokens[:index])
                    )
                    break
        return shares
