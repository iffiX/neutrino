"""Fixed values of the ZFS module.

There is no configuration to render: a pool's truth is written on its
member disks and ``zpool`` is its own database, so the module is a viewport
plus guarded verbs.
"""

import re

ZFS_ZED_UNIT = "zfs-zed.service"
ZFS_MODULE_NAME = "zfs"

# Offered compressions, and the recordsizes worth choosing.
ZFS_COMPRESSIONS = ("lz4", "zstd", "off")
ZFS_RECORDSIZES = ("16K", "32K", "64K", "128K", "256K", "512K", "1M")

# How a vdev is laid out, and the fewest disks each layout means anything with.
ZFS_VDEV_LAYOUTS = {"single": 1, "mirror": 2, "raidz1": 3, "raidz2": 4}

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

# Mounting a dataset over these would bury the operating system alive.
ZFS_FORBIDDEN_MOUNT_ROOTS = (
    "bin",
    "boot",
    "dev",
    "etc",
    "lib",
    "lib64",
    "proc",
    "run",
    "sbin",
    "sys",
    "usr",
)

# The ARC would take half the machine's memory by default; a quarter leaves
# room for everything else the machine does. Written as a modprobe option
# so it holds across reboots, and poked into the live module on apply.
ZFS_ARC_MAX_FRACTION = 0.25
ZFS_MODPROBE_CONF = "/etc/modprobe.d/99_neutrino_zfs.conf"
ZFS_ARC_MAX_PARAMETER = "/sys/module/zfs/parameters/zfs_arc_max"
ZFS_MEMINFO_PATH = "/proc/meminfo"

ZFS_DISK_BY_ID_DIR = "/dev/disk/by-id"
ZFS_DISK_BY_PATH_DIR = "/dev/disk/by-path"

# by-id gives every disk several names; the one used for pools should be
# the one a person can match to a label on the drive.
ZFS_DISK_ID_PREFERENCE = ("ata-", "scsi-", "nvme-", "usb-", "mmc-", "wwn-")

# vdev grouping lines in `zpool status` output. `replacing-N` and `spare-N`
# are transient groups whose children are members of the enclosing vdev.
ZFS_VDEV_GROUP_PREFIXES = ("mirror-", "raidz1-", "raidz2-", "raidz3-")
ZFS_TRANSIENT_GROUP_PREFIXES = ("replacing-", "spare-")

ZFS_COMMAND_OP = "zfs_op"
ZFS_COMMAND_SCAN = "zfs_scan"

# The verbs `zfs_op` takes.
ZFS_OP_CREATE_POOL = "create_pool"
ZFS_OP_DESTROY_POOL = "destroy_pool"
ZFS_OP_EXPAND_POOL = "expand_pool"
ZFS_OP_IMPORT_POOL = "import_pool"
ZFS_OP_SCRUB = "scrub"
ZFS_OP_STOP_SCRUB = "stop_scrub"
ZFS_OP_REPLACE = "replace"
ZFS_OP_OFFLINE = "offline"
ZFS_OP_ONLINE = "online"
ZFS_OP_CREATE_DATASET = "create_dataset"
ZFS_OP_DESTROY_DATASET = "destroy_dataset"
ZFS_OPS = (
    ZFS_OP_CREATE_POOL,
    ZFS_OP_DESTROY_POOL,
    ZFS_OP_EXPAND_POOL,
    ZFS_OP_IMPORT_POOL,
    ZFS_OP_SCRUB,
    ZFS_OP_STOP_SCRUB,
    ZFS_OP_REPLACE,
    ZFS_OP_OFFLINE,
    ZFS_OP_ONLINE,
    ZFS_OP_CREATE_DATASET,
    ZFS_OP_DESTROY_DATASET,
)
