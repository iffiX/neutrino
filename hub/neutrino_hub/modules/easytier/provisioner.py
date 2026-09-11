"""Installing the EasyTier engine the package carries, with the hub's own unit.

EasyTier is one of the overlays a hub can be reached through, and installing
it is what choosing it on the Overlay page does. The engine is LGPL-3.0 and
travels inside the package as two unmodified binaries run as separate
processes, so installing is putting a unit in front of files that are already
there; a checkout, which no package staged, fetches the pinned release
instead.

Joining a network stays a separate step: a network is a name and a secret,
and both are the panel's to write.
"""

import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from neutrino_hub.modules.easytier.constants import (
    EASYTIER_ASSET_ARCHITECTURES,
    EASYTIER_CLI_NAME,
    EASYTIER_CLI_PATH,
    EASYTIER_CORE_NAME,
    EASYTIER_CORE_PATH,
    EASYTIER_DOWNLOAD_URL,
    EASYTIER_SHA256,
    EASYTIER_SUPPORTED_ARCHITECTURES,
    EASYTIER_UNIT,
    EASYTIER_VERSION,
)
from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.system.machine import machine_architecture, require_architecture
from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.constants import UTILS_DATA_DIR, is_dev_root_set
from neutrino_hub.utils.subprocess_run import run


def download_url(architecture: str) -> str:
    """The vendor release download for one architecture.

    Args:
        architecture: A normalized name from :mod:`neutrino_hub.system.machine`.

    Returns:
        The URL of the release archive.

    Raises:
        KeyError: On a machine the vendor publishes no asset for.
    """
    return EASYTIER_DOWNLOAD_URL.format(
        version=EASYTIER_VERSION,
        asset_arch=EASYTIER_ASSET_ARCHITECTURES[architecture],
    )


class EasyTierProvisioner:
    """Installs the carried EasyTier engine as a unit of the hub's own."""

    def provision(
        self, *, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Put the engine in place and run it under the hub's unit.

        Args:
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            RuntimeError: On a machine the vendor publishes no build for.
            ValueError: If what the vendor served is not what is pinned.
            subprocess.CalledProcessError: If the download or any setup step
                fails.
        """
        require_architecture(EASYTIER_SUPPORTED_ARCHITECTURES, "easytier")
        is_changed = False
        if not EASYTIER_CORE_PATH.is_file() or not EASYTIER_CLI_PATH.is_file():
            architecture = machine_architecture()
            say(
                report,
                f"downloading EasyTier {EASYTIER_VERSION} for "
                f"{architecture} (~25 MB)",
            )
            self._download_binaries(architecture)
            is_changed = True
        # A development root runs the panel in the foreground instead of
        # installing the hub as a service; design/install_and_dev.md.
        if not is_dev_root_set():
            if self._refresh_unit():
                say(report, "installed the systemd unit")
                is_changed = True
            # Enabled but not started: the engine has nothing to run on until
            # a network is written, and the panel's apply is what starts it.
            run(["systemctl", "enable", EASYTIER_UNIT])
        return ProvisionResult(
            is_changed=is_changed,
            message=(
                f"easytier {EASYTIER_VERSION}" if is_changed else "already provisioned"
            ),
        )

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Stop the engine and take the unit away; the binaries stay.

        The engine's files are what the hub's package installed and its
        package manager owns, so they are not this method's to delete. The
        network itself lives in ``config/``, which a deprovision never
        touches: the choice of overlay is the panel's, and coming back to
        EasyTier must not cost the network.

        Args:
            is_data_kept: Accepted for the shape every provisioner has;
                EasyTier keeps no state of its own on this box.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            subprocess.CalledProcessError: If systemd refuses to reload.
        """
        del is_data_kept
        say(report, "stopping easytier")
        run(["systemctl", "disable", "--now", EASYTIER_UNIT], is_checked=False)
        (SYSTEM_SYSTEMD_DIR / EASYTIER_UNIT).unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])
        return ProvisionResult(is_changed=True, message="removed; the network is kept")

    def _refresh_unit(self) -> bool:
        """Install or update the systemd unit, telling whether it changed.

        Returns:
            Whether anything was written.

        Raises:
            subprocess.CalledProcessError: If systemd refuses to reload.
        """
        unit_text = (UTILS_DATA_DIR / "services" / EASYTIER_UNIT).read_text(
            encoding="utf-8"
        )
        unit_path = SYSTEM_SYSTEMD_DIR / EASYTIER_UNIT
        if unit_path.is_file() and unit_path.read_text(encoding="utf-8") == unit_text:
            return False
        unit_path.write_text(unit_text, encoding="utf-8")
        run(["systemctl", "daemon-reload"])
        return True

    def _download_binaries(self, architecture: str) -> None:
        """Fetch the pinned release and install the two binaries from it.

        Args:
            architecture: A normalized name from
                :mod:`neutrino_hub.system.machine`.

        Raises:
            ValueError: If what arrived is not what is pinned.
            subprocess.CalledProcessError: If the download fails.
        """
        with tempfile.TemporaryDirectory() as workdir:
            archive = Path(workdir) / "easytier.zip"
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
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest != EASYTIER_SHA256[architecture]:
                raise ValueError(
                    f"easytier {EASYTIER_VERSION} for {architecture} hashes to "
                    f"{digest}, not the pinned {EASYTIER_SHA256[architecture]}"
                )
            with zipfile.ZipFile(archive) as bundle:
                for name, target in (
                    (EASYTIER_CORE_NAME, EASYTIER_CORE_PATH),
                    (EASYTIER_CLI_NAME, EASYTIER_CLI_PATH),
                ):
                    member = _member(bundle, name)
                    extracted = Path(bundle.extract(member, workdir))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(extracted), target)
                    target.chmod(0o755)


def _member(bundle: zipfile.ZipFile, name: str) -> str:
    """Where one binary sits inside the release archive.

    Args:
        bundle: The opened archive.
        name: The file to find.

    Returns:
        The member's name.

    Raises:
        ValueError: If the archive does not carry it.
    """
    for member in bundle.namelist():
        if member.rsplit("/", 1)[-1] == name:
            return member
    raise ValueError(f"the easytier release carries no {name}")
