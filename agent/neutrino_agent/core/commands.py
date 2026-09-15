"""Carrying out the commands the hub opens.

A command names a module and a verb. The agent's own verbs are the closed
set in :data:`AGENT_VERBS`: the hub is trusted, but an agent running as
root should still not accept an arbitrary shell string just because
something sent one, so no verb runs one. Every other module's verbs are
its runner's, spelled without the module's name because the ``module``
field is the prefix. A module or a verb this build does not have is
refused ``verb_unknown``.

Installing a module is no verb: it follows from the hub's ``want``, and
``reinstall`` only puts this agent's own package back.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field

from neutrino_agent.constants import (
    AGENT_COMMAND_MODULE,
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_KILL_GRACE_S,
    AGENT_MODULE_COMMAND_SETTLE_S,
    AGENT_MODULE_VERB_VALIDATE,
    AGENT_OUTPUT_LIMIT_BYTES,
)
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.modules.remote_desktop import (
    SUPPORTED_PRODUCTS,
    RemoteDesktopReader,
)

VERB_REBOOT = "reboot"
VERB_SHUTDOWN = "shutdown"
VERB_REINSTALL = "reinstall"
VERB_RESIZE = "resize"
VERB_KILL = "kill"
VERB_REMOTE_DESKTOP_READ = "remote_desktop_read"
VERB_REMOTE_DESKTOP_PASSWORD_SET = "remote_desktop_password_set"  # scan: allow

# The verbs a ``command {module: agent}`` names.
AGENT_VERBS = (
    VERB_REBOOT,
    VERB_SHUTDOWN,
    VERB_REINSTALL,
    VERB_RESIZE,
    VERB_KILL,
    VERB_REMOTE_DESKTOP_READ,
    VERB_REMOTE_DESKTOP_PASSWORD_SET,
)
# The verbs the platform's power action carries out, by its own word.
POWER_VERBS = {VERB_REBOOT: "reboot", VERB_SHUTDOWN: "poweroff"}
# How often a signalled process is looked in on while its grace runs.
KILL_POLL_S = 0.05


@dataclass
class CommandOutcome:
    """Result of running one command.

    Attributes:
        exit_code: The command's exit status; 0 means success.
        output: Combined output, truncated to a size the hub will accept.
        code: Why it failed, typed; empty on success.
        params: What the wording names.
        result: What a reading command answers with, structured; empty
            for a command that only acts.
    """

    exit_code: int
    output: str
    code: str = ""
    params: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Whether the command succeeded."""
        return self.exit_code == 0


def _refused(code: str, **params) -> CommandOutcome:
    return CommandOutcome(exit_code=1, output="", code=code, params=params)


class DeviceOperator:
    """Runs the commands the hub opens on this device."""

    def __init__(
        self,
        *,
        platform,
        reinstall=None,
        resize=None,
        module_runners=None,
        remote_desktop=None,
        settle=None,
        on_module_changed=None,
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            reinstall: Called for the ``reinstall`` verb; returns empty
                when the install was launched, ``{"code", "params"}`` when
                not. None refuses the verb as unsupported.
            resize: Called with ``(stream_id, cols, rows)`` for the
                ``resize`` verb; returns True when a shell stream of that
                id took the size. None refuses the verb as unsupported.
            module_runners: Module name to its runner, for the verbs a
                module answers. None refuses every module verb.
            remote_desktop: The reader the remote desktop verbs run on.
                None reads this machine through the platform.
            settle: Called with a timeout before a module verb runs, to
                let a pending desired state apply first; None waits for
                nothing.
            on_module_changed: Called with the module name after one of its
                verbs succeeded, so its details are read again at once.
        """
        self._platform = platform
        self._reinstall = reinstall
        self._resize = resize
        self._module_runners = dict(module_runners or {})
        self._remote_desktop = remote_desktop or RemoteDesktopReader(platform=platform)
        self._settle = settle
        self._on_module_changed = on_module_changed

    def run(self, module: str, verb: str, args: dict, on_line=None) -> CommandOutcome:
        """Run one command.

        Args:
            module: ``agent``, or the module whose verb it is.
            verb: The verb, without the module's name.
            args: The verb's own arguments.
            on_line: Called with each output line a module verb produces.

        Returns:
            The outcome; an unknown module or verb is a typed refusal
            rather than an exception, so the hub always gets a close.
        """
        if module == AGENT_COMMAND_MODULE:
            return self._agent_verb(verb, args)
        runner = self._module_runners.get(module)
        if runner is None:
            return _refused("verb_unknown", module=module, verb=verb)
        return self._module_verb(module, runner, verb, args, on_line)

    def _agent_verb(self, verb: str, args: dict) -> CommandOutcome:
        if verb in POWER_VERBS:
            return self._power(POWER_VERBS[verb])
        if verb == VERB_REINSTALL:
            return self._reinstall_agent()
        if verb == VERB_RESIZE:
            return self._resize_shell(args)
        if verb == VERB_KILL:
            return self._kill_process(args)
        if verb in (VERB_REMOTE_DESKTOP_READ, VERB_REMOTE_DESKTOP_PASSWORD_SET):
            return self._remote_desktop_verb(verb, args)
        return _refused("verb_unknown", module=AGENT_COMMAND_MODULE, verb=verb)

    def _module_verb(
        self, module: str, runner, verb: str, args: dict, on_line
    ) -> CommandOutcome:
        is_reading = verb == AGENT_MODULE_VERB_VALIDATE
        if (
            not is_reading
            and self._settle is not None
            and not self._settle(AGENT_MODULE_COMMAND_SETTLE_S)
        ):
            return _refused("state_not_settled", module=module)
        try:
            outcome = runner.command(verb, dict(args), on_line)
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return _refused("agent_internal", error=type(error).__name__)
        exit_code = int(outcome.get("exit_code", 1))
        if exit_code == 0 and not is_reading and self._on_module_changed:
            self._on_module_changed(module)
        return CommandOutcome(
            exit_code=exit_code,
            output=str(outcome.get("output", "") or "")[-AGENT_OUTPUT_LIMIT_BYTES:],
            code=str(outcome.get("code", "") or ""),
            params=dict(outcome.get("params") or {}),
        )

    def _reinstall_agent(self) -> CommandOutcome:
        if self._reinstall is None:
            return _refused("unsupported_platform")
        refusal = self._reinstall()
        if refusal:
            return CommandOutcome(
                exit_code=1,
                output="",
                code=str(refusal.get("code", "")),
                params=dict(refusal.get("params") or {}),
            )
        return CommandOutcome(exit_code=0, output="reinstall launched\n")

    def _resize_shell(self, args: dict) -> CommandOutcome:
        """Give one shell stream a new window size."""
        stream_id = args.get("shell")
        if self._resize is None:
            return _refused("unsupported_platform")
        try:
            cols = int(args.get("cols", 0) or 0)
            rows = int(args.get("rows", 0) or 0)
        except (TypeError, ValueError):
            cols = rows = 0
        if (
            not isinstance(stream_id, int)
            or cols <= 0
            or rows <= 0
            or not self._resize(stream_id, cols, rows)
        ):
            return _refused("shell_unknown", shell=stream_id)
        return CommandOutcome(exit_code=0, output="")

    def _kill_process(self, args: dict) -> CommandOutcome:
        """End one process: a term, then a kill once its grace has run."""
        try:
            pid = int(args.get("pid", 0))
        except (TypeError, ValueError):
            pid = 0
        if pid <= 1 or pid == os.getpid():
            return _refused("kill_failed", pid=pid)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return _refused("process_missing", pid=pid)
        except OSError as error:
            return _refused("kill_failed", pid=pid, detail=str(error)[:200])
        deadline = time.monotonic() + AGENT_KILL_GRACE_S
        while time.monotonic() < deadline:
            if not _is_alive(pid):
                return CommandOutcome(exit_code=0, output=f"terminated {pid}\n")
            time.sleep(KILL_POLL_S)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return CommandOutcome(exit_code=0, output=f"terminated {pid}\n")
        except OSError as error:
            return _refused("kill_failed", pid=pid, detail=str(error)[:200])
        return CommandOutcome(exit_code=0, output=f"killed {pid}\n")

    def _remote_desktop_verb(self, verb: str, args: dict) -> CommandOutcome:
        product = str(args.get("product", ""))
        if product not in SUPPORTED_PRODUCTS:
            return _refused("product_unknown", product=product)
        try:
            if verb == VERB_REMOTE_DESKTOP_READ:
                status = self._remote_desktop.status(product)
                return CommandOutcome(exit_code=0, output="", result=status)
            outcome = self._remote_desktop.set_password(
                product, str(args.get("password", ""))
            )
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return _refused("agent_internal", error=type(error).__name__)
        return CommandOutcome(
            exit_code=int(outcome.get("exit_code", 1)),
            output=str(outcome.get("output", "") or "")[-AGENT_OUTPUT_LIMIT_BYTES:],
            code=str(outcome.get("code", "") or ""),
            params=dict(outcome.get("params") or {}),
        )

    def _power(self, action: str) -> CommandOutcome:
        try:
            exit_code, output = self._platform.power(action)
        except PlatformUnsupportedError as error:
            return CommandOutcome(exit_code=1, output=f"{error.code}\n")
        except subprocess.TimeoutExpired:
            return CommandOutcome(
                exit_code=124, output=f"timed out after {AGENT_COMMAND_TIMEOUT_S}s\n"
            )
        except OSError as error:
            return CommandOutcome(exit_code=1, output=f"{error}\n")
        return CommandOutcome(
            exit_code=exit_code, output=output[-AGENT_OUTPUT_LIMIT_BYTES:]
        )


def _is_alive(pid: int) -> bool:
    """Whether a process still exists; a zombie counts until it is reaped."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            state = handle.read().rsplit(") ", 1)[1].split()[0]
    except (OSError, IndexError):
        return True
    return state != "Z"
