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
from neutrino_hub.system.installation import venv_python
from neutrino_hub.system.units import SystemdUnitInstaller
from neutrino_hub.system.machine import machine_architecture, require_architecture
from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.constants import (
    UTILS_DATA_DIR,
    UTILS_GENERATED_DIR,
    is_dev_root_set,
)
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_ASSET_ARCHITECTURES,
    CLIPROXYAPI_AUTH_DIR,
    CLIPROXYAPI_BINARY_PATH,
    CLIPROXYAPI_DIR,
    CLIPROXYAPI_DOWNLOAD_URL,
    CLIPROXYAPI_GENERATED_NAME,
    CLIPROXYAPI_SUPPORTED_ARCHITECTURES,
    CLIPROXYAPI_UNIT,
    CLIPROXYAPI_VERSION,
)
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier


def download_url(architecture: str) -> str:
    """The vendor release download for one architecture.

    Args:
        architecture: A normalized name from :mod:`neutrino_hub.system.machine`.

    Returns:
        The URL of the release tarball.
    """
    return CLIPROXYAPI_DOWNLOAD_URL.format(
        version=CLIPROXYAPI_VERSION,
        asset_arch=CLIPROXYAPI_ASSET_ARCHITECTURES[architecture],
    )


class CliproxyApiProvisioner:
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
        applier = CliproxyApiConfigApplier()
        # Before the binary, and whether or not one has to be fetched: the
        # package carries the binary but nothing carries a directory the
        # gateway writes to, and the unit runs in it.
        if not CLIPROXYAPI_AUTH_DIR.is_dir():
            say(report, f"creating {CLIPROXYAPI_DIR}")
            CLIPROXYAPI_AUTH_DIR.mkdir(parents=True, exist_ok=True)
            CLIPROXYAPI_DIR.chmod(0o700)
            is_changed = True
        if not CLIPROXYAPI_BINARY_PATH.is_file():
            require_architecture(CLIPROXYAPI_SUPPORTED_ARCHITECTURES, "cliproxyapi")
            architecture = machine_architecture()
            say(
                report,
                f"downloading CLIProxyAPI {CLIPROXYAPI_VERSION} for "
                f"{architecture} (~20 MB)",
            )
            self._download_binary(architecture)
            is_changed = True
        if not is_dev_root_set():
            # Through the same renderer every other unit goes through: the
            # template names the interpreter as @PYTHON@, and a unit written
            # without substituting it fails at exec with that as the path.
            template = (UTILS_DATA_DIR / "services" / CLIPROXYAPI_UNIT).read_text(
                encoding="utf-8"
            )
            unit_text = SystemdUnitInstaller().render(template, str(venv_python()))
            if applier.refresh_unit(unit_text):
                say(report, "installed the systemd unit")
                is_changed = True
        say(report, "rendering the configuration")
        applier.apply()
        # A development root runs the panel in the foreground instead of
        # installing the hub as a service; design/install_and_dev.md.
        if not is_dev_root_set():
            run(["systemctl", "enable", "--now", CLIPROXYAPI_UNIT])
        return ProvisionResult(
            is_changed=is_changed,
            message=(
                f"cliproxyapi {CLIPROXYAPI_VERSION}"
                if is_changed
                else "already provisioned"
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
            is_data_kept: Keep ``/var/lib/neutrino/cliproxyapi`` — imported
                account logins live there. False deletes it.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.
        """
        if not CLIPROXYAPI_BINARY_PATH.is_file():
            return ProvisionResult(is_changed=False, message="not installed")

        say(report, "stopping and disabling the AI gateway")
        run(["systemctl", "disable", "--now", CLIPROXYAPI_UNIT], is_checked=False)
        (SYSTEM_SYSTEMD_DIR / CLIPROXYAPI_UNIT).unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])

        say(report, "removing the binary and the rendered configuration")
        CLIPROXYAPI_BINARY_PATH.unlink(missing_ok=True)
        (UTILS_GENERATED_DIR / CLIPROXYAPI_GENERATED_NAME).unlink(missing_ok=True)

        if not is_data_kept:
            say(report, "deleting imported account logins")
            shutil.rmtree(CLIPROXYAPI_DIR, ignore_errors=True)
            return ProvisionResult(is_changed=True, message="removed, data deleted")
        return ProvisionResult(is_changed=True, message="removed; logins kept")

    def _download_binary(self, architecture: str) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            archive = Path(workdir) / "cliproxyapi.tar.gz"
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
            shutil.move(str(Path(workdir) / "cli-proxy-api"), CLIPROXYAPI_BINARY_PATH)
        CLIPROXYAPI_BINARY_PATH.chmod(0o755)
