"""Installing system packages, whatever the distribution calls its tool.

Modules name what they need in their own ``constants.py``, keyed by
distribution family; this turns those names into installed software. The
operations here are the ones every family has — refresh, install, remove, ask
what is installed and what version is on offer. Anything a single family needs
and the others have no analogue for, such as enabling a repository, stays with
the module that needs it.

Not pure: runs the machine's package manager.
"""

from neutrino_hub.system.constants import SYSTEM_PACKAGE_NAMES
from neutrino_hub.system.machine import distribution_family, distribution_name
from neutrino_hub.system.sandbox import outside_sandbox
from neutrino_hub.utils.subprocess_run import CommandError, run

# Package managers are slow on a cold cache and this is not the place to find
# out. Long enough for a mirror to be reached and a kernel module to be built.
PACKAGE_REFRESH_TIMEOUT_S = 300
PACKAGE_INSTALL_TIMEOUT_S = 900
PACKAGE_REMOVE_TIMEOUT_S = 600


class SystemPackageController:
    """What the hub needs from a machine's package manager.

    One subclass per distribution family. :func:`current` picks the one this
    machine runs; nothing else instantiates them.
    """

    #: The distribution family this serves, as `machine.distribution_family`
    #: reports it.
    family = ""

    #: The executable, so a missing tool is reported by name.
    binary = ""

    #: What follows the executable to install. Printed rather than run when
    #: something the hub needs is missing: installing NetworkManager under a
    #: hub that is already running is what design/install.md exists to
    #: prevent, so the person is told and decides when.
    install_arguments = ("install",)

    def install_command(self, packages: tuple) -> str:
        """The command a person would run to install these by hand.

        Args:
            packages: Package names for this family.

        Returns:
            One line, ready to paste.
        """
        return " ".join(("sudo", self.binary, *self.install_arguments, *packages))

    def refresh(self) -> None:
        """Update the package lists.

        A stale list is not an error, so this never raises: the install that
        follows reports the real problem, and it reports it about a package
        rather than about a mirror.
        """
        raise NotImplementedError

    def install(self, packages: tuple) -> None:
        """Install packages, doing nothing for those already present.

        Args:
            packages: Package names for this family.

        Raises:
            CommandError: If the package manager refuses.
        """
        raise NotImplementedError

    def remove(self, packages: tuple, *, is_purged: bool = False) -> None:
        """Remove packages, ignoring those that are not installed.

        Args:
            packages: Package names for this family.
            is_purged: Also delete the configuration the packages own, where
                the family distinguishes the two. Families that do not treat
                this as a separate operation ignore it.
        """
        raise NotImplementedError

    def is_installed(self, package: str) -> bool:
        """Whether one package is installed.

        Args:
            package: The package name.

        Returns:
            True when the package manager reports it present.
        """
        raise NotImplementedError

    def available_version(self, package: str) -> str:
        """The version an install would get, as the distribution writes it.

        Args:
            package: The package name.

        Returns:
            Something like ``4.3.1+ds1-8+deb12u1``, or empty when the
            distribution offers no such package.
        """
        raise NotImplementedError


class AptPackageController(SystemPackageController):
    """Debian, Ubuntu and their derivatives."""

    family = "debian"
    binary = "apt-get"

    # apt asks questions when it thinks a terminal is watching, and the panel
    # is not one.
    _ENVIRONMENT = ("env", "DEBIAN_FRONTEND=noninteractive")

    def refresh(self) -> None:
        run(
            outside_sandbox([*self._ENVIRONMENT, "apt-get", "update"]),
            timeout_s=PACKAGE_REFRESH_TIMEOUT_S,
            is_checked=False,
        )

    def install(self, packages: tuple) -> None:
        run(
            outside_sandbox(
                [
                    *self._ENVIRONMENT,
                    "apt-get",
                    "install",
                    "-y",
                    "--no-install-recommends",
                    *packages,
                ]
            ),
            timeout_s=PACKAGE_INSTALL_TIMEOUT_S,
        )

    def remove(self, packages: tuple, *, is_purged: bool = False) -> None:
        action = ["remove", "--purge"] if is_purged else ["remove"]
        run(
            outside_sandbox([*self._ENVIRONMENT, "apt-get", *action, "-y", *packages]),
            timeout_s=PACKAGE_REMOVE_TIMEOUT_S,
            is_checked=False,
        )

    def is_installed(self, package: str) -> bool:
        return run(["dpkg", "-s", package], is_checked=False).is_success

    def available_version(self, package: str) -> str:
        result = run(["apt-cache", "policy", package], is_checked=False)
        for line in result.stdout.splitlines():
            if "Candidate:" in line:
                candidate = line.split("Candidate:", 1)[1].strip()
                return "" if candidate == "(none)" else candidate
        return ""


class DnfPackageController(SystemPackageController):
    """Fedora, RHEL and their rebuilds."""

    family = "rhel"
    binary = "dnf"

    def refresh(self) -> None:
        run(
            outside_sandbox(["dnf", "-y", "makecache"]),
            timeout_s=PACKAGE_REFRESH_TIMEOUT_S,
            is_checked=False,
        )

    def install(self, packages: tuple) -> None:
        run(
            outside_sandbox(
                ["dnf", "-y", "--setopt=install_weak_deps=False", "install", *packages]
            ),
            timeout_s=PACKAGE_INSTALL_TIMEOUT_S,
        )

    def remove(self, packages: tuple, *, is_purged: bool = False) -> None:
        # dnf has no purge: removing a package leaves its configuration as
        # .rpmsave either way.
        del is_purged
        run(
            outside_sandbox(["dnf", "-y", "remove", *packages]),
            timeout_s=PACKAGE_REMOVE_TIMEOUT_S,
            is_checked=False,
        )

    def is_installed(self, package: str) -> bool:
        return run(["rpm", "-q", package], is_checked=False).is_success

    def available_version(self, package: str) -> str:
        # --available belongs to repoquery, not to dnf, and dnf accepts an
        # unknown global option by ignoring the query it was meant to narrow.
        # --latest-limit 1 because a package present in two repositories is
        # answered twice, and the format string ends in a newline because
        # without one the two answers arrive concatenated.
        result = run(
            [
                "dnf",
                "-q",
                "repoquery",
                "--available",
                "--latest-limit",
                "1",
                "--qf",
                "%{version}\n",
                package,
            ],
            is_checked=False,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return lines[0] if lines else ""


class PacmanPackageController(SystemPackageController):
    """Arch and its derivatives."""

    family = "arch"
    binary = "pacman"
    install_arguments = ("-S", "--needed")

    def refresh(self) -> None:
        run(
            outside_sandbox(["pacman", "-Sy", "--noconfirm"]),
            timeout_s=PACKAGE_REFRESH_TIMEOUT_S,
            is_checked=False,
        )

    def install(self, packages: tuple) -> None:
        run(
            outside_sandbox(["pacman", "-S", "--needed", "--noconfirm", *packages]),
            timeout_s=PACKAGE_INSTALL_TIMEOUT_S,
        )

    def remove(self, packages: tuple, *, is_purged: bool = False) -> None:
        # -Rns removes the packages, their unused dependencies and the system
        # configuration they own; pacman does not separate the two.
        del is_purged
        run(
            outside_sandbox(["pacman", "-Rns", "--noconfirm", *packages]),
            timeout_s=PACKAGE_REMOVE_TIMEOUT_S,
            is_checked=False,
        )

    def is_installed(self, package: str) -> bool:
        return run(["pacman", "-Q", package], is_checked=False).is_success

    def available_version(self, package: str) -> str:
        result = run(["pacman", "-Si", package], is_checked=False)
        for line in result.stdout.splitlines():
            if line.startswith("Version"):
                return line.split(":", 1)[1].strip()
        return ""


CONTROLLERS = (AptPackageController, DnfPackageController, PacmanPackageController)


def current() -> SystemPackageController:
    """The package controller for the machine this runs on.

    Returns:
        The controller whose family matches ``/etc/os-release``.

    Raises:
        CommandError: On a distribution with no controller, naming what was
            found so the report says more than "unsupported".
    """
    family = distribution_family()
    for controller in CONTROLLERS:
        if controller.family == family:
            return controller()
    raise CommandError(
        f"no package manager is known for {distribution_name()}; "
        f"the hub installs on: {', '.join(c.family for c in CONTROLLERS)}"
    )


def is_version_at_least(found: str, minimum: str) -> bool:
    """Whether a package version meets a module's floor.

    Distributions decorate versions heavily — ``4.3.1+ds1-8+deb12u1+b3``,
    ``2:4.24.6-1``, ``1:6.15``. Only the leading dotted numbers decide, which
    is the part upstream chose and the part a floor is written against.

    Args:
        found: The version the package manager reports.
        minimum: The floor, as a plain dotted version.

    Returns:
        True when ``found`` is at least ``minimum``, and False when ``found``
        carries no numbers to compare.
    """
    left, right = _numeric_parts(found), _numeric_parts(minimum)
    if not left:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) >= right + (0,) * (width - len(right))


def _numeric_parts(version: str) -> tuple:
    """The leading dotted integers of a distribution's version string.

    Args:
        version: Anything the package manager printed.

    Returns:
        For ``2:4.24.6-1`` the tuple ``(4, 24, 6)``; empty when there are no
        numbers to read.
    """
    text = version.split(":")[-1]
    parts = []
    for piece in text.split("."):
        digits = ""
        for character in piece:
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        parts.append(int(digits))
        if digits != piece:
            # The upstream version ends where the distribution's own
            # decoration starts.
            break
    return tuple(parts)


def packages_for(family: str, packages: tuple) -> list:
    """One list of package names, spelled the way a family spells them.

    The hub's dependency lists are written once, in ``constants.py``; this is
    where they meet a distribution. Both the packaging build and a checkout's
    ``nhub setup`` read them through here, so a package's dependency field and
    what an installer would fetch cannot say different things.

    Args:
        family: The distribution family, as `machine.distribution_family`
            reports it.
        packages: Names as ``constants.py`` writes them.

    Returns:
        The names to install, with anything this family has no separate
        package for left out.
    """
    renames = SYSTEM_PACKAGE_NAMES.get(family, {})
    named = []
    for package in packages:
        renamed = renames.get(package, package)
        if renamed is not None:
            named.append(renamed)
    return named
