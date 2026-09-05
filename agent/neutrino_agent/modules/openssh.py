"""Reconciling the platform's own SSH server.

A platform capability the machine already carries, so its two states are
enabled and disabled — the server binary is a package dependency on Linux
and built into macOS and Windows, and nothing is ever downloaded or removed.
Disabling is allowed: the agent channel is the management path, not SSH.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.modules.base import ModuleReconciler, clean_status


class OpensshModuleReconciler(ModuleReconciler):
    """Switches the platform's SSH server on and off and reports its state."""

    kind = "openssh"

    def reconcile(
        self, *, name: str, manifest: dict, entry: dict, wanted: "dict | None"
    ) -> dict:
        """Bring the SSH server to its desired state, or just report it.

        Args:
            name: The module name.
            manifest: Its manifest.
            entry: The manifest's entry for this platform.
            wanted: The hub's decision, or None to only inspect.

        Returns:
            ``{"state", "code", "params", "is_active"}``.
        """
        is_enabled = None if wanted is None else bool(wanted.get("is_enabled"))
        is_running = self._platform.read_openssh_status(entry)
        if is_enabled is None or is_enabled == is_running:
            return clean_status("enabled" if is_running else "disabled")
        if is_enabled:
            self._log("enabling the SSH server")
            self._platform.enable_openssh(entry)
            return clean_status("enabled")
        self._log("disabling the SSH server")
        self._platform.disable_openssh(entry)
        return clean_status("disabled")
