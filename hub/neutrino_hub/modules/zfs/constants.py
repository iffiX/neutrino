"""Fixed values of the ZFS module.

There is no ``config/zfs/``: a pool's truth is written on its member disks and
``zpool`` is its own database, so the panel is a viewport plus guarded verbs
rather than a render pipeline. This is the one module where config/ is not the
source of truth, and :mod:`docs.architecture` says so.
"""

import re
from pathlib import Path

ZFS_ZED_UNIT = "zfs-zed.service"

# The kernel module ships with Ubuntu's kernels on these builds; zfsutils is
# tools only, so no DKMS compile is involved.
ZFS_SUPPORTED_ARCHITECTURES = ("amd64", "arm64")

# Offered compressions, best first. zstd is the default: on a gateway's CPU it
# is effectively free and routinely halves text-heavy datasets. Everything
# beyond this choice (recordsize, sync, dedup) keeps its ZFS default and stays
# out of the panel.
ZFS_COMPRESSIONS = ("lz4", "zstd", "off")

# Offered recordsizes. This is the one dataset property that moves real
# workloads — small for databases and VM images, large for media — so it is
# in the panel while everything else keeps its chosen default.
ZFS_RECORDSIZES = ("16K", "32K", "64K", "128K", "256K", "512K", "1M")

# How a vdev is laid out, and the fewest disks each layout means anything with.
ZFS_VDEV_LAYOUTS = {
    "single": 1,
    "mirror": 2,
    "raidz1": 3,
    "raidz2": 4,
}

# Pool and dataset names end up in mount paths, smb.conf sections and shell
# commands; both are held to charsets that cannot smuggle syntax anywhere.
ZFS_POOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,29}\Z")
ZFS_DATASET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")

# Names zpool gives a meaning of its own inside a create command.
ZFS_RESERVED_POOL_NAMES = (
    "mirror",
    "raidz",
    "raidz1",
    "raidz2",
    "raidz3",
    "spare",
    "log",
    "cache",
)

# The ARC would take half the machine's memory by default; a quarter leaves
# room for the gateway's own services. Written as a modprobe option so it
# holds across reboots, and poked into the live module on install.
ZFS_ARC_MAX_FRACTION = 0.25
ZFS_MODPROBE_CONF = Path("/etc/modprobe.d/99_neutrino_zfs.conf")
ZFS_ARC_MAX_PARAMETER = Path("/sys/module/zfs/parameters/zfs_arc_max")

ZFS_DISK_BY_ID_DIR = Path("/dev/disk/by-id")
