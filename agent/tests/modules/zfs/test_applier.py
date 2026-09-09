"""Parsing zpool's human output, and driving the tools with them replaced."""

import pytest

from neutrino_agent.modules.subprocess_run import CommandResult
from neutrino_agent.modules.zfs import applier as applier_module
from neutrino_agent.modules.zfs.applier import (
    ZfsDatasetManager,
    ZfsDiskScanner,
    ZfsPoolManager,
    ZfsPoolReader,
    cap_arc,
    parse_zpool_import,
    parse_zpool_status,
    vdev_arguments,
)

HEALTHY = """\
  pool: tank
 state: ONLINE
  scan: scrub repaired 0B in 00:00:01 with 0 errors on Fri Aug 29 10:00:01 2026
config:

\tNAME                        STATE     READ WRITE CKSUM
\ttank                        ONLINE       0     0     0
\t  raidz1-0                  ONLINE       0     0     0
\t    scsi-333333330000007d0  ONLINE       0     0     0
\t    scsi-33333333000000bb8  ONLINE       0     0     0
\t    scsi-33333333000000fa0  ONLINE       0     0     0
\t  mirror-1                  ONLINE       0     0     0
\t    scsi-33333333000001388  ONLINE       0     0     0
\t    scsi-33333333000001770  ONLINE       0     0     0

errors: No known data errors
"""

RESILVERING = """\
  pool: tank
 state: DEGRADED
status: One or more devices is currently being resilvered.
action: Wait for the resilver to complete.
  scan: resilver in progress since Fri Aug 29 10:05:00 2026
\t120M / 300M scanned at 60M/s, 80M issued at 40M/s, 300M total
\t0B resilvered, 26.67% done, 00:00:05 to go
config:

\tNAME                          STATE     READ WRITE CKSUM
\ttank                          DEGRADED     0     0     0
\t  raidz1-0                    DEGRADED     0     0     0
\t    scsi-333333330000007d0    ONLINE       0     0     0
\t    replacing-1               DEGRADED     0     0     0
\t      scsi-33333333000000bb8  OFFLINE      3     1     0
\t      scsi-33333333000001b58  ONLINE       0     0     0  (resilvering)
\t    scsi-33333333000000fa0    ONLINE       0     0     0

errors: No known data errors
"""

SINGLE = """\
  pool: scratch
 state: ONLINE
  scan: none requested
config:

\tNAME                      STATE     READ WRITE CKSUM
\tscratch                   ONLINE       0     0     0
\t  scsi-33333333000001f40  ONLINE       0     0     0

errors: No known data errors
"""

IMPORTABLE = """\
   pool: backup
     id: 1234567890
  state: ONLINE
status: The pool was last accessed by another system.
 action: The pool can be imported using its name or numeric identifier.
 config:

\tbackup      ONLINE
\t  mirror-0  ONLINE
"""


class FakeCommands:
    def __init__(self, answers=None):
        self.calls: list = []
        self.answers = dict(answers or {})

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        exit_code, stdout = self.answers.get(tuple(command[:2]), (0, ""))
        return CommandResult(list(command), exit_code, stdout, "")


@pytest.fixture
def commands(monkeypatch):
    held = FakeCommands()
    monkeypatch.setattr(applier_module, "run", held)
    return held


def test_a_healthy_pool_parses_into_its_vdevs():
    vdevs, scan, state, errors = parse_zpool_status(HEALTHY)

    assert state == "ONLINE"
    assert errors == ""
    assert [vdev.layout for vdev in vdevs] == ["raidz1", "mirror"]
    assert [len(vdev.members) for vdev in vdevs] == [3, 2]
    assert scan.kind is None
    assert scan.summary.startswith("scrub repaired 0B")


def test_a_replacing_disk_flattens_into_its_vdev():
    vdevs, scan, state, _ = parse_zpool_status(RESILVERING)

    assert state == "DEGRADED"
    members = vdevs[0].members
    assert [member.name for member in members] == [
        "scsi-333333330000007d0",
        "scsi-33333333000000bb8",
        "scsi-33333333000001b58",
        "scsi-33333333000000fa0",
    ]
    assert members[1].state == "OFFLINE"
    assert (members[1].read_errors, members[1].write_errors) == (3, 1)
    assert members[2].is_resilvering
    assert (scan.kind, scan.percent, scan.eta) == ("resilver", 26.67, "00:00:05")


def test_a_bare_disk_is_a_single_vdev():
    vdevs, scan, state, _ = parse_zpool_status(SINGLE)

    assert state == "ONLINE"
    assert vdevs[0].layout == "single"
    assert vdevs[0].members[0].name == "scsi-33333333000001f40"
    assert scan.kind is None and scan.summary == ""


def test_import_candidates_are_listed_by_name_and_state():
    candidates = parse_zpool_import(IMPORTABLE)

    assert [(c.name, c.state) for c in candidates] == [("backup", "ONLINE")]
    assert parse_zpool_import("") == []


def test_pools_read_the_listing_then_each_status(commands):
    commands.answers[("zpool", "list")] = (0, "tank\t1000\t400\t40\t3\tONLINE\n")
    commands.answers[("zpool", "status")] = (0, HEALTHY)

    (pool,) = ZfsPoolReader().pools()

    assert (pool.name, pool.size_bytes, pool.capacity_percent) == ("tank", 1000, 40)
    assert [vdev.layout for vdev in pool.vdevs] == ["raidz1", "mirror"]
    assert pool.to_dict()["vdevs"][0]["members"][0]["name"] == "scsi-333333330000007d0"
    members = ZfsPoolReader().member_pools([pool])
    assert members["scsi-33333333000001770"] == "tank"


def test_datasets_read_every_column(commands):
    commands.answers[("zfs", "list")] = (
        0,
        "tank\t100\t900\t131072\t/tank\tlz4\t1.85x\ntank/a\t10\t900\t16384\t/srv/a\tzstd\t1.00x\n",
    )

    datasets = ZfsPoolReader().datasets()

    assert [d.name for d in datasets] == ["tank", "tank/a"]
    assert datasets[0].compressratio == 1.85
    assert datasets[1].recordsize_bytes == 16384
    assert datasets[1].mountpoint == "/srv/a"


def test_no_tools_reads_as_nothing(commands):
    commands.answers[("zpool", "list")] = (1, "")
    commands.answers[("zfs", "list")] = (127, "")

    assert ZfsPoolReader().pools() == []
    assert ZfsPoolReader().datasets() == []


def test_the_scan_marks_system_and_pool_disks_and_skips_smart_by_default(
    commands, monkeypatch
):
    commands.answers[("lsblk", "--json")] = (
        0,
        '{"blockdevices": ['
        '{"name": "sda", "path": "/dev/sda", "size": 10, "type": "disk", "model": "A", '
        '"serial": "1", "rota": true, "tran": "sata", "wwn": null, "mountpoints": [null], '
        '"fstype": null, "children": [{"name": "sda1", "mountpoints": ["/"]}]},'
        '{"name": "sdb", "path": "/dev/sdb", "size": 20, "type": "disk", "model": "B", '
        '"serial": "2", "rota": false, "tran": "nvme", "wwn": "0x1", "mountpoints": [null], '
        '"fstype": "zfs_member"},'
        '{"name": "sdc", "path": "/dev/sdc", "size": 30, "type": "disk", "model": "C", '
        '"serial": "3", "rota": false, "tran": "usb", "wwn": null, "mountpoints": [null], '
        '"fstype": null}]}',
    )
    monkeypatch.setattr(
        applier_module.shutil, "which", lambda name: "/usr/sbin/smartctl"
    )

    disks = ZfsDiskScanner().scan(pool_members={"sdb": "tank"})

    by_device = {disk.device: disk for disk in disks}
    assert by_device["/dev/sda"].is_system is True
    assert by_device["/dev/sdb"].pool == "tank"
    assert by_device["/dev/sdb"].is_available is False
    assert by_device["/dev/sdc"].is_available is True
    assert by_device["/dev/sdc"].smart_passed is None
    assert not any(call[0] == "smartctl" for call in commands.calls)


def test_a_smart_scan_asks_every_non_system_disk(commands, monkeypatch):
    commands.answers[("lsblk", "--json")] = (
        0,
        '{"blockdevices": [{"name": "sdc", "path": "/dev/sdc", "size": 30, "type": "disk", '
        '"model": "C", "serial": "3", "rota": false, "mountpoints": [null]}]}',
    )
    commands.answers[("smartctl", "--health")] = (
        0,
        '{"smart_status": {"passed": true}, "temperature": {"current": 41}}',
    )
    monkeypatch.setattr(
        applier_module.shutil, "which", lambda name: "/usr/sbin/smartctl"
    )

    (disk,) = ZfsDiskScanner().scan(is_smart=True)

    assert (disk.smart_passed, disk.temperature_c) == (True, 41)


def test_create_uses_the_fixed_defaults_and_the_layout(commands):
    ZfsPoolManager().create(
        name="tank", layout="mirror", devices=["/dev/a", "/dev/b"], is_forced=True
    )

    (call,) = commands.calls
    assert call[:3] == ["zpool", "create", "-f"]
    assert "compression=lz4" in call and "ashift=12" in call
    assert call[-3:] == ["mirror", "/dev/a", "/dev/b"]


def test_vdev_arguments_spell_the_layout():
    assert vdev_arguments("single", ["a"]) == ["a"]
    assert vdev_arguments("raidz1", ["a", "b", "c"]) == ["raidz1", "a", "b", "c"]
    with pytest.raises(ValueError):
        vdev_arguments("stripe", ["a"])


def test_the_pool_verbs_map_onto_zpool(commands):
    pools = ZfsPoolManager()
    pools.add_vdev(pool="tank", layout="single", devices=["/dev/c"])
    pools.destroy("tank")
    pools.import_pool("backup")
    pools.start_scrub("tank")
    pools.stop_scrub("tank")
    pools.replace(pool="tank", old_device="a", new_device="b")
    pools.offline(pool="tank", device="a")
    pools.online(pool="tank", device="a")

    assert commands.calls == [
        ["zpool", "add", "tank", "/dev/c"],
        ["zpool", "destroy", "tank"],
        ["zpool", "import", "backup"],
        ["zpool", "scrub", "tank"],
        ["zpool", "scrub", "-s", "tank"],
        ["zpool", "replace", "tank", "a", "b"],
        ["zpool", "offline", "tank", "a"],
        ["zpool", "online", "tank", "a"],
    ]


def test_the_dataset_verbs_map_onto_zfs(commands):
    ZfsDatasetManager().create(
        pool="tank",
        name="nfs/home",
        compression="zstd",
        recordsize="1M",
        mountpoint="/srv/h",
    )
    ZfsDatasetManager().destroy("tank/nfs/home")

    assert commands.calls == [
        [
            "zfs",
            "create",
            "-p",
            "-o",
            "compression=zstd",
            "-o",
            "recordsize=1M",
            "-o",
            "mountpoint=/srv/h",
            "tank/nfs/home",
        ],
        ["zfs", "destroy", "tank/nfs/home"],
    ]


def test_the_arc_cap_is_written_once_and_poked_live(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       8000000 kB\n")
    conf = tmp_path / "modprobe.d/zfs.conf"
    parameter = tmp_path / "zfs_arc_max"
    parameter.write_text("0")
    monkeypatch.setattr(applier_module, "ZFS_MEMINFO_PATH", str(meminfo))
    monkeypatch.setattr(applier_module, "ZFS_MODPROBE_CONF", str(conf))
    monkeypatch.setattr(applier_module, "ZFS_ARC_MAX_PARAMETER", str(parameter))

    note = cap_arc()

    assert "capped the ARC" in note
    assert "zfs_arc_max=2048000000" in conf.read_text()
    assert parameter.read_text() == "2048000000"
    assert cap_arc() == ""
