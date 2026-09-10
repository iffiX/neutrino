"""What a module runner is.

A module is machine software the hub administers: a file share, a git
server, a container engine. One runner owns one module: it carries out an
order the hub sent, makes the hub's desired configuration true on the
machine, answers the commands the hub opens, and reports what is true
afterwards. It decides nothing about when, because the hub is the only
thing that holds policy.

Every status a runner's caller returns is typed:
``{"state", "code", "params"}``, never an English sentence, so every
surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


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
    """Carries out orders and configuration for one kind of module."""

    kind = ""

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

    def command(self, action: str, args: dict, on_line=None) -> dict:
        """Run one of this module's commands.

        Args:
            action: The command's action on the wire.
            args: What the action takes.
            on_line: Called with each output line as it is produced.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        return command_outcome(1, "unsupported_action", {"action": action})
