"""Installing and uninstalling the platform's own SSH server.

One pair of verbs, mechanics each platform's own: Linux installs the server
package and starts its unit, and uninstall genuinely removes the package;
Windows adds and removes the capability; macOS switches Remote Login, since
its sealed system volume lets nothing be removed. The row reads installed
while the server is serving. Uninstalling is allowed: the agent channel is
the management path, not SSH.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.modules.base import ModuleRunner


class OpensshModuleRunner(ModuleRunner):
    """Puts the platform's SSH server in service and takes it out."""

    kind = "openssh"

    def verify(self, resolved: dict) -> bool:
        """Whether the SSH server is serving.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when the platform reports it on.
        """
        return self._platform.read_openssh_status(resolved.get("entry") or {})

    def install(self, resolved: dict) -> None:
        """Have the SSH server in place and serving.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the platform's own step refuses.
            PlatformUnsupportedError: If this platform has no SSH story.
        """
        self._log("installing the SSH server")
        self._platform.install_openssh(resolved.get("entry") or {})

    def uninstall(self, resolved: dict) -> None:
        """Take the SSH server out of service.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the platform's own step refuses.
            PlatformUnsupportedError: If this platform has no SSH story.
        """
        self._log("uninstalling the SSH server")
        self._platform.uninstall_openssh(resolved.get("entry") or {})
