"""Parsing zpool's human output, which is the only shape this OpenZFS offers."""

from neutrino_hub.modules.zfs.ops import parse_zpool_import, parse_zpool_status

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


def test_a_healthy_pool_parses_into_its_vdevs():
    vdevs, scan, state, errors = parse_zpool_status(HEALTHY)

    assert state == "ONLINE"
    assert errors == ""
    assert [vdev.layout for vdev in vdevs] == ["raidz1", "mirror"]
    assert [len(vdev.members) for vdev in vdevs] == [3, 2]
    assert scan.kind is None
    assert scan.summary.startswith("scrub repaired 0B")


def test_a_replacing_disk_flattens_into_its_vdev():
    vdevs, scan, state, errors = parse_zpool_status(RESILVERING)

    assert state == "DEGRADED"
    members = vdevs[0].members
    assert [member.name for member in members] == [
        "scsi-333333330000007d0",
        "scsi-33333333000000bb8",
        "scsi-33333333000001b58",
        "scsi-33333333000000fa0",
    ]
    old = members[1]
    assert old.state == "OFFLINE"
    assert (old.read_errors, old.write_errors) == (3, 1)
    assert members[2].is_resilvering
    assert scan.kind == "resilver"
    assert scan.percent == 26.67
    assert scan.eta == "00:00:05"


def test_a_bare_disk_is_a_single_vdev():
    vdevs, scan, state, _ = parse_zpool_status(SINGLE)

    assert state == "ONLINE"
    assert vdevs[0].layout == "single"
    assert vdevs[0].members[0].name == "scsi-33333333000001f40"
    assert scan.kind is None and scan.summary == ""


def test_import_candidates_are_listed_by_name_and_state():
    candidates = parse_zpool_import(IMPORTABLE)

    assert len(candidates) == 1
    assert candidates[0].name == "backup"
    assert candidates[0].state == "ONLINE"
    assert parse_zpool_import("") == []
