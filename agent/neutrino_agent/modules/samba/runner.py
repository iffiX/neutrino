"""The file share as a module: package, configuration, details.

The package comes from the distribution, so the install rides the
system-package runner. What makes the package this hub's file share, the
rendered ``smb.conf`` with one share per enabled account and each account's
Samba password, is applied here from the hub's desired configuration; what
the machine actually serves, read back from Samba itself, is reported and
never imported. A root-only record under the agent's work root keeps the
digest of each password the module set, so a password is set again only
when the hub's differs. The record also stores whether the module turned the
SELinux boolean on, and an uninstall turns off only what the module turned on.

A Samba that was on the machine before the module installed it is the person's.
The record marks a Samba the install step found missing and installed, and only
that Samba's units and package are the module's: a stop then takes the server and
the name server down and keeps what it found the name server to be, and an
uninstall removes the package. On a person's Samba a stop takes the module's own
files off and the row reads the record's ``is_served``, a start turns a person's
server that was off on and the stop turns it back, and an uninstall removes no
package and leaves the module absent through the engine's uninstalled mark.

On Windows and macOS the same module drives the system's own SMB server
through the platform's applier instead.

Not pure: drives Samba, or the system's SMB server, through its applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import dataclasses
import functools
import json
import os
import subprocess
import tempfile
import threading
import time

from neutrino_agent.constants import (
    AGENT_CONFIGURED_DIR_NAME,
    AGENT_STEP_CONFIGURE,
    AGENT_STEP_UNINSTALL,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.samba.applier import (
    SambaConfigApplier,
    SambaConfigReader,
    SambaSelinuxApplier,
    SambaStatusReader,
    SambaUnitApplier,
    SambaUserManager,
    check_person_config,
    password_digest,
    testparm,
)
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_ACCOUNT_REFUSALS,
    SAMBA_BINARY_NAME,
    SAMBA_LINUX_USER_PREFIX,
    SAMBA_NATIVE_RECORD_NAME,
    SAMBA_NATIVE_STATUS_TTL_S,
    SAMBA_RECORD_NAME,
    SAMBA_SELINUX_BOOLEAN,
    samba_name_unit,
    samba_unit,
)
from neutrino_agent.modules.samba.renderer import SambaConfigRenderer
from neutrino_agent.modules.shared.step_locks import SYSTEM_ACCOUNTS_LOCKS
from neutrino_agent.modules.shared.subprocess_run import command_detail, unit_state
from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner
from neutrino_agent.platforms.detect import platform_tuple

# The steps that make or remove the module's accounts.
ACCOUNT_STEPS = (AGENT_STEP_CONFIGURE, AGENT_STEP_UNINSTALL)


def account_step_locks(step: str) -> tuple:
    """``system_accounts`` for the file share's ``configure`` and ``uninstall``.

    Args:
        step: The step's name.

    Returns:
        The step locks the module adds to the step.
    """
    return SYSTEM_ACCOUNTS_LOCKS if step in ACCOUNT_STEPS else ()


def stopped_configure_steps(want: str, steps: list, run_stopped) -> list:
    """The core's steps, the ``configure`` under ``stopped`` running ``run_stopped``.

    Args:
        want: ``running`` or ``stopped``.
        steps: ``configure``, then ``start`` or ``stop``.
        run_stopped: The ``configure`` step's run under ``stopped``.

    Returns:
        The steps.
    """
    if want != AGENT_WANT_STOPPED:
        return steps
    return [
        (
            dataclasses.replace(step, run=run_stopped)
            if step.name == AGENT_STEP_CONFIGURE
            else step
        )
        for step in steps
    ]


class SambaModuleRunner(SystemPackageModuleRunner):
    """Installs Samba by package and keeps it serving what the hub says."""

    runner = "samba"
    name = "samba"
    binary = SAMBA_BINARY_NAME

    def __init__(self, *, platform, log=print, publish=None, family: str = ""):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            family: The distribution family; detected when empty.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        family = family or platform_tuple().get("family", "")
        self._unit = samba_unit(family)
        self._server = SambaUnitApplier(unit=self._unit)
        self._name_server = SambaUnitApplier(unit=samba_name_unit(family))
        self._var_dir = platform.agent_var_dir()
        self._record_path = os.path.join(self._var_dir, SAMBA_RECORD_NAME)
        self._config: "SambaConfig | None" = None
        self._left_out: list = []

    @property
    def unit(self) -> str:
        """The unit this machine's Samba runs as."""
        return self._unit

    def step_locks(self, step: str) -> tuple:
        """``system_accounts`` for ``configure`` and ``uninstall``, which run ``useradd`` and ``userdel``.

        Args:
            step: The step's name.

        Returns:
            The step locks the module adds to the step.
        """
        return account_step_locks(step)

    def validate(self, config: dict) -> None:
        """Parse, check and render a configuration, then have Samba check it.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found;
                ``account_unknown {account}`` for an account a share writes
                as that the machine does not have, and the person's own
                configuration's refusals as :func:`check_person_config`
                names them.
        """
        parsed = SambaConfig.from_dict(config)
        parsed.validate()
        SambaUserManager().check_accounts(parsed.forced_users())
        smb_conf = self._check_persons(parsed)
        if parsed.served_shares():
            testparm(smb_conf, SambaConfigRenderer(config=parsed).render())

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """The core's steps, the ``configure`` under ``stopped`` starting no server.

        Args:
            config: The configuration the task's entry carries.
            want: ``running`` or ``stopped``.
            steps: ``configure``, then ``start`` or ``stop``.

        Returns:
            The steps.
        """
        return stopped_configure_steps(
            want, steps, functools.partial(self._run_apply_stopped, dict(config))
        )

    def apply(self, config: dict) -> None:
        """Make each SMB user, render the configuration, load it, and set each user's password.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused, an account
                a share writes as is not the machine's, or Samba will not
                take it.
        """
        self._apply(config, is_started=True)

    def apply_stopped(self, config: dict) -> None:
        """Make each SMB user, write the configuration and set the passwords under ``stopped``, starting no server.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: As :meth:`apply` does.
        """
        self._apply(config, is_started=False)

    def _run_apply_stopped(self, config: dict, context) -> None:
        """The ``configure`` step under ``stopped``."""
        self.apply_stopped(config)

    def _apply(self, config: dict, *, is_started: bool) -> None:
        """Make the users, write the files and set the passwords.

        With ``is_started`` false the unit is left as it is, and on a person's
        Samba the module's shares come off the server. A true one reloads an
        active unit and starts none: the ``start`` step does.
        """
        parsed = SambaConfig.from_dict(config)
        parsed.validate()
        users = SambaUserManager()
        users.check_accounts(parsed.forced_users())
        record = _read_record(self._record_path)
        is_ours = record.get("is_package_ours") is True
        is_withdrawn = not is_ours and not is_started
        if not is_withdrawn:
            self._check_persons(parsed)
        renderer = SambaConfigRenderer(config=parsed)
        rendered = renderer.render()
        held = read_digests(self._record_path)
        is_serving = bool(parsed.served_shares())
        try:
            changes = []
            applier = SambaConfigApplier(unit=self._unit)
            if self._is_first_apply():
                changes += users.sweep()
                if not is_withdrawn:
                    applier.remove()
                held = {}
            changes += users.converge_accounts(parsed)
            if is_withdrawn:
                note = applier.withdraw()
            else:
                note = applier.apply(
                    rendered,
                    config=parsed,
                    user_files=renderer.render_user_files(),
                    is_reloaded=is_started,
                )
            passwords, kept = users.converge(parsed, held)
            changes += passwords
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        is_turned_on = (
            is_started
            and is_serving
            and self._turn_selinux_boolean(SambaSelinuxApplier().turn_on, "on")
        )
        written = dict(record, passwords=kept)
        if is_turned_on:
            written["is_selinux_boolean_ours"] = True
        if not is_ours:
            written["is_served"] = is_started
        if written != _read_record(self._record_path):
            write_record(self._record_path, written)
        self._config = parsed
        self._left_out = renderer.left_out()
        if self._left_out:
            changes.append("left out " + ", ".join(self._left_out))
        self._log("samba: " + "; ".join([note] + changes))

    def _keep_started_server(self, record: dict) -> None:
        """Keep what the start about to run changes on a person's server.

        The first start the record holds stays, since it found the server as
        the person left it.

        Args:
            record: The record as this apply read it, kept up to date.

        Raises:
            OSError: When the record cannot be written.
        """
        if "started_server" in record:
            return
        found = self._server.read()
        record["started_server"] = {
            "is_enabled": not found.get("is_enabled", False),
            "is_active": not found.get("is_active", False),
        }
        write_record(self._record_path, record)

    def _turn_server_back(self, record: dict) -> None:
        """Undo what the module changed when it started a person's server.

        Args:
            record: The record; it stores nothing of the start afterwards.

        Raises:
            OSError: When the record cannot be written.
        """
        started = record.pop("started_server", None)
        if not isinstance(started, dict):
            return
        self._server.turn_back(started)
        write_record(self._record_path, record)

    def notice(self) -> dict:
        """``share_users_unknown {shares}`` while the last apply left shares out."""
        if not self._left_out:
            return {}
        return {
            "code": "share_users_unknown",
            "params": {"shares": ", ".join(self._left_out)},
        }

    def stop(self) -> None:
        """Take a Samba the module installed down, or turn a person's back.

        A Samba the module installed: the server and the name server go down
        and are disabled, the shares' files stay, and the record keeps what
        the name server was. A person's Samba: only what the module started
        is turned back, and the record marks the module stopped.

        Raises:
            OSError: When the record cannot be written.
        """
        record = _read_record(self._record_path)
        if record.get("is_package_ours") is not True:
            self._turn_server_back(record)
            record["is_served"] = False
            write_record(self._record_path, record)
            return
        SambaConfigApplier(unit=self._unit).stop()
        kept_name_server = self._name_server.read()
        if kept_name_server:
            record["kept_name_server"] = kept_name_server
            write_record(self._record_path, record)
            self._name_server.stop()

    def start(self) -> None:
        """Turn the server on, share or no share, and a Samba the module installed's name server as a stop found it.

        A person's server that was off is recorded for the stop to turn back.

        Raises:
            subprocess.CalledProcessError: If the unit will not come up.
            OSError: When the record cannot be written.
        """
        record = _read_record(self._record_path)
        if record.get("is_package_ours") is not True:
            if unit_state(self._unit) != "active":
                self._keep_started_server(record)
                SambaConfigApplier(unit=self._unit).start()
            return
        SambaConfigApplier(unit=self._unit).start()
        kept_name_server = record.pop("kept_name_server", None)
        if isinstance(kept_name_server, dict):
            self._name_server.restore(kept_name_server)
            write_record(self._record_path, record)

    def is_software_kept(self) -> bool:
        """Whether an uninstall leaves a Samba on the machine: a person's, one the record does not say the module installed.

        Returns:
            True while such a Samba is on the machine.
        """
        return not is_package_ours(self._record_path) and self.verify({})

    def install(self, recipe: dict) -> None:
        """Install the packages when the machine has no Samba, and record that the module did.

        A Samba already there with no such record is the person's: no package
        manager runs and nothing is recorded. The mark is written before the
        packages go on and deleted again when the run leaves no Samba.

        Args:
            recipe: The module's recipe.

        Raises:
            InstallError: If a step or the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
            OSError: When the record cannot be written.
        """
        record = _read_record(self._record_path)
        if record.get("is_package_ours") is not True:
            if self.verify(recipe):
                self._log("samba: found the machine's own Samba, installed nothing")
                return
            record["is_package_ours"] = True
            write_record(self._record_path, record)
        try:
            super().install(recipe)
        finally:
            if not self.verify(recipe):
                self._forget_package()

    def uninstall(self, recipe: dict) -> None:
        """Delete every ``neutrino-`` SMB user, then take the packages off a Samba the module installed.

        A person's Samba keeps its packages.

        Args:
            recipe: The module's recipe.

        Raises:
            subprocess.CalledProcessError: If Samba or ``userdel`` refuses.
            InstallError: If the uninstall refuses.
            PlatformUnsupportedError: If this platform removes nothing.
        """
        swept = SambaUserManager().sweep()
        if swept:
            self._log("samba: " + "; ".join(swept))
        if not is_package_ours(self._record_path):
            self._log("samba: removed no package")
            return
        super().uninstall(recipe)
        self._forget_package()

    def _forget_package(self) -> None:
        """Drop the mark that the module installed Samba."""
        record = _read_record(self._record_path)
        record.pop("is_package_ours", None)
        if record:
            write_record(self._record_path, record)
            return
        with contextlib.suppress(OSError):
            os.unlink(self._record_path)

    def remove_configuration(self) -> None:
        """Delete the module's file, its include line, the users' files and the record; the share directories stay.

        A running server reloads. The SELinux boolean goes off when the record
        marks it as the module's, and the mark that the module installed Samba
        stays for the uninstall.

        Raises:
            OSError: When the record cannot be written.
        """
        self._config = None
        self._left_out = []
        SambaConfigApplier(unit=self._unit).withdraw()
        if is_selinux_boolean_ours(self._record_path):
            self._turn_selinux_boolean(SambaSelinuxApplier().turn_off, "off")
        if is_package_ours(self._record_path):
            write_record(self._record_path, {"is_package_ours": True})
            return
        with contextlib.suppress(OSError):
            os.unlink(self._record_path)

    def _turn_selinux_boolean(self, turn, word: str) -> bool:
        """Turn the SELinux boolean and log it. A failure logs a line and the caller goes on.

        Args:
            turn: :meth:`SambaSelinuxApplier.turn_on` or its ``turn_off``.
            word: ``on`` or ``off``, for the line.

        Returns:
            True when this call turned it.
        """
        try:
            is_turned = turn()
        except (OSError, subprocess.SubprocessError) as error:
            self._log(
                f"samba: could not turn {word} the SELinux boolean "
                f"{SAMBA_SELINUX_BOOLEAN}: {command_detail(error)[:500]}"
            )
            return False
        if is_turned:
            self._log(
                f"samba: turned {word} the SELinux boolean {SAMBA_SELINUX_BOOLEAN}"
            )
        return is_turned

    def _is_first_apply(self) -> bool:
        """Whether no apply of the hub's configuration has succeeded here yet."""
        return not os.path.exists(
            os.path.join(self._var_dir, AGENT_CONFIGURED_DIR_NAME, self.name)
        )

    def _check_persons(self, parsed: SambaConfig) -> bytes:
        """Refuse what the person's own ``smb.conf`` makes impossible.

        Returns:
            ``smb.conf`` as the next apply leaves it, which the check read.
        """
        smb_conf, _ = SambaConfigApplier(unit=self._unit).plan(
            is_served=bool(parsed.served_shares())
        )
        global_section, shares = SambaConfigReader().read_persons(smb_conf)
        check_person_config(global_section, shares, parsed)
        return smb_conf

    def is_active(self) -> bool:
        """Whether the module serves.

        A Samba the module installed, and a Samba no ``configure`` marked yet,
        read the unit. A person's Samba reads the record's mark and the unit.

        Returns:
            True when it serves.
        """
        is_unit_active = unit_state(self._unit) == "active"
        record = _read_record(self._record_path)
        if record.get("is_package_ours") is True or "is_served" not in record:
            return is_unit_active
        return is_unit_active and record["is_served"] is True

    def journal_units(self) -> list:
        """This machine's Samba unit."""
        return [self._unit]

    def details(self, recipe: dict) -> dict:
        """What Samba serves, who it serves, and each account's state.

        The global section and the shares are what ``testparm -s`` prints
        for the live file, whoever wrote it; the users are every account
        the hub configures and every account of the module's prefix Samba
        holds a credential for.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"is_active", "global", "shares", "users", "sessions",
            "disk_usage"}``, each user ``{"name", "is_present",
            "has_password"}`` and each share ``{"name", "path", "params"}``.
        """
        config = self._config or SambaConfig()
        reader = SambaStatusReader()
        accounts = SambaUserManager()
        names = list(config.users)
        names += [
            name
            for name in accounts.credentialed_users()
            if name.startswith(SAMBA_LINUX_USER_PREFIX) and name not in names
        ]
        try:
            users = accounts.survey(names)
        except (OSError, subprocess.SubprocessError):
            users = []
        global_section, shares = SambaConfigReader().read()
        return {
            "is_active": self.is_active(),
            "global": global_section,
            "shares": shares,
            "users": [vars(state) for state in users],
            "sessions": reader.sessions(),
            "disk_usage": reader.disk_usage(config),
        }


def read_digests(path: str) -> dict:
    """The digest of each password the module set, by user.

    Args:
        path: The record's file.

    Returns:
        ``{user: digest}``; empty when there is no record or it does not
        read.
    """
    passwords = _read_record(path).get("passwords")
    if not isinstance(passwords, dict):
        return {}
    return {str(name): str(digest) for name, digest in passwords.items()}


def is_selinux_boolean_ours(path: str) -> bool:
    """Whether the module turned the SELinux boolean on.

    Args:
        path: The record's file.

    Returns:
        True when the record stores the mark; False when it stores none,
        there is no record or it does not read.
    """
    return _read_record(path).get("is_selinux_boolean_ours") is True


def is_package_ours(path: str) -> bool:
    """Whether the module installed the Samba on this machine.

    Args:
        path: The record's file.

    Returns:
        True when the record stores the mark; False when it stores none,
        there is no record or it does not read.
    """
    return _read_record(path).get("is_package_ours") is True


def _read_record(path: str) -> dict:
    """The record's fields; empty when there is no record or it does not read."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            held = json.load(stream)
    except (OSError, ValueError):
        return {}
    return held if isinstance(held, dict) else {}


def write_record(path: str, record: dict) -> None:
    """Keep a record, root-only, whole or not at all.

    Args:
        path: The record's file.
        record: What it holds.

    Raises:
        OSError: When it cannot be written.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".samba_")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


class SambaNativeServerRunner(ModuleRunner):
    """Keeps the system's own SMB server serving what the hub says.

    Windows and macOS carry the server, so there is nothing to install or
    uninstall; the platform's applier converges the shares and the accounts
    and fences nothing. Each
    account's password is set from the configuration's ``passwords``
    whenever it differs from the one the module set last. A root-only
    record under the agent's work root lists what the module made and the
    digest of each password it set. The server's state is read at most
    every 30 seconds and again after every change.
    """

    runner = "samba_native"
    name = "samba"

    def __init__(self, *, platform, log=print, publish=None, clock=time.monotonic):
        """
        Args:
            platform: The machine's platform; it has ``smb_server``.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            clock: The monotonic clock the status reading ages on.

        Raises:
            PlatformUnsupportedError: When the platform has no SMB server.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = platform.smb_server_applier()
        self._record_path = os.path.join(
            platform.agent_var_dir(), SAMBA_NATIVE_RECORD_NAME
        )
        self._clock = clock
        self._config: "SambaConfig | None" = None
        self._left_out: list = []
        self._lock = threading.Lock()
        # One open of the record at a time.
        self._record_lock = threading.Lock()
        self._status: "dict | None" = None
        self._status_at = 0.0

    def step_locks(self, step: str) -> tuple:
        """``system_accounts`` for ``configure`` and ``uninstall``, which make and disable the module's accounts.

        Args:
            step: The step's name.

        Returns:
            The step locks the module adds to the step.
        """
        return account_step_locks(step)

    def verify(self, recipe: dict) -> bool:
        """Whether the system's SMB server is there.

        Args:
            recipe: The module's recipe.

        Returns:
            True when the server answers for itself.
        """
        return bool(self._read_status().get("is_present"))

    def install(self, recipe: dict) -> None:
        """Install nothing: the system carries the server.

        Args:
            recipe: The module's recipe.
        """

    def uninstall(self, recipe: dict) -> None:
        """Remove nothing: the server stays with the system.

        Args:
            recipe: The module's recipe.
        """

    def validate(self, config: dict) -> None:
        """Parse and check a configuration for this system.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        SambaConfig.from_dict(config).validate(os_name=self._platform.os_name)

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """The core's steps, the ``configure`` under ``stopped`` serving no share and starting no server.

        Args:
            config: The configuration the task's entry carries.
            want: ``running`` or ``stopped``.
            steps: ``configure``, then ``start`` or ``stop``.

        Returns:
            The steps.
        """
        return stopped_configure_steps(
            want, steps, functools.partial(self._run_apply_stopped, dict(config))
        )

    def apply(self, config: dict) -> None:
        """Converge the server with the configuration and serve it.

        The record lists the configured shares before the server is
        touched, so a share made by an apply that then failed is still the
        module's to change. The first apply after an install or an adoption
        sweeps every share and account the module's marker names and starts
        from an empty record.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or the
                server will not take it.
        """
        self._apply(config, is_served=True)

    def apply_stopped(self, config: dict) -> None:
        """Make each account, grant the folders and set the passwords under ``stopped``, serving no share and starting no server.

        The module's shares come off the server, as :meth:`stop` takes
        them off.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: As :meth:`apply` does.
        """
        self._apply(config, is_served=False)

    def _run_apply_stopped(self, config: dict, context) -> None:
        """The ``configure`` step under ``stopped``."""
        self.apply_stopped(config)

    def _apply(self, config: dict, *, is_served: bool) -> None:
        """Converge the server with the configuration. With ``is_served`` false no share is served."""
        parsed = SambaConfig.from_dict(config)
        parsed.validate(os_name=self._platform.os_name)
        record = self._read_record()
        is_sweep = not os.path.exists(
            os.path.join(
                self._platform.agent_var_dir(), AGENT_CONFIGURED_DIR_NAME, self.name
            )
        )
        if is_sweep:
            record = dict(record, shares={}, accounts=[], passwords={})
        served = parsed.served_shares()
        shares = dict(record["shares"])
        shares.update({share.name: share.path for share in served})
        self._write_record(dict(record, shares=shares))
        refusal = None
        try:
            notes = self._applier.apply(
                parsed,
                dict(record, shares=shares),
                is_sweep=is_sweep,
                is_served=is_served,
            )
        except ModuleApplyError as error:
            if error.code not in SAMBA_ACCOUNT_REFUSALS:
                raise
            refusal = error
            notes = [f"passed over account {error.params.get('user', '')}"]
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        finally:
            self._forget_status()
        accounts = list(record["accounts"])
        accounts += [name for name in parsed.users if name not in accounts]
        refused = refusal.params.get("user", "") if refusal is not None else ""
        try:
            passwords = self._set_passwords(parsed, record["passwords"], refused)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        finally:
            self._forget_status()
        self._write_record(
            {
                "shares": {share.name: share.path for share in served},
                "accounts": accounts,
                "passwords": passwords,
                "is_served": is_served,
            }
        )
        self._config = parsed
        self._left_out = [share.name for share in parsed.shares if share not in served]
        if self._left_out:
            notes.append("left out " + ", ".join(self._left_out))
        self._log("samba: " + "; ".join(notes or ["unchanged"]))
        if refusal is not None:
            raise refusal

    def notice(self) -> dict:
        """``share_users_unknown {shares}`` while the last apply left shares out."""
        if not self._left_out:
            return {}
        return {
            "code": "share_users_unknown",
            "params": {"shares": ", ".join(self._left_out)},
        }

    def _set_passwords(self, config: SambaConfig, held: dict, refused: str) -> dict:
        """Set each account's password that differs from the one set last.

        Args:
            config: The configuration, with ``passwords``.
            held: The digest of each password the module set last.
            refused: An account the system would not make, passed over.

        Returns:
            The digests the module holds now, for the configured users.

        Raises:
            ModuleApplyError: When the system will not take an account's
                password.
            OSError: When the host or a command fails.
        """
        kept = {name: digest for name, digest in held.items() if name in config.users}
        for name in config.users:
            password = config.passwords.get(name, "")
            if not password or name == refused:
                continue
            digest = password_digest(password)
            if kept.get(name) == digest:
                continue
            self._applier.set_password(name, password)
            kept[name] = digest
            self._log(f"samba: set the password of {name}")
        return kept

    def stop(self) -> None:
        """Take the module's shares off the server; the accounts stay, and the record keeps each share's folder.

        Raises:
            OSError: When the server will not let them go.
        """
        record = self._read_record()
        try:
            self._applier.withdraw(record, is_removed=False)
        finally:
            self._forget_status()
        self._write_record(dict(record, is_served=False))

    def remove_configuration(self) -> None:
        """Take the shares away and disable the accounts.

        Raises:
            OSError: When the server will not let them go.
        """
        record = self._read_record()
        self._config = None
        self._left_out = []
        try:
            self._applier.withdraw(record, is_removed=True)
        finally:
            self._forget_status()
        self._write_record(dict(record, shares={}, passwords={}, is_served=False))

    def is_active(self) -> bool:
        """Whether the server runs and serves the module's shares."""
        is_running = bool(self._read_status().get("is_running"))
        return is_running and bool(self._read_record()["is_served"])

    def details(self, recipe: dict) -> dict:
        """What the server serves of the module's, and who uses it.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"is_active", "global", "shares", "users", "sessions",
            "disk_usage"}`` in the shapes the Linux module reports,
            ``global`` empty.
        """
        status = self._read_status()
        return {
            "is_active": self.is_active(),
            "global": {},
            "shares": list(status.get("shares") or []),
            "users": list(status.get("users") or []),
            "sessions": list(status.get("sessions") or []),
            "disk_usage": SambaStatusReader().disk_usage(self._config or SambaConfig()),
        }

    def journal_text(self, lines: int) -> list:
        """The server's own log, then the agent's lines about the module.

        Args:
            lines: How many lines to return at most.

        Returns:
            The server's latest lines followed by the agent's, oldest
            first within each.
        """
        own = self._read_source(
            "the SMB server's events", lambda: self._applier.read_server_log(lines)
        )
        return self._with_agent_lines(own, lines)

    def _read_status(self) -> dict:
        """The server's state, read again once the last reading is stale."""
        with self._lock:
            now = self._clock()
            if (
                self._status is not None
                and now - self._status_at < SAMBA_NATIVE_STATUS_TTL_S
            ):
                return self._status
        status = self._applier.read_status(self._read_record())
        with self._lock:
            self._status, self._status_at = status, self._clock()
        return status

    def _forget_status(self) -> None:
        with self._lock:
            self._status = None

    def _read_record(self) -> dict:
        """The record, ``{"shares", "accounts", "passwords", "is_served"}``.

        ``shares`` lists the folder of each share the module configured, on
        the server or not. ``accounts`` leaves out a name without the
        module's prefix. Empty when none.
        """
        with self._record_lock:
            try:
                with open(self._record_path, "r", encoding="utf-8") as stream:
                    held = json.load(stream)
            except (OSError, ValueError):
                held = {}
        held = held if isinstance(held, dict) else {}
        shares = held.get("shares")
        passwords = held.get("passwords")
        return {
            "shares": dict(shares) if isinstance(shares, dict) else {},
            "accounts": [
                str(name)
                for name in held.get("accounts") or []
                if str(name).startswith(SAMBA_LINUX_USER_PREFIX)
            ],
            "passwords": (
                {str(name): str(digest) for name, digest in passwords.items()}
                if isinstance(passwords, dict)
                else {}
            ),
            "is_served": bool(held.get("is_served", False)),
        }

    def _write_record(self, record: dict) -> None:
        """Keep the record, root-only, whole or not at all."""
        with self._record_lock:
            write_record(self._record_path, record)
