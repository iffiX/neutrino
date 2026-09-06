"""What a module runner is.

A module is machine software the hub administers — a remote desktop, the
SSH server. One runner owns one manifest kind: it carries out an order the
hub sent and reports what is true afterwards. It decides nothing — not when
to act, not whether to try again — because the hub is the only thing that
holds policy and the only thing with the memory to hold it in.

Every status a runner's caller returns is typed:
``{"state", "code", "params"}`` — a code and its parameters, never an
English sentence, so every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


def _ignore_status(name: str, status: dict) -> None:
    """Swallow a transient status when nobody is watching."""


class ModuleRunner:
    """Carries out orders for one kind of module on this machine."""

    kind = ""

    def __init__(self, *, platform, log=print, publish=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states —
                installing, uninstalling — so a watcher sees a step start
                rather than only its result. None publishes nothing.
        """
        self._platform = platform
        self._log = log
        self._publish = publish if publish is not None else _ignore_status
