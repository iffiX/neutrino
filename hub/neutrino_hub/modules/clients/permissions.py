"""What one client is allowed, by kind and by device.

A kind is a published service type, joining the hub's overlay, or opening a
shell on a managed machine. A permission may also narrow a kind to the
entries some devices provide: a kind with no list, or an empty one, allows
every device. A client follows the default permission unless it has one of
its own. Pure functions: the registry and the devices are read by the caller.
"""

from urllib.parse import urlsplit

from neutrino_hub.modules.clients.constants import (
    CLIENT_PERMISSION_FILTERED_KINDS,
    CLIENT_PERMISSION_KINDS,
)
from neutrino_hub.modules.services.constants import SERVICES_SOURCE_DECLARED


def permission_kinds(kinds) -> list:
    """A set of permission kinds in the one order every surface lists them.

    Args:
        kinds: The kinds, in any order, repeats allowed.

    Returns:
        The kinds, each once, in :data:`CLIENT_PERMISSION_KINDS` order.

    Raises:
        ValueError: If one of them is not a permission kind.
    """
    chosen = set(kinds)
    unknown = sorted(chosen - set(CLIENT_PERMISSION_KINDS))
    if unknown:
        raise ValueError(f"{unknown[0]!r} is not a permission kind")
    return [kind for kind in CLIENT_PERMISSION_KINDS if kind in chosen]


def permission_devices(devices) -> dict:
    """A device filter in the one shape it is stored in.

    Args:
        devices: Device ids by kind; None for no filter.

    Returns:
        The lists by kind, in :data:`CLIENT_PERMISSION_KINDS` order, each id
        once, and no kind whose list is empty.

    Raises:
        ValueError: If a kind is not one a device filter applies to.
    """
    devices = devices or {}
    unknown = sorted(set(devices) - set(CLIENT_PERMISSION_FILTERED_KINDS))
    if unknown:
        raise ValueError(f"{unknown[0]!r} takes no device filter")
    filters = {}
    for kind in CLIENT_PERMISSION_FILTERED_KINDS:
        chosen = list(dict.fromkeys(str(entry) for entry in devices.get(kind) or []))
        if chosen:
            filters[kind] = chosen
    return filters


def permitted_kinds(registry, client) -> frozenset:
    """The kinds one client is allowed now.

    Args:
        registry: The :class:`ClientRegistry` holding the default set.
        client: The client.

    Returns:
        Its own set when it has one, else the default set.
    """
    if client.permission is not None:
        return frozenset(client.permission)
    return frozenset(registry.default_permission())


def permitted_devices(registry, client) -> dict:
    """The device filter one client is held to now.

    Args:
        registry: The :class:`ClientRegistry` holding the default filter.
        client: The client.

    Returns:
        Device ids by kind: its own when it has a permission of its own,
        else the default's.
    """
    if client.permission is not None:
        return dict(client.permission_devices)
    return registry.default_permission_devices()


def is_device_permitted(devices: dict, kind: str, device_id: str) -> bool:
    """Whether a filter lets one kind through for one device.

    Args:
        devices: Device ids by kind.
        kind: The kind.
        device_id: The device providing the entry; empty for none known.

    Returns:
        True when the kind has no list, or the list names the device.
    """
    chosen = devices.get(kind) or []
    return not chosen or device_id in chosen


def permitted_entries(entries: list, kinds) -> list:
    """The published entries whose type is among the allowed kinds.

    Args:
        entries: The published entries, each with a ``type``.
        kinds: The allowed kinds.

    Returns:
        The entries allowed, in their given order.
    """
    return [entry for entry in entries if entry["type"] in kinds]


def entry_device_id(
    entry: dict, *, hub_device_id: str, device_ids_by_address: dict
) -> str:
    """The device that provides one published entry.

    Args:
        entry: The composed entry, with ``device_id`` and ``source``.
        hub_device_id: The hub's own device, empty when it has none.
        device_ids_by_address: Device ids by the address each is reached at.

    Returns:
        The device hosting it; the device at a declared record's address;
        the hub's own device for the hub's own modules; empty otherwise.
    """
    device_id = entry.get("device_id") or ""
    if device_id:
        return device_id
    if entry.get("source") == SERVICES_SOURCE_DECLARED:
        return device_ids_by_address.get(entry_host(entry), "")
    return hub_device_id


def entry_machine_id(
    entry: dict,
    *,
    hub_machine_id: str,
    device_ids_by_address: dict,
    machine_ids_by_device: dict,
) -> str:
    """The operating system's id for the machine that provides one entry.

    Args:
        entry: The composed entry, with ``device_id`` and ``source``.
        hub_machine_id: The hub box's own id.
        device_ids_by_address: Device ids by the address each is reached at.
        machine_ids_by_device: Each stored device's ``machine_id`` by its id.

    Returns:
        The device's id for an entry a device hosts or a declared record at
        a device's address; the hub box's for one of the hub's own modules;
        empty for a declared record no device is at.
    """
    device_id = entry_device_id(
        entry, hub_device_id="", device_ids_by_address=device_ids_by_address
    )
    if device_id:
        return machine_ids_by_device.get(device_id, "")
    if entry.get("source") == SERVICES_SOURCE_DECLARED:
        return ""
    return hub_machine_id


def entry_host(entry: dict) -> str:
    """The host an entry's payload names, wherever its type keeps it.

    Args:
        entry: The entry.

    Returns:
        The host, empty when the payload names none.
    """
    payload = entry.get("payload") or {}
    for key in ("url", "endpoint"):
        if payload.get(key):
            return urlsplit(str(payload[key])).hostname or ""
    return str(payload.get("host", "") or "")
