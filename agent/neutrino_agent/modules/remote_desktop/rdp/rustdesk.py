"""RustDesk's settings files, as the Remote desktop module writes them.

RustDesk keeps two files per account that runs it: ``RustDesk2.toml``, its
options, and ``RustDesk.toml``, its id, keys and permanent password. The
Remote desktop module writes both while the host is stopped: a running host
writes back what it holds as it exits. The options name the direct
connection and point the rendezvous and relay servers at the machine's own
loopback; the password goes in as ``password = '<p>'``, which RustDesk
reads as given, since ``--password`` from a copy outside RustDesk's
standard place sets nothing.

**The owner is part of the file.** A seated account's copy is written by
this root daemon but read and written by RustDesk running as that person;
on Wayland it stores the screen-capture permission there, so a copy left
owned by root costs that person the permission dialog on every connection.
A file keeps the owner and mode it had, and a new one under a home is made
as that home's owner.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import posixpath
import re
import sys

from neutrino_agent.exceptions import InstallError
from neutrino_agent.platforms.detect import OS_NAMES

# The settings file the seat's Wayland permission is read from, under
# root's and an account's own configuration on Linux.
RUSTDESK_CONFIG_NAME = "RustDesk2.toml"
RUSTDESK_ROOT_CONFIG = "/root/.config/rustdesk"
RUSTDESK_ACCOUNT_RELATIVE = ".config/rustdesk"

# A key = 'value' line, as RustDesk itself writes it.
RUSTDESK_OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=")
RUSTDESK_PASSWORD_KEY = "password"


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


def write_password(path: str, password: str) -> bool:
    """Write the permanent password into one ``RustDesk.toml``.

    Args:
        path: The file to write.
        password: The seat password.

    Returns:
        True when the file's text is not what it was.

    Raises:
        InstallError: If the file cannot be written.
    """
    return write_settings(path, lambda existing: render_password(existing, password))


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


def write_settings(path: str, render) -> bool:
    """Write one settings file through a renderer, keeping its owner and mode.

    Args:
        path: The file to write.
        render: Called with the file's current text, empty when there is
            none; returns the text to write.

    Returns:
        True when the file's text is not what it was.

    Raises:
        InstallError: If the file cannot be written.
    """
    try:
        existing = ""
        kept = _owner_of(path)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as stream:
                existing = stream.read()
        rendered = render(existing)
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(rendered)
        if kept is not None and hasattr(os, "chown"):
            os.chown(temporary, kept[0], kept[1])
            os.chmod(temporary, kept[2])
        os.replace(temporary, path)
    except OSError as error:
        raise InstallError(f"could not write {path}: {error}")
    return rendered != existing


def _quoted(value: str) -> str:
    """One TOML string: a literal one unless the value holds a quote."""
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


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
