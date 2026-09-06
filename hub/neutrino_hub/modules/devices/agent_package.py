"""The baked agent packages the hub can deliver.

Two callers hand these out: the SSH install pushes one to a device, and the
agent channel serves one to an agent updating itself. Both must resolve the
same file for a family and a machine.

The agent carries its own interpreter and compiled bindings, so a package is
for one architecture. What the hub package bakes is the architecture it was
itself built for; a fleet with a second one is served from
``config/devices/packages``, which wins over the baked copy.
"""

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR, UTILS_DATA_DIR

# What each format spells the same machine, mapped to the name the agent's
# platform tuple reports.
AGENT_PACKAGE_ARCHITECTURES = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def agent_packages() -> dict:
    """The agent packages the hub can deliver, newest per family and machine.

    A build pinned under ``config/devices/packages`` wins over the one the
    hub package carries in its own data.

    Returns:
        Family (``deb``, ``rpm``) to architecture (``amd64``, ``arm64``) to
        package path, for the ones found.
    """
    packages: dict = {}
    for family, pattern in (("deb", "*.deb"), ("rpm", "*.rpm")):
        for root in (
            UTILS_CONFIG_DIR / "devices" / "packages",
            UTILS_DATA_DIR / "agent_package",
        ):
            found = sorted(root.glob(pattern)) if root.is_dir() else []
            for path in found:
                architecture = package_architecture(path.name)
                if architecture:
                    packages.setdefault(family, {})[architecture] = path
            if packages.get(family):
                break
    return packages


def package_architecture(name: str) -> str:
    """Which machine a package file is for, read from its name.

    Args:
        name: The file name, as either format writes it.

    Returns:
        ``amd64`` or ``arm64``, or empty when the name says neither.
    """
    # Longest first: the two families punctuate the same machine differently,
    # and `aarch64` would otherwise be read by a shorter name inside it.
    for token in sorted(AGENT_PACKAGE_ARCHITECTURES, key=len, reverse=True):
        if token in name:
            return AGENT_PACKAGE_ARCHITECTURES[token]
    return ""
