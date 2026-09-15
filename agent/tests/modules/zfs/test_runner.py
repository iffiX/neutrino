"""The ZFS runner: the storage picture, the verbs, and the SMART scan.

The verbs are spelled without the module's name: ``op`` and ``scan``, with
``validate`` from the base. ``observe()`` reads the tools, the kernel
module and the picture in one go; there is no wanted pool list, so the
picture is what the machine has, whoever made it.
"""

import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.zfs import runner as runner_module
from neutrino_agent.modules.zfs.applier import ZfsDataset, ZfsDisk, ZfsPool
from neutrino_agent.modules.zfs.runner import ZfsModuleRunner
from neutrino_agent.platforms.base import AgentPlatform


class FakeReader:
    def pools(self):
        return [ZfsPool("tank", "ONLINE", 10, 4, 40, 1)]

    def datasets(self):
        return [ZfsDataset("tank", 4, 6, "/tank", "lz4", 1.0)]

    def member_pools(self, pools):
        return {"sdb": "tank"}

    def importable(self):
        return []


class FakeScanner:
    scans: list = []

    def scan(self, *, pool_members=None, is_smart=False):
        FakeScanner.scans.append((pool_members, is_smart))
        system = ZfsDisk("/dev/sda", "/dev/sda", 1, "", "", True, is_system=True)
        data = ZfsDisk("/dev/sdb", "/dev/disk/by-id/b", 2, "B", "2", False)
        if is_smart:
            data.smart_passed, data.temperature_c = True, 30
        return [system, data]


class FakePools:
    calls: list = []
    error = None

    def __getattr__(self, name):
        def verb(*args, **kwargs):
            if FakePools.error is not None:
                raise FakePools.error
            FakePools.calls.append((name, args, kwargs))

        return verb


@pytest.fixture
def runner(monkeypatch):
    FakeScanner.scans = []
    FakePools.calls = []
    FakePools.error = None
    monkeypatch.setattr(runner_module, "ZfsPoolReader", FakeReader)
    monkeypatch.setattr(runner_module, "ZfsDiskScanner", FakeScanner)
    monkeypatch.setattr(runner_module, "ZfsPoolManager", FakePools)
    monkeypatch.setattr(runner_module, "ZfsDatasetManager", FakePools)
    monkeypatch.setattr(runner_module, "is_zfs_installed", lambda: True)
    monkeypatch.setattr(runner_module, "cap_arc", lambda: "capped")
    return ZfsModuleRunner(platform=AgentPlatform(), log=lambda m: None)


def test_verify_is_the_tools_on_the_path(runner, monkeypatch):
    assert runner.verify({}) is True
    monkeypatch.setattr(runner_module, "is_zfs_installed", lambda: False)
    assert runner.verify({}) is False


def test_is_active_is_the_kernel_module_loaded(runner, monkeypatch, tmp_path):
    """ZFS runs as no unit: its kernel module being loaded is the fact."""
    monkeypatch.setattr(runner_module, "ZFS_KERNEL_MODULE_DIR", str(tmp_path / "zfs"))
    assert runner.is_active() is False

    (tmp_path / "zfs").mkdir()
    assert runner.is_active() is True


def test_apply_caps_the_arc_and_nothing_else(runner):
    runner.apply({})


def test_details_carry_the_picture_without_system_disks_or_a_smart_read(runner):
    details = runner.details({})

    assert details["pools"][0]["name"] == "tank"
    assert details["datasets"][0]["mountpoint"] == "/tank"
    assert [disk["device"] for disk in details["disks"]] == ["/dev/sdb"]
    assert details["disks"][0]["smart_passed"] is None
    assert FakeScanner.scans == [({"sdb": "tank"}, False)]


def test_a_scan_reads_smart_once_and_the_details_keep_it(runner):
    outcome = runner.command("scan", {})

    assert outcome["exit_code"] == 0
    details = runner.details({})
    assert details["disks"][0]["smart_passed"] is True
    assert details["disks"][0]["temperature_c"] == 30


def test_each_op_is_validated_then_driven(runner):
    outcome = runner.command(
        "op",
        {
            "op": "create_pool",
            "args": {"name": "tank", "layout": "mirror", "devices": ["a", "b"]},
        },
    )

    assert outcome["exit_code"] == 0
    assert FakePools.calls == [
        (
            "create",
            (),
            {
                "name": "tank",
                "layout": "mirror",
                "devices": ["a", "b"],
                "is_forced": False,
            },
        )
    ]


def test_a_refused_argument_is_typed_before_the_tool_runs(runner):
    outcome = runner.command(
        "op",
        {
            "op": "create_pool",
            "args": {"name": "mirror", "layout": "single", "devices": ["a"]},
        },
    )

    assert outcome["code"] == "pool_name_reserved"
    assert FakePools.calls == []


def test_an_op_outside_the_table_is_refused(runner):
    outcome = runner.command("op", {"op": "format_c"})

    assert outcome["code"] == "verb_unknown"
    assert outcome["params"] == {"module": "zfs", "verb": "format_c"}


def test_a_verb_the_module_does_not_have_is_refused(runner):
    assert runner.command("journal", {})["code"] == "verb_unknown"


def test_observe_is_the_tools_the_kernel_module_and_the_picture(
    runner, monkeypatch, tmp_path
):
    monkeypatch.setattr(runner_module, "ZFS_KERNEL_MODULE_DIR", str(tmp_path / "zfs"))

    unloaded = runner.observe({})
    (tmp_path / "zfs").mkdir()
    loaded = runner.observe({})

    assert (unloaded["is_installed"], unloaded["is_active"]) == (True, False)
    assert loaded["is_active"] is True
    assert set(loaded["details"]) == {"pools", "datasets", "disks", "importable"}
    assert loaded["details"]["pools"][0]["name"] == "tank"
    monkeypatch.setattr(runner_module, "is_zfs_installed", lambda: False)
    assert runner.observe({})["is_installed"] is False


def test_removing_the_configuration_drops_the_arc_cap(runner, monkeypatch, tmp_path):
    conf = tmp_path / "99_neutrino_zfs.conf"
    conf.write_text("options zfs zfs_arc_max=1")
    monkeypatch.setattr(runner_module, "ZFS_MODPROBE_CONF", str(conf))

    runner.remove_configuration()
    runner.remove_configuration()

    assert not conf.exists()


def test_a_tool_refusing_is_typed_with_its_words(runner):
    FakePools.error = subprocess.CalledProcessError(1, ["zpool"], stderr="no such pool")

    outcome = runner.command("op", {"op": "destroy_pool", "args": {"name": "tank"}})

    assert outcome["code"] == "command_failed"
    assert "no such pool" in outcome["params"]["detail"]


def test_a_dataset_op_carries_its_tunables_and_mountpoint(runner):
    runner.command(
        "op",
        {
            "op": "create_dataset",
            "args": {
                "pool": "tank",
                "name": "nfs/home",
                "compression": "zstd",
                "recordsize": "1M",
                "mountpoint": "/srv/h",
            },
        },
    )
    runner.command(
        "op", {"op": "destroy_dataset", "args": {"dataset": "tank/nfs/home"}}
    )

    assert FakePools.calls == [
        (
            "create",
            (),
            {
                "pool": "tank",
                "name": "nfs/home",
                "compression": "zstd",
                "recordsize": "1M",
                "mountpoint": "/srv/h",
            },
        ),
        ("destroy", ("tank/nfs/home",), {}),
    ]


def test_the_disk_verbs_name_the_pool_and_the_device(runner):
    runner.command("op", {"op": "offline", "args": {"name": "tank", "device": "a"}})
    runner.command(
        "op",
        {
            "op": "replace",
            "args": {"name": "tank", "old_device": "a", "new_device": "b"},
        },
    )
    runner.command("op", {"op": "scrub", "args": {"name": "tank"}})
    runner.command("op", {"op": "import_pool", "args": {"name": "backup"}})

    assert [call[0] for call in FakePools.calls] == [
        "offline",
        "replace",
        "start_scrub",
        "import_pool",
    ]
    assert FakePools.calls[1][2] == {
        "pool": "tank",
        "old_device": "a",
        "new_device": "b",
    }
