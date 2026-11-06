"""Making the share configuration true on the machine.

Four effects, kept apart from the pure renderer: setting each SMB user's
Samba password, installing the module's own file and the one line of
``smb.conf`` that includes it, turning the SELinux boolean on and off, and
reading what the server is doing right now. ``smb.conf`` itself stays the
person's, a whole file an earlier version
rendered included: the module adds that line once after the ``[global]``
header and takes it out at uninstall. At its first apply after an install
or an adoption the module sweeps every user of its own from the machine,
told by its comment, and its credential, and makes the wanted ones anew.

Each SMB user is a system account of the module's own, ``neutrino_`` and
the person's account, made with no home and no login shell; its share writes
every file as the person's account. Its Samba password is set from the one
the hub generated whenever it differs from the one the module set last. A
user the module set a password for and that the configuration no longer
names loses that credential and, when the module made it, the account too;
the person's own account is never touched.

Not pure: writes ``/etc/samba``, runs Samba's and SELinux's tools and drives the unit.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_CONF_PATH,
    SAMBA_CONF_MARKER,
    SAMBA_DOMAIN_SECURITY_MODES,
    SAMBA_EARLIER_GROUP,
    SAMBA_DOMAIN_SERVER_ROLES,
    SAMBA_GLOBAL_HEADER,
    SAMBA_LINUX_NOLOGIN_SHELLS,
    SAMBA_LINUX_USER_COMMENT,
    SAMBA_USER_PREFIXES,
    SAMBA_MINIMAL_CONF,
    SAMBA_MODULE_CONF_PATH,
    SAMBA_SELINUX_ACTIVE_MODES,
    SAMBA_SELINUX_BOOLEAN,
    SAMBA_SHARE_NAME_TAKEN_CODE,
    SAMBA_STOCK_CONF_PATHS,
    SAMBA_USERS_DIR,
    SAMBA_USERS_FILE_SUFFIX,
)
from neutrino_agent.modules.shared.subprocess_run import run, unit_state

# One row of ``smbstatus -p``: pid, user, group, then the client's name with
# its address in parentheses.
SESSION_ROW_PATTERN = re.compile(r"^(\S+)\s+(\S+)\s+\S+\s+(\S+) \(([^)]+)\)")
# A section header in what ``testparm -s`` prints.
SECTION_PATTERN = re.compile(r"^\[(.+)\]\s*$")
GLOBAL_SECTION = "global"
# The shares Samba serves for printing, which a file share never declares.
PRINTER_SECTIONS = ("printers", "print$")
# The user ids ``useradd`` gives an ordinary account, the ones a module of 0.5
# made.
EARLIER_UID_FIRST = 1000
EARLIER_UID_END = 60000


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


def read_bytes(path: str) -> "bytes | None":
    """A file's bytes, or None when it is not there or cannot be read."""
    try:
        with open(path, "rb") as stream:
            return stream.read()
    except OSError:
        return None


def read_stock_conf() -> tuple:
    """The distribution's stock ``smb.conf``, for a machine that has none to keep.

    Returns:
        ``(data, source)``: the first of :data:`SAMBA_STOCK_CONF_PATHS` that
        is there and its path, else a ``[global]`` of one line and its name.
    """
    for path in SAMBA_STOCK_CONF_PATHS:
        data = read_bytes(path)
        if data is not None:
            return data, f"the distribution's {path}"
    return SAMBA_MINIMAL_CONF.encode("utf-8"), "a one-line [global]"


def conf_digest() -> str:
    """The sha256 of ``smb.conf`` without the module's include line.

    Returns:
        The hex digest; empty when the machine has no file.
    """
    data = read_bytes(SAMBA_CONF_PATH)
    if data is None:
        return ""
    return hashlib.sha256(without_include_line(data)).hexdigest()


def remove_conf() -> None:
    """Delete ``smb.conf``; a file already gone stays gone."""
    with contextlib.suppress(OSError):
        os.unlink(SAMBA_CONF_PATH)


def include_line() -> bytes:
    """The one line of ``smb.conf`` that is the module's, without its ending."""
    return f"   include = {SAMBA_MODULE_CONF_PATH}".encode("utf-8")


def is_include_line(line: bytes) -> bool:
    """Whether a line of ``smb.conf`` is the module's include line."""
    key, _, value = line.strip().partition(b"=")
    return key.strip().lower() == b"include" and (
        value.strip() == SAMBA_MODULE_CONF_PATH.encode("utf-8")
    )


def has_include_line(data: bytes) -> bool:
    """Whether ``smb.conf`` already includes the module's file."""
    return any(is_include_line(line) for line in _conf_lines(data))


def with_include_line(data: bytes) -> bytes:
    """``smb.conf`` with the module's include line after its ``[global]`` header.

    Args:
        data: The file without the line.

    Returns:
        The file with the line added once and every other byte kept. The
        line ends as the file's first line ends. In a file with no
        ``[global]`` header the line comes first, and Samba reads a line
        before any section as a global line. After a header with no line
        ending the ending goes before the line, and the file still has no
        last newline.
    """
    lines = _conf_lines(data)
    ending = _conf_line_ending(lines)
    for index, line in enumerate(lines):
        if line.strip().lower() == SAMBA_GLOBAL_HEADER.encode("utf-8"):
            is_ended = line.endswith(b"\n")
            added = include_line() + ending if is_ended else ending + include_line()
            lines.insert(index + 1, added)
            return b"".join(lines)
    return include_line() + ending + data


def without_include_line(data: bytes) -> bytes:
    """``smb.conf`` without the module's include line.

    Args:
        data: The file.

    Returns:
        The file with every other byte kept. Removing a line with no line
        ending also removes the ending before it, and the file still has no
        last newline.
    """
    lines = _conf_lines(data)
    kept = [line for line in lines if not is_include_line(line)]
    if kept and is_include_line(lines[-1]) and not lines[-1].endswith(b"\n"):
        kept[-1] = kept[-1].removesuffix(_conf_line_ending(lines))
    return b"".join(kept)


def earlier_share_lines(params: dict, name: str) -> "list | None":
    """The lines a module of 0.5 rendered for one share, without their endings. Pure.

    Args:
        params: The section's ``key = value`` pairs, keys lowered.
        name: The section's name.

    Returns:
        The lines, None when the section lacks a line every 0.5 share has.
    """
    if not {"path", "valid users", "read only"} <= set(params):
        return None
    lines = [
        f"[{name}]",
        f"   path = {params['path']}",
        f"   valid users = {params['valid users']}",
        f"   read only = {params['read only']}",
    ]
    if "comment" in params:
        lines.append(f"   comment = {params['comment']}")
    if params["read only"] != "yes":
        lines += [
            f"   force group = {SAMBA_EARLIER_GROUP}",
            "   create mask = 0664",
            "   directory mask = 2775",
        ]
    return lines


def without_earlier_shares(data: bytes) -> tuple:
    """``smb.conf`` without the shares a module of 0.5 rendered in it. Pure.

    A file whose first line is the module's marker was rendered whole by
    0.5. Each share section in it whose lines are, one for one, the lines
    0.5 rendered for a share of its values goes, with the one blank line 0.5
    rendered after each such share but the last; every other byte stays. A
    file without the marker is the person's alone and stays as it is.

    Args:
        data: The file.

    Returns:
        ``(data, names, users)``: the file, the shares taken out, and the
        words of their ``valid users`` lines in order, each once.
    """
    lines = _conf_lines(data)
    if not lines or lines[0].rstrip(b"\r\n").decode("utf-8", "replace") != (
        SAMBA_CONF_MARKER
    ):
        return data, [], []
    starts = [
        index
        for index, line in enumerate(lines)
        if SECTION_PATTERN.match(line.decode("utf-8", "replace").strip())
    ]
    texts = [line.rstrip(b"\r\n").decode("utf-8", "replace") for line in lines]
    shares: list = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        name = SECTION_PATTERN.match(texts[start].strip()).group(1).strip()
        if name.lower() == GLOBAL_SECTION:
            continue
        body = list(range(start, end))
        while body and not texts[body[-1]].strip():
            body.pop()
        params = {}
        for index in body[1:]:
            key, is_pair, value = texts[index].partition("=")
            if is_pair:
                params[key.strip().lower()] = value.strip()
        if earlier_share_lines(params, name) == [texts[index] for index in body]:
            shares.append((name, body, end, params["valid users"]))
    dropped: set = set()
    users: list = []
    for position, (_name, body, end, valid) in enumerate(shares):
        dropped.update(body)
        following = body[-1] + 1
        # 0.5 ended each share but its last with one blank line.
        is_last = position == len(shares) - 1
        if not is_last and following < end and not texts[following].strip():
            dropped.add(following)
        for word in valid.split():
            if word not in users:
                users.append(word)
    kept = [line for index, line in enumerate(lines) if index not in dropped]
    return b"".join(kept), [name for name, _, _, _ in shares], users


def named_users(data: bytes) -> set:
    """Every word of each share's ``valid users`` and ``force user`` lines in ``smb.conf``. Pure.

    Args:
        data: The file.

    Returns:
        The words, a group's with its ``@``.
    """
    named: set = set()
    section = ""
    for line in _conf_lines(data):
        text = line.decode("utf-8", "replace").strip()
        header = SECTION_PATTERN.match(text)
        if header:
            section = header.group(1).strip().lower()
            continue
        key, is_pair, value = text.partition("=")
        if not is_pair or section == GLOBAL_SECTION:
            continue
        if key.strip().lower() in ("valid users", "force user"):
            named.update(value.split())
    return named


def plan_smb_conf(current: "bytes | None", *, stock: tuple, is_served: bool) -> tuple:
    """What ``smb.conf`` is to hold beside the module's file. Pure.

    Args:
        current: The file as it is, None when the machine has none.
        stock: ``(data, source)`` as :func:`read_stock_conf` gives them.
        is_served: Whether the module serves at least one share of its own.

    Returns:
        ``(data, note)``: the file to write, and what changed in words,
        empty when the file stays as it is. The file is the person's,
        whoever wrote it, an earlier version of this module included, and
        is left as it is; a missing file is the stock text. While the
        module serves a share the include line is added once to a file that
        lacks it; while it serves none the line is taken out, and a file
        without it is left byte for byte.
    """
    notes = []
    data = current
    if data is None:
        if not is_served:
            return b"", ""
        data, source = stock
        notes.append(f"wrote {source}")
    if is_served and not has_include_line(data):
        data = with_include_line(data)
        notes.append("added the include line")
    elif not is_served and has_include_line(data):
        data = without_include_line(data)
        notes.append("took the include line out")
    return data, "; ".join(notes)


def testparm(smb_conf: bytes, rendered: str) -> None:
    """Have Samba check ``smb.conf`` as it will be with the module's file.

    Args:
        smb_conf: The ``smb.conf`` bytes, with the include line.
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
        with open(conf_path, "wb") as stream:
            stream.write(
                smb_conf.replace(
                    SAMBA_MODULE_CONF_PATH.encode("utf-8"), module_path.encode("utf-8")
                )
            )
        result = run(["testparm", "-s", conf_path], is_checked=False)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if not result.is_success:
        raise ModuleApplyError(
            "samba_config_rejected", {"detail": result.stderr.strip()[-500:]}
        )


def taken_shares(shares: list, config: SambaConfig) -> list:
    """Each served share of the module's whose name a share of the person's has. Pure.

    Args:
        shares: The person's shares, each ``{"name", "path", "params"}``.
        config: The module's configuration.

    Returns:
        ``share_name_taken {name}`` for each, in the configuration's order,
        the names compared without case.
    """
    persons = {str(share.get("name", "")).lower() for share in shares}
    return [
        {"code": SAMBA_SHARE_NAME_TAKEN_CODE, "params": {"name": share.name}}
        for share in config.served_shares()
        if share.name.lower() in persons
    ]


def check_person_config(global_section: dict) -> None:
    """Refuse what the person's own ``[global]`` makes impossible, changing nothing.

    Args:
        global_section: The person's ``[global]`` as testparm prints it.

    Raises:
        ModuleApplyError: ``samba_hosts_allow_no_loopback`` for a ``hosts
            allow`` without the loopback; ``samba_interfaces_no_loopback``
            for ``bind interfaces only`` whose ``interfaces`` has no ``lo``;
            ``samba_domain_member`` for a domain member's ``security`` or
            ``server role``.
    """
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


def _conf_lines(data: bytes) -> list:
    """The lines of ``smb.conf``, each with its ending. Samba ends a line at LF alone."""
    return io.BytesIO(data).readlines()


def _conf_line_ending(lines: list) -> bytes:
    """The line ending of ``smb.conf``. CRLF when its first line ends in CR or CRLF, else LF."""
    if lines and lines[0].rstrip(b"\n").endswith(b"\r"):
        return b"\r\n"
    return b"\n"


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

    def read_persons(self, data: bytes) -> tuple:
        """The person's own configuration: ``smb.conf`` without the module's line.

        Args:
            data: ``smb.conf`` as the next apply leaves it
                (:meth:`SambaConfigApplier.plan`), so a whole file an
                earlier version rendered is not mistaken for the person's.

        Returns:
            ``(global, shares)`` of the file with the include line taken
            out, so the module's shares are not among them; both empty
            when testparm is not there.
        """
        if shutil.which("testparm") is None:
            return {}, []
        handle, path = tempfile.mkstemp(prefix="smb_", suffix=".conf")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(without_include_line(data))
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
            removed, and the account too when the module made it. A name
            without the module's prefix is passed over.

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
            if name in config.users or not name.startswith(SAMBA_USER_PREFIXES):
                continue
            if name in credentialed:
                run(["smbpasswd", "-x", name])
            if self._is_module_account(name):
                run(["userdel", name])
            changes.append(f"retired {name}")
        return changes, kept

    def sweep(self) -> list:
        """Delete every SMB user of the module's, credential and account.

        A user is the module's when its name starts ``neutrino_``, or
        ``neutrino-`` as earlier builds named it, and its account's comment
        is the module's; a credential of such a name with no account goes
        too. ``neutrino_transport`` and any other account without the
        comment stay.

        Returns:
            One note per credential and per account removed.

        Raises:
            subprocess.CalledProcessError: If Samba or ``userdel`` refuses.
        """
        notes = []
        for name in self.credentialed_users():
            if not name.startswith(SAMBA_USER_PREFIXES):
                continue
            if self._account_exists(name) and not self._is_module_account(name):
                continue
            run(["smbpasswd", "-x", name])
            notes.append(f"swept the credential of {name}")
        for name in self._module_accounts():
            run(["userdel", name])
            notes.append(f"swept the account {name}")
        return notes

    def sweep_earlier(
        self, named: list, *, kept: "set | frozenset" = frozenset()
    ) -> list:
        """Take away the Samba logins of the users the shares of 0.5 named.

        Each user named, and each member of the group 0.5 put its users in
        where a share named the group, loses its Samba credential; its
        account goes too when 0.5 made it (:meth:`_is_earlier_account`). A
        name with either of the module's starts, a user ``kept`` names and
        any other group are passed over.

        Args:
            named: The words of the swept shares' ``valid users`` lines.
            kept: The words the shares that stay name.

        Returns:
            One note per credential and per account removed.

        Raises:
            subprocess.CalledProcessError: If Samba or ``userdel`` refuses.
        """
        names: list = []
        for word in named:
            if word.startswith("@"):
                if word[1:] == SAMBA_EARLIER_GROUP:
                    names += self._group_members(SAMBA_EARLIER_GROUP)
                continue
            names.append(word)
        credentialed = self._credentialed_users()
        notes = []
        for name in dict.fromkeys(names):
            if name.startswith(SAMBA_USER_PREFIXES) or name in kept:
                continue
            if name in credentialed:
                run(["smbpasswd", "-x", name])
                notes.append(f"swept the 0.5 credential of {name}")
            if self._is_earlier_account(name):
                run(["userdel", name])
                notes.append(f"swept the 0.5 account {name}")
        return notes

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

    def _is_earlier_account(self, name: str) -> bool:
        """Whether a module of 0.5 made the account.

        0.5 ran ``useradd --no-create-home --shell <nologin>``: an ordinary
        account, no comment, a login shell that never signs in, and a home
        folder that is not on the machine.
        """
        result = run(["getent", "passwd", name], is_checked=False)
        if not result.is_success:
            return False
        fields = result.stdout.strip().split(":")
        if len(fields) < 7 or not fields[2].isdigit():
            return False
        return (
            EARLIER_UID_FIRST <= int(fields[2]) < EARLIER_UID_END
            and not fields[4]
            and fields[6] in SAMBA_LINUX_NOLOGIN_SHELLS
            and not os.path.isdir(fields[5])
        )

    def _group_members(self, group: str) -> list:
        result = run(["getent", "group", group], is_checked=False)
        if not result.is_success:
            return []
        fields = result.stdout.strip().split(":")
        return [
            name for name in (fields[3] if len(fields) > 3 else "").split(",") if name
        ]

    def _credentialed_users(self) -> set:
        return set(self.credentialed_users())

    def _module_accounts(self) -> list:
        """Every account with either of the module's starts and the module's comment."""
        result = run(["getent", "passwd"], is_checked=False)
        if not result.is_success:
            return []
        names = []
        for line in result.stdout.splitlines():
            fields = line.split(":")
            if (
                fields[0].startswith(SAMBA_USER_PREFIXES)
                and len(fields) > 4
                and fields[4] == SAMBA_LINUX_USER_COMMENT
            ):
                names.append(fields[0])
        return names


class SambaConfigApplier:
    """Writes the module's own file, keeps ``smb.conf`` including it, and loads both."""

    def __init__(self, *, unit: str):
        """
        Args:
            unit: The unit this machine's Samba runs as.
        """
        self._unit = unit

    def plan(self, *, is_served: bool) -> tuple:
        """``smb.conf`` as the next apply leaves it.

        Args:
            is_served: Whether the module serves at least one share of its own.

        Returns:
            ``(data, note)`` as :func:`plan_smb_conf` gives them, for the
            file, the backup and the stock text on this machine; empty
            bytes when the machine has no file and the module serves nothing.
        """
        return plan_smb_conf(
            read_bytes(SAMBA_CONF_PATH), stock=read_stock_conf(), is_served=is_served
        )

    def apply(
        self,
        rendered: str,
        *,
        config: SambaConfig,
        user_files: "dict | None" = None,
        is_reloaded: bool = True,
    ) -> str:
        """Validate, install and load the module's file, or take it away.

        Validation runs on copies before anything moves, so a bad render
        never takes the running server's configuration with it. A
        configuration with no share that admits a user leaves no file and
        no include line behind: the person's ``smb.conf`` stays as it is.

        Args:
            rendered: The module's own file.
            config: The configuration it was rendered from, whose served
                shares decide whether the file is written.
            user_files: The files under :data:`SAMBA_USERS_DIR` by name, as
                the renderer gives them; every other file there goes.
            is_reloaded: Whether an active unit reloads the files. Nothing
                here starts a unit that is off.

        Returns:
            A short summary of what changed.

        Raises:
            ModuleApplyError: If Samba rejects the configuration.
            subprocess.CalledProcessError: If the reload fails.
        """
        is_served = bool(config.served_shares())
        smb_conf, note = self.plan(is_served=is_served)
        notes = [note] if note else []
        current = read_bytes(SAMBA_CONF_PATH)
        if not is_served:
            self._remove_own()
            if smb_conf != (current or b""):
                _write_smb_conf(smb_conf)
            if notes and is_reloaded and unit_state(self._unit) == "active":
                run(["systemctl", "reload", self._unit])
                notes.append("reloaded")
            return "; ".join(notes or ["unchanged"])
        testparm(smb_conf, rendered)
        self._write_user_files(dict(user_files or {}))
        _write_file(SAMBA_MODULE_CONF_PATH, rendered.encode("utf-8"))
        if smb_conf != current:
            _write_smb_conf(smb_conf)
        if is_reloaded and unit_state(self._unit) == "active":
            run(["systemctl", "reload", self._unit])
            return "; ".join(notes + ["reloaded"])
        return "; ".join(notes + ["written"])

    def remove(self) -> None:
        """Delete the module's file and its users' files, and take the include line out of ``smb.conf``."""
        self._remove_own()
        data = read_bytes(SAMBA_CONF_PATH)
        if data is not None and has_include_line(data):
            _write_smb_conf(without_include_line(data))

    def sweep_earlier(self) -> tuple:
        """Take the shares a module of 0.5 rendered out of ``smb.conf``, and reload an active unit.

        Every other byte of the file stays, with its mode, its owner and its
        link (:func:`without_earlier_shares`).

        Returns:
            ``(notes, named, kept)``: one note per share taken out, the words
            of their ``valid users`` lines, and the words the shares that
            stay name.

        Raises:
            OSError: When the file cannot be written.
        """
        data = read_bytes(SAMBA_CONF_PATH)
        if data is None:
            return [], [], set()
        kept, names, named = without_earlier_shares(data)
        if not names:
            return [], [], set()
        _write_smb_conf(kept)
        notes = [f"swept the 0.5 share {name}" for name in names]
        if unit_state(self._unit) == "active":
            run(["systemctl", "reload", self._unit], is_checked=False)
        return notes, named, named_users(kept)

    def withdraw(self) -> str:
        """Take the module's shares off a server that goes on running.

        Deletes what :meth:`remove` deletes and reloads an active unit when
        anything was there. Nothing else of the unit changes.

        Returns:
            A short summary of what changed.
        """
        data = read_bytes(SAMBA_CONF_PATH)
        has_line = data is not None and has_include_line(data)
        has_file = os.path.exists(SAMBA_MODULE_CONF_PATH)
        if not has_line and not has_file:
            return "unchanged"
        self.remove()
        if unit_state(self._unit) != "active":
            return "took the module's shares off"
        result = run(["systemctl", "reload", self._unit], is_checked=False)
        if not result.is_success:
            return "took the module's shares off; could not reload"
        return "took the module's shares off; reloaded"

    def _remove_own(self) -> None:
        with contextlib.suppress(OSError):
            os.unlink(SAMBA_MODULE_CONF_PATH)
        shutil.rmtree(SAMBA_USERS_DIR, ignore_errors=True)

    def stop(self) -> None:
        """Take the server down and disable it until the next start."""
        run(["systemctl", "disable", "--now", self._unit], is_checked=False)

    def start(self) -> None:
        """Enable and start the server, on the stock ``smb.conf`` where the machine has none.

        Raises:
            subprocess.CalledProcessError: If the unit will not come up.
        """
        if read_bytes(SAMBA_CONF_PATH) is None:
            _write_smb_conf(read_stock_conf()[0])
        run(["systemctl", "enable", "--now", self._unit])

    def _write_user_files(self, user_files: dict) -> None:
        """Write each user's file under the users directory and drop the rest."""
        os.makedirs(SAMBA_USERS_DIR, exist_ok=True)
        os.chmod(SAMBA_USERS_DIR, 0o755)
        for name in os.listdir(SAMBA_USERS_DIR):
            if name.endswith(SAMBA_USERS_FILE_SUFFIX) and name not in user_files:
                os.unlink(os.path.join(SAMBA_USERS_DIR, name))
        for name, text in user_files.items():
            _write_file(os.path.join(SAMBA_USERS_DIR, name), text.encode("utf-8"))


class SambaUnitApplier:
    """Reads one of Samba's units, and changes it only as the runner asks."""

    def __init__(self, *, unit: str):
        """
        Args:
            unit: The unit.
        """
        self._unit = unit

    def read(self) -> dict:
        """What the unit is now.

        Returns:
            ``{"is_enabled", "is_active"}``, empty when it is neither: a
            unit disabled, masked or not on this machine.
        """
        shown = run(
            ["systemctl", "show", "--property=UnitFileState,ActiveState", self._unit],
            is_checked=False,
        ).stdout
        fields = dict(line.split("=", 1) for line in shown.splitlines() if "=" in line)
        kept = {
            "is_enabled": fields.get("UnitFileState") == "enabled",
            "is_active": fields.get("ActiveState") == "active",
        }
        return kept if any(kept.values()) else {}

    def start(self) -> None:
        """Enable and start the unit. A masked or missing unit stays as it is."""
        run(["systemctl", "enable", "--now", self._unit], is_checked=False)

    def stop(self) -> None:
        """Take the unit down and disable it."""
        run(["systemctl", "disable", "--now", self._unit], is_checked=False)

    def put_back(self, found: dict) -> None:
        """Make the unit enabled and active as it was found.

        Args:
            found: What :meth:`read` gave then.
        """
        verb = "enable" if found.get("is_enabled") else "disable"
        run(["systemctl", verb, self._unit], is_checked=False)
        verb = "start" if found.get("is_active") else "stop"
        run(["systemctl", verb, self._unit], is_checked=False)


def _write_smb_conf(data: bytes) -> None:
    """Write ``smb.conf`` through a symlink to its target, keeping the target's mode and owner."""
    target = os.path.realpath(SAMBA_CONF_PATH)
    try:
        kept = os.stat(target)
    except FileNotFoundError:
        kept = None
    _write_file(target, data, kept=kept)


def _write_file(
    path: str, data: bytes, *, kept: "os.stat_result | None" = None
) -> None:
    """Write a file in one move, in place of a symlink too.

    Args:
        path: The file.
        data: Its bytes.
        kept: The mode and the owner it takes; None makes it world-readable
            and the agent's.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".neutrino_")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        if kept is None:
            os.chmod(temporary, 0o644)
        else:
            # A chown clears the setuid and setgid bits, so the mode comes after it.
            os.chown(temporary, kept.st_uid, kept.st_gid)
            os.chmod(temporary, stat.S_IMODE(kept.st_mode))
        if os.path.islink(path):
            os.unlink(path)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


class SambaSelinuxApplier:
    """Turns :data:`SAMBA_SELINUX_BOOLEAN` on and off where SELinux is active."""

    def turn_on(self) -> bool:
        """Turn the boolean on when it is off.

        Returns:
            True when this call turned it on; False when it is on already,
            or where SELinux is disabled or absent.

        Raises:
            OSError: When ``getsebool`` or ``setsebool`` cannot start.
            subprocess.SubprocessError: When either refuses or does not finish.
        """
        return self._change("off", "on")

    def turn_off(self) -> bool:
        """Turn the boolean off when it is on.

        Returns:
            True when this call turned it off; False when it is off already,
            or where SELinux is disabled or absent.

        Raises:
            OSError: When ``getsebool`` or ``setsebool`` cannot start.
            subprocess.SubprocessError: When either refuses or does not finish.
        """
        return self._change("on", "off")

    def _change(self, before: str, after: str) -> bool:
        """Run ``setsebool -P`` only when the boolean reads ``before``."""
        if self._read() != before:
            return False
        run(["setsebool", "-P", SAMBA_SELINUX_BOOLEAN, after])
        return True

    def _read(self) -> str:
        """The boolean's value; empty where SELinux is disabled or absent."""
        if shutil.which("getenforce") is None:
            return ""
        mode = run(["getenforce"], is_checked=False).stdout.strip()
        if mode not in SAMBA_SELINUX_ACTIVE_MODES:
            return ""
        return (
            run(["getsebool", SAMBA_SELINUX_BOOLEAN]).stdout.rpartition(" ")[2].strip()
        )


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
