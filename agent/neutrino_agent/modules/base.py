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

from neutrino_agent.constants import (
    AGENT_MODULE_JOURNAL_LINES,
    AGENT_MODULE_VERB_JOURNAL,
    AGENT_MODULE_VERB_VALIDATE,
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.subprocess_run import units_journal


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
        kind: The recipe kind this runner installs by.
        name: The module's name on the wire; empty for a runner that
            serves a kind rather than one module.
    """

    kind = ""
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

    def verify(self, resolved: dict) -> bool:
        """Whether the software is on this machine, by the runner's own check.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            False for a runner with no check of its own.
        """
        return False

    def observe(self, resolved: dict) -> dict:
        """What is true of this module right now, acting on nothing.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"is_installed", "is_active", "details"}``: the runner's own
            presence check, its unit's word, and its live details; the
            last two are not read for software that is not there.
        """
        is_installed = bool(self.verify(resolved))
        return {
            "is_installed": is_installed,
            "is_active": bool(self.is_active()) if is_installed else False,
            "details": self.details(resolved) if is_installed else {},
        }

    def details(self, resolved: dict) -> dict:
        """What the surfaces show beside this module's row.

        Bounded live reads a person looks at, never anything a wording
        table words. Empty for a module with nothing to add.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            The details, empty by default.
        """
        return {}

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

    def stop(self) -> None:
        """Take the module's service down, leaving its data in place."""

    def remove_configuration(self) -> None:
        """Delete what the hub's applies wrote, leaving the module's data.

        Run on uninstall, only for a module the hub configured.
        """

    def is_active(self) -> bool:
        """Whether the unit this module runs as is active.

        Returns:
            False for a module that runs as no unit.
        """
        return False

    def journal_units(self) -> list:
        """The units whose journal is this module's output.

        Returns:
            The unit names; empty for a module that runs as no unit.
        """
        return []

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
        """The tail of the module's units' journal, as the verb answers it."""
        try:
            lines = int(args.get("lines", AGENT_MODULE_JOURNAL_LINES))
        except (TypeError, ValueError):
            lines = AGENT_MODULE_JOURNAL_LINES
        lines = max(1, min(lines, AGENT_MODULE_JOURNAL_LINES))
        return command_outcome(
            0, output="\n".join(units_journal(self.journal_units(), lines))
        )

    def _validate_command(self, args: dict) -> dict:
        """Check the configuration the verb carries, typed either way."""
        config = args.get("config")
        try:
            self.validate(dict(config) if isinstance(config, dict) else {})
        except ModuleApplyError as error:
            return command_outcome(1, error.code, error.params)
        except PlatformUnsupportedError:
            return command_outcome(1, "unsupported_platform")
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return command_outcome(1, "validate_failed", {"detail": str(error)[:200]})
        return command_outcome(0)
