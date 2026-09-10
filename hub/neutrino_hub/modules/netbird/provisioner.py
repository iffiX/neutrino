"""Installing NetBird from its vendor repository.

NetBird is the way back into this box from anywhere else, which is why it is
a core service: the panel installs it but refuses to stop, disable or remove
it — any of those, done from abroad, is how the owner locks themselves out.

Joining a network stays a separate step: it needs a setup key, and which
management plane to trust is a decision the installer should not make
silently.
"""

import shutil
from pathlib import Path
from typing import Callable

from neutrino_hub.system import package_manager
from neutrino_hub.system.provisioning import ProvisionResult, say
from neutrino_hub.system.sandbox import outside_sandbox
from neutrino_hub.utils.subprocess_run import run

NETBIRD_INSTALL_URL = "https://pkgs.netbird.io/install.sh"

# What the vendor script drops into apt's configuration, removed with the
# package so an uninstalled NetBird does not keep a repository around.
APT_SOURCE_PATHS = (
    Path("/etc/apt/sources.list.d/netbird.list"),
    Path("/usr/share/keyrings/netbird-archive-keyring.gpg"),
)

# The machine's identity and the management plane it enrolled with.
STATE_DIR = Path("/etc/netbird")


class NetbirdProvisioner:
    """Installs NetBird from its vendor repository."""

    def provision(
        self, *, report: Callable[[str], None] | None = None
    ) -> ProvisionResult:
        """Install the NetBird package if it is missing.

        Args:
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.

        Raises:
            subprocess.CalledProcessError: If the vendor installer fails.
            FileNotFoundError: If it finishes but leaves no binary.
        """
        if shutil.which("netbird"):
            version = run(["netbird", "version"], is_checked=False).stdout.strip()
            return ProvisionResult(is_changed=False, message=version or "present")
        say(report, "adding the vendor repository and installing netbird")
        script = run(["curl", "-fsSL", NETBIRD_INSTALL_URL], timeout_s=120).stdout
        # The script runs the machine's own package manager, which is a level
        # below anything this process can pass a flag to — so the whole script
        # goes outside the panel's sandbox rather than the apt call inside it.
        run(outside_sandbox(["sh", "-"]), input_text=script, timeout_s=600)
        if not shutil.which("netbird"):
            raise FileNotFoundError("the NetBird installer finished but left no binary")
        return ProvisionResult(is_changed=True, message="installed")

    def deprovision(
        self,
        *,
        is_data_kept: bool = True,
        report: Callable[[str], None] | None = None,
    ) -> ProvisionResult:
        """Remove the package, and — only when asked — the enrollment.

        The panel never calls this — netbird is core, and removing the way
        back in is refused there — but the contract stays symmetric for the
        installer and for a hand at a local shell.

        Args:
            is_data_kept: Keep ``/etc/netbird``, the machine's identity, so a
                reinstall rejoins as the same peer. False deletes it.
            report: Sink for progress lines, if anyone is watching.

        Returns:
            What was done.
        """
        if not shutil.which("netbird"):
            return ProvisionResult(is_changed=False, message="not installed")

        say(report, "leaving the network and stopping netbird")
        run(["netbird", "down"], is_checked=False, timeout_s=30)
        run(["systemctl", "disable", "--now", "netbird"], is_checked=False)

        say(report, "removing the package and its repository")
        package_manager.current().remove(("netbird",))
        for path in APT_SOURCE_PATHS:
            path.unlink(missing_ok=True)

        if not is_data_kept:
            say(report, "deleting the peer identity")
            shutil.rmtree(STATE_DIR, ignore_errors=True)
            return ProvisionResult(is_changed=True, message="removed, identity deleted")
        return ProvisionResult(is_changed=True, message="removed; identity kept")
