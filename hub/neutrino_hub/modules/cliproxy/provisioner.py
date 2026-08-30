"""Installing CLIProxyAPI as a single released binary with a systemd unit.

The vendor publishes prebuilt tarballs per architecture; the binary is the
only thing inside worth keeping. Configuration is rendered by the panel, so
provisioning ends with an apply rather than a wizard.
"""

import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Callable

from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.system.machine import machine_architecture, require_architecture
from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.constants import UTILS_DATA_DIR, UTILS_GENERATED_DIR
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.cliproxy.constants import (
    CLIPROXY_ASSET_ARCHITECTURES,
    CLIPROXY_AUTH_DIR,
    CLIPROXY_BINARY_PATH,
    CLIPROXY_DIR,
    CLIPROXY_DOWNLOAD_URL,
    CLIPROXY_GENERATED_NAME,
    CLIPROXY_SUPPORTED_ARCHITECTURES,
    CLIPROXY_UNIT,
    CLIPROXY_VERSION,
)
from neutrino_hub.modules.cliproxy.ops import CliproxyConfigApplier


def download_url(architecture: str) -> str:
    """The vendor release download for one architecture.

    Args:
        architecture: A normalized name from :mod:`neutrino_hub.system.machine`.

    Returns:
        The URL of the release tarball.
    """
    return CLIPROXY_DOWNLOAD_URL.format(
        version=CLIPROXY_VERSION,
        asset_arch=CLIPROXY_ASSET_ARCHITECTURES[architecture],
    )


class CliproxyProvisioner:
    """Installs CLIProxyAPI as a single binary with a systemd unit."""

    def provision(
        self, *, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Install the binary, its directories, its unit, and apply config.

        Args:
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            RuntimeError: On a machine the vendor publishes no binary for.
            CommandError: If the download or any setup step fails.
        """
        is_changed = False
        applier = CliproxyConfigApplier()
        if not CLIPROXY_BINARY_PATH.is_file():
            require_architecture(CLIPROXY_SUPPORTED_ARCHITECTURES, "cliproxy")
            say(report, "creating /var/lib/neutrino_cliproxy")
            CLIPROXY_AUTH_DIR.mkdir(parents=True, exist_ok=True)
            CLIPROXY_DIR.chmod(0o700)
            architecture = machine_architecture()
            say(
                report,
                f"downloading CLIProxyAPI {CLIPROXY_VERSION} for "
                f"{architecture} (~20 MB)",
            )
            self._download_binary(architecture)
            is_changed = True
        unit_text = (UTILS_DATA_DIR / "services" / CLIPROXY_UNIT).read_text(
            encoding="utf-8"
        )
        if applier.refresh_unit(unit_text):
            say(report, "installed the systemd unit")
            is_changed = True
        say(report, "rendering the configuration")
        applier.apply()
        run(["systemctl", "enable", "--now", CLIPROXY_UNIT])
        return ProvisionResult(
            is_changed=is_changed,
            message=(
                f"cliproxy {CLIPROXY_VERSION}" if is_changed else "already provisioned"
            ),
        )

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Remove the software; the panel-side configuration always survives.

        Args:
            is_data_kept: Keep ``/var/lib/neutrino_cliproxy`` — imported
                account logins live there. False deletes it.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.
        """
        if not CLIPROXY_BINARY_PATH.is_file():
            return ProvisionResult(is_changed=False, message="not installed")

        say(report, "stopping and disabling the AI gateway")
        run(["systemctl", "disable", "--now", CLIPROXY_UNIT], is_checked=False)
        (SYSTEM_SYSTEMD_DIR / CLIPROXY_UNIT).unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])

        say(report, "removing the binary and the rendered configuration")
        CLIPROXY_BINARY_PATH.unlink(missing_ok=True)
        (UTILS_GENERATED_DIR / CLIPROXY_GENERATED_NAME).unlink(missing_ok=True)

        if not is_data_kept:
            say(report, "deleting imported account logins")
            shutil.rmtree(CLIPROXY_DIR, ignore_errors=True)
            return ProvisionResult(is_changed=True, message="removed, data deleted")
        return ProvisionResult(is_changed=True, message="removed; logins kept")

    def _download_binary(self, architecture: str) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            archive = Path(workdir) / "cliproxy.tar.gz"
            run(
                [
                    "curl",
                    "-fL",
                    "--retry",
                    "2",
                    "-o",
                    str(archive),
                    download_url(architecture),
                ],
                timeout_s=600,
            )
            with tarfile.open(archive) as tar:
                member = tar.getmember("cli-proxy-api")
                tar.extract(member, workdir)
            shutil.move(str(Path(workdir) / "cli-proxy-api"), CLIPROXY_BINARY_PATH)
        CLIPROXY_BINARY_PATH.chmod(0o755)
