"""The file share on macOS's own SMB server.

The server is Apple's smbd, enabled through launchd. Share points are made
with ``sharing``, their record names starting with the module's prefix, SMB
only, no guest, never encrypted. Accounts are made with ``sysadminctl``,
without a login shell or a home, hidden, and given an SMB password with the
NT hash turned on first. Folders are granted with ``chmod +a``. The fence is
a pf sub-anchor under ``com.apple``, loaded from a file under the work root
at every apply and again when the agent starts, since pf forgets it at boot.

``sysadminctl`` and ``dscl`` take a password only on the command line, so a
password set here is visible in the process list while the command runs.

Not pure: runs launchctl, sharing, sysadminctl, dscl, pwpolicy, chmod,
pfctl, lsof and log.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_DARWIN_ACCESS_GROUP,
    SAMBA_DARWIN_ACCOUNT_KEYS,
    SAMBA_DARWIN_ACCOUNT_NAME,
    SAMBA_DARWIN_LOG_PREFIX,
    SAMBA_DARWIN_ACL_CHANGE,
    SAMBA_DARWIN_ACL_READ,
    SAMBA_DARWIN_HOME,
    SAMBA_DARWIN_PF_ANCHOR,
    SAMBA_DARWIN_PF_TABLE,
    SAMBA_LOOPBACK_NETWORKS,
    SAMBA_DARWIN_SERVER_LOG_COMMAND,
    SAMBA_DARWIN_SHARE_PREFIX,
    SAMBA_DARWIN_SHELL,
    SAMBA_DARWIN_SMBD_PLIST,
    SAMBA_DARWIN_SMBD_TARGET,
)
from neutrino_agent.modules.subprocess_run import run as run_command

# One established connection to the server in ``lsof -nP`` output: the
# peer's address after the arrow.
LSOF_PEER_PATTERN = re.compile(r":445->(\[?[0-9A-Fa-f:.]+\]?):\d+")
# The NT hash turned on for an account, as its authentication authority
# lists the hash types it keeps.
SMB_NT_HASH = "SMB-NT"


def render_pf_rules(allowed_subnets: list) -> str:
    """The fence's pf rules: SMB from loopback and the allowed subnets, nothing else.

    Args:
        allowed_subnets: The networks the shares answer; an entry that is
            no network is left out, which blocks more.

    Returns:
        The anchor's rules, one per line.
    """
    networks = []
    for subnet in allowed_subnets:
        try:
            networks.append(
                str(ipaddress.ip_network(str(subnet).strip(), strict=False))
            )
        except ValueError:
            continue
    loopback = ", ".join(SAMBA_LOOPBACK_NETWORKS)
    lines = [f"pass in quick proto tcp from {{ {loopback} }} to any port 445"]
    if networks:
        lines.append(
            f"table <{SAMBA_DARWIN_PF_TABLE}> const {{ {', '.join(networks)} }}"
        )
        lines.append(
            f"pass in quick proto tcp from <{SAMBA_DARWIN_PF_TABLE}> to any port 445"
        )
    lines.append("block drop in quick proto tcp from any to any port 445")
    return "\n".join(lines) + "\n"


def parse_share_points(text: str) -> list:
    """The share points ``sharing -l -f json`` lists.

    Args:
        text: What the command printed: an object keyed by record name, or
            a list of objects each naming itself. The SMB name and the
            read-only flag are read from ``smb_name`` and ``smb_read_only``,
            or from an ``smb`` object's ``name`` and ``read-only``.

    Returns:
        ``[{"record", "path", "smb_name", "is_read_only"}]``; empty when the
        output is not JSON.
    """
    try:
        listed = json.loads(text or "")
    except ValueError:
        return []
    if isinstance(listed, dict):
        entries = [
            dict(value, name=value.get("name", key))
            for key, value in listed.items()
            if isinstance(value, dict)
        ]
    elif isinstance(listed, list):
        entries = [entry for entry in listed if isinstance(entry, dict)]
    else:
        entries = []
    points = []
    for entry in entries:
        smb = entry.get("smb") if isinstance(entry.get("smb"), dict) else {}
        record = str(entry.get("name", "") or "")
        smb_name = entry.get("smb_name", smb.get("name", ""))
        read_only = entry.get("smb_read_only", smb.get("read-only", 0))
        points.append(
            {
                "record": record,
                "path": str(entry.get("path", "") or ""),
                "smb_name": str(smb_name or record),
                "is_read_only": str(read_only).lower() in ("1", "true"),
            }
        )
    return points


def account_full_name(name: str) -> str:
    """The full name the module gives one of its accounts.

    Args:
        name: The account's short name.

    Returns:
        The module's words followed by the short name.
    """
    return f"{SAMBA_DARWIN_ACCOUNT_NAME} {name}"


def is_module_full_name(full_name: str) -> bool:
    """Whether a full name is one the module gives its accounts.

    Args:
        full_name: An account's full name.

    Returns:
        True for the module's words alone, as earlier builds wrote them,
        or followed by a short name.
    """
    return full_name == SAMBA_DARWIN_ACCOUNT_NAME or full_name.startswith(
        SAMBA_DARWIN_ACCOUNT_NAME + " "
    )


def tool_line(result) -> str:
    """The last line a tool printed, without NSLog's prefix.

    Args:
        result: The tool's :class:`CommandResult`.

    Returns:
        The last non-empty line of its standard error, else of its
        standard output, else the tool's name and exit status.
    """
    for text in (result.stderr, result.stdout):
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if lines:
            return re.sub(SAMBA_DARWIN_LOG_PREFIX, "", lines[-1])[:500]
    return f"{result.command[0]} exited {result.exit_code}"


class SambaDarwinApplier:
    """Converges macOS's SMB server with the module's configuration."""

    def __init__(self, *, rules_path: str, run=None):
        """
        Args:
            rules_path: Where the fence's pf rules are kept between loads.
            run: Runs one command as :func:`subprocess_run.run` does; None
                runs it.
        """
        self._rules_path = rules_path
        self._run = run if run is not None else run_command

    def read_status(self, record: dict) -> dict:
        """What the server holds of the module's, read now.

        Args:
            record: The module's record: ``{"shares", "accounts"}``.

        Returns:
            ``{"is_present", "is_running", "shares", "sessions", "users",
            "fence"}``; ``is_present`` false without smbd's job or when
            launchctl cannot run.
        """
        if not os.path.isfile(SAMBA_DARWIN_SMBD_PLIST):
            return {"is_present": False, "is_running": False}
        try:
            return self._read_status(record)
        except (OSError, subprocess.SubprocessError):
            return {"is_present": False, "is_running": False}

    def apply(self, config: SambaConfig, record: dict) -> list:
        """Make the server serve the configuration, and nothing else of ours.

        An account is the module's when the record lists it or its full name
        is the module's; a record of the account's name that the module did
        not make, a bare one included, is refused. A share point is the
        module's when the record lists its name and its record name has the module's prefix. Each share
        keeps one point: a matching one stays, the others of its name go.

        Args:
            config: The validated configuration.
            record: The module's record: ``{"shares", "accounts"}``.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``share_name_taken`` or ``user_name_taken`` for
                a name the module did not make, before anything is touched;
                ``user_create_failed`` or ``user_record_unusable`` for the
                first account the system would not make, once every other
                account and every share is applied.
            OSError: When a command cannot run.
            subprocess.CalledProcessError: When a command refuses.
        """
        owned_shares = dict(record.get("shares") or {})
        owned_accounts = list(record.get("accounts") or [])
        points = self._share_points()
        for share in config.shares:
            held = [point for point in points if point["smb_name"] == share.name]
            is_ours = share.name in owned_shares and all(
                point["record"].startswith(SAMBA_DARWIN_SHARE_PREFIX) for point in held
            )
            if held and not is_ours:
                raise ModuleApplyError("share_name_taken", {"name": share.name})
        for name in config.users:
            if name in owned_accounts or not self._record_exists(name):
                continue
            if not is_module_full_name(self._full_name(name)):
                raise ModuleApplyError("user_name_taken", {"user": name})
        notes = self._serve()
        self._load_fence(render_pf_rules(config.allowed_subnets))
        account_notes, refusals = self._converge_accounts(config, owned_accounts)
        notes += account_notes
        refused = {refusal.params["user"] for refusal in refusals}
        notes += self._converge_shares(
            config, owned_shares, owned_accounts, points, refused=refused
        )
        if refusals:
            raise refusals[0]
        return notes

    def withdraw(self, record: dict, *, is_removed: bool) -> None:
        """Take the module's share points off the server.

        Args:
            record: The module's record: ``{"shares", "accounts"}``.
            is_removed: Also disable the module's accounts and empty the
                fence, as an uninstall does.

        Raises:
            OSError: When a command cannot run.
            subprocess.CalledProcessError: When a command refuses.
        """
        owned = set(record.get("shares") or {})
        for point in self._share_points():
            if point["smb_name"] in owned and point["record"].startswith(
                SAMBA_DARWIN_SHARE_PREFIX
            ):
                self._run(["sharing", "-r", point["record"]])
        if not is_removed:
            return
        for name in record.get("accounts") or []:
            self._run(["pwpolicy", "-u", name, "-disableuser"], is_checked=False)
        self._run(
            ["pfctl", "-a", SAMBA_DARWIN_PF_ANCHOR, "-F", "all"], is_checked=False
        )
        if os.path.exists(self._rules_path):
            os.unlink(self._rules_path)

    def set_password(self, name: str, password: str) -> None:
        """Set one of the module's accounts' SMB password and enable it.

        An account that does not exist yet is made first, as an apply makes
        it. The account is enabled before the password is set, since
        ``dscl`` refuses a disabled one, and the NT hash is turned on
        before it, or the server has no hash to check it against.

        Args:
            name: An account the record lists.
            password: The new password.

        Raises:
            ModuleApplyError: ``user_create_failed`` when the system would
                not make the account.
            OSError: When a command cannot run.
            subprocess.CalledProcessError: When a command refuses.
        """
        self._ensure_account(name, has_access_group=self._has_access_group())
        self._run(["pwpolicy", "-u", name, "-enableuser"], is_checked=False)
        self._run(["pwpolicy", "-u", name, "-sethashtypes", SMB_NT_HASH, "on"])
        self._run(["dscl", ".", "-passwd", f"/Users/{name}", password])

    def read_server_log(self, lines: int) -> list:
        """What the unified log holds of smbd over the last 15 minutes.

        Args:
            lines: How many lines to return at most.

        Returns:
            The latest lines, oldest first, without ``log``'s header.

        Raises:
            OSError: When ``log`` cannot run or fails.
            subprocess.SubprocessError: When ``log`` does not answer in time.
        """
        result = self._run(list(SAMBA_DARWIN_SERVER_LOG_COMMAND), is_checked=False)
        if not result.is_success:
            raise OSError(
                f"log exited {result.exit_code}: {result.stderr.strip()[-200:]}"
            )
        held = [
            line
            for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("Timestamp")
        ]
        return held[-lines:] if lines > 0 else []

    def reload_fence(self) -> None:
        """Load the kept fence into pf again, as the agent does at start.

        Raises:
            OSError: When pfctl cannot run.
        """
        if os.path.isfile(self._rules_path):
            self._load_rules_file()

    def _read_status(self, record: dict) -> dict:
        """The status once smbd's job is known to be there.

        A user has a password once the record lists it under ``passworded``
        and its NT hash is on.
        """
        owned = set(record.get("shares") or {})
        passworded = set(record.get("passworded") or [])
        shares: dict = {}
        for point in self._share_points():
            if not point["record"].startswith(SAMBA_DARWIN_SHARE_PREFIX):
                continue
            if point["smb_name"] not in owned or point["smb_name"] in shares:
                continue
            shares[point["smb_name"]] = {
                "name": point["smb_name"],
                "path": point["path"],
                "params": {
                    "comment": "",
                    "read only": "Yes" if point["is_read_only"] else "No",
                    "valid users": "",
                },
            }
        return {
            "is_present": True,
            "is_running": self._is_loaded(),
            "shares": list(shares.values()),
            "sessions": self._sessions(),
            "users": [
                {
                    "name": name,
                    "is_present": self._is_usable(name),
                    "has_password": name in passworded
                    and SMB_NT_HASH
                    in self._read(
                        [
                            "dscl",
                            ".",
                            "-read",
                            f"/Users/{name}",
                            "AuthenticationAuthority",
                        ]
                    ),
                }
                for name in record.get("accounts") or []
            ],
            "fence": self._fence(),
        }

    def _serve(self) -> list:
        """Enable smbd and make sure launchd holds it."""
        self._run(["launchctl", "enable", SAMBA_DARWIN_SMBD_TARGET])
        if self._is_loaded():
            return []
        self._run(
            ["launchctl", "bootstrap", "system", SAMBA_DARWIN_SMBD_PLIST],
            is_checked=False,
        )
        self._run(["launchctl", "kickstart", SAMBA_DARWIN_SMBD_TARGET])
        return ["started the server"]

    def _load_fence(self, rules: str) -> None:
        """Keep the rules under the work root and load them."""
        directory = os.path.dirname(self._rules_path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        temporary = self._rules_path + ".new"
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(rules)
        os.chmod(temporary, 0o600)
        os.replace(temporary, self._rules_path)
        self._load_rules_file()

    def _load_rules_file(self) -> None:
        """Load the kept rules into the anchor and turn pf on if it is off."""
        self._run(["pfctl", "-a", SAMBA_DARWIN_PF_ANCHOR, "-f", self._rules_path])
        if "Status: Enabled" not in self._read(["pfctl", "-s", "info"]):
            self._run(["pfctl", "-E"])

    def _converge_accounts(self, config: SambaConfig, owned: list) -> tuple:
        """Make every configured account, hidden and in the SMB group.

        An account the system will not make is passed over so the others
        are still made.

        Returns:
            ``(notes, refusals)``: what changed, and one
            :class:`ModuleApplyError` per account passed over.
        """
        notes = []
        refusals = []
        has_access_group = self._has_access_group()
        for name in config.users:
            try:
                note = self._ensure_account(name, has_access_group=has_access_group)
            except ModuleApplyError as refusal:
                refusals.append(refusal)
                notes.append(f"passed over account {name}: {refusal.code}")
                continue
            if note:
                notes.append(note)
        for name in owned:
            if name not in config.users:
                self._run(["pwpolicy", "-u", name, "-disableuser"], is_checked=False)
                notes.append(f"retired {name}")
        return notes, refusals

    def _has_access_group(self) -> bool:
        return self._run(
            ["dscl", ".", "-read", f"/Groups/{SAMBA_DARWIN_ACCESS_GROUP}"],
            is_checked=False,
        ).is_success

    def _ensure_account(self, name: str, *, has_access_group: bool) -> str:
        """Make one of the module's accounts usable, hidden, in the SMB group.

        A record of the name that is not a usable account, which a failed
        attempt of an earlier build left, is deleted and the account made
        again. Callers have refused a record the module did not make.

        Returns:
            What changed, empty when the account was already usable.

        Raises:
            ModuleApplyError: ``user_record_unusable`` with the system's own
                line when such a record cannot be deleted, which macOS 15
                answers even to root; ``user_create_failed`` when the
                system would not make the account.
        """
        if self._is_usable(name):
            self._settle_account(name, has_access_group=has_access_group)
            return ""
        if self._record_exists(name):
            deleted = self._run(
                ["dscl", ".", "-delete", f"/Users/{name}"], is_checked=False
            )
            if not deleted.is_success:
                raise ModuleApplyError(
                    "user_record_unusable",
                    {"user": name, "detail": tool_line(deleted)},
                )
            self._make_account(name, has_access_group=has_access_group)
            return f"made account {name} again"
        self._make_account(name, has_access_group=has_access_group)
        return f"created account {name}"

    def _make_account(self, name: str, *, has_access_group: bool) -> None:
        """Make one account with a random password, hidden, in the SMB group.

        sysadminctl can refuse and still exit 0, so the record is read back.

        Raises:
            ModuleApplyError: ``user_create_failed`` with the tool's own
                line when the record is not a usable account afterwards.
        """
        result = self._run(
            [
                "sysadminctl",
                "-addUser",
                name,
                "-fullName",
                account_full_name(name),
                "-shell",
                SAMBA_DARWIN_SHELL,
                "-home",
                SAMBA_DARWIN_HOME,
                "-password",
                secrets.token_urlsafe(24),
            ],
            is_checked=False,
        )
        if not self._is_usable(name):
            raise ModuleApplyError(
                "user_create_failed", {"user": name, "detail": tool_line(result)}
            )
        self._settle_account(name, has_access_group=has_access_group)

    def _settle_account(self, name: str, *, has_access_group: bool) -> None:
        """Hide one account and put it in the SMB group where there is one."""
        self._run(["dscl", ".", "-create", f"/Users/{name}", "IsHidden", "1"])
        if has_access_group:
            self._run(
                [
                    "dseditgroup",
                    "-o",
                    "edit",
                    "-a",
                    name,
                    "-t",
                    "user",
                    SAMBA_DARWIN_ACCESS_GROUP,
                ]
            )

    def _converge_shares(
        self,
        config: SambaConfig,
        owned: dict,
        accounts: list,
        points: list,
        *,
        refused: "set | None" = None,
    ) -> list:
        """Keep one point per configured share, and remove the module's others.

        An account in ``refused`` does not exist as one, so no folder names
        it.
        """
        refused = refused or set()
        notes = []
        wanted = {share.name for share in config.shares}
        ours = [
            point
            for point in points
            if point["record"].startswith(SAMBA_DARWIN_SHARE_PREFIX)
        ]
        for name in sorted(set(owned) - wanted):
            held = [point for point in ours if point["smb_name"] == name]
            for point in held:
                self._run(["sharing", "-r", point["record"]])
            if held:
                notes.append(f"removed share {name}")
        known = accounts + [name for name in config.users if name not in accounts]
        known = [name for name in known if name not in refused]
        for share in config.shares:
            granted = [
                name
                for name in share.valid_users or config.users
                if name not in refused
            ]
            self._run(["mkdir", "-p", share.path])
            for name in known:
                for entry in (SAMBA_DARWIN_ACL_CHANGE, SAMBA_DARWIN_ACL_READ):
                    self._run(
                        ["chmod", "-a", f"user:{name} allow {entry}", share.path],
                        is_checked=False,
                    )
            entry = (
                SAMBA_DARWIN_ACL_READ if share.is_read_only else SAMBA_DARWIN_ACL_CHANGE
            )
            for name in granted:
                self._run(["chmod", "+a", f"user:{name} allow {entry}", share.path])
            held = [point for point in ours if point["smb_name"] == share.name]
            kept = _kept_point(held, share)
            for point in held:
                if point is not kept:
                    self._run(["sharing", "-r", point["record"]])
                    notes.append(f"removed share point {point['record']}")
            if kept is not None:
                continue
            command = [
                "sharing",
                "-a",
                share.path,
                "-S",
                share.name,
                "-n",
                SAMBA_DARWIN_SHARE_PREFIX + share.name,
                "-s",
                "001",
                "-g",
                "000",
            ]
            if share.is_read_only:
                command += ["-R", "1"]
            self._run(command)
            notes.append(f"created share {share.name}")
        return notes

    def _share_points(self) -> list:
        return parse_share_points(self._read(["sharing", "-l", "-f", "json"]))

    def _is_loaded(self) -> bool:
        return self._run(
            ["launchctl", "print", SAMBA_DARWIN_SMBD_TARGET], is_checked=False
        ).is_success

    def _record_exists(self, name: str) -> bool:
        return self._run(
            ["dscl", ".", "-read", f"/Users/{name}", "RecordName"], is_checked=False
        ).is_success

    def _is_usable(self, name: str) -> bool:
        """Whether the account's record holds every key a sign-in needs."""
        text = self._read(
            ["dscl", ".", "-read", f"/Users/{name}", *SAMBA_DARWIN_ACCOUNT_KEYS]
        )
        return all(
            re.search(rf"^{key}:", text, re.MULTILINE)
            for key in SAMBA_DARWIN_ACCOUNT_KEYS
        )

    def _full_name(self, name: str) -> str:
        text = self._read(["dscl", ".", "-read", f"/Users/{name}", "RealName"])
        return " ".join(text.partition(":")[2].split())

    def _sessions(self) -> list:
        text = self._read(["lsof", "-nP", "-iTCP:445", "-sTCP:ESTABLISHED"])
        return [
            {
                "username": "",
                "hostname": address.strip("[]"),
                "remote_address": address.strip("[]"),
                "shares": [],
            }
            for address in LSOF_PEER_PATTERN.findall(text)
        ]

    def _fence(self) -> dict:
        rules = self._read(["pfctl", "-a", SAMBA_DARWIN_PF_ANCHOR, "-s", "rules"])
        is_enabled = "Status: Enabled" in self._read(["pfctl", "-s", "info"])
        return {
            "is_present": bool(rules.strip()),
            "is_enabled": is_enabled,
            "blocked": [],
        }

    def _read(self, command: list) -> str:
        """One command's output, empty when it fails or cannot run."""
        try:
            result = self._run(command, is_checked=False)
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout if result.is_success else ""


def _kept_point(held: list, share) -> "dict | None":
    """The one point of a share's that already serves it as configured.

    Args:
        held: The module's points of the share's name.
        share: The configured share.

    Returns:
        The point with the share's path and read-only flag, the one under
        the module's own record name first; None when no point matches.
    """
    matching = [
        point
        for point in held
        if point["path"] == share.path and point["is_read_only"] == share.is_read_only
    ]
    for point in matching:
        if point["record"] == SAMBA_DARWIN_SHARE_PREFIX + share.name:
            return point
    return matching[0] if matching else None
