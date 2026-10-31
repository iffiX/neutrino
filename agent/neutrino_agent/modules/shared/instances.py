"""The runner every program run as a person's account shares.

One instance runs per account the configuration names, as one account
service through :mod:`account_service`, with the agent's forwarder in
front of it where the module names an admission rule. The runner takes each
instance's port itself, the first free port on loopback from the module's
``base_port`` up, at the instance's first start, and keeps it in the
instance's root-only record, a retired one while the account is not
enabled; a kept port another program holds at a start is replaced by the
next free one. The record lets a forwarder start again after the agent
restarts. A task applies the module in steps: ``configure`` for what every
instance shares, then one ``account {account}`` per enabled account, after
its ``npm {account}`` where the module installs per account. A record the
hooks change is applied by a configure task the runner asks for. The runner
answers ``details`` and ``journal`` in the one shape, and asks the module's
:class:`InstanceHooks` for what differs: how the software is installed and
found, what each instance's service runs, what its first start needs, and
what its forwarder admits.

Not pure: drives the account service layer and the forwarders.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import dataclasses
import functools
import ntpath
import os
import subprocess
import threading
import time

from neutrino_agent.constants import (
    AGENT_STEP_ACCOUNT,
    AGENT_STEP_CONFIGURE,
    AGENT_WANT_RUNNING,
)
from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_TEMPLATE_ACCOUNT,
)
from neutrino_agent.modules.shared.base import ModuleRunner, ModuleStep
from neutrino_agent.modules.shared.http_forward import InstanceForwarder
from neutrino_agent.modules.shared.log_tail import file_tail
from neutrino_agent.modules.shared.loopback_port import is_port_free, pick_port
from neutrino_agent.modules.shared.package import joiner, unpacked_paths
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.subprocess_run import (
    bounded_detail,
    command_detail,
)
from neutrino_agent.modules.shared.unpacked_tree import remove_tree
from neutrino_agent.modules.shared.windows_acl import leave_to_system

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

# How long one reading of the instances is believed.
STATUS_TTL_S = 30.0
# How long a reading that finds an instance not running is believed within
# STATUS_TTL_S of an apply or a stop. A service just started can read
# stopped for a moment.
STATUS_SETTLING_TTL_S = 2.0
# The account the template unit is rendered for, systemd's own name for it.
TEMPLATE_ACCOUNT = ACCOUNT_SERVICE_TEMPLATE_ACCOUNT
# What an account the machine does not have reads as, where a service is
# retired without one.
NOBODY = AccountEntry(0, 0, "", "")
# How much of a failed command's words an ``apply_failed`` keeps.
DETAIL_CHARS = 500
# How many times, and how often, an uninstall deletes the module's directory.
# Windows refuses to delete a program file for a moment after its process ended.
REMOVE_TRIES = 30
REMOVE_RETRY_S = 1.0


def machine_for(platform, name: str) -> ServiceMachine:
    """This machine as the account service layer reaches it, for one module.

    Args:
        platform: The machine's platform.
        name: The module's name, its directory under the state root, which
            holds its software and its instances' records.

    Returns:
        The machine, with the account lookup the platform answers, and on
        Windows its PowerShell host, its process table and its batch logon
        right.
    """
    join = ntpath.join if platform.os_name == "windows" else os.path.join
    module_dir = join(platform.agent_var_dir(), name)
    return ServiceMachine(
        os_name=platform.os_name,
        module_dir=module_dir,
        record_dir=module_dir,
        lookup_account=functools.partial(_lookup_account, platform),
        powershell=platform.powershell_host,
        processes=platform.process_table,
        batch_logon=platform.batch_logon,
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
        base_port: The port the runner takes each instance's port from,
            the first free one from it up on loopback.
        page_cookie: The fixed name of the page's own login cookie, which
            the forwarder renames to the record's ``cookie_name`` toward the
            browser and back toward the page; empty for a page with none.
        prepare_step: The step each account's :meth:`prepare` runs as, ahead
            of its ``account`` step; empty runs it inside ``account``.
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
    base_port = 0
    page_cookie = ""
    prepare_step = ""

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
                one instance's record and ask for a configure task that runs
                the instance on it.
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
            ``installing``; the step then runs again every recheck interval
            until the account leaves the set.
        """
        return []

    def record(self, parsed, instance, held: dict) -> dict:
        """One instance's record, from the configuration and the record before.

        Args:
            parsed: The parsed configuration.
            instance: The instance.
            held: The record held before this apply, with the ``port`` the
                runner took for the instance.

        Returns:
            The record, every field in ``record_fields``: the port the
            runner took, and every other field the instance's or, where it
            has none, the record's before.
        """
        return {
            field: (
                held.get(field)
                if field == "port"
                else getattr(instance, field, held.get(field))
            )
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

    def stop_installs(self) -> None:
        """Stop every install still running, before the module's files go.

        Raises:
            OSError: When the system will not stop one.
        """


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
        is_port_free=is_port_free,
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
            is_port_free: Answers whether a loopback port can be bound now.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._hooks = hooks_class(platform=platform, log=log)
        self._is_port_free = is_port_free
        self.runner = self._hooks.runner
        self.name = self._hooks.name
        self._machine = (
            machine if machine is not None else machine_for(platform, self.name)
        )
        self._hooks.bind(self._machine, self._reapply)
        self._records = InstanceRecordStore(
            directory=self._machine.record_dir,
            fields=self._hooks.record_fields,
            seal=(
                functools.partial(leave_to_system, self._machine.run)
                if self._machine.os_name == "windows"
                else None
            ),
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
        # When an apply or a stop last forgot the reading.
        self._changed_at = float("-inf")
        self._refusal: "tuple | None" = None
        # One change of the records at a time: a step's, or the hooks'.
        self._apply_lock = threading.Lock()
        # The accounts whose running instance a changed template restarts.
        self._owed_restarts: set = set()
        self._recipe: dict = {}

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
        """Keep the recipe the state names, and hand it to the module's hooks.

        Args:
            recipe: ``{runner, method, params}``.
        """
        self._recipe = dict(recipe)
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
        """Stop every install still running and delete the module's directory; each account's own data stays.

        Args:
            recipe: The module's recipe.

        Raises:
            OSError: When the system will not stop an install.
        """
        self._close_forwarders()
        self._hooks.stop_installs()
        self._remove_module_dir()

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
        with self._apply_lock:
            self._refusing(self._apply, config)
        with self._lock:
            self._refusal = None

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """The module's ``configure``, and under ``running`` the steps of each enabled account.

        Args:
            config: The configuration the task's entry carries.
            want: ``running`` or ``stopped``.
            steps: ``configure``, then ``start`` or ``stop``, as the core
                plans them.

        Returns:
            ``configure`` for what every instance shares, then under
            ``running`` per enabled account its ``npm {account}`` where the
            hooks name that step and its ``account {account}``, then the
            core's ``start`` or ``stop``.
        """
        try:
            accounts = [
                instance.account for instance in self._hooks.parse(config).instances
            ]
        except ModuleApplyError:
            accounts = []
        planned = []
        for step in steps:
            if step.name != AGENT_STEP_CONFIGURE:
                planned.append(step)
                continue
            planned.append(
                dataclasses.replace(
                    step, run=functools.partial(self._run_configure, dict(config))
                )
            )
            if want != AGENT_WANT_RUNNING:
                continue
            for account in accounts:
                if self._hooks.prepare_step:
                    planned.append(
                        ModuleStep(
                            name=self._hooks.prepare_step,
                            params={"account": account},
                            run=functools.partial(
                                self._run_prepare, dict(config), account
                            ),
                        )
                    )
                planned.append(
                    ModuleStep(
                        name=AGENT_STEP_ACCOUNT,
                        params={"account": account},
                        run=functools.partial(self._run_account, dict(config), account),
                    )
                )
        return planned

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
            for account in self._records.accounts():
                self._records.remove(account)
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

    def _remove_module_dir(self) -> None:
        """Delete the module's directory, trying again while a file of it stays."""
        directory = self._machine.module_dir
        for _turn in range(REMOVE_TRIES):
            remove_tree(directory)
            if not os.path.exists(directory):
                return
            time.sleep(REMOVE_RETRY_S)

    def _run_configure(self, config: dict, context) -> None:
        """The ``configure`` step: what every instance shares, and no instance for an account no longer named."""
        with self._apply_lock:
            self._refusing(self._configure, config)
        with self._lock:
            self._refusal = None

    def _run_prepare(self, config: dict, account: str, context) -> None:
        """The step the hooks name for one account's :meth:`InstanceHooks.prepare`, such as ``npm {account}``."""
        parsed, instance, entry = self._instance(config, account)
        self._refusing(self._prepare_one, parsed, instance, entry)

    def _run_account(self, config: dict, account: str, context) -> None:
        """The ``account {account}`` step: one instance prepared, written, started and recorded."""
        with self._apply_lock:
            self._refusing(self._account, config, account)

    def _refusing(self, run, *args):
        """Run one part of an apply, keeping its refusal for the journal.

        Returns:
            What the part returns.

        Raises:
            ModuleApplyError: The part's own refusal, and ``apply_failed
                {detail}`` for a failure of the system.
            ModuleInstallPending: While an account's install still runs.
        """
        try:
            try:
                return run(*args)
            except (OSError, subprocess.SubprocessError) as error:
                raise ModuleApplyError(
                    "apply_failed",
                    {"detail": bounded_detail(command_detail(error), DETAIL_CHARS)},
                ) from None
        except ModuleApplyError as error:
            with self._lock:
                self._refusal = (error.code, dict(error.params))
            raise

    def _apply(self, config: dict) -> None:
        """Make the whole configuration true: every account prepared first, then every instance run."""
        parsed, entries = self._parsed(config)
        held = self._held()
        try:
            notes = self._prepare_module()
            for instance in parsed.instances:
                notes += self._hooks.prepare(
                    parsed, instance, entries[instance.account]
                )
            pending = sorted(self._hooks.installing)
            if pending:
                raise ModuleInstallPending(", ".join(pending))
            notes += self._define_and_retire(parsed, held)
            for instance in parsed.instances:
                notes += self._run_instance(parsed, instance, entries[instance.account])
        finally:
            self._forget_states()
        self._resume_instances()
        self._log(f"{self.name}: " + "; ".join(notes or ["unchanged"]))

    def _configure(self, config: dict) -> None:
        """Label the unpacks, prepare the module, write the template and retire every account no longer named."""
        parsed, _entries = self._parsed(config)
        held = self._held()
        try:
            notes = self._prepare_module()
            notes += self._define_and_retire(parsed, held)
        finally:
            self._forget_states()
        self._sync_forwarders()
        self._log(f"{self.name}: " + "; ".join(notes or ["unchanged"]))

    def _account(self, config: dict, account: str) -> None:
        """Prepare one account unless its own step did, then run its instance and its forwarder."""
        parsed, instance, entry = self._instance(config, account)
        try:
            notes = []
            if not self._hooks.prepare_step:
                notes += self._prepare_one(parsed, instance, entry)
            notes += self._run_instance(parsed, instance, entry)
        finally:
            self._forget_states()
        self._resume_instances()
        self._log(f"{self.name}: " + "; ".join(notes or [f"{account} unchanged"]))

    def _parsed(self, config: dict) -> tuple:
        """The configuration parsed, and each account it names as the machine has it.

        Raises:
            ModuleApplyError: The hooks' refusal, and ``account_unknown
                {account}`` for an account the machine lacks.
        """
        parsed = self._hooks.parse(config)
        entries = {
            instance.account: self._entry_of(instance.account)
            for instance in parsed.instances
        }
        return parsed, entries

    def _instance(self, config: dict, account: str) -> tuple:
        """The configuration parsed, one account's instance in it, and the account.

        Raises:
            ModuleApplyError: The hooks' refusal, and ``account_unknown
                {account}`` for an account the machine lacks or the
                configuration does not name.
        """
        parsed = self._hooks.parse(config)
        for instance in parsed.instances:
            if instance.account == account:
                return parsed, instance, self._entry_of(account)
        raise ModuleApplyError("account_unknown", {"account": account})

    def _entry_of(self, account: str) -> AccountEntry:
        """One account as the machine has it.

        Raises:
            ModuleApplyError: ``account_unknown {account}`` for one it lacks.
        """
        try:
            return self._machine.lookup_account(account)
        except KeyError:
            raise ModuleApplyError("account_unknown", {"account": account}) from None

    def _held(self) -> dict:
        """Every live record, by account."""
        return {str(record["account"]): record for record in self._records.read_all()}

    def _prepare_module(self) -> list:
        """Label each unpack, then what the hooks need before any instance runs."""
        for path in unpacked_paths(
            self._recipe,
            module_dir=self.module_dir,
            join=joiner(self._platform.os_name),
        ):
            self._platform.label_programs(path)
        return list(self._hooks.prepare_module())

    def _prepare_one(self, parsed, instance, entry: AccountEntry) -> list:
        """One account's preparation by the hooks.

        Raises:
            ModuleInstallPending: While the account's install still runs.
        """
        notes = list(self._hooks.prepare(parsed, instance, entry))
        if instance.account in self._hooks.installing:
            raise ModuleInstallPending(instance.account)
        return notes

    def _define_and_retire(self, parsed, held: dict) -> list:
        """Write the template, and retire the instance of every account no longer named.

        A changed template owes every named account a restart at its own
        ``account`` step.
        """
        template = self._hooks.service(
            self._hooks.instance_class.from_dict({"account": TEMPLATE_ACCOUNT}),
            NOBODY,
            {},
        )
        wanted = {instance.account for instance in parsed.instances}
        if account_service.define(template, self._machine):
            self._owed_restarts |= wanted
        notes = []
        for account, record in held.items():
            if account not in wanted:
                self._retire(record)
                self._owed_restarts.discard(account)
                notes.append(f"stopped the instance of {account}")
        return notes

    def _run_instance(self, parsed, instance, entry: AccountEntry) -> list:
        """Write and start one instance on its port, then keep its record.

        A new instance, a changed one and one a changed template owes a
        restart are started again; an unchanged one is kept up.
        """
        account = instance.account
        held = self._records.read(account)
        port = self._take_port(account, self._records.kept_ports(), is_held=bool(held))
        record = self._hooks.record(parsed, instance, {**held, "port": port})
        record["port"] = port
        service = self._hooks.service(instance, entry, record)
        is_changed = account_service.write(service, self._machine)
        is_restart = is_changed or account in self._owed_restarts or not held
        account_service.start(service, self._machine, is_restart=is_restart)
        self._owed_restarts.discard(account)
        self._records.write(record)
        return [f"started the instance of {account}"] if is_restart else []

    def _resume_instances(self) -> None:
        """Mark the module running, and run one forwarder per record."""
        with self._lock:
            self._is_resumed = True
            self._is_stopped = False
        self._sync_forwarders()

    def _retire(self, record: dict) -> None:
        """Remove one instance's service and keep its port alone in its record."""
        account_service.remove(self._service_of(record), self._machine)
        self._records.retire(str(record["account"]))

    def _take_port(self, account: str, ports: dict, *, is_held: bool) -> int:
        """The port one instance runs on: the one kept for it, else the next free.

        A port kept for an instance whose record is live is its own, whoever
        listens there. A port kept for an account enabled again, or for a
        new one, is taken only while nothing else holds it.

        Args:
            account: The instance's account.
            ports: Account to the port every record keeps.
            is_held: Whether the instance's record is live.

        Returns:
            The port.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when no port from
                the module's base up is free.
        """
        kept = int(ports.get(account, 0) or 0)
        if kept and (is_held or self._is_port_free(kept)):
            return kept
        others = [port for name, port in ports.items() if name != account]
        try:
            port = pick_port(
                self._base_port(), taken=others, is_free=self._is_port_free
            )
        except OSError as error:
            raise ModuleApplyError("apply_failed", {"detail": str(error)})
        if kept:
            self._log(f"{self.name}: {account} moved from port {kept} to {port}")
        return port

    def _base_port(self) -> int:
        """The module's base port.

        Raises:
            RuntimeError: For a module whose hooks name none.
        """
        if not self._hooks.base_port:
            raise RuntimeError(f"{self.name}: no base port")
        return int(self._hooks.base_port)

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
        """Change one instance's record and ask for a configure task, which runs the instance on it.

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
        self.ask_configure()
        self._log(f"{self.name}: the record of {account} changed")

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
            now = self._clock()
            ttl = STATUS_TTL_S
            if (
                applied is not None
                and now - self._changed_at < STATUS_TTL_S
                and not all(seen.get("is_running") for seen in applied.values())
            ):
                ttl = STATUS_SETTLING_TTL_S
            is_fresh = applied is not None and now - self._applied_at < ttl
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
            record = self._free_forwarder_port(records[account])
            forwarder = self._forwarder_factory(
                name=self.name,
                record=record,
                hooks=self._hooks,
                log=self._log,
            )
            with self._lock:
                self._forwarders[account] = forwarder
            forwarder.start()

    def _free_forwarder_port(self, record: dict) -> dict:
        """One record whose port another program holds, moved to the next free port.

        A forwarder that starts for a record finds its kept port taken only
        when something else took it while no forwarder held it; the record
        then keeps the next free one, which the report names.

        Args:
            record: The instance's record.

        Returns:
            The record as the forwarder serves it.
        """
        port = int(record.get("port", 0) or 0)
        if not port or self._is_port_free(port):
            return record
        account = str(record.get("account", "") or "")
        ports = self._records.kept_ports()
        try:
            moved = self._take_port(account, ports, is_held=False)
        except ModuleApplyError:
            return record
        changed = {**record, "port": moved}
        try:
            self._records.write(changed)
        except OSError as error:
            self._log(f"{self.name}: could not keep the port of {account}: {error}")
            return record
        return changed

    def _close_forwarders(self) -> None:
        with self._lock:
            forwarders, self._forwarders = self._forwarders, {}
        for forwarder in forwarders.values():
            forwarder.close()

    def _forget_states(self) -> None:
        with self._lock:
            self._applied = None
            self._changed_at = self._clock()
