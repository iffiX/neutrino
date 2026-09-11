"""Installing the NetBird client the package carries, with the hub's own unit.

NetBird is one of the overlays a hub can be reached through, and installing
it is what choosing it on the Overlay page does. The client is BSD-3-Clause
and travels inside the package, so installing it is putting a unit in front
of a binary that is already there; a checkout, which no package staged,
fetches the pinned release instead.

Joining a network stays a separate step: it needs a setup key, and which
management plane to trust is a decision the installer should not make
silently.
"""

import hashlib
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Callable

from neutrino_hub.modules.netbird.constants import (
    NETBIRD_ASSET_ARCHITECTURES,
    NETBIRD_BINARY_NAME,
    NETBIRD_BINARY_PATH,
    NETBIRD_DOWNLOAD_URL,
    NETBIRD_SHA256,
    NETBIRD_STATE_DIR,
    NETBIRD_SUPPORTED_ARCHITECTURES,
    NETBIRD_UNIT,
    NETBIRD_VENDOR_UNIT,
    NETBIRD_VERSION,
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
        The URL of the release tarball.

    Raises:
        KeyError: On a machine the vendor publishes no asset for.
    """
    return NETBIRD_DOWNLOAD_URL.format(
        version=NETBIRD_VERSION,
        asset_arch=NETBIRD_ASSET_ARCHITECTURES[architecture],
    )


class NetbirdProvisioner:
    """Installs the carried NetBird client as a unit of the hub's own."""

    def provision(
        self, *, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Put the client in place and run it under the hub's unit.

        Args:
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            RuntimeError: On a machine the vendor publishes no binary for.
            ValueError: If what the vendor served is not what is pinned.
            subprocess.CalledProcessError: If the download or any setup step
                fails.
        """
        require_architecture(NETBIRD_SUPPORTED_ARCHITECTURES, "netbird")
        is_changed = False
        if not NETBIRD_BINARY_PATH.is_file():
            architecture = machine_architecture()
            say(
                report,
                f"downloading NetBird {NETBIRD_VERSION} for "
                f"{architecture} (~15 MB)",
            )
            self._download_binary(architecture)
            is_changed = True
        # A development root runs the panel in the foreground instead of
        # installing the hub as a service; design/install_and_dev.md.
        if not is_dev_root_set():
            self._stand_vendor_down(report=report)
            if self._refresh_unit():
                say(report, "installed the systemd unit")
                is_changed = True
            run(["systemctl", "enable", "--now", NETBIRD_UNIT])
        return ProvisionResult(
            is_changed=is_changed,
            message=(
                f"netbird {NETBIRD_VERSION}" if is_changed else "already provisioned"
            ),
        )

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Stop the daemon and take the unit away; the binary stays.

        The panel never calls this — netbird is core, and removing the way
        back in is refused there — but the contract stays symmetric for the
        installer and for a hand at a local shell.

        The client itself is a file the hub's package installed and its
        package manager owns, so it is not this method's to delete.

        Args:
            is_data_kept: Keep ``/var/lib/netbird``, the machine's identity,
                so a reinstall rejoins as the same peer. False deletes it.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            subprocess.CalledProcessError: If systemd refuses to reload.
        """
        say(report, "leaving the network and stopping netbird")
        run([str(NETBIRD_BINARY_PATH), "down"], is_checked=False, timeout_s=30)
        run(["systemctl", "disable", "--now", NETBIRD_UNIT], is_checked=False)
        (SYSTEM_SYSTEMD_DIR / NETBIRD_UNIT).unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])

        if not is_data_kept:
            say(report, "deleting the peer identity")
            shutil.rmtree(NETBIRD_STATE_DIR, ignore_errors=True)
            return ProvisionResult(is_changed=True, message="removed, identity deleted")
        return ProvisionResult(is_changed=True, message="removed; identity kept")

    def _stand_vendor_down(self, *, report: Callable[[str], None] | None) -> None:
        """Stop and disable a NetBird the vendor's package installed.

        `netbird service install` generates that unit, and it drives the same
        state file and the same socket as the hub's own: two daemons on one
        machine overwrite each other's record of what to revert. The unit
        file and ``/var/lib/netbird`` are the vendor's and stay where they
        are.

        Args:
            report: Sink for progress lines, if anyone is watching.
        """
        if not (SYSTEM_SYSTEMD_DIR / NETBIRD_VENDOR_UNIT).is_file():
            return
        say(report, "stopping the vendor's netbird service")
        run(["systemctl", "disable", "--now", NETBIRD_VENDOR_UNIT], is_checked=False)

    def _refresh_unit(self) -> bool:
        """Install or update the systemd unit, telling whether it changed.

        Returns:
            Whether anything was written.

        Raises:
            subprocess.CalledProcessError: If systemd refuses to reload.
        """
        unit_text = (UTILS_DATA_DIR / "services" / NETBIRD_UNIT).read_text(
            encoding="utf-8"
        )
        unit_path = SYSTEM_SYSTEMD_DIR / NETBIRD_UNIT
        if unit_path.is_file() and unit_path.read_text(encoding="utf-8") == unit_text:
            return False
        unit_path.write_text(unit_text, encoding="utf-8")
        run(["systemctl", "daemon-reload"])
        return True

    def _download_binary(self, architecture: str) -> None:
        """Fetch the pinned release and install the client from it.

        Args:
            architecture: A normalized name from
                :mod:`neutrino_hub.system.machine`.

        Raises:
            ValueError: If what arrived is not what is pinned.
            subprocess.CalledProcessError: If the download fails.
        """
        with tempfile.TemporaryDirectory() as workdir:
            archive = Path(workdir) / "netbird.tar.gz"
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
            if digest != NETBIRD_SHA256[architecture]:
                raise ValueError(
                    f"netbird {NETBIRD_VERSION} for {architecture} hashes to "
                    f"{digest}, not the pinned {NETBIRD_SHA256[architecture]}"
                )
            with tarfile.open(archive) as bundle:
                # Only the client: the licences beside it in the release are
                # carried in the package's own licence directory.
                bundle.extract(NETBIRD_BINARY_NAME, workdir)
            NETBIRD_BINARY_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(Path(workdir) / NETBIRD_BINARY_NAME), NETBIRD_BINARY_PATH)
        NETBIRD_BINARY_PATH.chmod(0o755)
