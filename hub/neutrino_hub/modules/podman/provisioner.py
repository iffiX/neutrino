"""Installing and removing the container engine.

Podman rather than Docker, deliberately: no root daemon, and every declared
container is an ordinary systemd unit through Quadlet — which is exactly the
shape of everything else on this box. The docker CLI habit keeps working
through the podman-docker shim.
"""

import shutil
from typing import Callable

from neutrino_hub.system import package_manager
from neutrino_hub.system.machine import require_distribution
from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.podman.constants import (
    PODMAN_DATA_DIR,
    PODMAN_QUADLET_VERSION,
    PODMAN_PACKAGES,
    PODMAN_QUADLET_DIR,
)
from neutrino_hub.modules.podman.renderer import GENERATED_MARKER


class PodmanProvisioner:
    """Installs the podman engine and takes it away again."""

    def provision(
        self, *, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Install podman if it is missing.

        Args:
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            CommandError: If this distribution offers no podman new enough for
                Quadlet, or the package manager fails.
            RuntimeError: If this distribution has no podman packages named.
        """
        if shutil.which("podman"):
            version = run(["podman", "--version"], is_checked=False).stdout.strip()
            return ProvisionResult(is_changed=False, message=version or "present")

        packages = require_distribution(PODMAN_PACKAGES, "podman")
        controller = package_manager.current()
        controller.refresh()
        say(report, _require_podman(controller))

        say(report, "installing podman and the docker command shim")
        controller.install(packages)
        return ProvisionResult(is_changed=True, message="installed")

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Remove the engine, and — only when asked — images and volumes.

        Declared containers' Quadlet files go either way: they describe
        something that can no longer run. The declarations in config/ stay,
        so a reinstall brings every declared container back.

        Args:
            is_data_kept: Keep ``/var/lib/containers`` — images, container
                layers and named volumes. False deletes it all.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.
        """
        if not shutil.which("podman"):
            return ProvisionResult(is_changed=False, message="not installed")

        say(report, "stopping every container and the API socket")
        run(["podman", "stop", "--all"], is_checked=False, timeout_s=300)
        run(["systemctl", "disable", "--now", "podman.socket"], is_checked=False)
        for path in PODMAN_QUADLET_DIR.glob("*.container"):
            try:
                if path.read_text(encoding="utf-8").startswith(GENERATED_MARKER):
                    path.unlink()
            except OSError:
                continue
        run(["systemctl", "daemon-reload"], is_checked=False)

        say(report, "removing the engine")
        # The family's own packages through the family's own manager. The
        # names live in a dict keyed by family, so splatting it hands the
        # keys — `apt-get remove -y debian rhel arch` — which fails on every
        # distribution and leaves the engine installed with its containers
        # already stopped and its Quadlets already deleted.
        package_manager.current().remove(
            require_distribution(PODMAN_PACKAGES, "podman")
        )

        if not is_data_kept:
            say(report, "deleting every image and volume")
            shutil.rmtree(PODMAN_DATA_DIR, ignore_errors=True)
            return ProvisionResult(
                is_changed=True, message="removed, images and volumes deleted"
            )
        return ProvisionResult(
            is_changed=True, message="removed; images and volumes kept"
        )


def _require_podman(controller: package_manager.SystemPackageController) -> str:
    """Refuse only a distribution that offers no podman at all.

    It used to refuse anything below the Quadlet version, which read the
    module's own floor as podman's: `PodmanUnitRenderer` exists precisely for
    the older ones, and Debian 12 and Ubuntu 22.04 — where podman is 4.3.1 and
    3.4.4 — could not install it at all.

    Args:
        controller: The machine's package manager, already refreshed.

    Returns:
        Which unit style this version will be driven through, to say in the
        report: the two behave the same and are worth telling apart when a
        container misbehaves.

    Raises:
        CommandError: When the distribution has no podman to offer.
    """
    offered = controller.available_version("podman")
    if not offered:
        raise CommandError("this distribution offers no podman")
    if package_manager.is_version_at_least(offered, PODMAN_QUADLET_VERSION):
        return f"podman {offered}, driven through Quadlet"
    return (
        f"podman {offered}, driven through plain systemd units: Quadlet "
        f"arrives in {PODMAN_QUADLET_VERSION}"
    )
