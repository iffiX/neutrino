"""Making the share configuration true on the machine.

Three effects, kept apart from the pure renderer: setting each SMB user's
Samba password, installing the module's own file and the one line of
``smb.conf`` that includes it, and reading what the server is doing right
now. ``smb.conf`` itself stays the person's: the module adds that line once
after the ``[global]`` header and takes it out at uninstall, and a whole
``smb.conf`` an earlier version rendered gives way to the copy kept before
it or to the distribution's stock file.

Each SMB user is a system account of the module's own, ``neutrino-`` and
the person's account, made with no home and no login shell; its share writes
every file as the person's account. Its Samba password is set from the one
the hub generated whenever it differs from the one the module set last. A
user the module set a password for and that the configuration no longer
names loses that credential and, when the module made it, the account too;
the person's own account is never touched.

Not pure: writes ``/etc/samba``, runs Samba's tools and drives the unit.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_CONF_BACKUP_PATH,
    SAMBA_CONF_MARKER,
    SAMBA_CONF_PATH,
    SAMBA_DOMAIN_SECURITY_MODES,
    SAMBA_DOMAIN_SERVER_ROLES,
    SAMBA_LINUX_NOLOGIN_SHELLS,
    SAMBA_LINUX_USER_COMMENT,
    SAMBA_MINIMAL_CONF,
    SAMBA_MODULE_CONF_PATH,
    SAMBA_STOCK_CONF_PATHS,
    SAMBA_USERS_DIR,
    SAMBA_USERS_FILE_SUFFIX,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult, run, unit_state

try:
    import pwd
except ImportError:  # Windows carries no pwd.
    pwd = None

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


def password_digest(password: str) -> str:
    """What the module keeps of a password it set: its SHA-256 in hex.

    Args:
        password: The password.

    Returns:
        The digest.
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def read_text(path: str) -> "str | None":
    """A file's text, or None when it is not there or cannot be read."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as stream:
            return stream.read()
    except OSError:
        return None


def read_stock_conf() -> tuple:
    """The distribution's stock ``smb.conf``, for a machine that has none to keep.

    Returns:
        ``(text, source)``: the first of :data:`SAMBA_STOCK_CONF_PATHS` that
        is there and its path, else a ``[global]`` of one line and its name.
    """
    for path in SAMBA_STOCK_CONF_PATHS:
        text = read_text(path)
        if text is not None:
            return text, f"the distribution's {path}"
    return SAMBA_MINIMAL_CONF, "a one-line [global]"


def include_line() -> str:
    """The one line of ``smb.conf`` that is the module's."""
    return f"   include = {SAMBA_MODULE_CONF_PATH}"


def is_include_line(line: str) -> bool:
    """Whether a line of ``smb.conf`` is the module's include line."""
    key, _, value = line.strip().partition("=")
    return key.strip().lower() == "include" and value.strip() == SAMBA_MODULE_CONF_PATH


def has_include_line(text: str) -> bool:
    """Whether ``smb.conf`` already includes the module's file."""
    return any(is_include_line(line) for line in text.splitlines())


def with_include_line(text: str) -> str:
    """``smb.conf`` with the module's include line after its ``[global]`` header.

    Args:
        text: The file without the line.

    Returns:
        The file with the line added once; a file with no ``[global]``
        header gets one, with the line, in front.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() == "[global]":
            lines.insert(index + 1, include_line())
            return "\n".join(lines) + "\n"
    return "[global]\n" + include_line() + "\n\n" + text


def without_include_line(text: str) -> str:
    """``smb.conf`` without the module's include line."""
    lines = [line for line in text.splitlines() if not is_include_line(line)]
    return "\n".join(lines) + ("\n" if lines else "")


def plan_smb_conf(
    current: "str | None", *, backup: "str | None", stock: tuple
) -> tuple:
    """What ``smb.conf`` is to hold so that it includes the module's file. Pure.

    Args:
        current: The file as it is, None when the machine has none.
        backup: The copy an earlier version kept before it replaced the
            file, None when there is none.
        stock: ``(text, source)`` as :func:`read_stock_conf` gives them.

    Returns:
        ``(text, note)``: the file to write, and what changed in words,
        empty when the file stays as it is. A file an earlier version
        rendered whole, its first line the marker, gives way to the backup
        when there is one, else to the stock text; a missing file is the
        stock text; and the include line is added once to whichever file
        lacks it.
    """
    notes = []
    text = current
    if text is None:
        text, source = stock
        notes.append(f"wrote {source}")
    elif text.split("\n", 1)[0].rstrip() == SAMBA_CONF_MARKER:
        if backup is not None:
            text = backup
            notes.append("put back smb.conf.before_neutrino")
        else:
            text, source = stock
            notes.append(f"put back {source}")
    if not has_include_line(text):
        text = with_include_line(text)
        notes.append("added the include line")
    return text, "; ".join(notes)


def testparm(smb_conf: str, rendered: str) -> None:
    """Have Samba check ``smb.conf`` as it will be with the module's file.

    Args:
        smb_conf: The ``smb.conf`` text, with the include line.
        rendered: The module's own file.

    Raises:
        ModuleApplyError: ``samba_config_rejected`` with Samba's own words,
            or ``samba_missing`` when testparm is not on the machine.
    """
    if shutil.which("testparm") is None:
        raise ModuleApplyError("samba_missing")
    directory = tempfile.mkdtemp(prefix="smb_")
    try:
        module_path = os.path.join(directory, "neutrino.conf")
        conf_path = os.path.join(directory, "smb.conf")
        with open(module_path, "w", encoding="utf-8") as stream:
            stream.write(rendered)
        with open(conf_path, "w", encoding="utf-8") as stream:
            stream.write(smb_conf.replace(SAMBA_MODULE_CONF_PATH, module_path))
        result = run(["testparm", "-s", conf_path], is_checked=False)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if not result.is_success:
        raise ModuleApplyError(
            "samba_config_rejected", {"detail": result.stderr.strip()[-500:]}
        )


def check_person_config(
    global_section: dict, shares: list, config: SambaConfig
) -> None:
    """Refuse what the person's own ``smb.conf`` makes impossible, changing nothing.

    Args:
        global_section: The person's ``[global]`` as testparm prints it.
        shares: The person's shares, each ``{"name", "path", "params"}``.
        config: The module's configuration.

    Raises:
        ModuleApplyError: ``share_name_taken {name}`` for a share of the
            person's with the name one of the module's takes;
            ``samba_hosts_allow_no_loopback`` for a ``hosts allow`` without
            the loopback; ``samba_interfaces_no_loopback`` for ``bind
            interfaces only`` whose ``interfaces`` has no ``lo``;
            ``samba_domain_member`` for a domain member's ``security`` or
            ``server role``.
    """
    ours = {share.name.lower() for share in config.shares}
    for share in shares:
        if str(share.get("name", "")).lower() in ours:
            raise ModuleApplyError("share_name_taken", {"name": share["name"]})
    allowed = global_section.get("hosts allow", "").replace(",", " ").split()
    if allowed and not any(_is_loopback_word(word) for word in allowed):
        raise ModuleApplyError("samba_hosts_allow_no_loopback")
    if global_section.get("bind interfaces only", "").lower() in ("yes", "true", "1"):
        interfaces = global_section.get("interfaces", "").replace(",", " ").split()
        if not any(word == "lo" or _is_loopback_word(word) for word in interfaces):
            raise ModuleApplyError("samba_interfaces_no_loopback")
    if (
        global_section.get("security", "").lower() in SAMBA_DOMAIN_SECURITY_MODES
        or global_section.get("server role", "").lower() in SAMBA_DOMAIN_SERVER_ROLES
    ):
        raise ModuleApplyError("samba_domain_member")


def _is_loopback_word(word: str) -> bool:
    lowered = word.lower()
    return lowered.startswith(("127.", "::1", "localhost"))


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
        return _testparm_output(SAMBA_CONF_PATH)

    def read_persons(self) -> tuple:
        """The person's own configuration: ``smb.conf`` without the module's line.

        Returns:
            ``(global, shares)`` of the file with the include line taken
            out, so the module's shares are not among them; both empty
            when there is no file or testparm is not there.
        """
        text = read_text(SAMBA_CONF_PATH)
        if text is None or shutil.which("testparm") is None:
            return {}, []
        handle, path = tempfile.mkstemp(prefix="smb_", suffix=".conf")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(without_include_line(text))
            return _testparm_output(path)
        finally:
            os.unlink(path)


def _testparm_output(path: str) -> tuple:
    try:
        result = run(["testparm", "-s", path], is_checked=False)
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


def nologin_shell() -> str:
    """The shell of an account that never signs in: the first of
    :data:`SAMBA_LINUX_NOLOGIN_SHELLS` this system has, else the last."""
    for shell in SAMBA_LINUX_NOLOGIN_SHELLS:
        if os.path.exists(shell):
            return shell
    return SAMBA_LINUX_NOLOGIN_SHELLS[-1]


class SambaUserManager:
    """Makes each configured SMB user and keeps its Samba password the one the hub generated."""

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

    def check_accounts(self, accounts: list) -> None:
        """Refuse an account the shares write as that the machine does not have.

        Args:
            accounts: The shares' forced users, the machine's own accounts.

        Raises:
            ModuleApplyError: ``account_unknown {account}`` for the first
                name the machine has no account of.
        """
        for name in accounts:
            if not self._account_exists(name):
                raise ModuleApplyError("account_unknown", {"account": name})

    def converge_accounts(self, config: SambaConfig) -> list:
        """Make every configured SMB user the machine does not have.

        Args:
            config: The configuration, with ``users``.

        Returns:
            One note per user made.

        Raises:
            subprocess.CalledProcessError: If ``useradd`` refuses.
        """
        changes = []
        for name in config.users:
            if self._account_exists(name):
                continue
            run(
                [
                    "useradd",
                    "--system",
                    "--no-create-home",
                    "--shell",
                    nologin_shell(),
                    "--comment",
                    SAMBA_LINUX_USER_COMMENT,
                    name,
                ]
            )
            changes.append(f"made the user {name}")
        return changes

    def converge(self, config: SambaConfig, held: dict) -> tuple:
        """Set every configured user's password that differs from the one set last.

        Args:
            config: The configuration, with ``passwords``.
            held: The digest of the password the module set last, by user.

        Returns:
            ``(changes, held)``: notes on what was changed, and the digests
            the module holds now. A user the module set a password for and
            the configuration no longer names has its Samba credential
            removed, and the account too when the module made it.

        Raises:
            subprocess.CalledProcessError: If Samba refuses a password or a
                removal, or ``userdel`` refuses.
        """
        changes = []
        kept = {name: digest for name, digest in held.items() if name in config.users}
        credentialed = self._credentialed_users()
        for name in config.users:
            password = config.passwords.get(name, "")
            if not password:
                continue
            digest = password_digest(password)
            if kept.get(name) == digest and name in credentialed:
                continue
            self.set_password(name, password)
            kept[name] = digest
            changes.append(f"set the password of {name}")
        for name in held:
            if name in config.users:
                continue
            if name in credentialed:
                run(["smbpasswd", "-x", name])
            if self._is_module_account(name):
                run(["userdel", name])
            changes.append(f"retired {name}")
        return changes, kept

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

    def _is_module_account(self, name: str) -> bool:
        """Whether the module made the account: its comment is the module's."""
        result = run(["getent", "passwd", name], is_checked=False)
        if not result.is_success:
            return False
        fields = result.stdout.strip().split(":")
        return len(fields) > 4 and fields[4] == SAMBA_LINUX_USER_COMMENT

    def _credentialed_users(self) -> set:
        return set(self.credentialed_users())


class SambaConfigApplier:
    """Writes the module's own file, keeps ``smb.conf`` including it, and loads both."""

    def __init__(self, *, unit: str):
        """
        Args:
            unit: The unit this machine's Samba runs as.
        """
        self._unit = unit

    def plan(self) -> tuple:
        """``smb.conf`` as the next apply leaves it.

        Returns:
            ``(text, note)`` as :func:`plan_smb_conf` gives them, for the
            file, the backup and the stock text on this machine.
        """
        return plan_smb_conf(
            read_text(SAMBA_CONF_PATH),
            backup=read_text(SAMBA_CONF_BACKUP_PATH),
            stock=read_stock_conf(),
        )

    def apply(
        self, rendered: str, *, config: SambaConfig, user_files: "dict | None" = None
    ) -> str:
        """Validate, install and load the module's file.

        Validation runs on copies before anything moves, so a bad render
        never takes the running server's configuration with it.

        Args:
            rendered: The module's own file.
            config: The configuration it was rendered from, for the share
                directories to create.
            user_files: The files under :data:`SAMBA_USERS_DIR` by name, as
                the renderer gives them; every other file there goes.

        Returns:
            A short summary of what changed.

        Raises:
            ModuleApplyError: If Samba rejects the configuration.
            subprocess.CalledProcessError: If the unit will not come up.
        """
        smb_conf, note = self.plan()
        testparm(smb_conf, rendered)
        self._ensure_share_directories(config)
        self._write_user_files(dict(user_files or {}))
        _write_file(SAMBA_MODULE_CONF_PATH, rendered)
        if smb_conf != read_text(SAMBA_CONF_PATH):
            _write_file(SAMBA_CONF_PATH, smb_conf)
            if "smb.conf.before_neutrino" in note:
                os.unlink(SAMBA_CONF_BACKUP_PATH)
        notes = [note] if note else []
        if unit_state(self._unit) == "active":
            run(["systemctl", "reload", self._unit])
            return "; ".join(notes + ["reloaded"])
        run(["systemctl", "enable", "--now", self._unit])
        return "; ".join(notes + ["started"])

    def remove(self) -> None:
        """Delete the module's file and its users' files, and take the include line out of ``smb.conf``."""
        with contextlib.suppress(OSError):
            os.unlink(SAMBA_MODULE_CONF_PATH)
        shutil.rmtree(SAMBA_USERS_DIR, ignore_errors=True)
        text = read_text(SAMBA_CONF_PATH)
        if text is not None and has_include_line(text):
            _write_file(SAMBA_CONF_PATH, without_include_line(text))

    def stop(self) -> None:
        """Take the server down until the next apply; the unit stays enabled."""
        run(["systemctl", "stop", self._unit], is_checked=False)

    def _ensure_share_directories(self, config: SambaConfig) -> None:
        """Make a share's folder that is missing, owned by its one user."""
        for share in config.shares:
            if os.path.isdir(share.path):
                continue
            os.makedirs(share.path, exist_ok=True)
            if len(share.valid_users) == 1 and pwd is not None:
                entry = pwd.getpwnam(share.valid_users[0])
                os.chown(share.path, entry.pw_uid, entry.pw_gid)

    def _write_user_files(self, user_files: dict) -> None:
        """Write each user's file under the users directory and drop the rest."""
        os.makedirs(SAMBA_USERS_DIR, exist_ok=True)
        os.chmod(SAMBA_USERS_DIR, 0o755)
        for name in os.listdir(SAMBA_USERS_DIR):
            if name.endswith(SAMBA_USERS_FILE_SUFFIX) and name not in user_files:
                os.unlink(os.path.join(SAMBA_USERS_DIR, name))
        for name, text in user_files.items():
            _write_file(os.path.join(SAMBA_USERS_DIR, name), text)


def _write_file(path: str, text: str) -> None:
    """Write a world-readable file in one move, in place of a symlink too."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".neutrino_")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, 0o644)
        if os.path.islink(path):
            os.unlink(path)
        os.replace(temporary, path)
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
