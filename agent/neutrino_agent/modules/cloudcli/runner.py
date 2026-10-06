"""CloudCLI as a module: a web page for AI coding sessions, per account.

Node.js is the archive the hub caches, down a package stream, unpacked into
the module's own directory. Each instance is one account's CloudCLI,
installed by npm into the account's own app directory, listening on a
loopback port the agent picks, and started the way the system starts a
process as an account: a systemd unit with ``User=`` on Linux, a
LaunchDaemon with ``UserName`` on macOS, a scheduled task with the
account's login on Windows. In front of each stands a forwarder of the
agent on the instance's port, started again from the instance's record when
the agent restarts. While an account's install runs the module reads
installing, and its log is the install's output where a file keeps it. The
code the last apply was refused with ends the log until an apply takes.

Not pure: drives the platform's applier and the forwarders.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import ntpath
import os
import socket
import subprocess
import threading
import time

from neutrino_agent.constants import AGENT_DESIRED_STATE_NAME
from neutrino_agent.exceptions import (
    ModuleApplyError,
    ModuleInstallPending,
    PlatformUnsupportedError,
)
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.cloudcli.config import CloudcliConfig
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_DATABASE_NAME,
    CLOUDCLI_FRESH_DATABASE_PATTERN,
    CLOUDCLI_FRESH_STAMP_FORMAT,
    CLOUDCLI_DIR_NAME,
    CLOUDCLI_KIND,
    CLOUDCLI_NAME,
    CLOUDCLI_STATUS_TTL_S,
    CLOUDCLI_UPSTREAM_HOST,
)
from neutrino_agent.modules.cloudcli.darwin_applier import CloudcliDarwinApplier
from neutrino_agent.modules.cloudcli.forwarder import CloudcliForwarder
from neutrino_agent.modules.cloudcli.installer import remove_node, unpack_node
from neutrino_agent.modules.cloudcli.linux_applier import CloudcliLinuxApplier
from neutrino_agent.modules.cloudcli.record_store import CloudcliRecordStore
from neutrino_agent.modules.cloudcli.windows_applier import CloudcliWindowsApplier
from neutrino_agent.modules.log_tail import file_tail
from neutrino_agent.modules.subprocess_run import command_detail


def cloudcli_applier_for(platform, log=print):
    """The applier that starts CloudCLI as an account on this system.

    Args:
        platform: The machine's platform.
        log: Callable used for progress messages.

    Returns:
        The Linux, macOS or Windows applier.

    Raises:
        PlatformUnsupportedError: On a system with none.
    """
    if platform.os_name == "linux":
        return CloudcliLinuxApplier(
            module_dir=os.path.join(platform.agent_var_dir(), CLOUDCLI_DIR_NAME),
            etc_dir=os.path.join(platform.agent_data_dir(), CLOUDCLI_DIR_NAME),
            log=log,
        )
    if platform.os_name == "darwin":
        return CloudcliDarwinApplier(
            module_dir=os.path.join(platform.agent_var_dir(), CLOUDCLI_DIR_NAME),
            record_dir=os.path.join(platform.agent_data_dir(), CLOUDCLI_DIR_NAME),
            log=log,
        )
    if platform.os_name == "windows":
        return CloudcliWindowsApplier(
            module_dir=ntpath.join(platform.agent_var_dir(), CLOUDCLI_DIR_NAME),
            record_dir=ntpath.join(platform.agent_data_dir(), CLOUDCLI_DIR_NAME),
            account_home=platform.account_home,
        )
    raise PlatformUnsupportedError("no CloudCLI here")


def free_loopback_port() -> int:
    """A port nothing listens on at the loopback address, as the system picks one.

    Returns:
        The port.

    Raises:
        OSError: When the system gives none.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((CLOUDCLI_UPSTREAM_HOST, 0))
        return int(probe.getsockname()[1])


def _refusal_line(code: str, params: dict) -> str:
    """One refused apply as a journal line: ``cloudcli: <code> <name>=<value>``."""
    named = "".join(
        f" {name}={' '.join(str(value).split())}"
        for name, value in sorted(params.items())
    )
    return f"{CLOUDCLI_NAME}: {code}{named}"


def kept_config(path: str) -> dict:
    """CloudCLI's configuration in a kept desired state.

    Args:
        path: The kept state's file.

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
    entry = modules.get(CLOUDCLI_NAME) if isinstance(modules, dict) else None
    config = entry.get("config") if isinstance(entry, dict) else None
    return dict(config) if isinstance(config, dict) else {}


class CloudcliModuleRunner(ModuleRunner):
    """Installs Node.js from the hub's bytes and runs CloudCLI per account."""

    kind = CLOUDCLI_KIND
    name = CLOUDCLI_NAME
    download_failure_code = "cloudcli_node_download_failed"

    def __init__(
        self,
        *,
        platform,
        log=print,
        publish=None,
        applier=None,
        forwarder_factory=None,
        pick_port=None,
        clock=time.monotonic,
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            applier: The system's applier; None picks the platform's own.
            forwarder_factory: Called with a record's fields as keywords and
                ``log``; returns a started-on-demand forwarder. None makes a
                :class:`CloudcliForwarder`.
            pick_port: Returns a free loopback port for a new instance; None
                asks the system.
            clock: The monotonic clock the instances' reading ages on.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = (
            applier if applier is not None else cloudcli_applier_for(platform, log)
        )
        self._records = CloudcliRecordStore(directory=self._applier.record_dir)
        self._forwarder_factory = (
            forwarder_factory if forwarder_factory is not None else CloudcliForwarder
        )
        self._pick_port = pick_port if pick_port is not None else free_loopback_port
        self._clock = clock
        self._lock = threading.Lock()
        self._forwarders: dict = {}
        self._is_resumed = False
        self._is_stopped = False
        self._applied: "dict | None" = None
        self._applied_at = 0.0
        self._refusal: "tuple | None" = None
        # One apply at a time: the state's, or an instance's start afresh.
        self._apply_lock = threading.Lock()
        self._last_config: "dict | None" = None

    def verify(self, resolved: dict) -> bool:
        """Whether Node.js is on the machine.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the interpreter's file exists.
        """
        node = self._applier.node
        return bool(node) and os.path.isfile(node)

    def install(self, resolved: dict, package_path: str) -> None:
        """Unpack the Node.js the hub handed down.

        Args:
            resolved: The module as the hub resolved it; its entry names
                ``package_kind``, ``tar`` or ``zip``.
            package_path: The archive on local disk.

        Raises:
            ModuleApplyError: ``cloudcli_node_download_failed`` when the
                archive is not one Node.js comes in.
            OSError: When the module's directory cannot be written or
                opened to every account.
        """
        entry = resolved.get("entry") or {}
        unpack_node(
            package_path,
            package_kind=str(entry.get("package_kind", "")),
            root=self._applier.module_dir,
        )
        self._platform.open_to_accounts(self._applier.module_dir)
        self._forget_states()

    def uninstall(self, resolved: dict) -> None:
        """Delete Node.js; each account's app directory stays.

        Args:
            resolved: The module as the hub resolved it.
        """
        self._close_forwarders()
        remove_node(self._applier.module_dir)

    def validate(self, config: dict) -> None:
        """Parse and check a configuration for this system.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        CloudcliConfig.from_dict(config).validate(os_name=self._platform.os_name)

    def apply(self, config: dict) -> None:
        """Run CloudCLI and its forwarder per instance and none for an account no longer named.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused, an
                account's install or lookup fails, or the system will not
                run it.
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

    def start_afresh(self, account: str) -> None:
        """Start one instance on a new database, the old one left beside it.

        Its record names ``auth-<UTC time>.db``, and the configuration last
        applied, or the kept state's after a restart, is applied again, so
        the instance runs on that file and its forwarder registers the
        account in it.

        Args:
            account: The instance's account.
        """
        stamp = time.strftime(CLOUDCLI_FRESH_STAMP_FORMAT, time.gmtime())
        name = CLOUDCLI_FRESH_DATABASE_PATTERN.format(stamp=stamp)
        with self._apply_lock:
            record = self._records.read(account)
            if not record:
                return
            record["database"] = name
            try:
                self._records.write(record)
            except OSError as error:
                self._log(f"cloudcli: could not start {account} afresh: {error}")
                return
            config = self._last_config or kept_config(self._state_path())
            if not config:
                self._log(f"cloudcli: {account} waits for a state to start afresh on")
                return
            try:
                self._apply(config)
            except (ModuleApplyError, ModuleInstallPending) as error:
                self._log(f"cloudcli: {account} did not start afresh: {error}")
                return
        self._log(f"cloudcli: {account} starts afresh on {name}")

    def stop(self) -> None:
        """Stop every instance and its forwarder; Node.js and the records stay.

        Raises:
            OSError: When the system will not stop one.
        """
        with self._lock:
            self._is_resumed = True
            self._is_stopped = True
        self._close_forwarders()
        try:
            self._applier.stop()
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
        for account in self._records.accounts():
            self._records.remove(account)
        try:
            self._applier.remove()
        finally:
            self._forget_states()

    def is_active(self) -> bool:
        """Whether there is an instance and every one of them answers."""
        states = self._read_states()
        return bool(states) and all(state["is_running"] for state in states)

    def is_installing(self) -> bool:
        """Whether an account's install runs.

        Returns:
            True while the applier runs or waits on an install.
        """
        return bool(self._applier.installing)

    def journal_units(self) -> list:
        """Every instance's unit, on Linux."""
        return self._applier.units()

    def journal_text(self, lines: int) -> list:
        """Every instance's output: the units' journal, or each log file's tail.

        Where no unit keeps the output, the agent's own lines that name the
        module follow the log files' lines; an account whose install runs
        is there by the install's log where the applier keeps one. The code
        the last apply was refused with is the last line, on every system.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first within each instance; a log file's lines
            start with its account's name.
        """
        with self._lock:
            refusal = self._refusal
        tail = [_refusal_line(*refusal)] if refusal is not None else []
        accounts = set(self._records.accounts()) | set(self._applier.installing)
        logs = self._applier.log_paths(sorted(accounts))
        if not logs and self.journal_units():
            return (super().journal_text(lines) + tail)[-lines:]
        share = max(1, lines // len(logs)) if logs else 0
        own = []
        for account, path in logs:
            read = self._read_source(path, lambda path=path: file_tail(path, share))
            own += [f"{account}: {line}" for line in read]
        held = self._with_agent_lines(own, lines)
        return (held + tail)[-lines:]

    def details(self, resolved: dict) -> dict:
        """Each instance, its port and whether it answers.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"instances": [{"account", "port", "is_running", "code"}]}``:
            ``is_running`` while CloudCLI runs and its forwarder listens,
            ``code`` the reason it does not, such as
            ``cloudcli_register_failed`` or ``credential_invalid``.
        """
        return {"instances": [dict(state) for state in self._read_states()]}

    def _apply(self, config: dict) -> None:
        """Make the configuration true, raising what it refused."""
        parsed = CloudcliConfig.from_dict(config)
        parsed.validate(os_name=self._platform.os_name)
        upstream_ports = {
            instance.account: self._upstream_port(instance.account)
            for instance in parsed.instances
        }
        databases = {
            instance.account: str(
                self._records.read(instance.account).get("database", "")
                or CLOUDCLI_DATABASE_NAME
            )
            for instance in parsed.instances
        }
        before = set(self._applier.installing)
        try:
            notes = self._applier.apply(parsed, upstream_ports, databases)
        except ModuleInstallPending:
            started = sorted(set(self._applier.installing) - before)
            if started:
                self._log("cloudcli: installing CloudCLI for " + ", ".join(started))
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        finally:
            self._forget_states()
        wanted = {instance.account for instance in parsed.instances}
        for account in self._records.accounts():
            if account not in wanted:
                self._records.remove(account)
        for instance in parsed.instances:
            try:
                self._records.write(
                    {
                        "account": instance.account,
                        "port": instance.port,
                        "upstream_port": upstream_ports[instance.account],
                        "web_password": instance.web_password,
                        "token_secret": instance.token_secret,
                        "database": databases[instance.account],
                    }
                )
            except OSError as error:
                raise ModuleApplyError("apply_failed", {"detail": str(error)[:500]})
        with self._lock:
            self._is_resumed = True
            self._is_stopped = False
        self._sync_forwarders()
        self._log("cloudcli: " + "; ".join(notes or ["unchanged"]))

    def _state_path(self) -> str:
        """The kept desired state beside the agent's configuration."""
        return os.path.join(self._platform.agent_data_dir(), AGENT_DESIRED_STATE_NAME)

    def _upstream_port(self, account: str) -> int:
        """The loopback port an account's CloudCLI keeps, or a new one."""
        held = int(self._records.read(account).get("upstream_port", 0) or 0)
        return held if held else self._pick_port()

    def _read_states(self) -> list:
        """Every instance as it stands; the system's reading is kept a while."""
        self._resume()
        records = self._records.read_all()
        accounts = [str(record["account"]) for record in records]
        with self._lock:
            applied = self._applied
            is_fresh = (
                applied is not None
                and self._clock() - self._applied_at < CLOUDCLI_STATUS_TTL_S
            )
        if not is_fresh:
            applied = self._applier.states(accounts)
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
            states.append(
                {
                    "account": account,
                    "port": int(record.get("port", 0) or 0),
                    "is_running": bool(seen.get("is_running"))
                    and forwarder is not None
                    and forwarder.is_listening,
                    "code": code,
                }
            )
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
            record = records[account]
            forwarder = self._forwarder_factory(
                account=account,
                port=int(record.get("port", 0) or 0),
                upstream_port=int(record.get("upstream_port", 0) or 0),
                web_password=str(record.get("web_password", "") or ""),
                token_secret=str(record.get("token_secret", "") or ""),
                log=self._log,
                on_refused=self.start_afresh,
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
