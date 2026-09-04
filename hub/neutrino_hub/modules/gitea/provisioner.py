"""Installing Gitea as a single released binary with a systemd unit.

The Ubuntu archive does not ship Gitea at all, so the binary comes from the
vendor's release downloads. The unit is the packaged one from ``services/``;
everything it used to carry as environment overrides now lives in the
rendered ``app.ini``.
"""

import shutil
from pathlib import Path
from typing import Callable

from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.system.machine import (
    machine_architecture,
    require_architecture,
    require_distribution,
)
from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.constants import (
    UTILS_CONFIG_DIR,
    UTILS_DATA_DIR,
    UTILS_GENERATED_DIR,
)
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.system import package_manager
from neutrino_hub.modules.gitea.constants import (
    GITEA_BINARY_PATH,
    GITEA_CONF_LINK_PATH,
    GITEA_DIR,
    GITEA_GENERATED_NAME,
    GITEA_PACKAGES,
    GITEA_SUPPORTED_ARCHITECTURES,
    GITEA_USER,
    GITEA_VERSION,
)
from neutrino_hub.modules.gitea.ops import GiteaConfigApplier


def download_url(architecture: str) -> str:
    """The vendor release download for one architecture.

    Args:
        architecture: A normalized name from :mod:`neutrino_hub.system.machine`, which the
            vendor's file names happen to use directly.

    Returns:
        The URL of the release binary.
    """
    return (
        f"https://dl.gitea.com/gitea/{GITEA_VERSION}/"
        f"gitea-{GITEA_VERSION}-linux-{architecture}"
    )


class GiteaProvisioner:
    """Installs Gitea as a single binary with a systemd unit."""

    def provision(
        self, *, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Install the binary, its user, its directories, and its unit.

        Args:
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            RuntimeError: On a machine the vendor publishes no binary for —
                before anything lands, not after it fails to start.
            CommandError: If the download or any setup step fails.
        """
        is_changed = False
        if not GITEA_BINARY_PATH.is_file():
            require_architecture(GITEA_SUPPORTED_ARCHITECTURES, "gitea")
            controller = package_manager.current()
            packages = require_distribution(GITEA_PACKAGES, "the git server")
            missing = [n for n in packages if not controller.is_installed(n)]
            if missing:
                say(report, f"installing {', '.join(missing)}")
                controller.refresh()
                controller.install(tuple(missing))
            say(report, "creating the git user and its directories")
            self._create_user()
            self._create_directories()
            architecture = machine_architecture()
            say(
                report,
                f"downloading gitea {GITEA_VERSION} for {architecture} "
                f"(~120 MB, this is the slow part)",
            )
            self._download_binary()
            is_changed = True
        unit_text = (
            UTILS_DATA_DIR / "services" / "neutrino_hub_gitea.service"
        ).read_text(encoding="utf-8")
        if GiteaConfigApplier().refresh_unit(unit_text):
            say(report, "installed the systemd unit")
            is_changed = True
        return ProvisionResult(
            is_changed=is_changed,
            message=f"gitea {GITEA_VERSION}" if is_changed else "already provisioned",
        )

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Remove the software, and — only when asked — what it stored.

        The configuration under ``config/gitea/`` always survives, so
        reinstalling converges back to the same server. With the data kept,
        so do the repositories: install after uninstall is a round trip.

        Args:
            is_data_kept: Keep ``/var/lib/gitea`` — every repository and
                account. False deletes it, along with the git user and the
                generated secrets that only that data gave meaning to.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.
        """
        if not GITEA_BINARY_PATH.is_file():
            return ProvisionResult(is_changed=False, message="not installed")

        say(report, "stopping and disabling gitea")
        run(["systemctl", "disable", "--now", "neutrino_hub_gitea"], is_checked=False)
        (SYSTEM_SYSTEMD_DIR / "neutrino_hub_gitea.service").unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])

        say(report, "removing the binary and the rendered configuration")
        GITEA_BINARY_PATH.unlink(missing_ok=True)
        GITEA_CONF_LINK_PATH.unlink(missing_ok=True)
        (UTILS_GENERATED_DIR / GITEA_GENERATED_NAME).unlink(missing_ok=True)

        if not is_data_kept:
            say(report, "deleting every repository and account under /var/lib/gitea")
            shutil.rmtree(GITEA_DIR, ignore_errors=True)
            run(["userdel", GITEA_USER], is_checked=False)
            # The secrets signed sessions and tokens for a database that no
            # longer exists; a reinstall generates fresh ones.
            (UTILS_CONFIG_DIR / "gitea/secrets.json").unlink(missing_ok=True)
            return ProvisionResult(is_changed=True, message="removed, data deleted")
        return ProvisionResult(
            is_changed=True, message="removed; repositories kept in /var/lib/gitea"
        )

    def _create_user(self) -> None:
        if run(["id", GITEA_USER], is_checked=False).is_success:
            return
        run(
            [
                "useradd",
                "--system",
                "--shell",
                "/bin/bash",
                "--comment",
                "Gitea",
                "--create-home",
                "--home-dir",
                str(GITEA_DIR),
                GITEA_USER,
            ]
        )

    def _create_directories(self) -> None:
        for directory in (
            GITEA_DIR / "custom",
            GITEA_DIR / "data",
            GITEA_DIR / "log",
            Path("/etc/gitea"),
        ):
            directory.mkdir(parents=True, exist_ok=True)
            shutil.chown(directory, user=GITEA_USER, group=GITEA_USER)
        Path("/etc/gitea").chmod(0o770)

    def _download_binary(self) -> None:
        url = download_url(machine_architecture())
        run(
            ["curl", "-fL", "--retry", "2", "-o", str(GITEA_BINARY_PATH), url],
            timeout_s=600,
        )
        GITEA_BINARY_PATH.chmod(0o755)
