"""The modules the panel can install and remove, in one place.

Each installable module already declares its own pieces — a provisioner, the
architectures it runs on, the unit it becomes. This is where those
declarations are gathered so the Services page, the API and the installer all
read one list. Adding an installable module is writing its package and adding
one entry here.

Core modules may appear here too — netbird is core and still needs
installing — but the uninstall route refuses anything core: the panel will
put the way back into the box in place, and will not take it away.
"""

from dataclasses import dataclass
from typing import Callable

from neutrino_hub.modules.cliproxy.constants import (
    CLIPROXY_SUPPORTED_ARCHITECTURES,
    CLIPROXY_UNIT,
)
from neutrino_hub.modules.cliproxy.provisioner import CliproxyProvisioner
from neutrino_hub.modules.gitea.constants import GITEA_SUPPORTED_ARCHITECTURES
from neutrino_hub.modules.gitea.provisioner import GiteaProvisioner
from neutrino_hub.modules.podman.constants import (
    PODMAN_SUPPORTED_ARCHITECTURES,
    PODMAN_UNIT,
)
from neutrino_hub.modules.podman.provisioner import PodmanProvisioner
from neutrino_hub.modules.samba.constants import SAMBA_SUPPORTED_ARCHITECTURES
from neutrino_hub.modules.samba.provisioner import SambaProvisioner
from neutrino_hub.modules.netbird.constants import NETBIRD_SUPPORTED_ARCHITECTURES
from neutrino_hub.modules.netbird.provisioner import NetbirdProvisioner
from neutrino_hub.modules.zfs.constants import ZFS_SUPPORTED_ARCHITECTURES, ZFS_ZED_UNIT
from neutrino_hub.modules.zfs.provisioner import ZfsProvisioner


@dataclass
class ModuleSpec:
    """One module as the install machinery sees it.

    Attributes:
        unit: The systemd unit the module becomes once installed.
        provisioner: Builds the object with ``provision`` / ``deprovision``.
        architectures: What machines it runs on, ``("*",)`` for any.
        install_note: What installing actually entails, shown before the
            button is pressed — a download's rough size, a vendor repository
            being added.
        data_description: What "delete the data too" would delete, named
            plainly so the checkbox is a decision rather than a gamble.
    """

    unit: str
    provisioner: Callable
    architectures: tuple
    install_note: str
    data_description: str


MODULE_SPECS = {
    "samba": ModuleSpec(
        unit="smbd.service",
        provisioner=SambaProvisioner,
        architectures=SAMBA_SUPPORTED_ARCHITECTURES,
        install_note="file sharing over SMB, for the LAN and the overlay",
        data_description="the files in every configured share",
    ),
    "gitea": ModuleSpec(
        unit="gitea.service",
        provisioner=GiteaProvisioner,
        architectures=GITEA_SUPPORTED_ARCHITECTURES,
        install_note="a private git server with its own web UI (~120 MB download)",
        data_description="every repository and account under /var/lib/gitea",
    ),
    "podman": ModuleSpec(
        unit=PODMAN_UNIT,
        provisioner=PodmanProvisioner,
        architectures=PODMAN_SUPPORTED_ARCHITECTURES,
        install_note="containers as systemd units, with a docker-compatible CLI",
        data_description="every image, container layer and named volume",
    ),
    "netbird": ModuleSpec(
        unit="netbird.service",
        provisioner=NetbirdProvisioner,
        architectures=NETBIRD_SUPPORTED_ARCHITECTURES,
        install_note="remote access to this gateway from anywhere",
        data_description="this machine's peer identity",
    ),
    "cliproxy": ModuleSpec(
        unit=CLIPROXY_UNIT,
        provisioner=CliproxyProvisioner,
        architectures=CLIPROXY_SUPPORTED_ARCHITECTURES,
        install_note="one AI endpoint for every tool on every machine (~20 MB download)",
        data_description="imported provider account logins",
    ),
    "zfs": ModuleSpec(
        unit=ZFS_ZED_UNIT,
        provisioner=ZfsProvisioner,
        architectures=ZFS_SUPPORTED_ARCHITECTURES,
        install_note="pooled storage with redundancy and compression",
        data_description="nothing — pools stay on their disks either way",
    ),
}
