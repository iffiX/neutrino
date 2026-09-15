"""One command the hub opens: a module, a verb, and the verb's arguments.

The open is ``command {module, verb, ...args}``; the command runs in the
stream's thread, each line it prints goes up as one binary frame, and the
close carries its exit status, its output and its result. A command that
was refused closes with its code, and ``verb_unknown`` names a verb, or a
module, this agent does not have.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.exceptions import StreamClosed

# The fields of the open that are not the verb's own arguments.
COMMAND_ENVELOPE_FIELDS = ("module", "verb")


class ModuleCommandStream:
    """One command, run to completion, closed with what it answered."""

    def __init__(self, channel, args: dict, *, run):
        """
        Args:
            channel: The stream's channel.
            args: ``{"module", "verb", ...}``, the rest being the verb's own.
            run: Called with ``(module, verb, args, on_line)``; returns
                ``{"exit_code", "code", "params", "output", "result"}``.
        """
        self._channel = channel
        self._module = str(args.get("module", "") or "")
        self._verb = str(args.get("verb", "") or "")
        self._args = {
            key: value
            for key, value in args.items()
            if key not in COMMAND_ENVELOPE_FIELDS
        }
        self._run = run

    def open(self) -> None:
        """Nothing to check: the command itself answers."""

    def run(self) -> dict:
        """Run the command, its lines going up as they come.

        Returns:
            ``{"code", "params"}``, the params ``{"exit_code", "output",
            "result"}`` beside what the code's wording names.
        """
        outcome = self._run(self._module, self._verb, self._args, self._send_line)
        params = dict(outcome.get("params") or {})
        params["exit_code"] = int(outcome.get("exit_code", 1))
        params["output"] = str(outcome.get("output", "") or "")
        result = outcome.get("result")
        params["result"] = dict(result) if isinstance(result, dict) else {}
        return {"code": str(outcome.get("code", "") or ""), "params": params}

    def _send_line(self, line: str) -> None:
        """One output line up the stream; a stream the hub closed takes none."""
        try:
            self._channel.send_line(line)
        except StreamClosed:
            return
