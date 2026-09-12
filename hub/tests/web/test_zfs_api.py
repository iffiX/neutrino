"""The ZFS page's per-device API, with the agent underneath replaced.

The picture comes from the device's last report; every verb runs on the
device and answers the fresh view; sharing a dataset writes the device's
Samba configuration through the same checked door every save uses.
"""

import pytest

from neutrino_hub.web.routers import zfs as zfs_router
from tests.web.module_api_box import DEVICE, HOST, OFFLINE, module_box

BASE = f"/api/zfs/devices/{DEVICE}"

POOL = {
    "name": "tank",
    "state": "ONLINE",
    "size_bytes": 1000,
    "allocated_bytes": 400,
    "capacity_percent": 40,
    "fragmentation_percent": 1,
    "vdevs": [
        {
            "name": "mirror-0",
            "layout": "mirror",
            "state": "ONLINE",
            "members": [
                {"name": "a", "state": "ONLINE"},
                {"name": "b", "state": "ONLINE"},
            ],
        }
    ],
    "scan": {"kind": None, "percent": None, "eta": None, "summary": ""},
    "errors": "",
}
DATASETS = [
    {
        "name": "tank",
        "used_bytes": 400,
        "available_bytes": 600,
        "mountpoint": "/tank",
        "compression": "lz4",
        "compressratio": 1.0,
        "recordsize_bytes": 131072,
    },
    {
        "name": "tank/media",
        "used_bytes": 10,
        "available_bytes": 600,
        "mountpoint": "/srv/media",
        "compression": "zstd",
        "compressratio": 1.5,
        "recordsize_bytes": 1048576,
    },
]
DISK = {
    "device": "/dev/sdc",
    "by_id": "/dev/disk/by-id/ata-c",
    "size_bytes": 30,
    "model": "C",
    "serial": "3",
    "is_rotational": False,
    "is_available": True,
}


@pytest.fixture
def box(monkeypatch, tmp_path):
    client, runtime = module_box(monkeypatch, tmp_path, zfs_router.router)
    runtime.report(
        DEVICE,
        "zfs",
        "installed",
        pools=[POOL],
        datasets=DATASETS,
        disks=[DISK],
        importable=[],
    )
    runtime.desired_states.set_enabled(DEVICE, "samba", True)
    runtime.desired_states.write(
        DEVICE,
        "samba",
        {"shares": [{"name": "old", "path": "/srv/old"}], "users": ["ann"]},
    )
    runtime.report(DEVICE, "samba", "installed", is_active=True)
    with client:
        yield client, runtime


def test_the_view_nests_datasets_under_their_pool_with_their_share(box):
    client, runtime = box
    runtime.desired_states.write(
        DEVICE,
        "samba",
        {"shares": [{"name": "media", "path": "/srv/media"}], "users": ["ann"]},
    )

    payload = client.get(BASE).json()

    assert payload["is_installed"] is True
    (pool,) = payload["pools"]
    assert pool["name"] == "tank"
    assert [d["name"] for d in pool["datasets"]] == ["tank", "tank/media"]
    assert pool["datasets"][1]["share"] == "media"
    assert pool["vdevs"][0]["members"][0]["name"] == "a"
    assert payload["disks"][0]["by_id"] == "/dev/disk/by-id/ata-c"
    assert payload["samba"] == {"is_ready": True, "users": ["ann"]}
    assert (payload["device_id"], payload["host"]) == (DEVICE, HOST)


def test_samba_is_not_ready_while_it_is_off_or_down(box):
    client, runtime = box
    runtime.report(DEVICE, "samba", "installed", is_active=False)

    assert client.get(BASE).json()["samba"] == {"is_ready": False, "users": []}


def test_a_device_that_never_reported_is_not_installed(box):
    client, _ = box

    payload = client.get(f"/api/zfs/devices/{OFFLINE}").json()

    assert payload["is_installed"] is False
    assert payload["pools"] == []


@pytest.mark.parametrize(
    "method, path, body, op, args",
    [
        (
            "post",
            "/pools",
            {"name": "tank", "layout": "mirror", "devices": ["a", "b"]},
            "create_pool",
            {
                "name": "tank",
                "layout": "mirror",
                "devices": ["a", "b"],
                "is_forced": False,
            },
        ),
        ("delete", "/pools/tank", None, "destroy_pool", {"name": "tank"}),
        ("post", "/pools/tank/scrub", None, "scrub", {"name": "tank"}),
        ("post", "/pools/tank/scrub/stop", None, "stop_scrub", {"name": "tank"}),
        (
            "post",
            "/pools/tank/expand",
            {"layout": "single", "devices": ["c"]},
            "expand_pool",
            {"name": "tank", "layout": "single", "devices": ["c"], "is_forced": False},
        ),
        (
            "post",
            "/pools/tank/replace",
            {"old_device": "a", "new_device": "c"},
            "replace",
            {"name": "tank", "old_device": "a", "new_device": "c"},
        ),
        (
            "post",
            "/pools/tank/offline",
            {"device": "a"},
            "offline",
            {"name": "tank", "device": "a"},
        ),
        (
            "post",
            "/pools/tank/online",
            {"device": "a"},
            "online",
            {"name": "tank", "device": "a"},
        ),
        ("post", "/import/backup", None, "import_pool", {"name": "backup"}),
        (
            "post",
            "/datasets",
            {"pool": "tank", "name": "nfs/home", "compression": "zstd"},
            "create_dataset",
            {
                "pool": "tank",
                "name": "nfs/home",
                "compression": "zstd",
                "recordsize": "128K",
                "mountpoint": None,
            },
        ),
        (
            "post",
            "/datasets/destroy",
            {"dataset": "tank/media"},
            "destroy_dataset",
            {"dataset": "tank/media"},
        ),
    ],
)
def test_each_verb_runs_its_op_on_the_device_and_answers_the_view(
    box, method, path, body, op, args
):
    client, runtime = box

    if body is None:
        response = getattr(client, method)(BASE + path)
    else:
        response = getattr(client, method)(BASE + path, json=body)

    assert response.status_code == 200, response.text
    assert (
        DEVICE,
        "zfs_op",
        {"op": op, "args": args},
    ) in runtime.agent_sessions.commands
    assert response.json()["device_id"] == DEVICE


def test_a_scan_runs_the_smart_read(box):
    client, runtime = box

    client.post(f"{BASE}/scan")

    assert runtime.agent_sessions.commands == [(DEVICE, "zfs_scan", {})]


def test_a_verb_the_agent_refuses_is_answered_with_its_code(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "pool_name_reserved",
        "params": {"name": "mirror"},
        "output": "",
    }

    response = client.post(
        f"{BASE}/pools", json={"name": "mirror", "layout": "single", "devices": ["a"]}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "pool_name_reserved",
        "params": {"name": "mirror"},
    }


def test_sharing_a_dataset_writes_the_devices_samba_through_the_checked_door(box):
    client, runtime = box

    response = client.post(
        f"{BASE}/datasets/share", json={"dataset": "tank/media", "users": ["ann"]}
    )

    assert response.status_code == 200, response.text
    key, module, checked = runtime.agent_sessions.validations[0]
    assert (key, module) == (DEVICE, "samba")
    added = checked["shares"][-1]
    assert added["name"] == "media"
    assert added["path"] == "/srv/media"
    assert added["valid_users"] == ["ann"]
    stored = runtime.desired_states.read(DEVICE, "samba")
    assert [share["name"] for share in stored["shares"]] == ["old", "media"]
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]
    assert response.json()["pools"][0]["datasets"][1]["share"] == "media"


def test_sharing_refuses_what_cannot_be_a_share(box):
    client, runtime = box

    unknown = client.post(f"{BASE}/datasets/share", json={"dataset": "tank/none"})
    ghost = client.post(
        f"{BASE}/datasets/share", json={"dataset": "tank/media", "users": ["ghost"]}
    )
    runtime.desired_states.write(
        DEVICE, "samba", {"shares": [{"name": "x", "path": "/srv/media"}], "users": []}
    )
    twice = client.post(f"{BASE}/datasets/share", json={"dataset": "tank/media"})

    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (
        404,
        "dataset_unknown",
    )
    assert (ghost.status_code, ghost.json()["detail"]["code"]) == (
        400,
        "share_user_unknown",
    )
    assert (twice.status_code, twice.json()["detail"]["code"]) == (400, "share_exists")
    assert runtime.agent_sessions.validations == []


def test_destroying_a_pool_drops_the_shares_rooted_in_it_first(box):
    client, runtime = box
    runtime.desired_states.write(
        DEVICE,
        "samba",
        {
            "shares": [
                {"name": "media", "path": "/srv/media"},
                {"name": "old", "path": "/srv/old"},
            ],
            "users": [],
        },
    )

    response = client.delete(f"{BASE}/pools/tank")

    assert response.status_code == 200
    stored = runtime.desired_states.read(DEVICE, "samba")
    assert [share["name"] for share in stored["shares"]] == ["old"]
    assert runtime.agent_sessions.validations[0][1] == "samba"
    assert runtime.agent_sessions.commands[-1] == (
        DEVICE,
        "zfs_op",
        {"op": "destroy_pool", "args": {"name": "tank"}},
    )


def test_unsharing_removes_the_share_and_touches_no_pool(box):
    client, runtime = box
    runtime.desired_states.write(
        DEVICE,
        "samba",
        {"shares": [{"name": "media", "path": "/srv/media"}], "users": []},
    )

    response = client.post(f"{BASE}/datasets/unshare", json={"dataset": "tank/media"})

    assert response.status_code == 200
    assert runtime.desired_states.read(DEVICE, "samba")["shares"] == []
    assert runtime.agent_sessions.commands == []


def test_an_offline_device_takes_no_verb(box):
    client, runtime = box

    response = client.post(f"/api/zfs/devices/{OFFLINE}/pools/tank/scrub")

    assert response.status_code == 409
    assert runtime.agent_sessions.commands == []


def test_the_view_answered_after_a_destroy_is_the_report_after_it(box):
    """The route waits for the report the agent sends behind the command
    and reads the device again from it: the pool that was just destroyed
    is gone from the answer, and the page draws that answer as it is."""
    client, runtime = box
    sessions = runtime.agent_sessions
    sessions.report_serials[DEVICE] = 3

    def machine_after(key, action, args):
        runtime.report(
            DEVICE,
            "zfs",
            "installed",
            pools=[],
            datasets=[],
            disks=[DISK],
            importable=[],
        )
        sessions.report_serials[DEVICE] = 4

    sessions.after_command = machine_after

    payload = client.delete(f"{BASE}/pools/tank").json()

    assert sessions.waited == [(DEVICE, 3, 6.0)]
    assert payload["pools"] == []
    assert [disk["device"] for disk in payload["disks"]] == ["/dev/sdc"]
