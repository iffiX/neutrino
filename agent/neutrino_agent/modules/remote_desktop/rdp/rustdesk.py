"""RustDesk's settings files, as the Remote desktop module writes them.

RustDesk keeps two files per account that runs it: ``RustDesk2.toml``, its
options, and ``RustDesk.toml``, its id, keys and permanent password. The
Remote desktop module writes both while the host is stopped: a running host
writes back what it holds as it exits. The options name the direct
connection and point the rendezvous and relay servers at the machine's own
loopback; the password goes in as ``password = '<p>'``, which RustDesk
reads as given, since ``--password`` from a copy outside RustDesk's
standard place sets nothing.

**The service's file holds an id and a key pair before the service starts.**
A session's host copies the service's settings only when that file holds
both, and keeps its own otherwise; empty options mean upstream's public
server.

**The owner is part of the file.** A seated account's copy is written by
this root daemon but read and written by RustDesk running as that person;
on Wayland it stores the screen-capture permission there, so a copy left
owned by root costs that person the permission dialog on every connection.
A file keeps the owner and mode it had, and a new one under a home is made
as that home's owner, as is each folder made for it there; a folder there
that root owns is given to that owner.

**RustDesk seals the password when it rewrites the file**: ``00``, then
base64 of the format byte 1, a 24-byte nonce and the secretbox, keyed by the
machine id cut or padded with zeros to 32 bytes. An older form is the
secretbox alone under a zero nonce.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import contextlib
import os
import posixpath
import re
import secrets
import stat
import sys

from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules.remote_desktop.rdp.ed25519 import (
    ED25519_SEED_BYTES,
    public_key,
)
from neutrino_agent.modules.remote_desktop.rdp.secretbox import (
    SECRETBOX_KEY_BYTES,
    SECRETBOX_NONCE_BYTES,
    SECRETBOX_TAG_BYTES,
    secretbox_open,
)
from neutrino_agent.platforms.detect import OS_NAMES

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# The settings file the seat's Wayland permission is read from, under
# root's and an account's own configuration on Linux.
RUSTDESK_CONFIG_NAME = "RustDesk2.toml"
RUSTDESK_ROOT_CONFIG = "/root/.config/rustdesk"
RUSTDESK_ACCOUNT_RELATIVE = ".config/rustdesk"

# A key = 'value' line, as RustDesk itself writes it.
RUSTDESK_OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=")
RUSTDESK_PASSWORD_KEY = "password"
# What RustDesk's own emptiness test of RustDesk.toml reads: an id, plain or
# sealed, and a key pair.
RUSTDESK_ID_KEYS = ("id", "enc_id")
RUSTDESK_KEY_PAIR_KEY = "key_pair"
# The range of the id the agent writes, nine digits. RustDesk seals it when it
# rewrites the file.
RUSTDESK_ID_FIRST = 100000000
RUSTDESK_ID_COUNT = 900000000
# The table RustDesk2.toml keeps its options in.
RUSTDESK_OPTIONS_TABLE = "[options]"
# The login shells that open no session.
RUSTDESK_NO_LOGIN_SHELLS = ("nologin", "false")
# A sealed value's prefix, and the format byte its decoded bytes open with.
RUSTDESK_SEALED_PREFIX = "00"
RUSTDESK_SEALED_FORMAT = 1


def rustdesk_os() -> str:
    """The operating system the settings are read for.

    Returns:
        ``linux``, ``windows`` or ``darwin``.
    """
    reported = "linux" if sys.platform.startswith("linux") else sys.platform
    return OS_NAMES.get(reported, reported)


def config_paths(account_home: str = "") -> list:
    """Every ``RustDesk2.toml`` a Linux machine's host reads.

    Args:
        account_home: The home of the account at the screen; empty names
            root's alone.

    Returns:
        The paths, root's first.
    """
    if rustdesk_os() == "windows":
        return []
    paths = [posixpath.join(RUSTDESK_ROOT_CONFIG, RUSTDESK_CONFIG_NAME)]
    if account_home:
        paths.append(
            posixpath.join(
                account_home, RUSTDESK_ACCOUNT_RELATIVE, RUSTDESK_CONFIG_NAME
            )
        )
    return paths


def render_config(existing: str, options: tuple) -> str:
    """One ``RustDesk2.toml`` with the given options settled into it.

    Everything above the options table is kept as it was, and an option
    RustDesk wrote that this does not name is kept too.

    Args:
        existing: The file's current text, empty when there is none.
        options: ``(key, value)`` pairs to set.

    Returns:
        The whole file to write.
    """
    preamble = []
    kept = []
    is_in_options = False
    named = {key for key, _ in options}
    for line in existing.splitlines():
        if line.strip().startswith("[") and line.strip().endswith("]"):
            is_in_options = line.strip() == "[options]"
            if not is_in_options:
                break
            continue
        if not is_in_options:
            preamble.append(line)
            continue
        match = RUSTDESK_OPTION_PATTERN.match(line)
        if match is not None and match.group(1) not in named:
            kept.append(line)
    body = "\n".join(line for line in preamble if line.strip())
    lines = [body] if body else []
    lines.append("[options]")
    lines.extend(f"{key} = {_quoted(value)}" for key, value in options)
    lines.extend(kept)
    return "\n".join(lines) + "\n"


def render_identity(existing: str) -> str:
    """One ``RustDesk.toml`` that holds an id and a key pair.

    What the text already holds is kept; the rest is made here and added at
    the top, above every table.

    Args:
        existing: The file's current text, empty when there is none.

    Returns:
        The whole file to write.
    """
    lines = existing.splitlines()
    values = _values_of(lines)
    added = []
    if not _has_id(values):
        number = RUSTDESK_ID_FIRST + secrets.randbelow(RUSTDESK_ID_COUNT)
        lines = _without_key(lines, RUSTDESK_ID_KEYS[0])
        added.append(f"{RUSTDESK_ID_KEYS[0]} = {_quoted(str(number))}")
    if not _has_key_pair(values):
        seed = os.urandom(ED25519_SEED_BYTES)
        public = public_key(seed)
        lines = _without_key(lines, RUSTDESK_KEY_PAIR_KEY)
        added.append(
            f"{RUSTDESK_KEY_PAIR_KEY} = [{list(seed + public)}, {list(public)}]"
        )
    if not added:
        return existing
    return "\n".join(added + lines) + "\n"


def render_password(existing: str, password: str) -> str:
    """One ``RustDesk.toml`` with its permanent password set as plain text.

    The line takes the place of the one there, or is added before the
    first table; everything else is kept as it was.

    Args:
        existing: The file's current text, empty when there is none.
        password: The seat password.

    Returns:
        The whole file to write.
    """
    line = f"{RUSTDESK_PASSWORD_KEY} = {_quoted(password)}"
    lines = existing.splitlines()
    for index, held in enumerate(lines):
        if held.strip().startswith("["):
            break
        match = RUSTDESK_OPTION_PATTERN.match(held)
        if match is not None and match.group(1) == RUSTDESK_PASSWORD_KEY:
            lines[index] = line
            return "\n".join(lines) + "\n"
    table = next(
        (index for index, held in enumerate(lines) if held.strip().startswith("[")),
        len(lines),
    )
    lines.insert(table, line)
    return "\n".join(lines) + "\n"


def read_password(path: str) -> str:
    """The permanent password a ``RustDesk.toml`` holds as plain text.

    Args:
        path: The file.

    Returns:
        The value when it is plain text; empty when the file is missing,
        names none, or holds RustDesk's own encrypted form.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            lines = stream.read().splitlines()
    except OSError:
        return ""
    for line in lines:
        if line.strip().startswith("["):
            return ""
        match = RUSTDESK_OPTION_PATTERN.match(line)
        if match is None or match.group(1) != RUSTDESK_PASSWORD_KEY:
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return ""


def read_values(path: str) -> dict:
    """The keys above the first table of one RustDesk settings file.

    Args:
        path: The file.

    Returns:
        Each key's value: a string without its quotes, anything else as
        written, an array across every line it spans; empty when the file
        is missing.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return _values_of(stream.read().splitlines())
    except OSError:
        return {}


def read_options(path: str) -> dict:
    """The options table of one ``RustDesk2.toml``.

    Args:
        path: The file.

    Returns:
        Each option's value without its quotes; empty when the file is
        missing, is no text or holds no such table.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            lines = stream.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    stripped = [line.strip() for line in lines]
    if RUSTDESK_OPTIONS_TABLE not in stripped:
        return {}
    return _values_of(lines[stripped.index(RUSTDESK_OPTIONS_TABLE) + 1 :])


def holds_options(path: str, options: tuple) -> bool:
    """Whether one ``RustDesk2.toml`` holds the given options, in any order.

    Args:
        path: The file.
        options: ``(key, value)`` pairs.

    Returns:
        True when each key has that value.
    """
    held_options = read_options(path)
    return all(held_options.get(key) == value for key, value in options)


def is_being_written(path: str) -> bool:
    """Whether one settings file is there and empty: RustDesk truncates a file
    before it writes it.

    Args:
        path: The file.

    Returns:
        True for a file of no bytes.
    """
    status = _stat(path)
    return status is not None and status.st_size == 0


def has_identity(path: str) -> bool:
    """Whether one ``RustDesk.toml`` holds an id and a key pair.

    A session's host copies root's settings only when root's file holds
    both.

    Args:
        path: The file.

    Returns:
        True when it names an ``id`` or an ``enc_id`` and a key pair with
        bytes in it.
    """
    values = read_values(path)
    return _has_id(values) and _has_key_pair(values)


def is_sealed(value: str) -> bool:
    """Whether a stored value has RustDesk's sealed form.

    Args:
        value: The value as the file holds it.

    Returns:
        True for the prefix followed by base64 of at least a tag's length.
    """
    encoded = value[len(RUSTDESK_SEALED_PREFIX) :]
    if not value.startswith(RUSTDESK_SEALED_PREFIX) or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except ValueError:
        return False
    return len(decoded) >= SECRETBOX_TAG_BYTES


def open_sealed(value: str, machine_id: str) -> "str | None":
    """The text RustDesk sealed into one stored value.

    Args:
        value: The value as the file holds it.
        machine_id: The machine's id, which RustDesk seals with.

    Returns:
        The text; None when the value is not sealed or does not open with
        that id.
    """
    if not is_sealed(value):
        return None
    sealed = base64.b64decode(value[len(RUSTDESK_SEALED_PREFIX) :])
    key = machine_id.encode("utf-8")[:SECRETBOX_KEY_BYTES]
    key = key.ljust(SECRETBOX_KEY_BYTES, b"\0")
    nonce_end = 1 + SECRETBOX_NONCE_BYTES
    tries = [(sealed, bytes(SECRETBOX_NONCE_BYTES))]
    if (
        sealed[0] == RUSTDESK_SEALED_FORMAT
        and len(sealed) >= nonce_end + SECRETBOX_TAG_BYTES
    ):
        tries.insert(0, (sealed[nonce_end:], sealed[1:nonce_end]))
    for body, nonce in tries:
        try:
            return secretbox_open(body, nonce, key).decode("utf-8", "replace")
        except ValueError:
            continue
    return None


def stored_password(path: str, machine_id) -> "str | None":
    """The permanent password one ``RustDesk.toml`` holds, as a peer types it.

    Args:
        path: The file.
        machine_id: Called for the machine's id when the value is sealed.

    Returns:
        A sealed value opened, any other value as written; empty when the
        file is missing or names none; None when a sealed value does not
        open with the machine's id.
    """
    stored = read_values(path).get(RUSTDESK_PASSWORD_KEY, "")
    if not is_sealed(stored):
        return stored
    return open_sealed(stored, machine_id())


def give_back_dirs(directory: str, home: str) -> list:
    """Give each folder below a home down to a settings folder that root
    owns to the home's owner.

    Args:
        directory: The settings folder.
        home: The home of the account the folder is for.

    Returns:
        The folders given, top down; empty when ``directory`` is not under
        ``home``, the home is root's, or this system sets no owners.

    Raises:
        OSError: If a folder's owner cannot be changed.
    """
    return _give_dirs(os.path.normpath(directory), home, ())


def is_below_link(path: str, home: str) -> bool:
    """Whether a settings file under a home is reached through a symbolic
    link, the file itself included.

    Args:
        path: The file.
        home: The home of the account the file is for.

    Returns:
        True when a level below the home is a link; False for a path that is
        not under the home.
    """
    for level in _levels_below(home, path):
        status = _lstat(level)
        if status is not None and stat.S_ISLNK(status.st_mode):
            return True
    return False


def account_homes(first_uid: int, named: tuple) -> list:
    """The home of every account that can come to this machine's screen.

    Args:
        first_uid: The first uid of a person's account. An account from there
            up counts unless its shell opens no session.
        named: The accounts that count whatever their uid and shell: a
            display manager's greeter.

    Returns:
        The homes that are folders the account owns, each once; empty where
        the system has no account database.
    """
    if pwd is None:
        return []
    homes = []
    for entry in pwd.getpwall():
        is_person = entry.pw_uid >= first_uid and not entry.pw_shell.endswith(
            RUSTDESK_NO_LOGIN_SHELLS
        )
        if not is_person and entry.pw_name not in named:
            continue
        status = _stat(entry.pw_dir)
        if status is None or not stat.S_ISDIR(status.st_mode):
            continue
        if status.st_uid == entry.pw_uid and entry.pw_dir not in homes:
            homes.append(entry.pw_dir)
    return homes


def write_config(path: str, options: tuple) -> bool:
    """Write one ``RustDesk2.toml``, keeping what it said and whose it was.

    Args:
        path: The file to write.
        options: ``(key, value)`` pairs to set.

    Returns:
        True when the file's text is not what it was.

    Raises:
        InstallError: If the file cannot be written.
    """
    return write_settings(path, lambda existing: render_config(existing, options))


def would_change(path: str, render) -> bool:
    """Whether writing one settings file would change it.

    Args:
        path: The file.
        render: Called with the file's text; returns the text to write.

    Returns:
        True when the file is missing or its text would change.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            existing = stream.read()
    except OSError:
        return True
    return render(existing) != existing


def write_settings(path: str, render, home: str = "") -> bool:
    """Write one settings file through a renderer, keeping its owner and mode.

    Args:
        path: The file to write.
        render: Called with the file's current text, empty when there is
            none; returns the text to write.
        home: The home of the account the file belongs to; each folder made
            under it is given the home's owner. Empty makes every folder as
            this process.

    Returns:
        True when the file's text is not what it was.

    Raises:
        InstallError: If the file cannot be written.
    """
    try:
        existing = ""
        _make_dirs(os.path.dirname(path) or ".", home)
        kept = _owner_of(path)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as stream:
                existing = stream.read()
        rendered = render(existing)
        temporary = f"{path}.tmp"
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        with open(temporary, "x", encoding="utf-8", opener=_private) as stream:
            stream.write(rendered)
        if kept is not None and hasattr(os, "chown"):
            os.chown(temporary, kept[0], kept[1])
            os.chmod(temporary, kept[2])
        os.replace(temporary, path)
    except OSError as error:
        raise InstallError(f"could not write {path}: {error}")
    return rendered != existing


def _private(path: str, flags: int) -> int:
    """Open a new file only its owner reads."""
    return os.open(path, flags, 0o600)


def _values_of(lines: list) -> dict:
    """The keys above the first table of the given lines; a string without its
    quotes, anything else as written, an array across every line it spans."""
    values = {}
    key = ""
    depth = 0
    for line in lines:
        if depth > 0:
            values[key] += "\n" + line
            depth += line.count("[") - line.count("]")
            continue
        if line.strip().startswith("["):
            break
        match = RUSTDESK_OPTION_PATTERN.match(line)
        if match is None:
            continue
        key = match.group(1)
        value = line.split("=", 1)[1].strip()
        values[key] = _unquoted(value)
        if value.startswith("["):
            depth = value.count("[") - value.count("]")
    return values


def _has_id(values: dict) -> bool:
    """Whether the keys of one ``RustDesk.toml`` name an id, plain or sealed."""
    return any(values.get(key, "") for key in RUSTDESK_ID_KEYS)


def _has_key_pair(values: dict) -> bool:
    """Whether the keys of one ``RustDesk.toml`` name a key pair with bytes."""
    return any(part.isalnum() for part in values.get(RUSTDESK_KEY_PAIR_KEY, ""))


def _without_key(lines: list, key: str) -> list:
    """The lines without one key above the first table, an array across every
    line it spans."""
    kept = []
    depth = 0
    is_dropped = False
    is_above_table = True
    for line in lines:
        if depth > 0:
            depth += line.count("[") - line.count("]")
            if not is_dropped:
                kept.append(line)
            continue
        if line.strip().startswith("["):
            is_above_table = False
        match = RUSTDESK_OPTION_PATTERN.match(line)
        if is_above_table and match is not None:
            value = line.split("=", 1)[1].strip()
            depth = value.count("[") - value.count("]") if value[:1] == "[" else 0
            is_dropped = match.group(1) == key
            if is_dropped:
                continue
        kept.append(line)
    return kept


def _quoted(value: str) -> str:
    """One TOML string: a literal one unless the value holds a quote."""
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _unquoted(value: str) -> str:
    """One TOML value without its quotes; a value that is not a string as is."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _make_dirs(directory: str, home: str) -> None:
    """Make a folder and each missing one above it; each under ``home``
    that was made here or that root owns is given the home's owner."""
    directory = os.path.normpath(directory)
    missing = []
    current = directory
    while current and not os.path.isdir(current):
        missing.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    made = []
    for level in reversed(missing):
        try:
            os.mkdir(level)
        except FileExistsError:
            continue
        made.append(level)
    _give_dirs(directory, home, made)


def _give_dirs(directory: str, home: str, made) -> list:
    """Give each folder below ``home`` down to ``directory`` that is in
    ``made`` or that root owns to the home's owner; symbolic links are
    skipped."""
    owner = _stat(home) if home else None
    if owner is None or not hasattr(os, "chown"):
        return []
    given = []
    for level in _levels_below(home, directory):
        status = _lstat(level)
        if status is None or not stat.S_ISDIR(status.st_mode):
            continue
        if level in made or (status.st_uid == 0 and owner.st_uid != 0):
            os.chown(level, owner.st_uid, owner.st_gid)
            given.append(level)
    return given


def _levels_below(home: str, directory: str) -> list:
    """Each folder from just below ``home`` down to ``directory``, empty
    when ``directory`` is not under ``home``."""
    if not _is_under(directory, home):
        return []
    top = os.path.normpath(home)
    levels = []
    current = os.path.normpath(directory)
    while current != top:
        levels.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            return []
        current = parent
    return list(reversed(levels))


def _is_under(path: str, directory: str) -> bool:
    """Whether a path lies below a folder."""
    parent = os.path.normpath(directory).rstrip(os.sep) + os.sep
    return os.path.normpath(path).startswith(parent)


def _owner_of(path: str):
    """Who a settings file belongs to, so a rewrite does not take it away.

    Args:
        path: The file being written.

    Returns:
        ``(uid, gid, mode)`` to restore, or None where nothing says whose
        the file is. An existing file answers for itself; a new one takes
        its directory's owner, which under a home is that person.
    """
    existing = _stat(path)
    if existing is not None:
        return existing.st_uid, existing.st_gid, existing.st_mode & 0o777
    for parent in (os.path.dirname(path), os.path.dirname(os.path.dirname(path))):
        owner = _stat(parent)
        if owner is not None and owner.st_uid != 0:
            return owner.st_uid, owner.st_gid, 0o644
    return None


def _stat(path: str):
    """One path's stat, or None when it cannot be read."""
    try:
        return os.stat(path)
    except OSError:
        return None


def _lstat(path: str):
    """One path's own stat, a symbolic link's not followed; None when it
    cannot be read."""
    try:
        return os.lstat(path)
    except OSError:
        return None
