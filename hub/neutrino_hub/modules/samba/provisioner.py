"""Installing and removing the Samba server itself.

The package comes from the distribution; what makes it this gateway's file
share — the rendered smb.conf, the accounts, the share directories — is the
work of :mod:`neutrino_hub.modules.samba.ops` and happens on apply, not here.
"""

import shutil
from pathlib import Path
from typing import Callable

from neutrino_hub.system import package_manager
from neutrino_hub.system.machine import distribution_family, require_distribution
from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.constants import (
    SAMBA_GENERATED_NAME,
    SAMBA_GROUP,
    SAMBA_PACKAGES,
    SAMBA_SERVICES,
)


class SambaProvisioner:
    """Installs the samba package and takes it away again."""

    def provision(
        self, *, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Install the samba package if it is missing.

        Args:
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            CommandError: If the package manager fails.
            RuntimeError: If this distribution has no samba packages named.
        """
        if shutil.which("smbd"):
            _require_share_group()
            return ProvisionResult(is_changed=False, message="already installed")

        packages = require_distribution(SAMBA_PACKAGES, "the file share")
        say(report, f"installing {', '.join(packages)}")
        controller = package_manager.current()
        controller.refresh()
        controller.install(packages)
        _require_share_group()
        return ProvisionResult(is_changed=True, message="installed")

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Remove the server, and — only when asked — the shared files.

        The unix accounts survive either way, as the Samba page promised when
        it made them: deleting accounts is how files end up owned by a
        recycled uid.

        Args:
            is_data_kept: Keep the share directories and their files. False
                deletes every directory the configuration exports.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.
        """
        if not shutil.which("smbd"):
            return ProvisionResult(is_changed=False, message="not installed")

        service = SAMBA_SERVICES.get(distribution_family(), "smbd")
        say(report, f"stopping {service} and removing the package")
        run(["systemctl", "disable", "--now", service], is_checked=False)
        # Purging takes the credential store with it; a plain remove leaves
        # passwords behind for a package that is gone.
        packages = SAMBA_PACKAGES.get(distribution_family(), ("samba",))
        package_manager.current().remove(packages, is_purged=True)
        (UTILS_GENERATED_DIR / SAMBA_GENERATED_NAME).unlink(missing_ok=True)

        if not is_data_kept:
            for share in self._configured_shares():
                say(report, f"deleting {share}")
                shutil.rmtree(Path(share), ignore_errors=True)
            return ProvisionResult(is_changed=True, message="removed, shares deleted")
        return ProvisionResult(
            is_changed=True, message="removed; shared files kept in place"
        )

    def _configured_shares(self) -> list[str]:
        try:
            config = SambaConfig.from_dict(read_config("samba/samba.json"))
        except (FileNotFoundError, ValueError):
            return []
        return [share.path for share in config.shares]


def _require_share_group() -> None:
    """Make sure the group every share account joins exists.

    Debian ships it with the package. RHEL and Arch do not, and a share whose
    files have no common group is a share whose members cannot edit each
    other's files.
    """
    if run(["getent", "group", SAMBA_GROUP], is_checked=False).is_success:
        return
    run(["groupadd", "--system", SAMBA_GROUP], is_checked=False)
