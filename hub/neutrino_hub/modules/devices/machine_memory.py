"""The memory a machine's container modules need, against its Podman machine's.

On Windows and macOS every container runs in the one Podman machine the Run
settings name, so the container modules share its memory. A container
module's manifest may name the memory it needs, ``memory_mib``. The hub sums
it over the container modules a machine is asked for and advises a larger
machine when the sum passes the machine's memory.

Pure apart from reading the manifests.
"""

import math

from neutrino_hub.modules.devices.constants import (
    DEVICE_MIB_PER_GIB,
    DEVICE_PODMAN_MACHINE_OS,
)
from neutrino_hub.modules.devices.hub_containers import container_modules
from neutrino_hub.modules.devices.manifests import load_module_manifests


def memory_need(wants: dict, *, os_name: str, stored: dict, reported: dict):
    """The memory to advise for a machine's Podman machine.

    Args:
        wants: Module name to ``{want, is_settled}``, as ``modules.json``
            holds them.
        os_name: The machine's system, ``linux``, ``windows`` or ``darwin``.
        stored: The Run settings as stored, ``{account, cpus, memory_gib,
            disk_gib}``; empty when none are.
        reported: The Podman machine as last reported, ``details.machine``;
            empty before a report.

    Returns:
        ``{need_gib, memory_gib}``: the sum of the ``memory_mib`` of the
        container modules not asked ``absent``, in whole GiB rounded up, and
        the Podman machine's memory. None on Linux, while the machine's
        memory is not known, and while the sum fits in it.
    """
    if os_name not in DEVICE_PODMAN_MACHINE_OS:
        return None
    manifests = load_module_manifests()
    need_mib = sum(
        int(manifests[name].get("memory_mib", 0)) for name in container_modules(wants)
    )
    memory_gib = machine_memory_gib(stored, reported)
    if memory_gib <= 0 or need_mib <= memory_gib * DEVICE_MIB_PER_GIB:
        return None
    return {
        "need_gib": math.ceil(need_mib / DEVICE_MIB_PER_GIB),
        "memory_gib": memory_gib,
    }


def machine_memory_gib(stored: dict, reported: dict) -> int:
    """The Podman machine's memory in whole GiB.

    Args:
        stored: The Run settings as stored; empty when none are.
        reported: The Podman machine as last reported; empty before a
            report.

    Returns:
        The reported machine's memory while it runs for the stored account;
        else the stored memory; else, for a stored 0, the memory a 0 gives
        on the computer as the machine reported it. 0 when none is known.
    """
    account = str(stored.get("account", "") or "")
    is_stored_machine = account != "" and reported.get("account") == account
    running_gib = round(_number(reported.get("memory_gib")))
    if is_stored_machine and reported.get("is_running") is True and running_gib > 0:
        return running_gib
    stored_gib = int(_number(stored.get("memory_gib")))
    if stored_gib > 0:
        return stored_gib
    return int(_number(reported.get("default_memory_gib")))


def _number(value) -> float:
    """A reported number, 0 for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value
