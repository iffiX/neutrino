"""The modules the panel can install and remove, in one place.

Each installable module already declares its own pieces — a provisioner, the
architectures it runs on, the unit it becomes. This is where those
declarations are gathered so the Services page, the API and the installer all
read one list. Adding an installable module is writing its package and adding
one entry here.

A core module may appear here too when it still needs installing, and the
uninstall route refuses anything core: the panel puts what makes this a
gateway in place, and will not take it away.
"""

from dataclasses import dataclass
from typing import Callable

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_SUPPORTED_ARCHITECTURES,
    CLIPROXYAPI_UNIT,
)
from neutrino_hub.modules.cliproxyapi.provisioner import CliproxyApiProvisioner
from neutrino_hub.modules.netbird.constants import (
    NETBIRD_SUPPORTED_ARCHITECTURES,
    NETBIRD_UNIT,
)
from neutrino_hub.modules.netbird.provisioner import NetbirdProvisioner


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
    "netbird": ModuleSpec(
        unit=NETBIRD_UNIT,
        provisioner=NetbirdProvisioner,
        architectures=NETBIRD_SUPPORTED_ARCHITECTURES,
        install_note=(
            "remote access to this gateway from anywhere "
            "(the client is in the package)"
        ),
        data_description="this machine's peer identity",
    ),
    "cliproxyapi": ModuleSpec(
        unit=CLIPROXYAPI_UNIT,
        provisioner=CliproxyApiProvisioner,
        architectures=CLIPROXYAPI_SUPPORTED_ARCHITECTURES,
        install_note="one AI endpoint for every tool on every machine (~20 MB download)",
        data_description="imported provider account logins",
    ),
}
