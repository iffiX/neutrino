"""Reconciling the platform's own SSH server.

Never switched off from here: taking SSH off a machine the hub reaches over
SSH is a door locked from the inside.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.functions.base import FunctionReconciler, clean_status


class OpensshFunctionReconciler(FunctionReconciler):
    """Switches the platform's SSH server on and reports its state."""

    kind = "openssh"

    def reconcile(
        self, *, name: str, manifest: dict, entry: dict, wanted: "dict | None"
    ) -> dict:
        """Switch the SSH server on when asked, or just report it.

        Args:
            name: The function name.
            manifest: Its manifest.
            entry: The manifest's entry for this platform.
            wanted: The hub's decision, or None to only inspect.

        Returns:
            ``{"state", "code", "params", "is_active"}``.
        """
        is_enabled = None if wanted is None else bool(wanted.get("is_enabled"))
        is_running = self._platform.read_openssh_status(entry)
        if not is_enabled:
            return clean_status("installed" if is_running else "absent")
        if is_running:
            return clean_status("installed")
        self._log("enabling the SSH server")
        self._platform.enable_openssh(entry)
        return clean_status("installed")
