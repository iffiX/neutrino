"""Reading and driving ZFS: disks, pools, datasets.

Everything here talks to the machine through ``lsblk``, ``smartctl``,
``zpool`` and ``zfs``. The only text parsing is ``zpool status`` and
``zpool import``, which have no machine format on the OpenZFS this targets;
those parsers are module-level functions so they can be tested on canned
output without a pool in sight.

Not pure: runs the storage tools and writes the modprobe option.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field

from neutrino_agent.modules.subprocess_run import CommandError, run
from neutrino_agent.modules.zfs.constants import (
    ZFS_ARC_MAX_FRACTION,
    ZFS_ARC_MAX_PARAMETER,
    ZFS_DISK_BY_ID_DIR,
    ZFS_DISK_BY_PATH_DIR,
    ZFS_DISK_ID_PREFERENCE,
    ZFS_MEMINFO_PATH,
    ZFS_MODPROBE_CONF,
    ZFS_TRANSIENT_GROUP_PREFIXES,
    ZFS_VDEV_GROUP_PREFIXES,
    ZFS_VDEV_LAYOUTS,
)


@dataclass
class ZfsDisk:
    """One physical disk as the panel sees it."""

    device: str
    by_id: str
    size_bytes: int
    model: str
    serial: str
    is_rotational: bool
    transport: str = ""
    wwn: "str | None" = None
    by_path: "str | None" = None
    fstype: str = ""
    pool: "str | None" = None
    is_system: bool = False
    smart_passed: "bool | None" = None
    temperature_c: "int | None" = None

    @property
    def is_available(self) -> bool:
        """Whether this disk can be offered for a new vdev."""
        return self.pool is None and not self.is_system

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "by_id": self.by_id,
            "size_bytes": self.size_bytes,
            "model": self.model,
            "serial": self.serial,
            "is_rotational": self.is_rotational,
            "transport": self.transport,
            "wwn": self.wwn,
            "by_path": self.by_path,
            "fstype": self.fstype,
            "pool": self.pool,
            "is_available": self.is_available,
            "smart_passed": self.smart_passed,
            "temperature_c": self.temperature_c,
        }


@dataclass
class ZfsVdevMember:
    """One device inside a vdev."""

    name: str
    state: str
    read_errors: int = 0
    write_errors: int = 0
    checksum_errors: int = 0
    is_resilvering: bool = False


@dataclass
class ZfsVdev:
    """One vdev of a pool."""

    name: str
    layout: str
    state: str
    members: list = field(default_factory=list)


@dataclass
class ZfsScanStatus:
    """What the pool's scrub or resilver is doing."""

    kind: "str | None" = None
    percent: "float | None" = None
    eta: "str | None" = None
    summary: str = ""


@dataclass
class ZfsPool:
    """One imported pool."""

    name: str
    state: str
    size_bytes: int
    allocated_bytes: int
    capacity_percent: int
    fragmentation_percent: int
    vdevs: list = field(default_factory=list)
    scan: ZfsScanStatus = field(default_factory=ZfsScanStatus)
    errors: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "size_bytes": self.size_bytes,
            "allocated_bytes": self.allocated_bytes,
            "capacity_percent": self.capacity_percent,
            "fragmentation_percent": self.fragmentation_percent,
            "vdevs": [
                {
                    "name": vdev.name,
                    "layout": vdev.layout,
                    "state": vdev.state,
                    "members": [vars(member) for member in vdev.members],
                }
                for vdev in self.vdevs
            ],
            "scan": vars(self.scan),
            "errors": self.errors,
        }


@dataclass
class ZfsDataset:
    """One filesystem dataset."""

    name: str
    used_bytes: int
    available_bytes: int
    mountpoint: str
    compression: str
    compressratio: float
    recordsize_bytes: int = 131072

    def to_dict(self) -> dict:
        return dict(vars(self))


@dataclass
class ZfsImportable:
    """A pool sitting on attached disks, waiting to be imported."""

    name: str
    state: str


def is_zfs_installed() -> bool:
    """Whether the ZFS userland tools are present."""
    return shutil.which("zpool") is not None


def parse_zpool_status(text: str) -> tuple:
    """Parse one pool's ``zpool status`` output.

    The config tree is indentation-structured: the pool at the root, vdev
    groups one level in, members below them. A bare device at vdev level
    is a single-disk vdev. Transient groups are flattened into the
    enclosing vdev.

    Args:
        text: Output of ``zpool status <pool>``.

    Returns:
        ``(vdevs, scan, pool_state, errors)``.
    """
    vdevs: list = []
    scan = ZfsScanStatus()
    pool_state = ""
    errors = ""
    scan_lines: list = []
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
        # A tab prefixes the whole tree; every level below the pool adds
        # two spaces.
        indent = len(line.expandtabs(0)) - len(line.expandtabs(0).lstrip())
        depth = indent // 2
        name = columns[0]
        state = columns[1] if len(columns) > 1 else ""
        counts = [_as_count(value) for value in columns[2:5]]
        while len(counts) < 3:
            counts.append(0)
        member = ZfsVdevMember(
            name=name,
            state=state,
            read_errors=counts[0],
            write_errors=counts[1],
            checksum_errors=counts[2],
            is_resilvering="(resilvering)" in stripped,
        )
        if depth == 0:
            continue
        if depth == 1:
            if name.startswith(ZFS_VDEV_GROUP_PREFIXES):
                layout = name.split("-", 1)[0]
                vdevs.append(ZfsVdev(name=name, layout=layout, state=state))
            else:
                vdevs.append(
                    ZfsVdev(name=name, layout="single", state=state, members=[member])
                )
            continue
        if not vdevs or name.startswith(ZFS_TRANSIENT_GROUP_PREFIXES):
            continue
        vdevs[-1].members.append(member)

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


def parse_zpool_import(text: str) -> list:
    """Parse the candidates ``zpool import`` (with no arguments) lists.

    Args:
        text: The command's output; empty when nothing is importable.

    Returns:
        One :class:`ZfsImportable` per pool found on attached disks.
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


def cap_arc() -> str:
    """Hold the ARC to a quarter of memory instead of its default half.

    Returns:
        A note when the option was written, empty otherwise.
    """
    arc_max = int(_total_memory_bytes() * ZFS_ARC_MAX_FRACTION)
    if arc_max <= 0:
        return ""
    wanted = (
        "# Generated by neutrino. Do not edit; the ZFS module owns it.\n"
        f"options zfs zfs_arc_max={arc_max}\n"
    )
    note = ""
    if _read(ZFS_MODPROBE_CONF) != wanted:
        os.makedirs(os.path.dirname(ZFS_MODPROBE_CONF), exist_ok=True)
        with open(ZFS_MODPROBE_CONF, "w", encoding="utf-8") as stream:
            stream.write(wanted)
        note = f"capped the ARC at {arc_max // (1024 * 1024)} MiB"
    if os.path.isfile(ZFS_ARC_MAX_PARAMETER):
        try:
            with open(ZFS_ARC_MAX_PARAMETER, "w", encoding="utf-8") as stream:
                stream.write(str(arc_max))
        except OSError:
            pass
    return note


class ZfsDiskScanner:
    """Finds the machine's disks and what they are doing."""

    def scan(self, *, pool_members: "dict | None" = None, is_smart: bool = False):
        """Read every whole disk on the machine.

        Args:
            pool_members: Member device name, as ``zpool status`` prints
                it, to its pool, used to mark disks as taken.
            is_smart: Whether to ask each disk for its SMART verdict, which
                takes seconds per disk.

        Returns:
            One :class:`ZfsDisk` per whole disk, system disks marked.
        """
        members = pool_members or {}
        try:
            result = run(
                [
                    "lsblk",
                    "--json",
                    "--bytes",
                    "-o",
                    "NAME,PATH,SIZE,TYPE,MODEL,SERIAL,ROTA,TRAN,WWN,MOUNTPOINTS,FSTYPE",
                ],
                is_checked=False,
                timeout_s=30,
            )
        except CommandError:
            return []
        if not result.is_success:
            return []
        try:
            entries = json.loads(result.stdout or "{}").get("blockdevices", [])
        except ValueError:
            return []
        by_id = self._by_id_links()
        by_path = self._by_path_links()
        disks = []
        for entry in entries:
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
            if is_smart and not disk.is_system:
                disk.smart_passed, disk.temperature_c = self._smart(path)
            disks.append(disk)
        return disks

    def _pool_of(self, disk: ZfsDisk, entry: dict, members: dict) -> "str | None":
        names = {disk.device.rsplit("/", 1)[-1], disk.by_id.rsplit("/", 1)[-1]}
        for child in entry.get("children") or []:
            names.add(child.get("name", ""))
        for member, pool in members.items():
            base = member.rsplit("/", 1)[-1]
            if base in names or _strip_partition(base) in names:
                return pool
        return None

    def _by_id_links(self) -> dict:
        if not os.path.isdir(ZFS_DISK_BY_ID_DIR):
            return {}
        links: dict = {}
        for name in os.listdir(ZFS_DISK_BY_ID_DIR):
            link = os.path.join(ZFS_DISK_BY_ID_DIR, name)
            try:
                target = os.path.basename(os.path.realpath(link))
            except OSError:
                continue
            links.setdefault(target, {})[name] = link
        preferred = {}
        for target, names in links.items():
            for prefix in ZFS_DISK_ID_PREFERENCE:
                chosen = sorted(name for name in names if name.startswith(prefix))
                if chosen:
                    preferred[target] = names[chosen[0]]
                    break
        return preferred

    def _by_path_links(self) -> dict:
        if not os.path.isdir(ZFS_DISK_BY_PATH_DIR):
            return {}
        links = {}
        for name in sorted(os.listdir(ZFS_DISK_BY_PATH_DIR)):
            if "-part" in name:
                continue
            try:
                target = os.path.basename(
                    os.path.realpath(os.path.join(ZFS_DISK_BY_PATH_DIR, name))
                )
            except OSError:
                continue
            links.setdefault(target, name)
        return links

    def _smart(self, device: str) -> tuple:
        if shutil.which("smartctl") is None:
            return None, None
        try:
            result = run(
                ["smartctl", "--health", "--attributes", "--json", device],
                is_checked=False,
                timeout_s=15,
            )
            data = json.loads(result.stdout or "{}")
        except (CommandError, ValueError):
            return None, None
        passed = data.get("smart_status", {}).get("passed")
        temperature = data.get("temperature", {}).get("current")
        return (
            bool(passed) if passed is not None else None,
            int(temperature) if temperature is not None else None,
        )


class ZfsPoolReader:
    """Reads the imported pools, their datasets, and the import candidates."""

    def pools(self) -> list:
        """Read every imported pool with its full topology.

        Returns:
            The :class:`ZfsPool` list, empty when there are none.
        """
        try:
            listing = run(
                [
                    "zpool",
                    "list",
                    "-Hp",
                    "-o",
                    "name,size,allocated,capacity,fragmentation,health",
                ],
                is_checked=False,
                timeout_s=30,
            )
        except CommandError:
            return []
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

    def datasets(self) -> list:
        """Read every filesystem dataset across the pools.

        Returns:
            The :class:`ZfsDataset` list, pool roots included.
        """
        try:
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
                timeout_s=30,
            )
        except CommandError:
            return []
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

    def member_pools(self, pools: list) -> dict:
        """Map every member device name to its pool."""
        members = {}
        for pool in pools:
            for vdev in pool.vdevs:
                for member in vdev.members:
                    members[member.name] = pool.name
        return members

    def importable(self) -> list:
        """Find exported or foreign pools sitting on attached disks."""
        try:
            result = run(["zpool", "import"], is_checked=False, timeout_s=60)
        except CommandError:
            return []
        return parse_zpool_import(result.stdout)


class ZfsPoolManager:
    """The guarded verbs on pools. Nothing here asks twice; the panel does."""

    def create(
        self, *, name: str, layout: str, devices: list, is_forced: bool = False
    ) -> None:
        """Create a pool with one vdev, on defaults chosen once here."""
        arguments = ["zpool", "create"]
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
        run(arguments + vdev_arguments(layout, devices), timeout_s=120)

    def add_vdev(
        self, *, pool: str, layout: str, devices: list, is_forced: bool = False
    ) -> None:
        """Grow a pool by another vdev, which is permanent."""
        arguments = ["zpool", "add"]
        if is_forced:
            arguments.append("-f")
        arguments.append(pool)
        run(arguments + vdev_arguments(layout, devices), timeout_s=120)

    def destroy(self, name: str) -> None:
        """Destroy a pool and everything on it."""
        run(["zpool", "destroy", name], timeout_s=120)

    def import_pool(self, name: str) -> None:
        """Import a pool found on attached disks."""
        run(["zpool", "import", name], timeout_s=300)

    def start_scrub(self, name: str) -> None:
        """Start scrubbing a pool."""
        run(["zpool", "scrub", name])

    def stop_scrub(self, name: str) -> None:
        """Stop a running scrub."""
        run(["zpool", "scrub", "-s", name], is_checked=False)

    def replace(self, *, pool: str, old_device: str, new_device: str) -> None:
        """Replace a member disk, kicking off the resilver."""
        run(["zpool", "replace", pool, old_device, new_device], timeout_s=120)

    def offline(self, *, pool: str, device: str) -> None:
        """Take a member disk offline, for pulling it."""
        run(["zpool", "offline", pool, device])

    def online(self, *, pool: str, device: str) -> None:
        """Bring an offlined member back."""
        run(["zpool", "online", pool, device])


class ZfsDatasetManager:
    """The verbs on datasets."""

    def create(
        self,
        *,
        pool: str,
        name: str,
        compression: str,
        recordsize: str,
        mountpoint: "str | None" = None,
    ) -> None:
        """Create a dataset, parents included, its tunables fixed for life."""
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
        run(arguments + [f"{pool}/{name}"])

    def destroy(self, dataset: str) -> None:
        """Destroy a dataset and its files; a dataset with children refuses."""
        run(["zfs", "destroy", dataset], timeout_s=120)


def vdev_arguments(layout: str, devices: list) -> list:
    """The vdev part of a create or add command.

    Args:
        layout: One of the offered layouts.
        devices: The member disks.

    Returns:
        The arguments.

    Raises:
        ValueError: For a layout outside the table.
    """
    if layout not in ZFS_VDEV_LAYOUTS:
        raise ValueError(layout)
    if layout == "single":
        return list(devices)
    return [layout, *devices]


def _tree_is_mounted(entry: dict) -> bool:
    if any(mount for mount in entry.get("mountpoints") or [] if mount):
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


def _total_memory_bytes() -> int:
    try:
        with open(ZFS_MEMINFO_PATH, "r", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _read(path: str) -> "str | None":
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return None
