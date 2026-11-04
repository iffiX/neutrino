"""Each account's ``PATH`` for the command line programs, on Linux and macOS.

One file per account, ``env.sh`` in the account's own Neutrino tree, puts
the launcher folder of every command line program the account is enabled
in at the front of ``PATH``, each once however often it is loaded. One line
carrying Neutrino's mark, at the end of each startup file the account's
login shell reads, loads it; fish reads ``env.fish`` beside it from
``config.fish``. The line and the env files are the account's, shared by
every command line program: the first program enabled writes them and the
last one let go removes them. ``program_path.json`` under the state root
keeps, per account, the programs the env files name, the env files, and
each startup file the line is in, with whether the module made the file and
whether it added a newline before the line. Every read and write of the
account's files runs as the account through :class:`AccountFiles`, a
startup file in place.

Not pure: runs commands as the accounts and writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os
import posixpath
import tempfile
import threading

from neutrino_agent.constants import (
    AGENT_PROGRAM_BASH_LOGIN_FILES,
    AGENT_PROGRAM_BASH_SHELL,
    AGENT_PROGRAM_ENV_FISH_NAME,
    AGENT_PROGRAM_ENV_NAME,
    AGENT_PROGRAM_FISH_SHELL,
    AGENT_PROGRAM_LINE_MARK,
    AGENT_PROGRAM_MODULES,
    AGENT_PROGRAM_OTHER_STARTUP_FILES,
    AGENT_PROGRAM_PATH_RECORD_NAME,
    AGENT_PROGRAM_STARTUP_FILES,
    AGENT_PROGRAM_TREE_OWN_PARTS,
    AGENT_PROGRAM_TREE_PARTS,
)
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.platforms.base import launcher_folders

# One edit of the record and of an account's files at a time, across every
# command line program of this process.
PATH_LOCK = threading.Lock()


def tree_folder(home: str, os_name: str) -> str:
    """The account's own Neutrino tree, where its env files sit. Pure.

    Args:
        home: The account's home.
        os_name: The system, ``linux`` or ``darwin``.

    Returns:
        ``~/.local/share/neutrino/agent`` on Linux and
        ``~/Library/Application Support/Neutrino/agent`` on macOS.
    """
    return posixpath.join(home, *AGENT_PROGRAM_TREE_PARTS[os_name])


def startup_line(os_name: str, *, is_fish: bool) -> bytes:
    """The marked line that loads the account's env file. Pure.

    Args:
        os_name: The system, ``linux`` or ``darwin``.
        is_fish: Whether the line is fish's, loading ``env.fish``.

    Returns:
        The line, without its newline.
    """
    tree = "/".join(AGENT_PROGRAM_TREE_PARTS[os_name])
    if is_fish:
        path = f"$HOME/{tree}/{AGENT_PROGRAM_ENV_FISH_NAME}"
        text = f'test -f "{path}"; and source "{path}" {AGENT_PROGRAM_LINE_MARK}'
    else:
        path = f"$HOME/{tree}/{AGENT_PROGRAM_ENV_NAME}"
        text = f'[ -f "{path}" ] && . "{path}" {AGENT_PROGRAM_LINE_MARK}'
    return text.encode("utf-8")


def env_sh_text(folders: list) -> str:
    """``env.sh``: each folder taken out of ``PATH`` and put at its front, in order. Pure.

    Args:
        folders: The launcher folders, first first.

    Returns:
        The script, for every POSIX shell.
    """
    quoted = [f"'{folder}'" for folder in folders]
    front = ":".join(quoted)
    return "\n".join(
        [
            "# Neutrino: the command line programs of this account, first on PATH.",
            "neutrino_rest=${PATH:+$PATH:}",
            "neutrino_path=",
            "neutrino_kept=0",
            'while [ -n "$neutrino_rest" ]; do',
            "  neutrino_part=${neutrino_rest%%:*}",
            "  neutrino_rest=${neutrino_rest#*:}",
            "  case $neutrino_part in",
            f"    {'|'.join(quoted)}) ;;",
            '    *) if [ "$neutrino_kept" = 1 ]; then'
            " neutrino_path=$neutrino_path:$neutrino_part;"
            " else neutrino_path=$neutrino_part; neutrino_kept=1; fi ;;",
            "  esac",
            "done",
            'if [ "$neutrino_kept" = 1 ]; then',
            f"  PATH={front}:$neutrino_path",
            "else",
            f"  PATH={front}",
            "fi",
            "export PATH",
            "unset neutrino_rest neutrino_path neutrino_kept neutrino_part",
            "",
        ]
    )


def env_fish_text(folders: list) -> str:
    """``env.fish``: the same folders first on ``PATH``, in fish's words. Pure.

    Args:
        folders: The launcher folders, first first.

    Returns:
        The script.
    """
    lines = ["# Neutrino: the command line programs of this account, first on PATH."]
    for folder in reversed(folders):
        lines.append(f"set -gx PATH '{folder}' (string match -v -- '{folder}' $PATH)")
    lines.append("")
    return "\n".join(lines)


def with_line_last(data: bytes, line: bytes) -> tuple:
    """A file's bytes with a line at their end. Pure.

    Args:
        data: The file as it stands; empty for a file that is not there.
        line: The line, without its newline.

    Returns:
        ``(bytes, is_newline_added)``: a newline goes before the line when
        the last byte is no newline.
    """
    is_added = bool(data) and not data.endswith(b"\n")
    return data + (b"\n" if is_added else b"") + line + b"\n", is_added


def without_lines(data: bytes, lines, is_newline_added: bool) -> bytes:
    """A file's bytes with every line equal to one of the module's lines taken out. Pure.

    Args:
        data: The file as it stands.
        lines: The module's lines, without their newlines.
        is_newline_added: Whether the module added a newline before its
            line; it goes again while that line was the file's last.

    Returns:
        The bytes.
    """
    marked = set(lines)
    parts = data.split(b"\n")
    body, tail = parts[:-1], parts[-1]
    was_last = bool(body) and body[-1] in marked and tail == b""
    if tail in marked:
        tail = b""
        was_last = True
    kept = [part for part in body if part not in marked]
    text = b"".join(part + b"\n" for part in kept) + tail
    if is_newline_added and was_last and text.endswith(b"\n"):
        text = text[:-1]
    return text


def startup_names(shell: str, existing) -> list:
    """The startup files a login shell reads, below the home. Pure.

    Args:
        shell: The login shell, by its path.
        existing: The names of bash's login files that are there.

    Returns:
        bash's ``.bashrc`` and its login file, zsh's ``.zshrc``, fish's
        ``config.fish``, and ``.profile`` for any other shell.
    """
    name = posixpath.basename(str(shell or ""))
    if name == AGENT_PROGRAM_BASH_SHELL:
        login = next(
            (each for each in AGENT_PROGRAM_BASH_LOGIN_FILES if each in set(existing)),
            AGENT_PROGRAM_BASH_LOGIN_FILES[-1],
        )
        return list(AGENT_PROGRAM_STARTUP_FILES[name]) + [login]
    return list(
        AGENT_PROGRAM_STARTUP_FILES.get(name, AGENT_PROGRAM_OTHER_STARTUP_FILES)
    )


def ordered_modules(modules) -> list:
    """Command line programs in :data:`AGENT_PROGRAM_MODULES`' order, each once. Pure."""
    named = set(modules or ())
    return [module for module in AGENT_PROGRAM_MODULES if module in named]


def file_stamp(path: str) -> "list | None":
    """One file's size, time and inode, as a record keeps them.

    Args:
        path: The file; a link is followed.

    Returns:
        ``[size, mtime_ns, inode]``; None when it is not there.
    """
    try:
        found = os.stat(path)
    except OSError:
        return None
    return [int(found.st_size), int(found.st_mtime_ns), int(found.st_ino)]


class ProgramPathApplier:
    """Each account's env files and marked startup lines, shared by the command line programs."""

    def __init__(self, *, platform, lookup_account, log=print):
        """
        Args:
            platform: The machine's platform, Linux or macOS.
            lookup_account: Called with an account; returns its
                :class:`AccountEntry` or raises ``KeyError``.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._os_name = platform.os_name
        self._lookup_account = lookup_account
        self._log = log

    @property
    def record_path(self) -> str:
        """The record of every account's env files and startup lines."""
        return os.path.join(
            self._platform.agent_var_dir(), AGENT_PROGRAM_PATH_RECORD_NAME
        )

    def set_module(
        self, account: str, entry, module: str, *, is_put_first: bool
    ) -> list:
        """Name a program's launcher folder in the account's env file, and put the line last in each startup file where asked.

        The line goes in at the account's first program and whenever
        ``is_put_first`` asks; otherwise no startup file is touched.

        Args:
            account: The account.
            entry: The account as the machine has it, with its home and
                its login shell.
            module: The program.
            is_put_first: Whether the line moves to the end of each file.

        Returns:
            What changed, one note each.

        Raises:
            OSError: When a file cannot be read or written as the account.
        """
        with PATH_LOCK:
            record = self._read_record()
            held = _held_of(record.get(account))
            held["modules"] = ordered_modules(held["modules"] + [module])
            notes = self._write_env(account, entry, held)
            if is_put_first or not held["files"]:
                notes += self._put_lines_last(account, entry, held)
            record[account] = held
            self._write_record(record)
        return notes

    def drop_module(self, account: str, module: str) -> list:
        """Take a program's folder out of the account's env file, and the line and the env files away with the last program.

        Each startup file is then byte for byte what it was, and a file
        the module made goes once nothing else is in it.

        Args:
            account: The account.
            module: The program.

        Returns:
            What changed, one note each.

        Raises:
            OSError: When a file cannot be read or written as the account.
        """
        with PATH_LOCK:
            record = self._read_record()
            if account not in record:
                return []
            held = _held_of(record.get(account))
            held["modules"] = [each for each in held["modules"] if each != module]
            try:
                entry = self._lookup_account(account)
            except KeyError:
                del record[account]
                self._write_record(record)
                return [f"{account} is gone, its PATH record dropped"]
            if held["modules"]:
                notes = self._write_env(account, entry, held)
                record[account] = held
            else:
                notes = self._take_back(account, entry, held)
                del record[account]
            self._write_record(record)
        return notes

    def stamps(self, account: str) -> dict:
        """The size, time and inode of each startup file and env file of an account the record names.

        Args:
            account: The account.

        Returns:
            Path to its stamp, None for a file that is not there; empty for
            an account the record does not name.
        """
        with PATH_LOCK:
            held = _held_of(self._read_record().get(account))
        paths = list(held["files"]) + list(held["env"])
        return {path: file_stamp(path) for path in sorted(paths)}

    # --- the account's files ---

    def _write_env(self, account: str, entry, held: dict) -> list:
        """Write the env file of the account's login shell when its text differs."""
        folders = launcher_folders(
            self._platform.agent_var_dir(), self._os_name, held["modules"]
        )
        is_fish = _is_fish(entry.shell)
        name = AGENT_PROGRAM_ENV_FISH_NAME if is_fish else AGENT_PROGRAM_ENV_NAME
        path = posixpath.join(tree_folder(entry.home, self._os_name), name)
        text = (env_fish_text if is_fish else env_sh_text)(folders).encode("utf-8")
        if path not in held["env"]:
            held["env"].append(path)
        if self._read(account, path) == text:
            return []
        self._write(account, path, text)
        return [f"wrote {path}"]

    def _put_lines_last(self, account: str, entry, held: dict) -> list:
        """Move the marked line to the end of each startup file of the account's login shell, adding it where it is missing."""
        home = entry.home
        login = [posixpath.join(home, name) for name in AGENT_PROGRAM_BASH_LOGIN_FILES]
        present = {posixpath.basename(path) for path in self._existing(account, login)}
        line = startup_line(self._os_name, is_fish=_is_fish(entry.shell))
        notes = []
        for name in startup_names(entry.shell, present):
            path = posixpath.join(home, name)
            facts = dict(held["files"].get(path) or {})
            data = self._read(account, path)
            if data is None:
                facts = {"is_made": True, "is_newline_added": False}
                data = b""
            else:
                facts.setdefault("is_made", False)
                data = without_lines(
                    data, self._lines(), bool(facts.get("is_newline_added"))
                )
            text, is_added = with_line_last(data, line)
            facts["is_newline_added"] = is_added
            self._write(account, path, text)
            held["files"][path] = facts
            notes.append(f"put the line last in {path}")
        return notes

    def _take_back(self, account: str, entry, held: dict) -> list:
        """Remove the line from each file it went in, the env files, and the Neutrino folders left empty."""
        notes = []
        for path, facts in sorted(held["files"].items()):
            data = self._read(account, path)
            if data is None:
                continue
            text = without_lines(
                data, self._lines(), bool(facts.get("is_newline_added"))
            )
            if text == data:
                continue
            if not text and facts.get("is_made"):
                self._remove(account, path)
                notes.append(f"removed {path}")
                continue
            self._write(account, path, text)
            notes.append(f"took the line out of {path}")
        for path in held["env"]:
            self._remove(account, path)
            notes.append(f"removed {path}")
        tree = tree_folder(entry.home, self._os_name)
        folders = [tree]
        for _turn in range(AGENT_PROGRAM_TREE_OWN_PARTS - 1):
            folders.append(posixpath.dirname(folders[-1]))
        self._files(account).remove_empty_dirs(folders)
        return notes

    def _lines(self) -> tuple:
        """Every line of the module's on this system, ``sh``'s and fish's."""
        return (
            startup_line(self._os_name, is_fish=False),
            startup_line(self._os_name, is_fish=True),
        )

    def _existing(self, account: str, paths: list) -> list:
        """The paths that are there, as the account sees them."""
        return self._files(account).existing(paths)

    def _read(self, account: str, path: str) -> "bytes | None":
        """A file's bytes, read as the account; None when it is not there.

        Raises:
            OSError: When it cannot be read.
        """
        return self._files(account).read(path)

    def _write(self, account: str, path: str, data: bytes) -> None:
        """Write a file's bytes in place as the account, its folder made.

        Raises:
            OSError: When it cannot be written.
        """
        self._files(account).write_in_place(path, data)

    def _remove(self, account: str, path: str) -> None:
        """Delete a file as the account.

        Raises:
            OSError: When it cannot be deleted.
        """
        self._files(account).remove(path)

    def _files(self, account: str) -> AccountFiles:
        """The account's places, reached as the account."""
        return AccountFiles(platform=self._platform, account=account)

    # --- the record ---

    def _read_record(self) -> dict:
        """Each account's facts, by account. Call under the lock."""
        try:
            with open(self.record_path, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        accounts = held.get("accounts") if isinstance(held, dict) else None
        if not isinstance(accounts, dict):
            return {}
        return {
            str(name): _held_of(facts)
            for name, facts in accounts.items()
            if isinstance(facts, dict)
        }

    def _write_record(self, records: dict) -> None:
        """Keep the record, root-only, whole or not at all. Call under the lock.

        Raises:
            OSError: When the file cannot be written.
        """
        folder = os.path.dirname(self.record_path)
        os.makedirs(folder, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=folder, prefix=".program_path_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"accounts": records}, stream, sort_keys=True)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.record_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise


def _held_of(facts) -> dict:
    """One account's facts with every key present. Pure."""
    facts = facts if isinstance(facts, dict) else {}
    files = facts.get("files")
    return {
        "modules": ordered_modules(facts.get("modules") or []),
        "env": [str(path) for path in facts.get("env") or [] if path],
        "files": {
            str(path): dict(each)
            for path, each in (files.items() if isinstance(files, dict) else [])
            if isinstance(each, dict)
        },
    }


def _is_fish(shell: str) -> bool:
    """Whether a login shell is fish. Pure."""
    return posixpath.basename(str(shell or "")) == AGENT_PROGRAM_FISH_SHELL
