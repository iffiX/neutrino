"""Reading and driving ZFS: disks, pools, datasets.

Everything here talks to the system through ``lsblk``, ``smartctl``, ``zpool``
and ``zfs``. The only text parsing is ``zpool status`` and ``zpool import``,
which have no machine format on the OpenZFS this targets; those parsers are
module-level functions so they can be tested on canned output without a pool
in sight.
"""

import json
import shutil
from dataclasses import dataclass, field

from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.zfs.constants import (
    ZFS_DISK_BY_ID_DIR,
    ZFS_VDEV_LAYOUTS,
)

# by-id gives every disk several names; the one used for pools should be the
# one a person can match to a label on the drive. Bus names carry the model
# and serial; wwn and eui are hex soup, kept only as a last resort.
DISK_ID_PREFERENCE = ("ata-", "scsi-", "nvme-", "usb-", "mmc-", "wwn-")

# vdev grouping lines in `zpool status` config output. `replacing-N` and
# `spare-N` are transient groups that appear inside a vdev while a disk is
# being swapped; their children are members of the enclosing vdev.
VDEV_GROUP_PREFIXES = ("mirror-", "raidz1-", "raidz2-", "raidz3-")
TRANSIENT_GROUP_PREFIXES = ("replacing-", "spare-")


@dataclass
class ZfsDisk:
    """One physical disk as the panel sees it.

    Attributes:
        device: Kernel path, for example ``/dev/sda``.
        by_id: Stable by-id path used for every pool operation, or the kernel
            path when no by-id link exists.
        size_bytes: Capacity.
        model: What the drive calls itself.
        serial: Its serial number, for matching the physical label.
        is_rotational: Spinning rust or not.
        transport: The bus it hangs off — ``nvme``, ``sata``, ``usb`` — empty
            when the kernel will not say.
        wwn: The drive's world-wide name, its bus-level identity.
        by_path: The stable by-path name, which encodes the PCI slot and port
            the drive is plugged into.
        fstype: Filesystem signature on the raw disk or a partition, empty
            when blank. Anything here means creating over it destroys data.
        pool: Name of the imported pool using it, or None.
        is_system: Whether the OS lives here — never offered for anything.
        smart_passed: SMART overall verdict, None when the drive will not say.
        temperature_c: Drive temperature, None when unknown.
    """

    device: str
    by_id: str
    size_bytes: int
    model: str
    serial: str
    is_rotational: bool
    transport: str = ""
    wwn: str | None = None
    by_path: str | None = None
    fstype: str = ""
    pool: str | None = None
    is_system: bool = False
    smart_passed: bool | None = None
    temperature_c: int | None = None

    @property
    def is_available(self) -> bool:
        """Whether this disk can be offered for a new vdev."""
        return self.pool is None and not self.is_system


@dataclass
class ZfsVdevMember:
    """One device inside a vdev.

    Attributes:
        name: The device as ``zpool status`` names it.
        state: ONLINE, DEGRADED, FAULTED, OFFLINE, UNAVAIL, REMOVED.
        read_errors: Read error count.
        write_errors: Write error count.
        checksum_errors: Checksum error count.
        is_resilvering: Whether this member is being rebuilt right now.
    """

    name: str
    state: str
    read_errors: int = 0
    write_errors: int = 0
    checksum_errors: int = 0
    is_resilvering: bool = False


@dataclass
class ZfsVdev:
    """One vdev of a pool.

    Attributes:
        name: The group name, for example ``raidz1-0`` — or the member's own
            name for a single-disk vdev.
        layout: ``single``, ``mirror``, ``raidz1``, ``raidz2``, ``raidz3``.
        state: The vdev's own state.
        members: Its devices.
    """

    name: str
    layout: str
    state: str
    members: list[ZfsVdevMember] = field(default_factory=list)


@dataclass
class ZfsScanStatus:
    """What the pool's scrub or resilver is doing.

    Attributes:
        kind: ``scrub`` or ``resilver`` while one runs, None otherwise.
        percent: Progress, when running.
        eta: Human time-to-go text, when the pool offers one.
        summary: The last completed scan's own summary line.
    """

    kind: str | None = None
    percent: float | None = None
    eta: str | None = None
    summary: str = ""


@dataclass
class ZfsPool:
    """One imported pool.

    Attributes:
        name: Pool name.
        state: Pool health state.
        size_bytes: Raw pool size.
        allocated_bytes: Raw bytes in use.
        capacity_percent: Fill level as zpool reports it.
        fragmentation_percent: Free-space fragmentation.
        vdevs: The topology.
        scan: Scrub or resilver state.
        errors: The ``errors:`` line, empty when it reads as none known.
    """

    name: str
    state: str
    size_bytes: int
    allocated_bytes: int
    capacity_percent: int
    fragmentation_percent: int
    vdevs: list[ZfsVdev] = field(default_factory=list)
    scan: ZfsScanStatus = field(default_factory=ZfsScanStatus)
    errors: str = ""


@dataclass
class ZfsDataset:
    """One filesystem dataset.

    Attributes:
        name: Full name, ``pool/child``.
        used_bytes: Space referenced plus descendants.
        available_bytes: Space left for it.
        mountpoint: Where it is mounted.
        compression: The property as set.
        compressratio: Achieved ratio, for example 1.85.
        recordsize_bytes: The record size in bytes.
    """

    name: str
    used_bytes: int
    available_bytes: int
    mountpoint: str
    compression: str
    compressratio: float
    recordsize_bytes: int = 131072


@dataclass
class ZfsImportable:
    """A pool sitting on attached disks, waiting to be imported."""

    name: str
    state: str


def is_zfs_installed() -> bool:
    """Whether the ZFS userland tools are present.

    Returns:
        True when ``zpool`` is on the path.
    """
    return shutil.which("zpool") is not None


def parse_zpool_status(text: str) -> tuple[list[ZfsVdev], ZfsScanStatus, str, str]:
    """Parse one pool's ``zpool status`` output.

    The config tree is indentation-structured: the pool at the root, vdev
    groups one level in, members below them. A bare device at vdev level is a
    single-disk vdev. Transient groups (``replacing-N``, ``spare-N``) are
    flattened into the enclosing vdev, because to the person watching, the
    old and new disk are both simply members until the resilver ends.

    Args:
        text: Output of ``zpool status <pool>``.

    Returns:
        The vdevs, the scan state, the pool state, and the errors line.
    """
    vdevs: list[ZfsVdev] = []
    scan = ZfsScanStatus()
    pool_state = ""
    errors = ""

    scan_lines: list[str] = []
    is_in_scan = False
    is_in_config = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("state:"):
            pool_state = stripped.split(":", 1)[1].strip()
            is_in_scan = False
            continue
        if stripped.startswith("scan:"):
            scan_lines = [stripped.split(":", 1)[1].strip()]
            is_in_scan = True
            continue
        if stripped.startswith("config:"):
            is_in_scan = False
            is_in_config = True
            continue
        if stripped.startswith("errors:"):
            is_in_config = False
            is_in_scan = False
            text_after = stripped.split(":", 1)[1].strip()
            if text_after.lower() != "no known data errors":
                errors = text_after
            continue
        if is_in_scan and stripped:
            scan_lines.append(stripped)
            continue
        if not is_in_config or not stripped:
            continue

        columns = stripped.split()
        if columns[0] == "NAME":
            continue
        # Depth: a tab prefixes the whole tree; every level below the pool
        # adds two spaces.
        indent = len(line.expandtabs(0)) - len(line.expandtabs(0).lstrip())
        depth = indent // 2
        name = columns[0]
        state = columns[1] if len(columns) > 1 else ""
        counts = [_as_count(value) for value in columns[2:5]]
        while len(counts) < 3:
            counts.append(0)
        is_resilvering = "(resilvering)" in stripped

        if depth == 0:
            continue
        if depth == 1:
            if name.startswith(VDEV_GROUP_PREFIXES):
                layout = name.split("-", 1)[0]
                if layout == "mirror":
                    layout = "mirror"
                vdevs.append(ZfsVdev(name=name, layout=layout, state=state))
            else:
                vdevs.append(
                    ZfsVdev(
                        name=name,
                        layout="single",
                        state=state,
                        members=[
                            ZfsVdevMember(
                                name=name,
                                state=state,
                                read_errors=counts[0],
                                write_errors=counts[1],
                                checksum_errors=counts[2],
                                is_resilvering=is_resilvering,
                            )
                        ],
                    )
                )
            continue
        if not vdevs:
            continue
        if name.startswith(TRANSIENT_GROUP_PREFIXES):
            continue
        vdevs[-1].members.append(
            ZfsVdevMember(
                name=name,
                state=state,
                read_errors=counts[0],
                write_errors=counts[1],
                checksum_errors=counts[2],
                is_resilvering=is_resilvering,
            )
        )

    scan_text = " ".join(scan_lines)
    if " in progress" in scan_text:
        scan.kind = "resilver" if scan_text.startswith("resilver") else "scrub"
        for token in scan_text.replace(",", " ").split():
            if token.endswith("%"):
                try:
                    scan.percent = float(token.rstrip("%"))
                except ValueError:
                    pass
        if " to go" in scan_text:
            before = scan_text.split(" to go", 1)[0]
            scan.eta = before.rsplit(" ", 1)[-1]
    elif scan_text and not scan_text.startswith("none"):
        scan.summary = scan_text

    return vdevs, scan, pool_state, errors


def parse_zpool_import(text: str) -> list[ZfsImportable]:
    """Parse the candidates ``zpool import`` (with no arguments) lists.

    Args:
        text: The command's output; empty when nothing is importable.

    Returns:
        One entry per pool found on attached disks.
    """
    candidates = []
    name = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("pool:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("state:") and name is not None:
            candidates.append(
                ZfsImportable(name=name, state=stripped.split(":", 1)[1].strip())
            )
            name = None
    return candidates


class ZfsDiskScanner:
    """Finds the machine's disks and what they are doing."""

    def scan(self, *, pool_members: dict[str, str] | None = None) -> list[ZfsDisk]:
        """Read every whole disk on the box.

        Args:
            pool_members: Map from a member device name (as ``zpool status``
                prints it) to its pool, used to mark disks as taken.

        Returns:
            One entry per whole disk, system disks included but marked — the
            panel shows them nowhere, and this scanner is the single place
            deciding what is offerable.
        """
        members = pool_members or {}
        result = run(
            [
                "lsblk",
                "--json",
                "--bytes",
                "-o",
                "NAME,PATH,SIZE,TYPE,MODEL,SERIAL,ROTA,TRAN,WWN,MOUNTPOINTS,FSTYPE",
            ],
            is_checked=False,
        )
        if not result.is_success:
            return []
        by_id = self._by_id_links()
        by_path = self._by_path_links()
        disks = []
        for entry in json.loads(result.stdout or "{}").get("blockdevices", []):
            if entry.get("type") != "disk":
                continue
            path = entry.get("path") or f"/dev/{entry['name']}"
            disk = ZfsDisk(
                device=path,
                by_id=by_id.get(entry["name"], path),
                size_bytes=int(entry.get("size") or 0),
                model=(entry.get("model") or "").strip(),
                serial=(entry.get("serial") or "").strip(),
                is_rotational=bool(entry.get("rota")),
                transport=(entry.get("tran") or "").strip(),
                wwn=(entry.get("wwn") or "").strip() or None,
                by_path=by_path.get(entry["name"]),
                fstype=entry.get("fstype") or "",
                is_system=_tree_is_mounted(entry),
            )
            disk.pool = self._pool_of(disk, entry, members)
            if not disk.is_system:
                disk.smart_passed, disk.temperature_c = self._smart(path)
            disks.append(disk)
        return disks

    def _pool_of(
        self, disk: ZfsDisk, entry: dict, members: dict[str, str]
    ) -> str | None:
        """Which imported pool holds this disk, if any.

        Matched on every name the disk answers to: the status listing prints
        whatever name the pool was created with — by-id, bare device, or a
        partition of either.
        """
        names = {disk.device.rsplit("/", 1)[-1], disk.by_id.rsplit("/", 1)[-1]}
        for child in entry.get("children") or []:
            names.add(child.get("name", ""))
        for member, pool in members.items():
            base = member.rsplit("/", 1)[-1]
            if base in names or _strip_partition(base) in names:
                return pool
        if disk.fstype == "zfs_member" and disk.pool is None:
            # A pool member the imported pools do not claim: exported or
            # foreign. Not offerable without wiping, so it reads as data.
            return None
        return None

    def _by_id_links(self) -> dict[str, str]:
        links: dict[str, dict[str, str]] = {}
        if not ZFS_DISK_BY_ID_DIR.is_dir():
            return {}
        for link in ZFS_DISK_BY_ID_DIR.iterdir():
            try:
                target = link.resolve().name
            except OSError:
                continue
            links.setdefault(target, {})[link.name] = str(link)
        preferred = {}
        for target, names in links.items():
            for prefix in DISK_ID_PREFERENCE:
                chosen = sorted(name for name in names if name.startswith(prefix))
                if chosen:
                    preferred[target] = names[chosen[0]]
                    break
        return preferred

    def _by_path_links(self) -> dict[str, str]:
        """Map each disk to its by-path name, which names the slot it sits in.

        Returns:
            Kernel device name to the by-path basename, partition links
            skipped.
        """
        directory = ZFS_DISK_BY_ID_DIR.parent / "by-path"
        if not directory.is_dir():
            return {}
        links = {}
        for link in sorted(directory.iterdir()):
            if "-part" in link.name:
                continue
            try:
                links.setdefault(link.resolve().name, link.name)
            except OSError:
                continue
        return links

    def _smart(self, device: str) -> tuple[bool | None, int | None]:
        if shutil.which("smartctl") is None:
            return None, None
        result = run(
            ["smartctl", "--health", "--attributes", "--json", device],
            is_checked=False,
            timeout_s=15,
        )
        try:
            data = json.loads(result.stdout or "{}")
        except ValueError:
            return None, None
        passed = data.get("smart_status", {}).get("passed")
        temperature = data.get("temperature", {}).get("current")
        return (
            bool(passed) if passed is not None else None,
            int(temperature) if temperature is not None else None,
        )


class ZfsPoolReader:
    """Reads the imported pools, their datasets, and the import candidates."""

    def pools(self) -> list[ZfsPool]:
        """Read every imported pool with its full topology.

        Returns:
            The pools, empty when there are none or the tools are absent.
        """
        listing = run(
            [
                "zpool",
                "list",
                "-Hp",
                "-o",
                "name,size,allocated,capacity,fragmentation,health",
            ],
            is_checked=False,
        )
        if not listing.is_success:
            return []
        pools = []
        for line in listing.stdout.splitlines():
            columns = line.split("\t")
            if len(columns) < 6:
                continue
            status = run(["zpool", "status", columns[0]], is_checked=False)
            vdevs, scan, state, errors = parse_zpool_status(status.stdout)
            pools.append(
                ZfsPool(
                    name=columns[0],
                    state=state or columns[5],
                    size_bytes=int(columns[1]),
                    allocated_bytes=int(columns[2]),
                    capacity_percent=_as_count(columns[3]),
                    fragmentation_percent=_as_count(columns[4]),
                    vdevs=vdevs,
                    scan=scan,
                    errors=errors,
                )
            )
        return pools

    def datasets(self) -> list[ZfsDataset]:
        """Read every filesystem dataset across the pools.

        Returns:
            The datasets, pool roots included.
        """
        result = run(
            [
                "zfs",
                "list",
                "-Hp",
                "-t",
                "filesystem",
                "-o",
                "name,used,avail,recordsize,mountpoint,compression,compressratio",
            ],
            is_checked=False,
        )
        if not result.is_success:
            return []
        datasets = []
        for line in result.stdout.splitlines():
            columns = line.split("\t")
            if len(columns) < 7:
                continue
            datasets.append(
                ZfsDataset(
                    name=columns[0],
                    used_bytes=int(columns[1]),
                    available_bytes=int(columns[2]),
                    recordsize_bytes=int(columns[3]),
                    mountpoint=columns[4],
                    compression=columns[5],
                    compressratio=_as_ratio(columns[6]),
                )
            )
        return datasets

    def member_pools(self, pools: list[ZfsPool]) -> dict[str, str]:
        """Map every member device name to its pool.

        Args:
            pools: The pools as :meth:`pools` returned them.

        Returns:
            Device name (as status prints it) to pool name.
        """
        members = {}
        for pool in pools:
            for vdev in pool.vdevs:
                for member in vdev.members:
                    members[member.name] = pool.name
        return members

    def importable(self) -> list[ZfsImportable]:
        """Find exported or foreign pools sitting on attached disks.

        Returns:
            The candidates, empty when there are none.
        """
        result = run(["zpool", "import"], is_checked=False, timeout_s=60)
        return parse_zpool_import(result.stdout)


class ZfsPoolManager:
    """The guarded verbs on pools. Nothing here asks twice; the panel does."""

    def create(
        self,
        *,
        name: str,
        layout: str,
        devices: list[str],
        is_forced: bool = False,
    ) -> None:
        """Create a pool with one vdev.

        The defaults are chosen once, here, and are not settings: ashift for
        4K sectors, zstd everywhere, no atime writes, ACLs the way Samba
        wants them.

        Args:
            name: Pool name.
            layout: One of the offered vdev layouts.
            devices: by-id paths of the member disks.
            is_forced: Pass ``-f``: overwrite old filesystem signatures, or
                accept members whose sizes or layouts zpool would question.
        """
        run(
            [
                "zpool",
                "create",
                *self._create_arguments(name, layout, devices, is_forced),
            ],
            timeout_s=120,
        )

    def add_vdev(
        self,
        *,
        pool: str,
        layout: str,
        devices: list[str],
        is_forced: bool = False,
    ) -> None:
        """Grow a pool by another vdev, which is permanent.

        Args:
            pool: The pool to grow.
            layout: The new vdev's layout.
            devices: by-id paths of its disks.
            is_forced: Pass ``-f``: overwrite old filesystem signatures, or
                accept a vdev whose layout mismatches the pool's.
        """
        arguments = ["zpool", "add"]
        if is_forced:
            arguments.append("-f")
        arguments.append(pool)
        arguments += _vdev_arguments(layout, devices)
        run(arguments, timeout_s=120)

    def destroy(self, name: str) -> None:
        """Destroy a pool and everything on it.

        Args:
            name: The pool. The typed confirmation happened in the panel.
        """
        run(["zpool", "destroy", name], timeout_s=120)

    def import_pool(self, name: str) -> None:
        """Import a pool found on attached disks.

        Args:
            name: The pool, as ``zpool import`` listed it.
        """
        run(["zpool", "import", name], timeout_s=300)

    def start_scrub(self, name: str) -> None:
        """Start scrubbing a pool.

        Args:
            name: The pool.
        """
        run(["zpool", "scrub", name])

    def stop_scrub(self, name: str) -> None:
        """Stop a running scrub.

        Args:
            name: The pool.
        """
        run(["zpool", "scrub", "-s", name], is_checked=False)

    def replace(self, *, pool: str, old_device: str, new_device: str) -> None:
        """Replace a member disk, kicking off the resilver.

        Args:
            pool: The pool.
            old_device: The member as the topology names it.
            new_device: by-id path of the replacement.
        """
        run(["zpool", "replace", pool, old_device, new_device], timeout_s=120)

    def offline(self, *, pool: str, device: str) -> None:
        """Take a member disk offline, for pulling it.

        Args:
            pool: The pool.
            device: The member as the topology names it.
        """
        run(["zpool", "offline", pool, device])

    def online(self, *, pool: str, device: str) -> None:
        """Bring an offlined member back.

        Args:
            pool: The pool.
            device: The member as the topology names it.
        """
        run(["zpool", "online", pool, device])

    def _create_arguments(
        self, name: str, layout: str, devices: list[str], is_forced: bool
    ) -> list[str]:
        arguments = []
        if is_forced:
            arguments.append("-f")
        arguments += [
            "-o",
            "ashift=12",
            "-o",
            "autotrim=on",
            "-O",
            "compression=lz4",
            "-O",
            "atime=off",
            "-O",
            "xattr=sa",
            "-O",
            "acltype=posixacl",
            "-O",
            "aclinherit=passthrough",
            "-O",
            "normalization=formD",
            "-O",
            "dnodesize=auto",
            name,
        ]
        arguments += _vdev_arguments(layout, devices)
        return arguments


class ZfsDatasetManager:
    """The verbs on datasets."""

    def create(
        self,
        *,
        pool: str,
        name: str,
        compression: str,
        recordsize: str,
        mountpoint: str | None = None,
    ) -> None:
        """Create a dataset. Its tunables are fixed here, for its lifetime.

        ``-p`` creates missing parents on the way, so ``nfs/home`` works
        before ``nfs`` was ever made; the parents take the pool's defaults.

        Args:
            pool: The pool it lives in.
            name: The dataset's path under the pool, slashes allowed.
            compression: One of the offered compressions.
            recordsize: One of the offered recordsizes.
            mountpoint: Where to mount it; None keeps ZFS's ``/pool/name``.
        """
        arguments = [
            "zfs",
            "create",
            "-p",
            "-o",
            f"compression={compression}",
            "-o",
            f"recordsize={recordsize}",
        ]
        if mountpoint is not None:
            arguments += ["-o", f"mountpoint={mountpoint}"]
        run([*arguments, f"{pool}/{name}"])

    def destroy(self, dataset: str) -> None:
        """Destroy a dataset and its files.

        Deliberately not recursive: a dataset with children refuses, and the
        refusal is surfaced rather than overridden.

        Args:
            dataset: Full dataset name.
        """
        run(["zfs", "destroy", dataset], timeout_s=120)


def _vdev_arguments(layout: str, devices: list[str]) -> list[str]:
    if layout not in ZFS_VDEV_LAYOUTS:
        raise ValueError(f"unknown vdev layout {layout!r}")
    if layout == "single":
        return list(devices)
    return [layout if layout != "mirror" else "mirror", *devices]


def _tree_is_mounted(entry: dict) -> bool:
    mounts = [mount for mount in entry.get("mountpoints") or [] if mount]
    if mounts:
        return True
    return any(_tree_is_mounted(child) for child in entry.get("children") or [])


def _strip_partition(name: str) -> str:
    stripped = name.rstrip("0123456789")
    if stripped.endswith("-part"):
        return stripped[: -len("-part")]
    if stripped.endswith("p") and stripped[:-1] and stripped[:-1][-1].isdigit():
        return stripped[:-1]
    return stripped


def _as_count(value: str) -> int:
    try:
        return int(value.rstrip("%"))
    except ValueError:
        return 0


def _as_ratio(value: str) -> float:
    try:
        return float(value.rstrip("x"))
    except ValueError:
        return 1.0
