"""Installing and uninstalling the packages of a ``system`` entry.

A ``system`` recipe names distro packages, never a download: its install
asks the hub for no bytes and the platform installs the names with its own
tooling, one operation at a time. A recipe may name ``pre_install`` shell
steps, run before the packages, for a repository the distribution keeps the
software in. Whether the software is there is the recipe's ``verify``; the
runner's own check, its binary on the path, answers only for a module the
state does not name, so software somebody installed by hand is observed.

Not pure: runs the package manager.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import shutil

from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.shared.package import params_of


def _recipe_packages(recipe: dict) -> list:
    """The package names a recipe installs."""
    return [str(name) for name in params_of(recipe).get("packages") or []]


def _recipe_steps(recipe: dict) -> list:
    """The shell steps a recipe runs before its packages."""
    return [str(step) for step in params_of(recipe).get("pre_install") or []]


def _removed_packages(recipe: dict) -> list:
    """The package names a recipe's uninstall removes."""
    removal = params_of(recipe).get("uninstall")
    if not isinstance(removal, dict):
        return []
    return [str(name) for name in removal.get("packages") or []]


class SystemPackageModuleRunner(ModuleRunner):
    """Installs named distro packages and removes them.

    Attributes:
        binary: The program that says the software is there for a module
            the state does not name; empty for a runner with none of its own.
    """

    binary = ""

    def verify(self, recipe: dict) -> bool:
        """Whether the runner's own program is on the path.

        Args:
            recipe: The module's recipe, empty for a module the state does
                not name.

        Returns:
            True when the binary is found.
        """
        return bool(self.binary) and shutil.which(self.binary) is not None

    def install(self, recipe: dict) -> None:
        """Run the recipe's steps, then install its packages with the machine's own tooling.

        Args:
            recipe: The module's recipe.

        Raises:
            InstallError: If a step or the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        for step in _recipe_steps(recipe):
            self._log(step)
            output = installers.run_shell(step)
            if output.strip():
                self._log(output.strip())
        output = self._platform.install_system_packages(_recipe_packages(recipe))
        if output.strip():
            self._log(output.strip())

    def uninstall(self, recipe: dict) -> None:
        """Take the packages the recipe's uninstall names off this machine.

        Args:
            recipe: The module's recipe.

        Raises:
            InstallError: If the uninstall refuses.
            PlatformUnsupportedError: If this platform removes nothing.
        """
        output = self._platform.remove_system_packages(_removed_packages(recipe))
        if output.strip():
            self._log(output.strip())
