"""The runner every program run as a person's account shares.

One instance runs per account the configuration names, as one account
service through :mod:`account_service`, with the agent's forwarder in
front of it where the module names an admission rule. The runner keeps a
root-only record per instance, so a forwarder starts again after the agent
restarts, answers ``details`` and ``journal`` in the one shape, and asks the
module's :class:`InstanceHooks` for what differs: how the software is
installed and found, what each instance's service runs, what its first
start needs, and what its forwarder admits.

Not pure: drives the account service layer and the forwarders.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import json
import ntpath
import os
import subprocess
import threading
import time

from neutrino_agent.constants import AGENT_DESIRED_STATE_NAME
from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_TEMPLATE_ACCOUNT,
)
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.shared.http_forward import InstanceForwarder
from neutrino_agent.modules.shared.log_tail import file_tail
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.subprocess_run import command_detail
from neutrino_agent.modules.shared.unpacked_tree import remove_tree

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# How long one reading of the instances is believed.
STATUS_TTL_S = 30.0
# The account the template unit is rendered for, systemd's own name for it.
TEMPLATE_ACCOUNT = ACCOUNT_SERVICE_TEMPLATE_ACCOUNT
# What an account the machine does not have reads as, where a service is
# retired without one.
NOBODY = AccountEntry(0, 0, "", "")


def kept_config(path: str, name: str) -> dict:
    """One module's configuration in a kept desired state.

    Args:
        path: The kept state's file.
        name: The module's name.

    Returns:
        The module's ``config`` as the state carries it; empty when the
        file or the entry is not there.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, ValueError):
        return {}
    modules = document.get("modules") if isinstance(document, dict) else None
    entry = modules.get(name) if isinstance(modules, dict) else None
    config = entry.get("config") if isinstance(entry, dict) else None
    return dict(config) if isinstance(config, dict) else {}


def machine_for(platform, name: str) -> ServiceMachine:
    """This machine as the account service layer reaches it, for one module.

    Args:
        platform: The machine's platform.
        name: The module's name, its directory under both roots.

    Returns:
        The machine, with the account lookup the platform answers, and on
        Windows its PowerShell host and its process table.
    """
    join = ntpath.join if platform.os_name == "windows" else os.path.join
    return ServiceMachine(
        os_name=platform.os_name,
        module_dir=join(platform.agent_var_dir(), name),
        record_dir=join(platform.agent_data_dir(), name),
        lookup_account=functools.partial(_lookup_account, platform),
        powershell=platform.powershell_host,
        processes=platform.process_table,
    )


def _lookup_account(platform, account: str) -> AccountEntry:
    """One account as the platform knows it.

    Raises:
        KeyError: When the machine does not have the account.
    """
    if platform.os_name == "windows" or pwd is None:
        return AccountEntry(0, 0, platform.account_home(account), "")
    entry = pwd.getpwnam(account)
    return AccountEntry(entry.pw_uid, entry.pw_gid, entry.pw_dir, entry.pw_shell)


class InstanceHooks:
    """What differs per module among the programs run as an account.

    A module subclasses this in its ``hooks.py`` and fills in what the
    shared runner cannot know; every method not overridden keeps the
    answer that fits a module with nothing of the kind.

    Attributes:
        name: The module's name on the wire and in every service's name.
        title: What the unit's description calls the program.
        runner: The name a recipe's ``runner`` chooses the module by.
        instance_class: The module's instance dataclass, with ``from_dict``.
        record_fields: The fields one instance's record holds.
        forwarder_fields: The record fields a forwarder serves; a change
            in one replaces the forwarder. None is every record field.
        secret_field: The record field holding the token secret.
        is_forwarded: Whether the agent's forwarder stands in front of
            each instance; False for a page that admits the browser itself.
        installing: The accounts whose install the module runs or waits on.
    """

    name = ""
    title = ""
    runner = ""
    instance_class = None
    record_fields = ("account", "port")
    forwarder_fields = None
    secret_field = "secret"
    is_forwarded = True

    def __init__(self, *, platform, log=print):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._log = log
        self._machine: "ServiceMachine | None" = None
        self._reapply = None
        self.installing: frozenset = frozenset()
        if self.forwarder_fields is None:
            self.forwarder_fields = tuple(self.record_fields)

    @property
    def machine(self) -> ServiceMachine:
        """The machine the runner bound these hooks to.

        Raises:
            RuntimeError: Before the runner bound them.
        """
        if self._machine is None:
            raise RuntimeError(f"{self.name}: hooks not bound to a machine")
        return self._machine

    def bind(self, machine: ServiceMachine, reapply) -> None:
        """Take the machine and the way back to the runner.

        Args:
            machine: The machine, with the module's directories.
            reapply: Called with ``(account, **record_changes)`` to change
                one instance's record and apply the configuration again.
        """
        self._machine = machine
        self._reapply = reapply

    def parse(self, config: dict):
        """The configuration parsed and checked.

        Args:
            config: The module's desired configuration.

        Returns:
            The parsed configuration, with ``instances``.

        Raises:
            ModuleApplyError: Naming the first problem found.
            NotImplementedError: For a module that defines no configuration.
        """
        raise NotImplementedError(f"{self.name}: parse")

    def verify(self) -> bool:
        """Whether the software is on the machine.

        Returns:
            True when the module's own check finds it.

        Raises:
            NotImplementedError: For a module that defines no check.
        """
        raise NotImplementedError(f"{self.name}: verify")

    def take_recipe(self, recipe: dict) -> None:
        """Take the recipe the state names for the module.

        Args:
            recipe: ``{runner, method, params}``.
        """

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's ``source_sets`` section.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """

    def after_install(self) -> None:
        """Tidy the module's directory once an archive landed.

        Raises:
            OSError: When a file cannot be removed.
        """

    def prepare_module(self) -> list:
        """What the machine needs before any instance runs, once per apply.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: When the machine refuses.
            OSError: When a file cannot be written.
        """
        return []

    def prepare(self, parsed, instance, entry: AccountEntry) -> list:
        """What one account needs before its service starts.

        Args:
            parsed: The parsed configuration.
            instance: The instance.
            entry: Its account.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: When a step fails, under its own code.
            OSError: When a file cannot be written.

        Note:
            An install the module leaves running puts its account into
            ``installing``; the runner then applies nothing more and the
            state is applied again until the set is empty.
        """
        return []

    def record(self, parsed, instance, held: dict) -> dict:
        """One instance's record, from the configuration and the record before.

        Args:
            parsed: The parsed configuration.
            instance: The instance.
            held: The record held before this apply, empty for a new one.

        Returns:
            The record, every field in ``record_fields``.
        """
        return {
            field: getattr(instance, field, held.get(field))
            for field in self.record_fields
        }

    def service(self, instance, entry: AccountEntry, record: dict):
        """The service one instance runs as.

        Args:
            instance: The instance; its account is ``%i`` for the template
                the Linux unit is rendered from.
            entry: Its account; empty for the template, or for an account
                the machine no longer has.
            record: Its record; empty for the template.

        Returns:
            The :class:`AccountService`.

        Raises:
            NotImplementedError: For a module that runs no service.
        """
        raise NotImplementedError(f"{self.name}: service")

    def on_first_start(self, record: dict) -> str:
        """What the page needs before its forwarder listens.

        Called at every start of the forwarder, so a registration or a
        first-run file is made once and found afterwards.

        Args:
            record: The instance's record.

        Returns:
            The code why the page is not ready, empty when it is.

        Raises:
            OSError: While the page does not answer yet.
        """
        return ""

    def admit(self, request, record: dict):
        """What the forwarder does with one request.

        Args:
            request: The :class:`ForwardRequest`.
            record: The instance's record.

        Returns:
            The :class:`ForwardDecision`.

        Raises:
            NotImplementedError: For a module with no forwarder.
        """
        raise NotImplementedError(f"{self.name}: admit")

    def connect(self, record: dict):
        """A connection to the page behind the forwarder.

        Args:
            record: The instance's record.

        Returns:
            A connected socket.

        Raises:
            OSError: When the page does not answer.
            NotImplementedError: For a module with no forwarder.
        """
        raise NotImplementedError(f"{self.name}: connect")

    def details_extra(self, record: dict) -> dict:
        """What one instance's row in ``details`` carries beside the shared fields.

        Args:
            record: The instance's record.

        Returns:
            More fields, empty by default.
        """
        return {}

    def module_details(self) -> dict:
        """What ``details`` carries beside the instances.

        Returns:
            More fields, empty by default.
        """
        return {}

    def journal_log(self, record: dict) -> str:
        """The module's own log of one instance, read in place of the service's output.

        Args:
            record: The instance's record.

        Returns:
            The file's path; empty for a module whose output the service
            keeps, or while the module has written none.
        """
        return ""

    def install_log(self, account: str) -> str:
        """The log of an install that runs for one account.

        Args:
            account: The account.

        Returns:
            The file's path, empty when no install runs or none is kept.
        """
        return ""

    def forget_module(self) -> None:
        """Delete what ``prepare_module`` wrote, once no instance is left."""


class InstancesModuleRunner(ModuleRunner):
    """Installs a module's software from the hub's bytes and runs it per account."""

    def __init__(
        self,
        *,
        hooks_class,
        platform,
        log=print,
        publish=None,
        machine: "ServiceMachine | None" = None,
        forwarder_factory=None,
        clock=time.monotonic,
    ):
        """
        Args:
            hooks_class: The module's :class:`InstanceHooks` subclass,
                made with ``platform`` and ``log``.
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            machine: The machine the account service layer reaches; None
                is the platform's own.
            forwarder_factory: Called with ``name``, ``record``, ``hooks``
                and ``log``; returns a started-on-demand forwarder. None
                makes an :class:`InstanceForwarder`.
            clock: The monotonic clock the instances' reading ages on.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._hooks = hooks_class(platform=platform, log=log)
        self.runner = self._hooks.runner
        self.name = self._hooks.name
        self._machine = (
            machine if machine is not None else machine_for(platform, self.name)
        )
        self._hooks.bind(self._machine, self._reapply)
        self._records = InstanceRecordStore(
            directory=self._machine.record_dir, fields=self._hooks.record_fields
        )
        self._forwarder_factory = (
            forwarder_factory if forwarder_factory is not None else InstanceForwarder
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._forwarders: dict = {}
        self._is_resumed = False
        self._is_stopped = False
        self._applied: "dict | None" = None
        self._applied_at = 0.0
        self._refusal: "tuple | None" = None
        # One apply at a time: the state's, or an instance's apply again.
        self._apply_lock = threading.Lock()
        self._last_config: "dict | None" = None

    @property
    def hooks(self) -> InstanceHooks:
        """The module's hooks."""
        return self._hooks

    @property
    def machine(self) -> ServiceMachine:
        """The machine the account service layer reaches."""
        return self._machine

    def verify(self, recipe: dict) -> bool:
        """Whether the software is on the machine, by the module's own check.

        Args:
            recipe: The module's recipe.

        Returns:
            True when the hooks find it.
        """
        return bool(self._hooks.verify())

    @property
    def module_dir(self) -> str:
        """The module's directory under the state root, the machine's own."""
        return self._machine.module_dir

    def take_recipe(self, recipe: dict) -> None:
        """Hand the recipe the state names to the module's hooks.

        Args:
            recipe: ``{runner, method, params}``.
        """
        self._hooks.take_recipe(recipe)

    def take_source_sets(self, source_sets: dict) -> None:
        """Hand the state's ``source_sets`` section to the module's hooks.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._hooks.take_source_sets(source_sets)

    def install_artifact(self, recipe: dict, artifact: dict, path: str) -> None:
        """Put one artifact on the machine as its kind says, then tidy the module's directory.

        Args:
            recipe: The module's recipe.
            artifact: ``{name, kind, digest, directory}``.
            path: The received file.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` for an artifact
                that cannot be put in place.
            OSError: When the module's directory cannot be written or
                opened to every account.
        """
        super().install_artifact(recipe, artifact, path)
        self._hooks.after_install()
        self._forget_states()

    def uninstall(self, recipe: dict) -> None:
        """Delete the module's directory; each account's own data stays.

        Args:
            recipe: The module's recipe.
        """
        self._close_forwarders()
        remove_tree(self._machine.module_dir)

    def validate(self, config: dict) -> None:
        """Parse and check a configuration for this system.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        self._hooks.parse(config)

    def apply(self, config: dict) -> None:
        """Run one instance and its forwarder per account named, and none for an account no longer named.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused, an
                account's step fails, or the system will not run it.
            ModuleInstallPending: While an account's install still runs.
        """
        try:
            with self._apply_lock:
                self._last_config = dict(config)
                self._apply(config)
        except ModuleApplyError as error:
            with self._lock:
                self._refusal = (error.code, dict(error.params))
            raise
        with self._lock:
            self._refusal = None

    def stop(self) -> None:
        """Stop every instance and its forwarder; the software and the records stay.

        Raises:
            OSError: When the system will not stop one.
        """
        with self._lock:
            self._is_resumed = True
            self._is_stopped = True
        self._close_forwarders()
        try:
            for record in self._records.read_all():
                account_service.stop(self._service_of(record), self._machine)
        finally:
            self._forget_states()

    def remove_configuration(self) -> None:
        """Stop every instance and delete what the applies wrote.

        Raises:
            OSError: When the system will not let one go.
        """
        with self._lock:
            self._is_resumed = True
            self._is_stopped = True
            self._refusal = None
        self._close_forwarders()
        try:
            for record in self._records.read_all():
                self._retire(record)
            account_service.forget(self.name, self._machine)
            self._hooks.forget_module()
        finally:
            self._forget_states()

    def is_active(self) -> bool:
        """Whether there is an instance and every one of them runs."""
        states = self._read_states()
        return bool(states) and all(state["is_running"] for state in states)

    def is_installing(self) -> bool:
        """Whether an account's install runs or is waited on."""
        return bool(self._hooks.installing)

    def forwarder_ports(self) -> tuple:
        """The ports the instances' forwarders listen on now, in order.

        Returns:
            Each listening forwarder's port; none while no forwarder
            listens.
        """
        with self._lock:
            forwarders = list(self._forwarders.values())
        return tuple(
            sorted(
                forwarder.listen_address[1]
                for forwarder in forwarders
                if forwarder.is_listening and forwarder.listen_address[1]
            )
        )

    def journal_units(self) -> list:
        """Every instance's unit, on Linux."""
        services = [self._service_of(record) for record in self._records.read_all()]
        return account_service.units(services, self._machine)

    def journal_text(self, lines: int) -> list:
        """Every instance's output: the units' journal, or each log file's tail.

        Where no unit keeps the output, the agent's own lines that name the
        module follow the log files' lines; an account whose install runs
        is there by the install's log where the module keeps one. The code
        the last apply was refused with is the last line, on every system.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first within each instance; a log file's lines
            start with its account's name.
        """
        with self._lock:
            refusal = self._refusal
        tail = [self._refusal_line(*refusal)] if refusal is not None else []
        logs = self._log_paths()
        if not logs and self.journal_units():
            return (super().journal_text(lines) + tail)[-lines:]
        share = max(1, lines // len(logs)) if logs else 0
        own = []
        for account, path in logs:
            read = self._read_source(path, functools.partial(file_tail, path, share))
            own += [f"{account}: {line}" for line in read]
        held = self._with_agent_lines(own, lines)
        return (held + tail)[-lines:]

    def details(self, recipe: dict) -> dict:
        """What the module adds, and each instance, its port and whether it runs.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"instances": [{"account", "port", "is_running", "code",
            ...}]}`` and what the hooks add: ``is_running`` while the
            instance runs and its forwarder listens, ``code`` the reason it
            does not.
        """
        details = dict(self._hooks.module_details())
        details["instances"] = [dict(state) for state in self._read_states()]
        return details

    def _apply(self, config: dict) -> None:
        """Make the configuration true, raising what it refused."""
        parsed = self._hooks.parse(config)
        entries = {}
        for instance in parsed.instances:
            try:
                entries[instance.account] = self._machine.lookup_account(
                    instance.account
                )
            except KeyError:
                raise ModuleApplyError(
                    "account_unknown", {"account": instance.account}
                ) from None
        held = {str(record["account"]): record for record in self._records.read_all()}
        try:
            notes = self._run_instances(parsed, entries, held)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        finally:
            self._forget_states()
        with self._lock:
            self._is_resumed = True
            self._is_stopped = False
        self._sync_forwarders()
        self._log(f"{self.name}: " + "; ".join(notes or ["unchanged"]))

    def _run_instances(self, parsed, entries: dict, held: dict) -> list:
        """Prepare, write, start and record every instance; retire the rest."""
        notes = list(self._hooks.prepare_module())
        for instance in parsed.instances:
            notes += self._hooks.prepare(parsed, instance, entries[instance.account])
        pending = sorted(self._hooks.installing)
        if pending:
            raise ModuleInstallPending(", ".join(pending))
        template = self._hooks.service(
            self._hooks.instance_class.from_dict({"account": TEMPLATE_ACCOUNT}),
            NOBODY,
            {},
        )
        is_defined = account_service.define(template, self._machine)
        wanted = {instance.account for instance in parsed.instances}
        for account, record in held.items():
            if account not in wanted:
                self._retire(record)
                notes.append(f"stopped the instance of {account}")
        records = []
        for instance in parsed.instances:
            account = instance.account
            record = self._hooks.record(parsed, instance, held.get(account, {}))
            service = self._hooks.service(instance, entries[account], record)
            is_changed = account_service.write(service, self._machine)
            is_restart = is_changed or is_defined or account not in held
            account_service.start(service, self._machine, is_restart=is_restart)
            if is_restart:
                notes.append(f"started the instance of {account}")
            records.append(record)
        for record in records:
            try:
                self._records.write(record)
            except OSError as error:
                raise ModuleApplyError("apply_failed", {"detail": str(error)[:500]})
        return notes

    def _retire(self, record: dict) -> None:
        """Remove one instance's service and forget its record."""
        account_service.remove(self._service_of(record), self._machine)
        self._records.remove(str(record["account"]))

    def _service_of(self, record: dict):
        """The service one record's instance runs as, from the record alone."""
        account = str(record.get("account", "") or "")
        try:
            entry = self._machine.lookup_account(account)
        except KeyError:
            entry = NOBODY
        instance = self._hooks.instance_class.from_dict(record)
        return self._hooks.service(instance, entry, record)

    def _reapply(self, account: str, **changes) -> None:
        """Change one instance's record and apply the configuration again.

        The configuration last applied, or the kept state's after a restart,
        is applied again, so the instance runs on the changed record.

        Args:
            account: The instance's account.
            **changes: The record fields that change.
        """
        with self._apply_lock:
            record = self._records.read(account)
            if not record:
                return
            record.update(changes)
            try:
                self._records.write(record)
            except OSError as error:
                self._log(
                    f"{self.name}: could not change the record of {account}: {error}"
                )
                return
            config = self._last_config or kept_config(self._state_path(), self.name)
            if not config:
                self._log(f"{self.name}: {account} waits for a state to apply again")
                return
            try:
                self._apply(config)
            except (ModuleApplyError, ModuleInstallPending) as error:
                self._log(f"{self.name}: {account} was not applied again: {error}")
                return
        self._log(f"{self.name}: {account} applied again on a changed record")

    def _state_path(self) -> str:
        """The kept desired state beside the agent's configuration."""
        return os.path.join(self._platform.agent_data_dir(), AGENT_DESIRED_STATE_NAME)

    def _refusal_line(self, code: str, params: dict) -> str:
        """One refused apply as a journal line: ``<module>: <code> <name>=<value>``."""
        named = "".join(
            f" {name}={' '.join(str(value).split())}"
            for name, value in sorted(params.items())
        )
        return f"{self.name}: {code}{named}"

    def _log_paths(self) -> list:
        """Each account's log file, the install's while one runs; on Linux the module's own alone."""
        records = {
            str(record["account"]): record for record in self._records.read_all()
        }
        logs = []
        for account in sorted(set(records) | set(self._hooks.installing)):
            path = self._hooks.install_log(account) or self._instance_log(
                account, records.get(account)
            )
            if path:
                logs.append((account, path))
        return logs

    def _instance_log(self, account: str, record) -> str:
        """Where one instance's output is read: the module's own log, else the service's file."""
        if record is None:
            return account_service.log_path(self.name, account, self._machine, "")
        service = self._service_of(record)
        own = self._hooks.journal_log(record)
        if own or service.is_output_discarded:
            return own
        return account_service.log_path(
            self.name, account, self._machine, service.log_name
        )

    def _read_states(self) -> list:
        """Every instance as it stands; the system's reading is kept a while."""
        self._resume()
        records = self._records.read_all()
        with self._lock:
            applied = self._applied
            is_fresh = (
                applied is not None and self._clock() - self._applied_at < STATUS_TTL_S
            )
        if not is_fresh:
            services = [self._service_of(record) for record in records]
            applied = account_service.states(services, self._machine)
            with self._lock:
                self._applied, self._applied_at = applied, self._clock()
        with self._lock:
            forwarders = dict(self._forwarders)
        states = []
        for record in records:
            account = str(record["account"])
            seen = applied.get(account) or {}
            forwarder = forwarders.get(account)
            code = str(seen.get("code", "") or "")
            if not code and forwarder is not None:
                code = forwarder.failure[0]
            is_running = bool(seen.get("is_running"))
            if self._hooks.is_forwarded:
                is_running = (
                    is_running and forwarder is not None and forwarder.is_listening
                )
            state = {
                "account": account,
                "port": int(record.get("port", 0) or 0),
                "is_running": is_running,
                "code": code,
            }
            state.update(self._hooks.details_extra(record))
            states.append(state)
        return states

    def _resume(self) -> None:
        """Start the forwarders the records name, once, after the agent starts."""
        with self._lock:
            if self._is_resumed:
                return
            self._is_resumed = True
        self._sync_forwarders()

    def _sync_forwarders(self) -> None:
        """Make one running forwarder per record, as the record stands."""
        if not self._hooks.is_forwarded:
            return
        records = {
            str(record["account"]): record for record in self._records.read_all()
        }
        with self._lock:
            if self._is_stopped:
                records = {}
            stale = [
                account
                for account, forwarder in self._forwarders.items()
                if account not in records or not forwarder.matches(records[account])
            ]
            closing = [self._forwarders.pop(account) for account in stale]
            missing = [
                account for account in records if account not in self._forwarders
            ]
        for forwarder in closing:
            forwarder.close()
        for account in missing:
            forwarder = self._forwarder_factory(
                name=self.name,
                record=records[account],
                hooks=self._hooks,
                log=self._log,
            )
            with self._lock:
                self._forwarders[account] = forwarder
            forwarder.start()

    def _close_forwarders(self) -> None:
        with self._lock:
            forwarders, self._forwarders = self._forwarders, {}
        for forwarder in forwarders.values():
            forwarder.close()

    def _forget_states(self) -> None:
        with self._lock:
            self._applied = None
