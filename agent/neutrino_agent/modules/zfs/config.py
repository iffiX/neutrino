"""What the ZFS verbs accept.

Pool and dataset names, layouts, tunables and mountpoints are checked
before anything reaches ``zpool`` or ``zfs``; every refusal is typed.

Pure: checks arguments only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.zfs.constants import (
    ZFS_COMPRESSIONS,
    ZFS_DATASET_NAME_PATTERN,
    ZFS_FORBIDDEN_MOUNT_ROOTS,
    ZFS_POOL_NAME_PATTERN,
    ZFS_RECORDSIZES,
    ZFS_RESERVED_POOL_NAMES,
    ZFS_VDEV_LAYOUTS,
)


def validate_pool_name(name: str) -> None:
    """Check a pool name.

    Args:
        name: The proposed name.

    Raises:
        ModuleApplyError: ``pool_name_invalid`` or ``pool_name_reserved``.
    """
    if not ZFS_POOL_NAME_PATTERN.match(name):
        raise ModuleApplyError("pool_name_invalid", {"name": name})
    if name in ZFS_RESERVED_POOL_NAMES:
        raise ModuleApplyError("pool_name_reserved", {"name": name})


def validate_vdev(layout: str, devices: list) -> None:
    """Check a vdev's layout against its disk count.

    Args:
        layout: One of the offered layouts.
        devices: The member disks.

    Raises:
        ModuleApplyError: ``layout_unknown`` or ``layout_disk_count``.
    """
    minimum = ZFS_VDEV_LAYOUTS.get(layout)
    if minimum is None:
        raise ModuleApplyError("layout_unknown", {"layout": layout})
    if len(devices) < minimum or (layout == "single" and len(devices) > 1):
        raise ModuleApplyError(
            "layout_disk_count",
            {"layout": layout, "minimum": minimum, "count": len(devices)},
        )


def validate_dataset_path(name: str) -> None:
    """Check a dataset path: slash-separated pieces, each a plain name.

    Args:
        name: The path under the pool, for example ``nfs/home``.

    Raises:
        ModuleApplyError: ``dataset_name_invalid``.
    """
    pieces = name.split("/")
    if not pieces or any(not ZFS_DATASET_NAME_PATTERN.match(piece) for piece in pieces):
        raise ModuleApplyError("dataset_name_invalid", {"name": name})


def validate_tunables(compression: str, recordsize: str) -> None:
    """Check a dataset's compression and recordsize are offered ones.

    Raises:
        ModuleApplyError: ``compression_unknown`` or ``recordsize_unknown``.
    """
    if compression not in ZFS_COMPRESSIONS:
        raise ModuleApplyError("compression_unknown", {"compression": compression})
    if recordsize not in ZFS_RECORDSIZES:
        raise ModuleApplyError("recordsize_unknown", {"recordsize": recordsize})


def validate_mountpoint(mountpoint: "str | None") -> None:
    """Check a mountpoint is an absolute path off the operating system.

    Args:
        mountpoint: The path, or None for ZFS's own default.

    Raises:
        ModuleApplyError: ``mountpoint_invalid`` or ``mountpoint_forbidden``.
    """
    if mountpoint is None:
        return
    if (
        not mountpoint.startswith("/")
        or mountpoint == "/"
        or ".." in mountpoint
        or any(character.isspace() for character in mountpoint)
    ):
        raise ModuleApplyError("mountpoint_invalid", {"mountpoint": mountpoint})
    if mountpoint.split("/")[1] in ZFS_FORBIDDEN_MOUNT_ROOTS:
        raise ModuleApplyError("mountpoint_forbidden", {"mountpoint": mountpoint})
