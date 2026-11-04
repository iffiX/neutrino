"""The runner every command line program shares.

A command line program runs nothing of its own. Each enabled account runs
its own copy, or the module's copy, unpacked under the module's directory
and started by the module's launcher. A task's plan begins with ``find``,
which looks for each enabled account's own copy as the account and keeps
what it found in the module's record. The install of the module's copy
follows while an account needs it, then ``configure``, which writes the
launcher and lets go of every account no longer enabled, then one
``account {account}`` per enabled account, which makes or removes the
account's link, or on Windows its user ``PATH`` entry. A read checks each
recorded copy and link, and asks for a task of the module's own when one
went, fell below the module's floor or was replaced. The module's
:class:`ProgramHooks` names what differs: the program's name, the places a
person's copy is looked for, where the program sits in the module's copy,
and what the launcher sets.

Not pure: runs commands as the accounts and writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import functools
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from neutrino_agent.constants import (
    AGENT_PROGRAM_CODE_LINK_TAKEN,
    AGENT_PROGRAM_CODE_OLD_COPY,
    AGENT_PROGRAM_COPY_MODULE,
    AGENT_PROGRAM_COPY_USER,
    AGENT_PROGRAM_FALLBACK_SHELL,
    AGENT_PROGRAM_JOURNAL_SCAN_LINES,
    AGENT_PROGRAM_LAUNCHER_DIR_NAME,
    AGENT_PROGRAM_LINK_DIR_PARTS,
    AGENT_PROGRAM_MODULES,
    AGENT_PROGRAM_PACKAGE_DIR_NAME,
    AGENT_PROGRAM_PATH_COMMAND,
    AGENT_PROGRAM_RECORD_NAME,
    AGENT_PROGRAM_SHELL_TIMEOUT_S,
    AGENT_PROGRAM_VERSION_TIMEOUT_S,
    AGENT_PROGRAM_WINDOWS_FIND_PARTS,
    AGENT_PROGRAM_WINDOWS_PATH_PARTS,
    AGENT_PROGRAM_WINDOWS_POWERSHELL,
    AGENT_PROGRAM_WINDOWS_RUN_TIMEOUT_S,
    AGENT_SERVICE_NAME,
    AGENT_STEP_ACCOUNT,
    AGENT_STEP_CONFIGURE,
    AGENT_STEP_FIND,
    AGENT_TASK_LINE_PATTERN,
)
from neutrino_agent.exceptions import (
    ModuleApplyError,
    PlatformUnsupportedError,
    StepSuperseded,
)
from neutrino_agent.modules.shared import subprocess_run
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
    write_if_changed,
)
from neutrino_agent.modules.shared.base import ModuleRunner, ModuleStep
from neutrino_agent.modules.shared.instances import machine_for
from neutrino_agent.modules.shared.package import joiner, params_of
from neutrino_agent.modules.shared.unpacked_tree import remove_tree
from neutrino_agent.modules.shared.windows_acl import leave_to_system

# An account name that survives a command line, a path and a task name.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")
# The first dotted number a program's ``--version`` prints.
VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)+")
# How many times, and how often, an uninstall deletes the module's directory.
# Windows refuses to delete a program file for a moment after its process ended.
REMOVE_TRIES = 30
REMOVE_RETRY_S = 1.0
# What ``sh`` prints of its arguments: each one that is a file the account
# may run, in order.
EXECUTABLES_SHELL = (
    'for p do [ -f "$p" ] && [ -x "$p" ] && printf "%s\\n" "$p"; done; exit 0'
)
# What ``sh`` runs as the account to make the link ``$0`` to the launcher
# ``$1``: its folder made first when missing. It prints ``made``,
# ``present`` or ``taken``, and 1 when it made the folder.
LINK_SHELL = (
    'd=$(dirname "$0"); m=0; '
    'if [ ! -d "$d" ]; then mkdir -p "$d" || exit 1; m=1; fi; '
    'if [ -L "$0" ] || [ -e "$0" ]; then '
    'if [ -L "$0" ] && [ "$(readlink "$0")" = "$1" ]; then echo "present $m"; '
    'else echo "taken $m"; fi; '
    'else ln -s "$1" "$0" || exit 1; echo "made $m"; fi'
)
# What ``sh`` runs as the account to remove the link ``$0`` while it still
# points at the launcher ``$1``, then the folder ``$2`` when one is named
# and empty.
UNLINK_SHELL = (
    'if [ -L "$0" ] && [ "$(readlink "$0")" = "$1" ]; then rm -f "$0"; fi; '
    'if [ -n "$2" ]; then rmdir "$2" 2>/dev/null; fi; echo done'
)
# What a link step prints.
LINK_MADE = "made"
LINK_PRESENT = "present"
LINK_TAKEN = "taken"
# What a Windows PATH entry step prints.
ENTRY_ADDED = "added"
ENTRY_PRESENT = "present"
ENTRY_REMOVED = "removed"
ENTRY_ABSENT = "absent"
# A read's reasons to ask for a task.
ASK_GONE = "gone"
ASK_BELOW = "below"
ASK_LINK = "link"
# How much of a failed command's words an ``apply_failed`` keeps.
DETAIL_CHARS = 500


@dataclass
class ProgramAccount:
    """One enabled account of a command line program.

    Attributes:
        account: The account.
        password: The account's password; Windows only.
    """

    account: str
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ProgramAccount":
        return cls(
            account=str(data.get("account", "") or ""),
            password=str(data.get("password", "") or ""),
        )


@dataclass
class ProgramConfig:
    """Everything a command line program's desired configuration holds.

    Attributes:
        accounts: The enabled accounts, in the order they were enabled.
    """

    accounts: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ProgramConfig":
        accounts = data.get("accounts")
        return cls(
            accounts=[
                ProgramAccount.from_dict(entry)
                for entry in (accounts if isinstance(accounts, list) else [])
                if isinstance(entry, dict)
            ]
        )

    def validate(self, *, os_name: str = "linux") -> None:
        """Check the configuration holds together.

        Args:
            os_name: The system; on ``windows`` every account needs its
                password.

        Raises:
            ModuleApplyError: ``account_invalid`` or ``account_duplicate``,
                naming the first problem found, and on Windows
                ``credential_missing`` for an account with no password.
        """
        accounts: set = set()
        for held in self.accounts:
            if not ACCOUNT_PATTERN.match(held.account):
                raise ModuleApplyError("account_invalid", {"account": held.account})
            if held.account.lower() in accounts:
                raise ModuleApplyError("account_duplicate", {"account": held.account})
            accounts.add(held.account.lower())
            if os_name == "windows" and not held.password:
                raise ModuleApplyError("credential_missing", {"account": held.account})


def first_version(text: str) -> str:
    """The first dotted number in a program's words. Pure.

    Args:
        text: What the program printed.

    Returns:
        The number, such as ``2.1.311``; empty when it prints none.
    """
    found = VERSION_PATTERN.search(str(text or ""))
    return found.group(0) if found else ""


def version_key(version: str) -> tuple:
    """A dotted number as a tuple of numbers, for ordering. Pure.

    Args:
        version: The number.

    Returns:
        Its parts; empty for text that is no dotted number.
    """
    number = first_version(version)
    return tuple(int(part) for part in number.split(".")) if number else ()


def is_supported(version: str, floor: str) -> bool:
    """Whether a person's copy is at the module's floor or newer. Pure.

    Args:
        version: The copy's version.
        floor: The manifest's ``user_copy_min_version``; empty admits every
            version.

    Returns:
        True when the copy's version is no lower than the floor.
    """
    if not version_key(version):
        return False
    return not version_key(floor) or version_key(version) >= version_key(floor)


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


def launcher_text(program: str, variables, os_name: str) -> str:
    """The launcher a module writes for its copy. Pure.

    Args:
        program: The unpacked program, by its full path.
        variables: ``(name, value)`` pairs the launcher sets.
        os_name: The system.

    Returns:
        A ``sh`` script on Linux and macOS; on Windows a ``.cmd`` script
        with CRLF line ends.
    """
    if os_name == "windows":
        lines = ["@echo off", "setlocal"]
        lines += [f'set "{name}={value}"' for name, value in variables]
        lines.append('"{}" %*'.format(program.replace("%", "%%")))
        lines.append("exit /b %ERRORLEVEL%")
        return "\r\n".join(lines) + "\r\n"
    lines = ["#!/bin/sh"]
    for name, value in variables:
        lines += [f"{name}={value}", f"export {name}"]
    lines.append(f'exec "{program}" "$@"')
    return "\n".join(lines) + "\n"


def windows_script(parts: tuple) -> str:
    """One of the scripts the agent's package carries for a run as a Windows account.

    Args:
        parts: The script's path under the package's own directory.

    Returns:
        Its absolute path.
    """
    package = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(package, *parts)


class ProgramHooks:
    """What differs per command line program.

    A module subclasses this in its ``hooks.py``.

    Attributes:
        name: The module's name on the wire.
        title: What the module is called in its log lines.
        runner: The name a recipe's ``runner`` chooses the module by.
        program: The name a shell runs the program by.
        known_places: By system, the places after ``PATH`` a person's copy
            is looked for, ``~`` being the account's home on Linux and macOS
            and Windows' variables expanded as the account.
        launcher_variables: ``(name, value)`` pairs the launcher sets.
        config_class: The module's configuration, with ``from_dict``.
    """

    name = ""
    title = ""
    runner = ""
    program = ""
    known_places: dict = {}
    launcher_variables: tuple = ()
    config_class = ProgramConfig

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform.
        """
        self._platform = platform

    def parse(self, config: dict):
        """The configuration parsed and checked for this system.

        Args:
            config: The module's desired configuration.

        Returns:
            The parsed configuration, with ``accounts``.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = self.config_class.from_dict(config)
        parsed.validate(os_name=self._platform.os_name)
        return parsed

    def program_parts(self) -> tuple:
        """Where the program sits under the module's copy on this machine.

        Returns:
            The path's parts under ``package``.

        Raises:
            NotImplementedError: For a module that names none.
        """
        raise NotImplementedError(f"{self.name}: program_parts")


class ProgramsModuleRunner(ModuleRunner):
    """Makes a command line program ready for each enabled account."""

    def __init__(
        self,
        *,
        hooks_class,
        platform,
        log=print,
        publish=None,
        run=subprocess_run.run,
        journal=subprocess_run.units_journal,
        machine: "ServiceMachine | None" = None,
    ):
        """
        Args:
            hooks_class: The module's :class:`ProgramHooks` subclass, made
                with ``platform``.
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            run: Runs one command as :func:`subprocess_run.run` does.
            journal: Reads the tail of units' journals as
                :func:`subprocess_run.units_journal` does.
            machine: The machine, with its account lookup; None is the
                platform's own.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._hooks = hooks_class(platform=platform)
        self.name = self._hooks.name
        self.runner = self._hooks.runner
        self._os_name = platform.os_name
        self._join = joiner(self._os_name)
        self._run = run
        self._journal = journal
        self._machine = (
            machine if machine is not None else machine_for(platform, self.name)
        )
        self._recipe: dict = {}
        self._config: dict = {}
        # One read or write of the record at a time.
        self._lock = threading.Lock()
        # The reasons a read asked for a task since the last ``find``.
        self._asked: set = set()
        # The module copy's version, by the stamp of the file it was read from.
        self._version_read: tuple = (None, "")

    @property
    def hooks(self) -> ProgramHooks:
        """The module's hooks."""
        return self._hooks

    @property
    def package_dir(self) -> str:
        """The module's own copy, unpacked."""
        return self._join(self.module_dir, AGENT_PROGRAM_PACKAGE_DIR_NAME)

    @property
    def program_path(self) -> str:
        """The program in the module's own copy."""
        return self._join(self.package_dir, *self._hooks.program_parts())

    @property
    def launcher_dir(self) -> str:
        """The launcher's folder, the one folder a ``PATH`` names."""
        return self._join(self.module_dir, AGENT_PROGRAM_LAUNCHER_DIR_NAME)

    @property
    def launcher_path(self) -> str:
        """The launcher of the module's copy."""
        suffix = ".cmd" if self._os_name == "windows" else ""
        return self._join(self.launcher_dir, self._hooks.program + suffix)

    @property
    def record_path(self) -> str:
        """The record of each account's copy."""
        return self._join(self.module_dir, AGENT_PROGRAM_RECORD_NAME)

    def take_recipe(self, recipe: dict) -> None:
        """Keep the recipe the state names.

        Args:
            recipe: ``{runner, method, params}``.
        """
        self._recipe = dict(recipe)

    def take_config(self, config: dict) -> None:
        """Keep the configuration the state names.

        Args:
            config: ``{accounts: [{account, password}]}``.
        """
        self._config = dict(config)

    def verify(self, recipe: dict) -> bool:
        """Whether the module's own copy is in the module's directory.

        Args:
            recipe: The module's recipe, empty for a module the state does
                not name.

        Returns:
            True while the program's file is there.
        """
        return os.path.isfile(self.program_path)

    def has_module_copy(self) -> bool:
        """Whether the module's own copy is in the module's directory.

        Returns:
            True while the program's file is there.
        """
        return os.path.isfile(self.program_path)

    def has_person_copies(self) -> bool:
        """Whether an enabled account runs its own copy at a supported version, its file unchanged.

        Reads each recorded copy and link first, and asks for a task when
        one went, fell below the floor or was replaced.

        Returns:
            True when the record names such an account.
        """
        return self._read_accounts(is_named=True)

    def needs_module_copy(self, config: dict) -> bool:
        """Whether an enabled account needs the module's own copy, by the record.

        Args:
            config: The module's desired configuration.

        Returns:
            True while no account is enabled, or an enabled account has no
            copy of its own the record names at a supported version.
        """
        try:
            accounts = [held.account for held in self._hooks.parse(config).accounts]
        except ModuleApplyError:
            return True
        with self._lock:
            records = self._read_record()
        return _needs_module_copy(accounts, records)

    def find_step(self, config: dict) -> ModuleStep:
        """The ``find`` step of a task planned from the record as it stands.

        Args:
            config: The configuration the task's entry carries.

        Returns:
            The step. It plans the task again when what it finds changes
            whether the module's own copy is needed.
        """
        return ModuleStep(
            name=AGENT_STEP_FIND,
            run=functools.partial(
                self._run_find, dict(config), self.needs_module_copy(config)
            ),
        )

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """``configure``, then one ``account {account}`` per enabled account.

        Args:
            config: The configuration the task's entry carries.
            want: The module's ``want``; a command line program starts
                nothing.
            steps: The core's ``configure`` and ``start`` or ``stop``.

        Returns:
            The steps, with no ``start`` and no ``stop``.
        """
        try:
            accounts = [held.account for held in self._hooks.parse(config).accounts]
        except ModuleApplyError:
            accounts = []
        planned = [
            ModuleStep(
                name=AGENT_STEP_CONFIGURE,
                run=functools.partial(self._run_configure, dict(config)),
            )
        ]
        planned += [
            ModuleStep(
                name=AGENT_STEP_ACCOUNT,
                params={"account": account},
                run=functools.partial(self._run_account, dict(config), account),
            )
            for account in accounts
        ]
        return planned

    def validate(self, config: dict) -> None:
        """Parse and check a configuration for this system.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        self._hooks.parse(config)

    def apply(self, config: dict) -> None:
        """Write the launcher and let go of every account no longer enabled.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or the
                machine will not take it.
        """
        self._run_configure(dict(config), None)

    def is_active(self) -> bool:
        """A command line program reads running once configured.

        Returns:
            True.
        """
        return True

    def remove_configuration(self) -> None:
        """Remove every link and ``PATH`` entry that still carries the module's mark."""
        for line in self.remove_ways_in():
            self._log(line)

    def uninstall(self, recipe: dict) -> None:
        """Remove every marked link and ``PATH`` entry, then the module's directory: its copy, its launcher and its record.

        Args:
            recipe: The module's recipe.
        """
        for line in self.remove_ways_in():
            self._log(line)
        self._remove_module_dir()

    def remove_ways_in(self) -> list:
        """Remove every link and ``PATH`` entry the record names that still carries the module's mark.

        A way in that cannot be removed is a line, and the others go on.

        Returns:
            What was removed or left, one line each.
        """
        with self._lock:
            records = self._read_record()
        passwords = self._passwords()
        lines = []
        for account, record in records.items():
            if not record.get("is_link_made"):
                continue
            password = passwords.get(account) or str(record.get("password", "") or "")
            try:
                is_folder_left = self._let_go(account, record, password)
            except (ModuleApplyError, OSError, subprocess.SubprocessError) as error:
                said = error.code if isinstance(error, ModuleApplyError) else str(error)
                lines.append(f"{self.name}: the way in of {account} stays: {said}")
                continue
            lines.append(f"{self.name}: removed the way in of {account}")
            with self._lock:
                held = self._read_record()
                if account in held:
                    held[account] = {
                        **held[account],
                        "is_link_made": False,
                        "is_local_bin_made": is_folder_left,
                    }
                    self._write_record(held)
        return lines

    def details(self, recipe: dict) -> dict:
        """Whether the module's copy is there, its version, and each enabled account's copy.

        Args:
            recipe: The module's recipe, empty for a module the state does
                not name.

        Returns:
            ``{has_module_copy, version, accounts: [{account, copy, path,
            version, code, params}]}``, ``version`` the module copy's and
            empty while it has none.
        """
        if recipe:
            self._read_accounts(is_named=True)
        with self._lock:
            records = self._read_record()
        order = self._enabled() if recipe else list(records)
        module_version = self._module_version()
        rows = []
        for account in order:
            record = records.get(account)
            if not record:
                continue
            is_user = record.get("copy") == AGENT_PROGRAM_COPY_USER
            rows.append(
                {
                    "account": account,
                    "copy": str(record.get("copy", "") or ""),
                    "path": str(record.get("path", "") or ""),
                    "version": (
                        str(record.get("version", "") or "")
                        if is_user
                        else module_version
                    ),
                    "code": str(record.get("code", "") or ""),
                    "params": dict(record.get("params") or {}),
                }
            )
        return {
            "has_module_copy": self.has_module_copy(),
            "version": module_version,
            "accounts": rows,
        }

    def journal_text(self, lines: int) -> list:
        """The agent's own lines that name the module, its journal on Linux and its log elsewhere.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first.
        """
        if self._os_name != "linux":
            return self._agent_log_lines(lines)
        pattern = re.compile(AGENT_TASK_LINE_PATTERN)
        named = [
            line
            for line in self._journal(
                [AGENT_SERVICE_NAME], AGENT_PROGRAM_JOURNAL_SCAN_LINES
            )
            if self.name in line and not pattern.search(line)
        ]
        return named[-lines:]

    # --- the steps ---

    def _run_find(self, config: dict, basis: bool, context) -> None:
        """The ``find`` step: each enabled account's own copy looked for as the account, and the record kept.

        Raises:
            ModuleApplyError: The configuration's refusal, ``account_unknown
                {account}``, ``account_no_profile {account}`` and on Windows
                ``credential_invalid {account}``.
            StepSuperseded: When what it found changes whether the module's
                own copy is needed.
        """
        parsed = self._hooks.parse(config)
        floor = self._floor()
        with self._lock:
            held = self._read_record()
        found = {}
        for item in parsed.accounts:
            entry = self._entry_of(item.account)
            before = dict(held.get(item.account) or {})
            copy = self._find_copy(item, entry, before)
            found[item.account] = self._found_record(item, copy, before, floor)
            self._log(_found_line(self.name, item.account, found[item.account]))
        with self._lock:
            held = self._read_record()
            kept = {name: record for name, record in held.items() if name not in found}
            self._write_record({**kept, **found})
            self._asked = set()
        accounts = [item.account for item in parsed.accounts]
        if _needs_module_copy(accounts, found) != basis:
            raise StepSuperseded(self.name)

    def _run_configure(self, config: dict, context) -> None:
        """The ``configure`` step: every account no longer enabled let go, and the launcher written.

        Raises:
            ModuleApplyError: The configuration's refusal, and ``apply_failed
                {detail}`` when the launcher cannot be written.
        """
        parsed = self._hooks.parse(config)
        enabled = {item.account for item in parsed.accounts}
        with self._lock:
            held = self._read_record()
        notes = []
        for account, record in held.items():
            if account in enabled:
                continue
            if record.get("is_link_made"):
                try:
                    self._let_go(account, record, str(record.get("password", "") or ""))
                except (ModuleApplyError, OSError, subprocess.SubprocessError) as error:
                    said = (
                        error.code
                        if isinstance(error, ModuleApplyError)
                        else str(error)
                    )
                    self._log(f"{self.name}: the way in of {account} stays: {said}")
            notes.append(f"let go of {account}")
        with self._lock:
            held = self._read_record()
            self._write_record(
                {name: record for name, record in held.items() if name in enabled}
            )
        try:
            if self._write_launcher():
                notes.append("wrote the launcher")
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": str(error)[:DETAIL_CHARS]}
            ) from None
        self._log(f"{self.name}: " + "; ".join(notes or ["unchanged"]))

    def _run_account(self, config: dict, account: str, context) -> None:
        """The ``account {account}`` step: the account's link or ``PATH`` entry made for the module's copy, or removed for its own.

        Raises:
            ModuleApplyError: ``account_unknown {account}``,
                ``account_no_profile {account}``, ``credential_invalid
                {account}``, or ``apply_failed {detail}`` when the link or
                the entry cannot be made.
        """
        parsed = self._hooks.parse(config)
        item = next((each for each in parsed.accounts if each.account == account), None)
        if item is None:
            raise ModuleApplyError("account_unknown", {"account": account})
        entry = self._entry_of(account)
        with self._lock:
            record = dict(self._read_record().get(account) or {})
        if not record:
            record = self._found_record(item, None, {}, self._floor())
        try:
            if record.get("copy") == AGENT_PROGRAM_COPY_USER:
                is_folder_left = False
                if record.get("is_link_made"):
                    is_folder_left = self._let_go(account, record, item.password)
                record["is_link_made"] = False
                record["is_local_bin_made"] = is_folder_left
                note = f"{account} runs its own copy"
            else:
                note = self._make_way_in(item, entry, record)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": str(error)[:DETAIL_CHARS]}
            ) from None
        if self._os_name == "windows":
            record["password"] = item.password
        with self._lock:
            held = self._read_record()
            held[account] = record
            self._write_record(held)
        self._log(f"{self.name}: {note}")

    # --- the find ---

    def _find_copy(self, item: ProgramAccount, entry: AccountEntry, before: dict):
        """An account's own copy, found as the account.

        Returns:
            ``{path, version, stamp, search_path}``; None when the account
            has no copy whose version reads.
        """
        if self._os_name == "windows":
            return self._find_windows(item)
        return self._find_posix(item.account, entry, before)

    def _find_posix(self, account: str, entry: AccountEntry, before: dict):
        """The first copy on the login shell's ``PATH``, then in the known places, that is not the module's."""
        shell = entry.shell or AGENT_PROGRAM_FALLBACK_SHELL
        search_path = self._login_path(account, shell)
        program = self._hooks.program
        candidates = [
            os.path.join(folder, program) for folder in search_path.split(":") if folder
        ]
        for place in self._hooks.known_places.get(self._os_name, ()):
            candidates.append(
                entry.home + place[1:] if place.startswith("~/") else place
            )
        unique = list(dict.fromkeys(candidates))
        for path in self._executables(account, unique):
            if self._is_module_own(path):
                continue
            stamp = file_stamp(path)
            if stamp is None:
                continue
            version = ""
            if before.get("path") == path and before.get("stamp") == stamp:
                version = str(before.get("version", "") or "")
            if not version:
                version = self._version_posix(account, path, search_path)
            if version:
                return {
                    "path": path,
                    "version": version,
                    "stamp": stamp,
                    "search_path": search_path,
                }
        return None

    def _login_path(self, account: str, shell: str) -> str:
        """The ``PATH`` the account's login shell prints, empty when the shell fails or runs past its time."""
        try:
            result = self._platform.run_as_account(
                account,
                [shell, "-l", "-i", "-c", AGENT_PROGRAM_PATH_COMMAND],
                stdin="",
                timeout_s=AGENT_PROGRAM_SHELL_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError, PlatformUnsupportedError) as error:
            self._log(
                f"{self.name}: the login shell {shell} of {account} gave no PATH: {error}"
            )
            return ""
        printed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if result.returncode != 0 or not printed:
            self._log(
                f"{self.name}: the login shell {shell} of {account} gave no PATH: "
                f"exit {result.returncode}"
            )
            return ""
        return printed[-1]

    def _executables(self, account: str, candidates: list) -> list:
        """The candidates the account may run, in their order."""
        if not candidates:
            return []
        try:
            result = self._platform.run_as_account(
                account,
                ["/bin/sh", "-c", EXECUTABLES_SHELL, "sh", *candidates],
                stdin="",
                timeout_s=AGENT_PROGRAM_VERSION_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError, PlatformUnsupportedError) as error:
            self._log(f"{self.name}: the copies of {account} were not read: {error}")
            return []
        found = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return [path for path in candidates if path in found]

    def _version_posix(self, account: str, path: str, search_path: str) -> str:
        """A copy's version, its ``--version`` run as the account on the account's ``PATH``."""
        try:
            result = self._platform.run_as_account(
                account,
                [path, "--version"],
                stdin="",
                timeout_s=AGENT_PROGRAM_VERSION_TIMEOUT_S,
                environment={"PATH": search_path} if search_path else None,
            )
        except (OSError, subprocess.SubprocessError, PlatformUnsupportedError):
            return ""
        if result.returncode != 0:
            return ""
        return first_version(f"{result.stdout}\n{result.stderr}")

    def _find_windows(self, item: ProgramAccount):
        """The copy the account's ``PATH`` and the known places hold, found by one run as the account."""
        answer = self._windows_run(
            item.account,
            item.password,
            AGENT_PROGRAM_WINDOWS_FIND_PARTS,
            {
                "name": self._hooks.program,
                "skip": self.launcher_dir,
                "places": list(self._hooks.known_places.get("windows", ())),
            },
        )
        path = str(answer.get("path", "") or "")
        version = first_version(str(answer.get("version", "") or ""))
        stamp = file_stamp(path) if path else None
        if not path or not version or stamp is None:
            return None
        return {"path": path, "version": version, "stamp": stamp, "search_path": ""}

    def _is_module_own(self, path: str) -> bool:
        """Whether a path reaches the module's launcher or its program."""
        own = {
            os.path.realpath(self.launcher_path),
            os.path.realpath(self.program_path),
        }
        return os.path.realpath(path) in own

    def _found_record(
        self, item: ProgramAccount, copy, before: dict, floor: str
    ) -> dict:
        """One account's record from what ``find`` found."""
        record = {
            "account": item.account,
            "is_link_made": bool(before.get("is_link_made")),
            "is_local_bin_made": bool(before.get("is_local_bin_made")),
            "password": item.password if self._os_name == "windows" else "",
        }
        if copy is not None and is_supported(copy["version"], floor):
            return {
                **record,
                "copy": AGENT_PROGRAM_COPY_USER,
                "path": copy["path"],
                "version": copy["version"],
                "stamp": copy["stamp"],
                "search_path": copy["search_path"],
                "code": "",
                "params": {},
            }
        code, params = "", {}
        if copy is not None:
            code = AGENT_PROGRAM_CODE_OLD_COPY
            params = {"account": item.account, "version": copy["version"], "min": floor}
        return {
            **record,
            "copy": AGENT_PROGRAM_COPY_MODULE,
            "path": self.launcher_path,
            "version": "",
            "stamp": None,
            "search_path": "",
            "code": code,
            "params": params,
        }

    # --- the ways in ---

    def _make_way_in(
        self, item: ProgramAccount, entry: AccountEntry, record: dict
    ) -> str:
        """Make the link, or on Windows the ``PATH`` entry, that reaches the module's launcher.

        Returns:
            What changed, one note.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when it cannot be made.
        """
        account = item.account
        if self._os_name == "windows":
            answer = self._windows_run(
                account,
                item.password,
                AGENT_PROGRAM_WINDOWS_PATH_PARTS,
                {"verb": "add", "folder": self.launcher_dir},
            )
            result = str(answer.get("result", "") or "")
            if result not in (ENTRY_ADDED, ENTRY_PRESENT):
                raise ModuleApplyError(
                    "apply_failed", {"detail": f"the user PATH of {account}: {result}"}
                )
            record["is_link_made"] = True
            return f"{account} reaches the module's copy through its PATH"
        link = self._link_path(entry.home)
        result = self._platform.run_as_account(
            account,
            ["/bin/sh", "-c", LINK_SHELL, link, self.launcher_path],
            stdin="",
            timeout_s=AGENT_PROGRAM_VERSION_TIMEOUT_S,
        )
        words = (result.stdout.strip().splitlines() or [""])[-1].split()
        if result.returncode != 0 or len(words) != 2:
            detail = (result.stderr or result.stdout).strip()[:DETAIL_CHARS]
            raise ModuleApplyError(
                "apply_failed", {"detail": f"the link {link}: {detail}"}
            )
        outcome, made = words
        if made == "1" or self._is_folder_made_by_sibling(account):
            record["is_local_bin_made"] = True
        if outcome == LINK_TAKEN:
            record["is_link_made"] = False
            if record.get("code") != AGENT_PROGRAM_CODE_OLD_COPY:
                record["code"] = AGENT_PROGRAM_CODE_LINK_TAKEN
                record["params"] = {"account": account, "path": link}
            return f"{link} of {account} holds something of the person's"
        record["is_link_made"] = True
        if record.get("code") == AGENT_PROGRAM_CODE_LINK_TAKEN:
            record["code"], record["params"] = "", {}
        return f"{account} reaches the module's copy through {link}"

    def _let_go(self, account: str, record: dict, password: str) -> bool:
        """Remove an account's link or ``PATH`` entry while it carries the module's mark.

        A ``~/.local/bin`` this module or the other command line program
        made goes with it once it is empty.

        Returns:
            Whether such a folder still stands, holding something else.

        Raises:
            ModuleApplyError: ``credential_invalid {account}`` or
                ``apply_failed {detail}`` on Windows.
            OSError: When the command cannot run.
            subprocess.SubprocessError: When it does not finish.
        """
        if self._os_name == "windows":
            if not password:
                raise ModuleApplyError("credential_missing", {"account": account})
            self._windows_run(
                account,
                password,
                AGENT_PROGRAM_WINDOWS_PATH_PARTS,
                {"verb": "remove", "folder": self.launcher_dir},
            )
            return False
        try:
            entry = self._machine.lookup_account(account)
        except KeyError:
            return False
        link = self._link_path(entry.home)
        folder = self._join(entry.home, *AGENT_PROGRAM_LINK_DIR_PARTS)
        is_made = bool(
            record.get("is_local_bin_made")
        ) or self._is_folder_made_by_sibling(account)
        self._platform.run_as_account(
            account,
            ["/bin/sh", "-c", UNLINK_SHELL, link, self.launcher_path]
            + [folder if is_made else ""],
            stdin="",
            timeout_s=AGENT_PROGRAM_VERSION_TIMEOUT_S,
        )
        return is_made and os.path.isdir(folder)

    def _is_folder_made_by_sibling(self, account: str) -> bool:
        """Whether the other command line program's record says it made the account's ``~/.local/bin``."""
        for module in AGENT_PROGRAM_MODULES:
            if module == self.name:
                continue
            path = self._join(
                self._platform.agent_var_dir(), module, AGENT_PROGRAM_RECORD_NAME
            )
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    held = json.load(stream)
            except (OSError, ValueError):
                continue
            accounts = held.get("accounts") if isinstance(held, dict) else None
            record = accounts.get(account) if isinstance(accounts, dict) else None
            if isinstance(record, dict) and record.get("is_local_bin_made"):
                return True
        return False

    def _link_path(self, home: str) -> str:
        """An account's link, ``~/.local/bin/<name>``."""
        return self._join(home, *AGENT_PROGRAM_LINK_DIR_PARTS, self._hooks.program)

    # --- the read ---

    def _read_accounts(self, *, is_named: bool) -> bool:
        """Read each enabled account's recorded copy and link, and ask for a task when one went, fell below the floor or was replaced.

        A copy whose file changed has its version read again as the
        account, and the record keeps it.

        Returns:
            Whether an enabled account runs its own copy at a supported
            version.
        """
        enabled = self._enabled()
        floor = self._floor()
        with self._lock:
            records = self._read_record()
        served = False
        asks = []
        updates = {}
        for account in enabled:
            record = records.get(account)
            if not record:
                continue
            if record.get("copy") == AGENT_PROGRAM_COPY_USER:
                path = str(record.get("path", "") or "")
                stamp = file_stamp(path)
                if stamp is None:
                    asks.append((account, ASK_GONE, path))
                    continue
                if stamp == record.get("stamp"):
                    served = served or is_supported(
                        str(record.get("version", "") or ""), floor
                    )
                    continue
                version = self._version_of(account, record)
                if not version:
                    asks.append((account, ASK_GONE, path))
                    continue
                if not is_supported(version, floor):
                    asks.append((account, ASK_BELOW, version))
                    continue
                updates[account] = {"version": version, "stamp": stamp}
                served = True
            elif record.get("is_link_made") and self._os_name != "windows":
                try:
                    home = self._machine.lookup_account(account).home
                except KeyError:
                    continue
                link = self._link_path(home)
                try:
                    target = os.readlink(link)
                except OSError:
                    target = ""
                if target != self.launcher_path:
                    asks.append((account, ASK_LINK, link))
        if updates:
            with self._lock:
                held = self._read_record()
                for account, changed in updates.items():
                    if account in held:
                        held[account] = {**held[account], **changed}
                self._write_record(held)
        if is_named:
            for ask in asks:
                self._ask(ask)
        return served

    def _version_of(self, account: str, record: dict) -> str:
        """A recorded copy's version, read again as the account."""
        path = str(record.get("path", "") or "")
        if self._os_name != "windows":
            return self._version_posix(
                account, path, str(record.get("search_path", "") or "")
            )
        password = self._passwords().get(account) or str(
            record.get("password", "") or ""
        )
        try:
            answer = self._windows_run(
                account,
                password,
                AGENT_PROGRAM_WINDOWS_FIND_PARTS,
                {"version_of": path},
            )
        except (ModuleApplyError, OSError, subprocess.SubprocessError):
            return ""
        return first_version(str(answer.get("version", "") or ""))

    def _ask(self, ask: tuple) -> None:
        """Ask for a task of the module's own, once per reason until the next ``find``."""
        with self._lock:
            if ask in self._asked:
                return
            self._asked.add(ask)
        account, reason, what = ask
        self._log(
            f"{self.name}: the copy of {account} changed ({reason} {what}), a task follows"
        )
        self.ask_configure()

    # --- the files ---

    def _write_launcher(self) -> bool:
        """Write the launcher beside the module's copy while the copy is there.

        Returns:
            Whether the launcher changed.

        Raises:
            OSError: When it cannot be written or opened to every account.
            subprocess.SubprocessError: When SELinux's label cannot be set.
        """
        if not self.has_module_copy():
            return False
        folder = self.launcher_dir
        os.makedirs(folder, exist_ok=True)
        text = launcher_text(
            self.program_path, self._hooks.launcher_variables, self._os_name
        )
        if self._os_name == "windows":
            is_changed = _write_bytes_if_changed(
                self.launcher_path, text.encode("utf-8")
            )
        else:
            os.chmod(folder, 0o755)
            is_changed = write_if_changed(self.launcher_path, text, 0o755)
        self._platform.label_programs(self.package_dir)
        self._platform.label_programs(folder)
        self._platform.open_to_accounts(self.module_dir)
        return is_changed

    def _read_record(self) -> dict:
        """Each account's record, by account. Call under the lock.

        Returns:
            The records; empty when the file is not there or cannot be read.
        """
        try:
            with open(self.record_path, "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        accounts = held.get("accounts") if isinstance(held, dict) else None
        if not isinstance(accounts, dict):
            return {}
        return {
            str(name): dict(record)
            for name, record in accounts.items()
            if isinstance(record, dict)
        }

    def _write_record(self, records: dict) -> None:
        """Keep each account's record, root-only, whole or not at all. Call under the lock.

        Raises:
            OSError: When the file cannot be written.
        """
        os.makedirs(self.module_dir, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.module_dir, prefix=".record_")
        try:
            if self._os_name == "windows":
                leave_to_system(self._run, temporary)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"accounts": records}, stream, sort_keys=True)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.record_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def _remove_module_dir(self) -> None:
        """Delete the module's directory, trying again while a file of it stays."""
        directory = self.module_dir
        for _turn in range(REMOVE_TRIES):
            remove_tree(directory)
            if not os.path.exists(directory):
                return
            time.sleep(REMOVE_RETRY_S)

    # --- what the state names ---

    def _enabled(self) -> list:
        """The enabled accounts of the latest state, in their order; none when it does not parse."""
        try:
            return [held.account for held in self._hooks.parse(self._config).accounts]
        except ModuleApplyError:
            return []

    def _passwords(self) -> dict:
        """Each enabled account's password the latest state names."""
        accounts = self._config.get("accounts")
        return {
            str(entry.get("account", "") or ""): str(entry.get("password", "") or "")
            for entry in (accounts if isinstance(accounts, list) else [])
            if isinstance(entry, dict)
        }

    def _floor(self) -> str:
        """The lowest version of a person's copy the module uses, the recipe's ``user_copy_min_version``."""
        return str(params_of(self._recipe).get("user_copy_min_version", "") or "")

    def _module_version(self) -> str:
        """The version of the module's own copy, empty while it has none."""
        path = self._join(self.package_dir, "package.json")
        stamp = file_stamp(path)
        if stamp is None:
            return ""
        held_stamp, held_version = self._version_read
        if held_stamp == stamp:
            return held_version
        try:
            with open(path, "r", encoding="utf-8") as stream:
                version = first_version(str(json.load(stream).get("version", "") or ""))
        except (OSError, ValueError, AttributeError):
            version = ""
        self._version_read = (stamp, version)
        return version

    def _entry_of(self, account: str) -> AccountEntry:
        """One account as the machine has it.

        Raises:
            ModuleApplyError: ``account_unknown {account}`` for one it lacks,
                ``account_no_profile {account}`` for one with no profile yet.
        """
        try:
            return self._machine.lookup_account(account)
        except KeyError:
            code = (
                "account_no_profile"
                if self._os_name == "windows" and self._platform.has_account(account)
                else "account_unknown"
            )
            raise ModuleApplyError(code, {"account": account}) from None

    def _windows_run(
        self, account: str, password: str, parts: tuple, request: dict
    ) -> dict:
        """Run one of the package's scripts as a Windows account, its request on standard input.

        Returns:
            The last JSON object the script printed.

        Raises:
            ModuleApplyError: ``credential_invalid {account}``, or
                ``apply_failed {detail}`` when the script printed no answer.
            OSError: When the task cannot run.
        """
        result = self._platform.run_as_account(
            account,
            [
                AGENT_PROGRAM_WINDOWS_POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_script(parts),
            ],
            stdin=json.dumps(request),
            timeout_s=AGENT_PROGRAM_WINDOWS_RUN_TIMEOUT_S,
            password=password,
        )
        for line in reversed(result.stdout.splitlines()):
            text = line.strip()
            if not text.startswith("{"):
                continue
            try:
                answer = json.loads(text)
            except ValueError:
                continue
            if isinstance(answer, dict):
                return answer
        raise ModuleApplyError(
            "apply_failed",
            {"detail": f"{account}: {result.stdout.strip()[-DETAIL_CHARS:]}"},
        )


def _needs_module_copy(accounts: list, records: dict) -> bool:
    """Whether the module's own copy is needed: no account enabled, or one with no own copy in the records. Pure."""
    if not accounts:
        return True
    return any(
        (records.get(account) or {}).get("copy") != AGENT_PROGRAM_COPY_USER
        for account in accounts
    )


def _found_line(module: str, account: str, record: dict) -> str:
    """The log line of what ``find`` found for one account. Pure."""
    if record.get("copy") == AGENT_PROGRAM_COPY_USER:
        return f"{module}: {account} runs its own copy {record['path']} {record['version']}"
    if record.get("code") == AGENT_PROGRAM_CODE_OLD_COPY:
        params = record.get("params") or {}
        return (
            f"{module}: {account} has its own copy {params.get('version')} below "
            f"{params.get('min')}, and runs the module's"
        )
    return f"{module}: {account} has no copy of its own, and runs the module's"


def _write_bytes_if_changed(path: str, data: bytes) -> bool:
    """Write a file whole unless it already holds these bytes.

    Returns:
        Whether it changed.

    Raises:
        OSError: When the file cannot be written.
    """
    try:
        with open(path, "rb") as stream:
            if stream.read() == data:
                return False
    except OSError:
        pass
    temporary = path + ".new"
    with open(temporary, "wb") as stream:
        stream.write(data)
    os.replace(temporary, path)
    return True
