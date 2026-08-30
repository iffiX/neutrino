"""Installing and removing the ZFS tools.

What the package manager adds here is the userland (``zpool``/``zfs``), the
event daemon, and smartmontools for the disk health column. Pools are never
touched in either direction: they live on their member disks, and removing the
tools merely makes them unreachable until the tools return.

No distribution ships ZFS in its default repositories except Ubuntu — the CDDL
does not sit beside a GPL kernel — so this adds the repository the
distribution keeps it in before installing. Somebody asked for ZFS by clicking
install; being asked again about a repository would be asking the same
question twice.

Not pure: edits repository configuration and installs packages.
"""

import shutil
from pathlib import Path
from typing import Callable

from neutrino_hub.system import package_manager
from neutrino_hub.system.constants import (
    SYSTEM_CONSENT_KERNEL_MODULE_BUILD,
    SYSTEM_CONSENT_THIRD_PARTY_REPOSITORY,
)
from neutrino_hub.system.machine import distribution_family, require_distribution
from neutrino_hub.system.provisioning import (
    ProvisionConsent,
    ProvisionNotConsented,
    ProvisionPlan,
    ProvisionResult,
    say,
)
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.zfs.constants import (
    ZFS_ARC_MAX_FRACTION,
    ZFS_ARC_MAX_PARAMETER,
    ZFS_ARCH_KEY,
    ZFS_ARCH_REPOSITORY,
    ZFS_ARCH_SERVER,
    ZFS_CONTRIB_COMPONENT,
    ZFS_MODPROBE_CONF,
    ZFS_DKMS_FAMILIES,
    ZFS_MODULE_NAME,
    ZFS_MODULE_PACKAGES,
    ZFS_PACKAGES,
    ZFS_RHEL_RELEASE_URL,
)

MEMINFO_PATH = Path("/proc/meminfo")

APT_SOURCES_LIST = Path("/etc/apt/sources.list")
APT_SOURCES_DIR = Path("/etc/apt/sources.list.d")
PACMAN_CONF = Path("/etc/pacman.conf")


class ZfsProvisioner:
    """Installs the ZFS userland and takes it away again."""

    def plan(self) -> ProvisionPlan:
        """What installing ZFS on this machine would do.

        Returns:
            A plan naming the third-party repository this distribution keeps
            ZFS in, and the kernel module build when the module is not
            already there and no prebuilt one exists.
        """
        if shutil.which("zpool"):
            return ProvisionPlan()

        family = distribution_family()
        consents = []
        if family in ("rhel", "arch"):
            consents.append(
                ProvisionConsent(
                    code=SYSTEM_CONSENT_THIRD_PARTY_REPOSITORY,
                    detail={
                        "repository": (
                            ZFS_RHEL_RELEASE_URL
                            if family == "rhel"
                            else ZFS_ARCH_REPOSITORY
                        ),
                        "reason": "zfs_license",
                    },
                )
            )
        if _is_module_build_needed(family):
            consents.append(
                ProvisionConsent(
                    code=SYSTEM_CONSENT_KERNEL_MODULE_BUILD,
                    detail={
                        "packages": list(ZFS_MODULE_PACKAGES.get(family, ())),
                        "kernel": _running_kernel(),
                    },
                )
            )
        return ProvisionPlan(consents=tuple(consents))

    def provision(
        self, *, is_consented: bool = False, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Install the tools and cap the ARC.

        Args:
            is_consented: Whether the person agreed to everything
                :meth:`plan` listed. An install that needs agreement and does
                not have it does nothing.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            ProvisionNotConsented: If the plan needs agreement and has none.
            CommandError: If the package manager fails, which on the families
                that build a kernel module includes the build failing.
            RuntimeError: If this distribution has no ZFS packages named.
        """
        if shutil.which("zpool"):
            self._cap_arc(report)
            return ProvisionResult(is_changed=False, message="already installed")

        if self.plan().is_consent_needed and not is_consented:
            raise ProvisionNotConsented(
                "installing ZFS here needs agreement that has not been given"
            )

        family = distribution_family()
        packages = require_distribution(ZFS_PACKAGES, "ZFS")
        controller = package_manager.current()
        controller.refresh()
        if not controller.available_version(packages[0]):
            _add_repository(report)
            controller.refresh()

        module_packages = ZFS_MODULE_PACKAGES.get(family, ())
        if module_packages and not _is_module_available():
            say(report, f"installing the kernel module: {', '.join(module_packages)}")
            controller.install(module_packages)

        say(report, f"installing {', '.join(packages)}")
        controller.install(packages)
        self._cap_arc(report)
        return ProvisionResult(is_changed=True, message="installed")

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Remove the tools. Pools stay on their disks, whatever was asked.

        ``is_data_kept`` is accepted for the uniform contract and ignored:
        destroying a pool is its own deliberate act in the ZFS page, never a
        side effect of uninstalling software.

        Args:
            is_data_kept: Ignored; the data is on the disks either way.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.
        """
        if not shutil.which("zpool"):
            return ProvisionResult(is_changed=False, message="not installed")
        say(report, "removing the ZFS tools; pools stay intact on their disks")
        packages = ZFS_PACKAGES.get(distribution_family(), ())
        package_manager.current().remove(packages)
        ZFS_MODPROBE_CONF.unlink(missing_ok=True)
        return ProvisionResult(
            is_changed=True, message="removed; pools remain on their disks"
        )

    def _cap_arc(self, report: Callable[[str], None] | None) -> None:
        """Hold the ARC to a quarter of memory instead of its default half.

        The gateway runs services beside storage; a cache that takes half the
        machine forces them to fight for the rest. Written for the next boot
        and poked into the live module for this one.
        """
        arc_max = int(_total_memory_bytes() * ZFS_ARC_MAX_FRACTION)
        if arc_max <= 0:
            return
        wanted = (
            "# Generated by neutrino. Do not edit; the ZFS module owns it.\n"
            "# The ARC keeps to a quarter of memory: this box runs a gateway\n"
            "# first and a file server second.\n"
            f"options zfs zfs_arc_max={arc_max}\n"
        )
        if (
            not ZFS_MODPROBE_CONF.is_file()
            or ZFS_MODPROBE_CONF.read_text(encoding="utf-8") != wanted
        ):
            ZFS_MODPROBE_CONF.write_text(wanted, encoding="utf-8")
            say(report, f"capped the ARC at {arc_max // (1024 * 1024)} MiB")
        if ZFS_ARC_MAX_PARAMETER.is_file():
            try:
                ZFS_ARC_MAX_PARAMETER.write_text(str(arc_max), encoding="utf-8")
            except OSError:
                pass


def _total_memory_bytes() -> int:
    try:
        for line in MEMINFO_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _add_repository(report: Callable[[str], None] | None) -> None:
    """Add the repository this distribution keeps ZFS in.

    Args:
        report: Sink for progress lines, if anyone is watching.

    Raises:
        CommandError: If the repository cannot be added.
    """
    family = distribution_family()
    if family == "debian":
        say(report, "enabling the contrib component, where Debian keeps ZFS")
        _enable_apt_component(ZFS_CONTRIB_COMPONENT)
    elif family == "rhel":
        say(report, "adding the OpenZFS repository")
        run(["dnf", "-y", "install", ZFS_RHEL_RELEASE_URL], timeout_s=300)
    elif family == "arch":
        say(report, "adding the archzfs repository")
        _add_pacman_repository()


def _enable_apt_component(component: str) -> None:
    """Add a component to every Debian repository already configured.

    Two formats are in the field: the one-line entries of ``sources.list`` and
    the deb822 stanzas Debian 12 writes into ``sources.list.d``. Both are
    edited in place, and a file that already names the component is left
    alone so this can run twice.

    Args:
        component: ``contrib``, or another component name.
    """
    for path in _apt_source_files():
        try:
            original = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = []
        for line in original.splitlines():
            lines.append(_line_with_component(line, component))
        rewritten = "\n".join(lines) + "\n"
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")


def _apt_source_files() -> list:
    """Every file apt reads repositories from.

    Returns:
        The paths that exist, ``sources.list`` first.
    """
    paths = [APT_SOURCES_LIST] if APT_SOURCES_LIST.is_file() else []
    if APT_SOURCES_DIR.is_dir():
        paths += sorted(APT_SOURCES_DIR.glob("*.list"))
        paths += sorted(APT_SOURCES_DIR.glob("*.sources"))
    return paths


def _line_with_component(line: str, component: str) -> str:
    """One repository line with the component added, if it belongs there.

    Args:
        line: A line of a sources file, either format.
        component: The component to add.

    Returns:
        The line, extended when it lists components and does not already name
        this one.
    """
    stripped = line.strip()
    if stripped.startswith("Components:"):
        listed = stripped[len("Components:") :].split()
        if component in listed:
            return line
        return f"Components: {' '.join(listed + [component])}"
    if stripped.startswith(("deb ", "deb-src ")) and component not in stripped.split():
        return f"{line.rstrip()} {component}"
    return line


def _add_pacman_repository() -> None:
    """Trust the archzfs key and add its repository to pacman.conf.

    Raises:
        CommandError: If the key cannot be fetched or signed.
    """
    run(["pacman-key", "--recv-keys", ZFS_ARCH_KEY], timeout_s=300)
    run(["pacman-key", "--lsign-key", ZFS_ARCH_KEY], timeout_s=120)
    text = PACMAN_CONF.read_text(encoding="utf-8")
    if f"[{ZFS_ARCH_REPOSITORY}]" in text:
        return
    PACMAN_CONF.write_text(
        f"{text.rstrip()}\n\n[{ZFS_ARCH_REPOSITORY}]\nServer = {ZFS_ARCH_SERVER}\n",
        encoding="utf-8",
    )


def _is_module_build_needed(family: str) -> bool:
    """Whether installing here means compiling against the running kernel.

    Args:
        family: The distribution family.

    Returns:
        False when the module is already present — Ubuntu ships it with the
        kernel — and False when the family has no module package named,
        because then nothing here would start a build.
    """
    if _is_module_available():
        return False
    return family in ZFS_DKMS_FAMILIES


def _is_module_available() -> bool:
    """Whether the running kernel already has a ZFS module to load.

    Returns:
        True when modprobe can resolve it, loaded or not.
    """
    return run(["modinfo", "-n", ZFS_MODULE_NAME], is_checked=False).is_success


def _running_kernel() -> str:
    """The kernel a module would be built against.

    Returns:
        What ``uname -r`` reports, or empty when it cannot be read.
    """
    return run(["uname", "-r"], is_checked=False).stdout.strip()
