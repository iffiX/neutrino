"""The baked agent packages the hub can deliver.

Two callers hand these out: the SSH install pushes one to a device, and the
agent channel serves one to an agent updating itself. Both must resolve the
same file for a family.
"""

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR, UTILS_DATA_DIR


def agent_packages() -> dict:
    """The agent packages the hub can deliver, newest per family.

    A build pinned under ``config/devices/packages`` wins over the one the
    hub package carries in its own data.

    Returns:
        Family (``deb``, ``rpm``) to package path, for the families found.
    """
    packages: dict = {}
    for family, pattern in (("deb", "*.deb"), ("rpm", "*.rpm")):
        for root in (
            UTILS_CONFIG_DIR / "devices" / "packages",
            UTILS_DATA_DIR / "agent_package",
        ):
            found = sorted(root.glob(pattern)) if root.is_dir() else []
            if found:
                packages[family] = found[-1]
                break
    return packages
