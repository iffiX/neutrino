"""Installing and removing the Samba server itself.

The package comes from the Ubuntu archive; what makes it this gateway's file
share — the rendered smb.conf, the accounts, the share directories — is the
work of :mod:`neutrino_hub.modules.samba.ops` and happens on apply, not here.
"""

import shutil
from pathlib import Path
from typing import Callable

from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.constants import SAMBA_GENERATED_NAME

SAMBA_PACKAGE = "samba"


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
            CommandError: If apt fails.
        """
        if shutil.which("smbd"):
            return ProvisionResult(is_changed=False, message="already installed")
        say(report, "installing the samba package from Ubuntu")
        run(["apt-get", "update"], timeout_s=300, is_checked=False)
        run(
            ["apt-get", "install", "-y", "--no-install-recommends", SAMBA_PACKAGE],
            timeout_s=900,
        )
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

        say(report, "stopping smbd and removing the package")
        run(["systemctl", "disable", "--now", "smbd"], is_checked=False)
        # Purge takes the credential store with it; a plain remove leaves
        # passwords behind for a package that is gone.
        run(["apt-get", "remove", "--purge", "-y", SAMBA_PACKAGE], timeout_s=600)
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
