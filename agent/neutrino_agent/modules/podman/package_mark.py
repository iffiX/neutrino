"""The mark that the module installed the computer's Podman.

The install writes the mark, root-only, into the module's directory under
the state root right before Podman's package, msi or pkg goes to the
system's installer on a computer with no Podman. A Podman with no mark is
the person's: no installer runs over it, and an uninstall keeps it.

Not pure: reads and writes one file.
"""

import contextlib
import os

from neutrino_agent.modules.podman.constants import PODMAN_PACKAGE_MARK


class PodmanPackageMark:
    """The one file that says the module installed the computer's Podman."""

    def __init__(self, *, module_dir: str, join=os.path.join):
        """
        Args:
            module_dir: The module's directory under the state root.
            join: How the system joins a path.
        """
        self._module_dir = module_dir
        self._path = join(module_dir, PODMAN_PACKAGE_MARK)

    @property
    def path(self) -> str:
        """The mark's file."""
        return self._path

    def is_kept(self) -> bool:
        """Whether the mark stands.

        Returns:
            True while the file is there.
        """
        return os.path.isfile(self._path)

    def keep(self) -> None:
        """Write the mark, root-only.

        Raises:
            OSError: When the mark cannot be written.
        """
        os.makedirs(self._module_dir, mode=0o700, exist_ok=True)
        with open(self._path, "a", encoding="utf-8"):
            pass
        os.chmod(self._path, 0o600)

    def forget(self) -> None:
        """Delete the mark, when there is one."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._path)
