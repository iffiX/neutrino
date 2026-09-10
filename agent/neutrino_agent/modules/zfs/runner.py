"""ZFS as a module: the tools by package, the storage picture, the verbs.

The packages come from the distribution, so orders ride the system-package
runner, with the repository steps the manifest names. There is nothing to
render: a pool's truth is on its disks, so apply caps the ARC and stops.

Not pure: drives the storage tools through the applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import command_outcome
from neutrino_agent.modules.subprocess_run import command_detail
from neutrino_agent.modules.system_package import SystemPackageModuleRunner
from neutrino_agent.modules.zfs.applier import (
    ZfsDatasetManager,
    ZfsDiskScanner,
    ZfsPoolManager,
    ZfsPoolReader,
    cap_arc,
    is_zfs_installed,
)
from neutrino_agent.modules.zfs.config import (
    validate_dataset_path,
    validate_mountpoint,
    validate_pool_name,
    validate_tunables,
    validate_vdev,
)
from neutrino_agent.modules.zfs.constants import (
    ZFS_COMMAND_OP,
    ZFS_COMMAND_SCAN,
    ZFS_OP_CREATE_DATASET,
    ZFS_OP_CREATE_POOL,
    ZFS_OP_DESTROY_DATASET,
    ZFS_OP_DESTROY_POOL,
    ZFS_OP_EXPAND_POOL,
    ZFS_OP_IMPORT_POOL,
    ZFS_OP_OFFLINE,
    ZFS_OP_ONLINE,
    ZFS_OP_REPLACE,
    ZFS_OP_SCRUB,
    ZFS_OP_STOP_SCRUB,
    ZFS_OPS,
)


class ZfsModuleRunner(SystemPackageModuleRunner):
    """Installs the ZFS tools by package and drives pools on request."""

    name = "zfs"

    def __init__(self, *, platform, log=print, publish=None):
        super().__init__(platform=platform, log=log, publish=publish)
        self._smart: dict = {}

    def verify(self, resolved: dict) -> bool:
        """Whether the tools are on the machine.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when ``zpool`` is on the path.
        """
        return is_zfs_installed()

    def apply(self, config: dict) -> None:
        """Cap the ARC; there is no configuration to render.

        Args:
            config: The desired configuration, which holds nothing.

        Raises:
            ModuleApplyError: ``apply_failed`` when the ARC cannot be capped.
        """
        try:
            note = cap_arc()
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        if note:
            self._log(f"zfs: {note}")

    def details(self, resolved: dict) -> dict:
        """The whole storage picture.

        SMART verdicts come from the last ``zfs_scan``: asking every disk on
        every read would keep the machine busy doing nothing.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"pools", "datasets", "disks", "importable"}``.
        """
        reader = ZfsPoolReader()
        pools = reader.pools()
        disks = ZfsDiskScanner().scan(pool_members=reader.member_pools(pools))
        for disk in disks:
            held = self._smart.get(disk.device)
            if held is not None:
                disk.smart_passed, disk.temperature_c = held
        return {
            "pools": [pool.to_dict() for pool in pools],
            "datasets": [dataset.to_dict() for dataset in reader.datasets()],
            "disks": [disk.to_dict() for disk in disks if not disk.is_system],
            "importable": [vars(candidate) for candidate in reader.importable()],
        }

    def command(self, action: str, args: dict, on_line=None) -> dict:
        """Run one of the storage verbs.

        Args:
            action: ``zfs_op`` or ``zfs_scan``.
            args: ``{"op", "args"}`` for an op; nothing for a scan.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        if action == ZFS_COMMAND_SCAN:
            for disk in ZfsDiskScanner().scan(is_smart=True):
                self._smart[disk.device] = (disk.smart_passed, disk.temperature_c)
            return command_outcome(0, output=f"scanned {len(self._smart)} disks\n")
        if action != ZFS_COMMAND_OP:
            return super().command(action, args, on_line)
        op = str(args.get("op", ""))
        fields = args.get("args") if isinstance(args.get("args"), dict) else {}
        if op not in ZFS_OPS:
            return command_outcome(1, "unsupported_action", {"action": op})
        try:
            self._run_op(op, fields)
        except ModuleApplyError as error:
            return command_outcome(1, error.code, error.params)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            detail = (
                str(error) if isinstance(error, ValueError) else command_detail(error)
            )
            return command_outcome(1, "command_failed", {"detail": detail[:500]})
        return command_outcome(0, output=f"{op} done\n")

    def _run_op(self, op: str, fields: dict) -> None:
        pools = ZfsPoolManager()
        name = str(fields.get("name", ""))
        if op == ZFS_OP_CREATE_POOL:
            devices = [str(device) for device in fields.get("devices") or []]
            validate_pool_name(name)
            validate_vdev(str(fields.get("layout", "")), devices)
            pools.create(
                name=name,
                layout=str(fields.get("layout", "")),
                devices=devices,
                is_forced=bool(fields.get("is_forced", False)),
            )
        elif op == ZFS_OP_DESTROY_POOL:
            pools.destroy(name)
        elif op == ZFS_OP_EXPAND_POOL:
            devices = [str(device) for device in fields.get("devices") or []]
            validate_vdev(str(fields.get("layout", "")), devices)
            pools.add_vdev(
                pool=name,
                layout=str(fields.get("layout", "")),
                devices=devices,
                is_forced=bool(fields.get("is_forced", False)),
            )
        elif op == ZFS_OP_IMPORT_POOL:
            pools.import_pool(name)
        elif op == ZFS_OP_SCRUB:
            pools.start_scrub(name)
        elif op == ZFS_OP_STOP_SCRUB:
            pools.stop_scrub(name)
        elif op == ZFS_OP_REPLACE:
            pools.replace(
                pool=name,
                old_device=str(fields.get("old_device", "")),
                new_device=str(fields.get("new_device", "")),
            )
        elif op == ZFS_OP_OFFLINE:
            pools.offline(pool=name, device=str(fields.get("device", "")))
        elif op == ZFS_OP_ONLINE:
            pools.online(pool=name, device=str(fields.get("device", "")))
        elif op == ZFS_OP_CREATE_DATASET:
            mountpoint = fields.get("mountpoint")
            mountpoint = str(mountpoint) if mountpoint is not None else None
            validate_dataset_path(name)
            validate_tunables(
                str(fields.get("compression", "")), str(fields.get("recordsize", ""))
            )
            validate_mountpoint(mountpoint)
            ZfsDatasetManager().create(
                pool=str(fields.get("pool", "")),
                name=name,
                compression=str(fields.get("compression", "")),
                recordsize=str(fields.get("recordsize", "")),
                mountpoint=mountpoint,
            )
        elif op == ZFS_OP_DESTROY_DATASET:
            ZfsDatasetManager().destroy(str(fields.get("dataset", "")))
