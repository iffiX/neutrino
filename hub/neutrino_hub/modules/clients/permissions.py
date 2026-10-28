"""What one client is allowed, by kind, by device and by row.

A kind is a published service type, joining the hub's overlay, opening a
shell or running one command on a managed machine, or opening the hub's
panel. A permission may narrow a kind to the entries some devices provide,
and may set a row, one app, share, desktop or machine, on or off whatever
its kind says. A client follows the default permission unless it has one of
its own. Pure functions: the registry and the devices are read by the caller.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from neutrino_hub.modules.clients.constants import (
    CLIENT_PERMISSION_FILTERED_KINDS,
    CLIENT_PERMISSION_KINDS,
    CLIENT_TERMINAL_ROW_PREFIX,
)
from neutrino_hub.modules.services.constants import (
    SERVICES_SOURCE_DECLARED,
    SERVICES_TYPE_AI,
    SERVICES_TYPE_FILE,
)
from neutrino_hub.modules.services.file_ids import file_row_id


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


def permission_entries(entries) -> dict:
    """A row map in the one shape it is stored in.

    Args:
        entries: Row id to ``True`` or ``False``; None for no row.

    Returns:
        The rows in their given order, without an empty id.

    Raises:
        ValueError: If a value is not ``True`` or ``False``.
    """
    rows = {}
    for row_id, value in (entries or {}).items():
        if not isinstance(value, bool):
            raise ValueError(f"row {row_id!r} is neither true nor false")
        if str(row_id):
            rows[str(row_id)] = value
    return rows


def client_permission(registry, client) -> "ClientPermission":
    """The permission one client is held to now.

    Args:
        registry: The :class:`ClientRegistry` holding the default.
        client: The client.

    Returns:
        Its own permission when it has one, else the default.
    """
    if client.permission is not None:
        return ClientPermission(
            kinds=frozenset(client.permission),
            devices=dict(client.permission_devices),
            entries=dict(client.permission_entries),
        )
    return default_permission(registry)


def default_permission(registry) -> "ClientPermission":
    """The permission a client with none of its own is held to.

    Args:
        registry: The :class:`ClientRegistry` holding the default.

    Returns:
        The default.
    """
    return ClientPermission(
        kinds=frozenset(registry.default_permission()),
        devices=registry.default_permission_devices(),
        entries=registry.default_permission_entries(),
    )


def is_permitted(
    permission: "ClientPermission", kind: str, device_id: str = "", row_id: str = ""
) -> bool:
    """Whether a permission allows one use.

    Args:
        permission: The permission the client is held to.
        kind: The kind the use falls under.
        device_id: The device providing the thing; empty for none known.
        row_id: The thing's row id; empty for a kind with no rows.

    Returns:
        The value ``entries`` gives the row when it names it; otherwise
        whether the kind is on and its device list lets the device through.
    """
    if row_id and row_id in permission.entries:
        return permission.entries[row_id]
    return kind in permission.kinds and is_device_permitted(
        permission.devices, kind, device_id
    )


def entry_row_id(entry: dict) -> str:
    """The row one published entry is judged under.

    Args:
        entry: The composed entry, with ``id``, ``type`` and ``app_id``.

    Returns:
        The app's id for an entry of an app, :func:`file_row_id` for a
        ``file`` entry of no app, the entry's own id for any other, and
        empty for the ``ai`` entry.
    """
    if entry.get("type") == SERVICES_TYPE_AI:
        return ""
    if entry.get("app_id"):
        return str(entry["app_id"])
    if entry.get("type") == SERVICES_TYPE_FILE:
        return file_row_id(entry)
    return str(entry.get("id", "") or "")


def terminal_row_id(device_id: str) -> str:
    """The row a managed machine's shells and commands are judged under.

    Args:
        device_id: The machine.

    Returns:
        ``terminal_<device id>``.
    """
    return f"{CLIENT_TERMINAL_ROW_PREFIX}{device_id}"


def is_row_of_device(row_id: str, device_id: str) -> bool:
    """Whether a row id names one device.

    Args:
        row_id: The row id.
        device_id: The device.

    Returns:
        True when the device's id is one of the row id's parts.
    """
    return bool(device_id) and f"_{device_id}_" in f"_{row_id}_"


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


@dataclass(frozen=True)
class ClientPermission:
    """What one client is allowed: its own permission, or the default.

    Attributes:
        kinds: The kinds that are on.
        devices: Device ids by kind; a kind with no list allows every
            device.
        entries: Row id to ``True`` or ``False``; a row absent follows its
            kind.
    """

    kinds: frozenset = frozenset()
    devices: dict = field(default_factory=dict)
    entries: dict = field(default_factory=dict)
