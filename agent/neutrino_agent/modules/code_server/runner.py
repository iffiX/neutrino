"""code-server as a module: VS Code in the browser, per account, on Linux and macOS.

The release is the archive the hub caches, down a package stream, unpacked
into the module's own directory. Each instance is one account's
code-server, listening on a socket in that account's run directory, and
started the way the system starts a process as an account: a systemd unit
with ``User=`` on Linux, a LaunchDaemon with ``UserName`` on macOS. In
front of each stands a forwarder of the agent on ``127.0.0.1`` at the
instance's port, started again from the instance's record when the agent
restarts. The code the last apply was refused with ends the log until an
apply takes.

Not pure: drives the platform's applier and the forwarders.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import os
import subprocess
import threading
import time

from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.base import ModuleRunner
from neutrino_agent.modules.cloudcli.record_store import CloudcliRecordStore
from neutrino_agent.modules.code_server import installer
from neutrino_agent.modules.code_server.config import CodeServerConfig
from neutrino_agent.modules.code_server.constants import (
    CODE_SERVER_DIR_NAME,
    CODE_SERVER_KIND,
    CODE_SERVER_NAME,
    CODE_SERVER_RECORD_FIELDS,
    CODE_SERVER_STATUS_TTL_S,
)
from neutrino_agent.modules.code_server.darwin_applier import CodeServerDarwinApplier
from neutrino_agent.modules.code_server.forwarder import CodeServerForwarder
from neutrino_agent.modules.code_server.linux_applier import CodeServerLinuxApplier
from neutrino_agent.modules.log_tail import file_tail
from neutrino_agent.modules.subprocess_run import command_detail


def code_server_applier_for(platform):
    """The applier that starts code-server as an account on this system.

    Args:
        platform: The machine's platform.

    Returns:
        The Linux or macOS applier.

    Raises:
        PlatformUnsupportedError: On a system with none.
    """
    appliers = {"linux": CodeServerLinuxApplier, "darwin": CodeServerDarwinApplier}
    applier = appliers.get(platform.os_name)
    if applier is None:
        raise PlatformUnsupportedError("no code-server here")
    return applier(
        module_dir=os.path.join(platform.agent_var_dir(), CODE_SERVER_DIR_NAME),
        record_dir=os.path.join(platform.agent_data_dir(), CODE_SERVER_DIR_NAME),
    )


def _refusal_line(code: str, params: dict) -> str:
    """One refused apply as a journal line: ``code_server: <code> <name>=<value>``."""
    named = "".join(
        f" {name}={' '.join(str(value).split())}"
        for name, value in sorted(params.items())
    )
    return f"{CODE_SERVER_NAME}: {code}{named}"


class CodeServerModuleRunner(ModuleRunner):
    """Installs code-server's release from the hub's bytes and runs it per account."""

    kind = CODE_SERVER_KIND
    name = CODE_SERVER_NAME
    download_failure_code = "code_server_download_failed"

    def __init__(
        self,
        *,
        platform,
        log=print,
        publish=None,
        applier=None,
        forwarder_factory=None,
        clock=time.monotonic,
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            applier: The system's applier; None picks the platform's own.
            forwarder_factory: Called with ``account``, ``port``, ``secret``,
                ``socket_path`` and ``log``; returns a started-on-demand
                forwarder. None makes a :class:`CodeServerForwarder`.
            clock: The monotonic clock the instances' reading ages on.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = (
            applier if applier is not None else code_server_applier_for(platform)
        )
        self._records = CloudcliRecordStore(
            directory=self._applier.record_dir, fields=CODE_SERVER_RECORD_FIELDS
        )
        self._forwarder_factory = (
            forwarder_factory if forwarder_factory is not None else CodeServerForwarder
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._forwarders: dict = {}
        self._is_resumed = False
        self._is_stopped = False
        self._applied: "dict | None" = None
        self._applied_at = 0.0
        self._refusal: "tuple | None" = None

    def verify(self, resolved: dict) -> bool:
        """Whether the release is on the machine.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when its launcher exists.
        """
        return os.path.isfile(installer.launcher_path(self._applier.module_dir))

    def install(self, resolved: dict, package_path: str) -> None:
        """Unpack the release the hub handed down, stopping the instances first.

        Args:
            resolved: The module as the hub resolved it; its entry names
                ``package_kind`` ``tar``.
            package_path: The archive on local disk.

        Raises:
            ModuleApplyError: ``code_server_download_failed`` when the
                archive is not a code-server release.
            OSError: When the module's directory cannot be written or
                opened to every account.
        """
        entry = resolved.get("entry") or {}
        if self.verify(resolved):
            self._applier.stop()
        installer.unpack_release(
            package_path,
            package_kind=str(entry.get("package_kind", "")),
            root=self._applier.module_dir,
        )
        self._platform.open_to_accounts(self._applier.module_dir)
        self._log(
            "code_server: unpacked code-server "
            + (installer.installed_version(self._applier.module_dir) or "?")
        )
        self._forget_states()

    def uninstall(self, resolved: dict) -> None:
        """Delete the release and every run directory; each account's own settings stay.

        Args:
            resolved: The module as the hub resolved it.
        """
        self._close_forwarders()
        installer.remove_release(self._applier.module_dir)

    def validate(self, config: dict) -> None:
        """Parse and check a configuration.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        CodeServerConfig.from_dict(config).validate()

    def apply(self, config: dict) -> None:
        """Run code-server and its forwarder per instance and none for an account no longer named.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or the
                system will not run it.
        """
        try:
            self._apply(config)
        except ModuleApplyError as error:
            with self._lock:
                self._refusal = (error.code, dict(error.params))
            raise
        with self._lock:
            self._refusal = None

    def stop(self) -> None:
        """Stop every instance and its forwarder; the release and the records stay.

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

    def journal_units(self) -> list:
        """Every instance's unit, on Linux."""
        return self._applier.units()

    def journal_text(self, lines: int) -> list:
        """Every instance's output: the units' journal, or each log file's tail.

        On macOS the agent's own lines that name the module follow the log
        files' lines. The code the last apply was refused with is the last
        line, on every system.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first within each instance; a log file's lines
            start with its account's name.
        """
        with self._lock:
            refusal = self._refusal
        tail = [_refusal_line(*refusal)] if refusal is not None else []
        logs = self._applier.log_paths(self._records.accounts())
        if not logs and self.journal_units():
            return (super().journal_text(lines) + tail)[-lines:]
        share = max(1, lines // len(logs)) if logs else 0
        own = []
        for account, path in logs:
            read = self._read_source(path, functools.partial(file_tail, path, share))
            own += [f"{account}: {line}" for line in read]
        held = self._with_agent_lines(own, lines)
        return (held + tail)[-lines:]

    def details(self, resolved: dict) -> dict:
        """The release installed, and each instance, its port and whether it answers.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"version", "instances": [{"account", "port", "is_running",
            "code"}]}``: ``is_running`` while code-server runs and its
            forwarder listens, ``code`` the reason it does not, such as
            ``code_server_port_taken``.
        """
        return {
            "version": installer.installed_version(self._applier.module_dir),
            "instances": [dict(state) for state in self._read_states()],
        }

    def _apply(self, config: dict) -> None:
        """Make the configuration true, raising what it refused."""
        parsed = CodeServerConfig.from_dict(config)
        parsed.validate()
        try:
            notes = self._applier.apply(parsed)
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
                        "secret": instance.secret,
                    }
                )
            except OSError as error:
                raise ModuleApplyError("apply_failed", {"detail": str(error)[:500]})
        with self._lock:
            self._is_resumed = True
            self._is_stopped = False
        self._sync_forwarders()
        self._log("code_server: " + "; ".join(notes or ["unchanged"]))

    def _read_states(self) -> list:
        """Every instance as it stands; the system's reading is kept a while."""
        self._resume()
        records = self._records.read_all()
        accounts = [str(record["account"]) for record in records]
        with self._lock:
            applied = self._applied
            is_fresh = (
                applied is not None
                and self._clock() - self._applied_at < CODE_SERVER_STATUS_TTL_S
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
        root = self._applier.module_dir
        with self._lock:
            if self._is_stopped:
                records = {}
            stale = [
                account
                for account, forwarder in self._forwarders.items()
                if account not in records
                or not forwarder.matches(
                    records[account], installer.socket_path(root, account)
                )
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
                secret=str(record.get("secret", "") or ""),
                socket_path=installer.socket_path(root, account),
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
