"""The runner every command line program shares.

A command line program runs nothing of its own. Its copy is unpacked under
the module's directory and started by the module's launcher, and each
enabled account's ``PATH`` names the launcher's folder first. A task
installs the copy as any ``hub`` module's does, then ``configure`` writes
the launcher and lets go of every account no longer enabled, then one
``account {account}`` per enabled account puts the launcher's folder first
on the account's ``PATH`` at its first enabling: through ``env.sh`` and a
marked line in each startup file on Linux and macOS, and an entry at the
front of the user ``PATH`` on Windows. The module's :class:`ProgramHooks`
names what differs: the program's name, where the program sits in the
module's copy, and what the launcher sets.

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
    AGENT_PROGRAM_JOURNAL_SCAN_LINES,
    AGENT_PROGRAM_LAUNCHER_DIR_NAME,
    AGENT_PROGRAM_PACKAGE_DIR_NAME,
    AGENT_PROGRAM_RECORD_NAME,
    AGENT_PROGRAM_VERIFY_HOME_DIR_NAME,
    AGENT_PROGRAM_WINDOWS_PATH_PARTS,
    AGENT_PROGRAM_WINDOWS_POWERSHELL,
    AGENT_PROGRAM_WINDOWS_RUN_TIMEOUT_S,
    AGENT_SERVICE_NAME,
    AGENT_STEP_ACCOUNT,
    AGENT_STEP_CONFIGURE,
    AGENT_TASK_LINE_PATTERN,
)
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared import subprocess_run
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
    write_if_changed,
)
from neutrino_agent.modules.shared.base import ModuleRunner, ModuleStep
from neutrino_agent.modules.shared.instances import machine_for
from neutrino_agent.modules.shared.package import joiner
from neutrino_agent.modules.shared.program_path import (
    ProgramPathApplier,
    file_stamp,
)
from neutrino_agent.modules.shared.unpacked_tree import remove_tree
from neutrino_agent.modules.shared.windows_acl import leave_to_system

# An account name that survives a command line, a path and a task name.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")
# The first dotted number of a version.
VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)+")
# How many times, and how often, an uninstall deletes the module's directory.
# Windows refuses to delete a program file for a moment after its process ended.
REMOVE_TRIES = 30
REMOVE_RETRY_S = 1.0
# What a Windows PATH entry step prints.
ENTRY_ADDED = "added"
ENTRY_PRESENT = "present"
ENTRY_MOVED = "moved"
# The verbs of the Windows PATH entry script: the entry moved or put at
# the front, and taken out.
ENTRY_VERB_FIRST = "first"
ENTRY_VERB_REMOVE = "remove"
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
    """The first dotted number in a version's words. Pure.

    Args:
        text: The words, such as a package's ``version``.

    Returns:
        The number, such as ``2.1.311``; empty when it prints none.
    """
    found = VERSION_PATTERN.search(str(text or ""))
    return found.group(0) if found else ""


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
        launcher_variables: ``(name, value)`` pairs the launcher sets.
        home_variable: The variable naming the folder the program writes its
            own files in, which its ``verify`` points into the module's
            directory; empty for a program that needs none.
        config_class: The module's configuration, with ``from_dict``.
    """

    name = ""
    title = ""
    runner = ""
    program = ""
    launcher_variables: tuple = ()
    home_variable = ""
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
    """Makes a command line program the first copy on each enabled account's ``PATH``."""

    is_service = False

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
        self._path = ProgramPathApplier(
            platform=platform, lookup_account=self._machine.lookup_account, log=log
        )
        self._recipe: dict = {}
        self._config: dict = {}
        # One read or write of the record at a time.
        self._lock = threading.Lock()
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
        """The record of each enabled account."""
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

    def verify_environment(self) -> dict:
        """The variables the recipe's ``verify`` runs with: the program's home folder in the module's directory.

        The folder is made root-only while the module's copy is there and
        the folder is missing. A folder that is not there is still named,
        and the program then writes no file of its own.

        Returns:
            ``{<home variable>: <module>/verify_home}``; empty for a program
            that names no home variable.
        """
        name = self._hooks.home_variable
        if not name:
            return {}
        folder = self._join(self.module_dir, AGENT_PROGRAM_VERIFY_HOME_DIR_NAME)
        if self.has_module_copy():
            with contextlib.suppress(OSError):
                os.makedirs(folder, mode=0o700, exist_ok=True)
        return {name: folder}

    def has_module_copy(self) -> bool:
        """Whether the module's own copy is in the module's directory.

        Returns:
            True while the program's file is there.
        """
        return os.path.isfile(self.program_path)

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
        """Take every account the record names off the module: its ``PATH`` given back."""
        for line in self.remove_ways_in():
            self._log(line)

    def uninstall(self, recipe: dict) -> None:
        """Give every account's ``PATH`` back, then remove the module's directory: its copy, its launcher and its record.

        Args:
            recipe: The module's recipe.
        """
        for line in self.remove_ways_in():
            self._log(line)
        self._remove_module_dir()

    def remove_ways_in(self) -> list:
        """Give back the ``PATH`` of every account the record names.

        An account whose ``PATH`` cannot be given back is a line, and the
        others go on.

        Returns:
            What was given back or left, one line each.
        """
        with self._lock:
            records = self._read_record()
        passwords = self._passwords()
        lines = []
        for account, record in records.items():
            if not record.get("is_path_set"):
                continue
            password = passwords.get(account) or str(record.get("password", "") or "")
            try:
                self._let_go(account, record, password)
            except (ModuleApplyError, OSError, subprocess.SubprocessError) as error:
                lines.append(
                    f"{self.name}: the PATH of {account} stays: {_said(error)}"
                )
                continue
            lines.append(f"{self.name}: gave back the PATH of {account}")
            with self._lock:
                held = self._read_record()
                if account in held:
                    held[account] = {**held[account], "is_path_set": False}
                    self._write_record(held)
        return lines

    def details(self, recipe: dict) -> dict:
        """Whether the module's copy is there, and its version.

        Args:
            recipe: The module's recipe, empty for a module the state does
                not name.

        Returns:
            ``{has_module_copy, version}``, ``version`` the module copy's and
            empty while it has none.
        """
        return {
            "has_module_copy": self.has_module_copy(),
            "version": self._module_version(),
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
            if record.get("is_path_set"):
                try:
                    self._let_go(account, record, str(record.get("password", "") or ""))
                except (ModuleApplyError, OSError, subprocess.SubprocessError) as error:
                    self._log(
                        f"{self.name}: the PATH of {account} stays: {_said(error)}"
                    )
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
        """The ``account {account}`` step: the module's copy put first at the account's first enabling.

        Raises:
            ModuleApplyError: ``account_unknown {account}``,
                ``account_no_profile {account}``, ``credential_invalid
                {account}``, or ``apply_failed {detail}`` when the ``PATH``
                cannot be set.
        """
        parsed = self._hooks.parse(config)
        item = next((each for each in parsed.accounts if each.account == account), None)
        if item is None:
            raise ModuleApplyError("account_unknown", {"account": account})
        with self._lock:
            is_set = bool((self._read_record().get(account) or {}).get("is_path_set"))
        try:
            self._set_way_in(item, is_put_first=not is_set)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": str(error)[:DETAIL_CHARS]}
            ) from None
        self._log(f"{self.name}: {account} runs the module's copy first")

    def _set_way_in(self, item: ProgramAccount, *, is_put_first: bool) -> None:
        """Put the launcher's folder first on an account's ``PATH`` where asked, and keep the record.

        Raises:
            ModuleApplyError: ``account_unknown {account}``,
                ``account_no_profile {account}``, ``credential_missing
                {account}`` or ``credential_invalid {account}`` on Windows,
                and ``apply_failed {detail}`` when the entry cannot be made.
            OSError: When a file cannot be written as the account.
            subprocess.SubprocessError: When a command does not finish.
        """
        account = item.account
        entry = self._entry_of(account)
        with self._lock:
            held = dict(self._read_record().get(account) or {})
        record = {"account": account}
        if self._os_name == "windows":
            if not item.password:
                raise ModuleApplyError("credential_missing", {"account": account})
            is_made = bool(held.get("is_value_made"))
            if is_put_first:
                answer = self._windows_entry(
                    account, item.password, ENTRY_VERB_FIRST, False
                )
                is_made = is_made or bool(answer.get("is_made"))
            record["is_value_made"] = is_made
            record["password"] = item.password
        else:
            for note in self._path.set_module(
                account, entry, self.name, is_put_first=is_put_first
            ):
                self._log(f"{self.name}: {account}: {note}")
        record["is_path_set"] = True
        with self._lock:
            held = self._read_record()
            held[account] = record
            self._write_record(held)

    # --- the ways in ---

    def _let_go(self, account: str, record: dict, password: str) -> None:
        """Give an account's ``PATH`` back: on Windows its entry taken out, elsewhere the module's folder out of ``env.sh``, and the line with the last program.

        Raises:
            ModuleApplyError: ``credential_missing {account}``,
                ``credential_invalid {account}`` or ``apply_failed
                {detail}`` on Windows.
            OSError: When a file cannot be written or the command cannot run.
            subprocess.SubprocessError: When it does not finish.
        """
        if self._os_name == "windows":
            if not password:
                raise ModuleApplyError("credential_missing", {"account": account})
            self._windows_entry(
                account,
                password,
                ENTRY_VERB_REMOVE,
                bool(record.get("is_value_made")),
            )
            return
        for note in self._path.drop_module(account, self.name):
            self._log(f"{self.name}: {account}: {note}")

    def _windows_entry(
        self, account: str, password: str, verb: str, is_made: bool
    ) -> dict:
        """Change the launcher folder's entry in a Windows account's user ``PATH``.

        Returns:
            The script's answer, ``{result, is_made}``.

        Raises:
            ModuleApplyError: ``credential_invalid {account}``, or
                ``apply_failed {detail}`` when the entry cannot be changed.
            OSError: When the run as the account cannot start.
        """
        answer = self._windows_run(
            account,
            password,
            AGENT_PROGRAM_WINDOWS_PATH_PARTS,
            {"verb": verb, "folder": self.launcher_dir, "is_made": is_made},
        )
        result = str(answer.get("result", "") or "")
        if verb != ENTRY_VERB_REMOVE and result not in (
            ENTRY_ADDED,
            ENTRY_PRESENT,
            ENTRY_MOVED,
        ):
            raise ModuleApplyError(
                "apply_failed", {"detail": f"the user PATH of {account}: {result}"}
            )
        return answer

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


def _said(error: BaseException) -> str:
    """What a failure says, its code for a refusal. Pure."""
    if isinstance(error, ModuleApplyError):
        return error.code
    return str(error)[:DETAIL_CHARS]


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
