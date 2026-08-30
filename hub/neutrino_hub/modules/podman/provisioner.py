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
    PODMAN_MINIMUM_VERSION,
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
        _require_quadlet(controller)

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
        run(
            ["apt-get", "remove", "-y", *PODMAN_PACKAGES],
            timeout_s=600,
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


def _require_quadlet(controller: package_manager.SystemPackageController) -> None:
    """Refuse a podman that cannot read a Quadlet file.

    Args:
        controller: The machine's package manager, already refreshed.

    Raises:
        CommandError: When the version on offer is below the floor, naming it
            so the report is about this distribution rather than about podman.
    """
    offered = controller.available_version("podman")
    if package_manager.is_version_at_least(offered, PODMAN_MINIMUM_VERSION):
        return
    raise CommandError(
        f"this distribution offers podman {offered or 'nothing'}; containers "
        f"need {PODMAN_MINIMUM_VERSION} or newer, which is where Quadlet "
        f"turns a declared container into a systemd unit"
    )
