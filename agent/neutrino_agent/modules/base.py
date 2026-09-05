"""What a module reconciler is.

A module is machine software the hub administers — a remote desktop, the
SSH server. One reconciler owns one manifest kind, and the engine hands each
catalog entry to the reconciler for its kind. A reconciler never applies a
local wish on its own: what it receives as ``wanted`` already came back from
the hub as desired state.

Every status a reconciler returns is typed:
``{"state", "code", "params", "is_active"}`` — a code and its parameters,
never an English sentence, so every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


def clean_status(state: str, *, is_active: bool = False) -> dict:
    """A status with nothing further to say.

    Args:
        state: The state word.
        is_active: Whether the module points at the hub.

    Returns:
        The typed status.
    """
    return {"state": state, "code": "", "params": {}, "is_active": is_active}


def _ignore_status(name: str, status: dict) -> None:
    """Swallow a transient status when nobody is watching."""


class ModuleReconciler:
    """Brings one kind of module to its desired state on this machine."""

    kind = ""

    def __init__(self, *, platform, log=print, publish=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states —
                installing, removing — so a watcher sees a step start rather
                than only its result. None publishes nothing.
        """
        self._platform = platform
        self._log = log
        self._publish = publish if publish is not None else _ignore_status

    def reconcile(
        self, *, name: str, manifest: dict, entry: dict, wanted: "dict | None"
    ) -> dict:
        """Bring one module to its desired state, or just report it.

        Args:
            name: The module name.
            manifest: Its manifest.
            entry: The manifest's entry for this platform.
            wanted: What the hub decided — ``is_enabled`` plus whatever
                ``config`` it resolved. None when nothing has been asked, in
                which case the module is inspected and never touched.

        Returns:
            ``{"state", "code", "params", "is_active"}``.
        """
        raise NotImplementedError
