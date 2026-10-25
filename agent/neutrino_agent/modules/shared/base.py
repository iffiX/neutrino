"""What a module runner is.

A module is machine software the hub administers: a file share, a git
server, a container engine. One runner owns one module: it puts the
software on the machine and takes it off, makes the hub's desired
configuration true, answers the verbs a ``command`` stream names, and
observes what is true afterwards. It decides nothing about when, because
the hub is the only thing that holds policy.

Every status a runner's caller returns is typed:
``{"state", "is_active", "code", "params", "details"}``, never an English
sentence, so every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import subprocess

from neutrino_agent.constants import (
    AGENT_ARTIFACT_KEPT_SUFFIXES,
    AGENT_ARTIFACT_KIND_BINARY,
    AGENT_ARTIFACT_KIND_MSI,
    AGENT_ARTIFACT_KIND_PKG,
    AGENT_LOG_ROTATED_SUFFIX,
    AGENT_MODULE_JOURNAL_LINES,
    AGENT_MODULE_VERB_JOURNAL,
    AGENT_MODULE_VERB_VALIDATE,
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared.log_tail import file_tail, mask_secrets
from neutrino_agent.modules.shared.package import (
    is_archive_kind,
    joiner,
    keep_artifact,
    params_of,
    place_binary,
    unpack_artifact,
)
from neutrino_agent.modules.shared.subprocess_run import units_journal


def _ignore_status(name: str, status: dict) -> None:
    """Swallow a transient status when nobody is watching."""


def command_outcome(
    exit_code: int, code: str = "", params: "dict | None" = None, output: str = ""
) -> dict:
    """One command's result, the shape every command stream closes with.

    Args:
        exit_code: The command's exit status; 0 means success.
        code: Why it failed, typed; empty on success.
        params: What the wording names.
        output: What the command printed.

    Returns:
        ``{"exit_code", "code", "params", "output"}``.
    """
    return {
        "exit_code": int(exit_code),
        "code": code,
        "params": dict(params or {}),
        "output": output,
    }


class ModuleRunner:
    """Installs, configures, observes and answers for one kind of module.

    Attributes:
        runner: The name a recipe's ``runner`` chooses this runner by.
        name: The module's name on the wire.
    """

    runner = ""
    name = ""

    def __init__(self, *, platform, log=print, publish=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states,
                installing and uninstalling, so a watcher sees a step start
                rather than only its result. None publishes nothing.
        """
        self._platform = platform
        self._log = log
        self._publish = publish if publish is not None else _ignore_status
        # The log sources a journal could not read, each warned of once.
        self._unread_sources: set = set()

    @property
    def module_dir(self) -> str:
        """The module's directory under the state root, where its software lands."""
        join = joiner(self._platform.os_name)
        return join(self._platform.agent_var_dir(), self.name)

    def verify(self, recipe: dict) -> bool:
        """Whether the software is on this machine, by the runner's own check.

        Only a ``builtin`` recipe and a module the state does not name are
        judged by it; every other method's check is its recipe's.

        Args:
            recipe: The module's recipe, empty for a module the state does
                not name.

        Returns:
            False for a runner with no check of its own.
        """
        return False

    def details(self, recipe: dict) -> dict:
        """What the surfaces show beside this module's row.

        Bounded live reads a person looks at, never anything a wording
        table words. Empty for a module with nothing to add.

        Args:
            recipe: The module's recipe, empty for a module the state does
                not name.

        Returns:
            The details, empty by default.
        """
        return {}

    def take_recipe(self, recipe: dict) -> None:
        """Take the recipe the state names for this module.

        Args:
            recipe: ``{runner, method, params}``.
        """

    def take_config(self, config: dict) -> None:
        """Take the configuration the state names for this module, before any apply of it.

        Args:
            config: The module's configuration in the state.
        """

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's ``source_sets`` section.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``, each set a
                recipe of the state names.
        """

    def install(self, recipe: dict) -> None:
        """Install what the recipe names by name: a ``hub`` entry's system packages.

        Args:
            recipe: The module's recipe.

        Raises:
            InstallError: If the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        packages = [str(name) for name in params_of(recipe).get("packages") or []]
        if not packages:
            return
        output = self._platform.install_system_packages(packages)
        if output.strip():
            self._log(output.strip())

    def install_artifact(self, recipe: dict, artifact: dict, path: str) -> None:
        """Put one artifact the hub handed down on the machine, as its kind says.

        An archive is unpacked under its directory in the module's own and
        sealed, an msi or a pkg is kept there and installed, a zstd file is
        kept there, and a program is kept at :meth:`binary_path`; the
        module's directory is then opened to every account.

        Args:
            recipe: The module's recipe.
            artifact: ``{name, kind, digest, directory}`` as the recipe
                names it.
            path: The received file, whose digest was checked.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` for an artifact
                this module cannot put anywhere or an archive that cannot be
                unpacked.
            InstallError: When the system's installer refuses a package.
            OSError: When the module's directory cannot be written.
        """
        kind = str(artifact.get("kind", "") or "")
        join = joiner(self._platform.os_name)
        module_dir = self.module_dir
        if is_archive_kind(kind):
            unpack_artifact(artifact, path, module_dir=module_dir, join=join)
        elif kind in AGENT_ARTIFACT_KEPT_SUFFIXES:
            kept = keep_artifact(artifact, path, module_dir=module_dir, join=join)
            if kind == AGENT_ARTIFACT_KIND_MSI:
                log_path = os.path.splitext(kept)[0] + ".log"
                installers.install_msi(kept, log_path=log_path)
            elif kind == AGENT_ARTIFACT_KIND_PKG:
                installers.install_pkg(kept)
        elif kind == AGENT_ARTIFACT_KIND_BINARY:
            place_binary(path, self.binary_path(recipe, artifact))
            return
        else:
            name = str(artifact.get("name", "") or "")
            raise ModuleApplyError(
                "install_failed", {"detail": f"artifact {name!r} of kind {kind!r}"}
            )
        self._platform.open_to_accounts(module_dir)

    def binary_path(self, recipe: dict, artifact: dict) -> str:
        """Where a ``binary`` artifact is kept, as the module's page says.

        Args:
            recipe: The module's recipe.
            artifact: The artifact.

        Returns:
            The program's path.

        Raises:
            ModuleApplyError: ``install_failed`` for a module that keeps no
                program of its own.
        """
        raise ModuleApplyError(
            "install_failed", {"detail": f"{self.name} keeps no program"}
        )

    def uninstall(self, recipe: dict) -> None:
        """Take the module's software off this machine; its data stays.

        Args:
            recipe: The module's recipe.
        """

    def validate(self, config: dict) -> None:
        """Check a configuration before the hub stores it.

        Args:
            config: The module's desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """

    def apply(self, config: dict) -> None:
        """Make a configuration true on this machine.

        Args:
            config: The module's desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or the
                machine will not take it.
        """

    def start(self) -> None:
        """Bring the module's service up once its configuration applied, under ``running``.

        A module whose apply already starts what it runs leaves this as it is.
        """

    def stop(self) -> None:
        """Take the module's service down, leaving its data in place."""

    def remove_configuration(self) -> None:
        """Delete what the hub's applies wrote, leaving the module's data.

        Run on uninstall, only for a module the hub configured.
        """

    def remove_data(self) -> None:
        """Delete the module's own data: what an uninstall otherwise leaves.

        Run on uninstall only when the recipe's ``is_data_kept`` is false.
        A runner with nothing to delete, or whose data is never the hub's to
        delete, leaves this as it is.
        """

    def is_installing(self) -> bool:
        """Whether an install the module's apply started still runs.

        Returns:
            False for a module whose apply installs nothing of its own.
        """
        return False

    def install_wait(self) -> dict:
        """What holds up the install :meth:`is_installing` reports.

        Returns:
            ``{"code", "params"}`` naming it, the code ``reboot_required``
            while a restart is owed; empty for a module whose install
            waits on nothing it names.
        """
        return {}

    def absent_reason(self, recipe: dict) -> dict:
        """What is missing of software whose check fails while part of it is there.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"code", "params"}`` naming the missing part; empty for a
            module that names none.
        """
        return {}

    def is_active(self) -> bool:
        """Whether the unit this module runs as is active.

        Returns:
            False for a module that runs as no unit.
        """
        return False

    def forwarder_ports(self) -> tuple:
        """The ports the agent's forwarders of this module listen on, on ``127.0.0.1``.

        Returns:
            An empty tuple for a module with no forwarder.
        """
        return ()

    def journal_units(self) -> list:
        """The units whose journal is this module's output.

        Returns:
            The unit names; empty for a module that runs as no unit.
        """
        return []

    def journal_text(self, lines: int) -> list:
        """The module's log, oldest line first.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines; by default the tail of the units' journal.
        """
        return units_journal(self.journal_units(), lines)

    def command(self, verb: str, args: dict, on_line=None) -> dict:
        """Run one of this module's verbs.

        Every module answers ``validate`` and ``journal``; the rest are the
        module's own.

        Args:
            verb: The verb on the wire, without the module's name.
            args: What the verb takes; ``{"lines"}`` for the journal.
            on_line: Called with each output line as it is produced.

        Returns:
            ``{"exit_code", "code", "params", "output"}``; ``verb_unknown``
            for a verb this module does not have.
        """
        if verb == AGENT_MODULE_VERB_VALIDATE:
            return self._validate_command(args)
        if verb == AGENT_MODULE_VERB_JOURNAL:
            return self._journal_command(args)
        return command_outcome(1, "verb_unknown", {"module": self.name, "verb": verb})

    def _journal_command(self, args: dict) -> dict:
        """The tail of the module's log, its tokens masked, as the verb answers it."""
        try:
            lines = int(args.get("lines", AGENT_MODULE_JOURNAL_LINES))
        except (TypeError, ValueError):
            lines = AGENT_MODULE_JOURNAL_LINES
        lines = max(1, min(lines, AGENT_MODULE_JOURNAL_LINES))
        text = "\n".join(self.journal_text(lines)[-lines:])
        return command_outcome(0, output=mask_secrets(text))

    def _agent_log_lines(self, lines: int) -> list:
        """The agent's own log lines that name this module, empty in a journal.

        The file the last rotation left is read before the current one, so
        a rotation does not empty the box.
        """
        path = self._platform.agent_log_path()
        if not path:
            return []
        rotated = path + AGENT_LOG_ROTATED_SUFFIX
        held = []
        if os.path.isfile(rotated):
            held = self._read_source(
                rotated, lambda: file_tail(rotated, lines, needle=self.name)
            )
        held += self._read_source(
            path, lambda: file_tail(path, lines, needle=self.name)
        )
        return held[-lines:]

    def _with_agent_lines(self, own: list, lines: int) -> list:
        """The module's own lines, then the agent's lines that name it.

        Args:
            own: The module's own sources' lines, oldest first.
            lines: How many lines to return at most.

        Returns:
            At most ``lines``: the agent's lines take at most half when the
            module has lines of its own, and the module's newest fill the rest.
        """
        agent = self._agent_log_lines(max(1, lines // 2) if own else lines)
        kept = max(0, lines - len(agent))
        return (own[-kept:] if kept else []) + agent

    def _read_source(self, source: str, read) -> list:
        """One source of the module's log, read; a failure is warned of once.

        Args:
            source: What the source is, as the warning names it.
            read: Returns the source's lines; raises when it cannot.

        Returns:
            The lines; empty when the source could not be read, after one
            line in the agent's own log naming the module and the source.
        """
        try:
            held = list(read())
        except (OSError, subprocess.SubprocessError, ModuleApplyError) as error:
            if source not in self._unread_sources:
                self._unread_sources.add(source)
                self._log(f"{self.name}: cannot read the log source {source}: {error}")
            return []
        self._unread_sources.discard(source)
        return held

    def _validate_command(self, args: dict) -> dict:
        """Check the configuration the verb carries, typed either way."""
        config = args.get("config")
        try:
            self.validate(dict(config) if isinstance(config, dict) else {})
        except ModuleApplyError as error:
            return self._validate_refused(error.code, error.params)
        except PlatformUnsupportedError:
            return self._validate_refused("unsupported_platform", {})
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return self._validate_refused(
                "validate_failed", {"detail": str(error)[:200]}
            )
        return command_outcome(0)

    def _validate_refused(self, code: str, params: "dict | None") -> dict:
        """Log one refused configuration and answer with its code."""
        named = " ".join(f"{key}={value}" for key, value in (params or {}).items())
        self._log(f"{self.name} validate refused: {code} {named}".rstrip())
        return command_outcome(1, code, params)
