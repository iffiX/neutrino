"""Installing and removing the container engine.

Podman rather than Docker, deliberately: no root daemon, and every declared
container is an ordinary systemd unit through Quadlet — which is exactly the
shape of everything else on this box. The docker CLI habit keeps working
through the podman-docker shim.
"""

import shutil
from typing import Callable

from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.podman.constants import PODMAN_DATA_DIR, PODMAN_QUADLET_DIR
from neutrino_hub.modules.podman.renderer import GENERATED_MARKER

# podman-docker adds a `docker` alias over podman, so hands and scripts that
# speak docker keep working unchanged.
PODMAN_PACKAGES = ("podman", "podman-docker")


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
            CommandError: If apt fails.
        """
        if shutil.which("podman"):
            version = run(["podman", "--version"], is_checked=False).stdout.strip()
            return ProvisionResult(is_changed=False, message=version or "present")
        say(report, "installing podman and the docker command shim")
        run(["apt-get", "update"], timeout_s=300, is_checked=False)
        run(
            ["apt-get", "install", "-y", "--no-install-recommends", *PODMAN_PACKAGES],
            timeout_s=900,
        )
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
