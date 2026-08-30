"""The nmcli calls everything else in the router layer is built from.

NetworkManager owns the interfaces on this box — it is what makes replugging
the uplink into a different network just work — so the gateway configures them
by rewriting NM connections rather than by setting addresses itself.

The one rule the rest of the layer relies on: **never activate a connection
that does not need to change**. Bringing a connection up drops every session on
that interface, and on the LAN that includes the panel session issuing the
request. :func:`modify_if_needed` compares before it writes for exactly that
reason.

Not pure: everything here talks to the system.
"""

from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.router.constants import ROUTER_NM_UNMANAGED_CONF

# nmcli reports a device with no connection as this rather than as empty.
NO_CONNECTION = "--"


def unescape(value: str) -> str:
    """Undo the escaping ``nmcli -t`` applies to separators in field values.

    Args:
        value: One field of terse nmcli output.

    Returns:
        The literal value.
    """
    return value.replace("\\:", ":").replace("\\\\", "\\")


def device_kinds() -> dict[str, str]:
    """Read every device NetworkManager knows and what kind it is.

    Returns:
        Interface name to kind, for example ``{"enp1s0": "ethernet"}``.
    """
    result = run(
        ["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"], is_checked=False
    )
    if not result.is_success:
        return {}
    kinds = {}
    for line in result.stdout.splitlines():
        device, _, kind = line.partition(":")
        if device:
            kinds[device] = kind
    return kinds


def connection_for_device(device: str) -> str | None:
    """Find the connection currently active on an interface.

    Args:
        device: Interface name.

    Returns:
        The connection name, or None when nothing is active on it.
    """
    result = run(
        ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
        is_checked=False,
    )
    if not result.is_success:
        return None
    for line in result.stdout.splitlines():
        name, _, bound = line.rpartition(":")
        if bound == device:
            return unescape(name)
    return None


def connections_for_device(device: str) -> list[str]:
    """List every saved connection bound to an interface by name.

    Args:
        device: Interface name.

    Returns:
        Connection names whose ``connection.interface-name`` is this device.
        A Wi-Fi profile that is not pinned to an interface will not appear.
    """
    names = []
    for name in all_connections():
        if read_property(name, "connection.interface-name") == device:
            names.append(name)
    return names


def all_connections() -> list[str]:
    """List every saved connection.

    Returns:
        Connection names.
    """
    result = run(["nmcli", "-t", "-f", "NAME", "connection", "show"], is_checked=False)
    if not result.is_success:
        return []
    return [unescape(line) for line in result.stdout.splitlines() if line]


def connections_of_type(kind: str) -> list[str]:
    """List saved connections of one type.

    Args:
        kind: An nmcli connection type such as ``802-11-wireless``.

    Returns:
        Connection names.
    """
    result = run(
        ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], is_checked=False
    )
    if not result.is_success:
        return []
    names = []
    for line in result.stdout.splitlines():
        name, _, found = line.rpartition(":")
        if found == kind:
            names.append(unescape(name))
    return names


def connection_exists(name: str) -> bool:
    """Whether a connection of this name is saved.

    Asked by listing rather than by naming the connection. ``nmcli -f NAME
    connection show <id>`` looks like it would answer this and does not: the
    detail form takes setting names such as ``connection.id``, rejects ``NAME``
    outright, and so reports every connection as missing — which silently turns
    "take the access point down" into a no-op and "create it if absent" into
    creating it again on every apply.

    Args:
        name: Connection name.

    Returns:
        True when NetworkManager holds it.
    """
    return name in all_connections()


def read_property(name: str, key: str) -> str:
    """Read one property of a saved connection.

    Args:
        name: Connection name.
        key: Property, for example ``ipv4.method``.

    Returns:
        The value as nmcli prints it, or an empty string when it cannot be
        read.
    """
    result = run(
        ["nmcli", "-g", key, "connection", "show", name],
        is_checked=False,
    )
    return result.stdout.strip() if result.is_success else ""


def modify(name: str, settings: dict[str, str]) -> None:
    """Write properties onto a saved connection.

    Args:
        name: Connection name.
        settings: Property to value. Written in one nmcli call so a failure
            part-way cannot leave the connection half-configured.
    """
    arguments = []
    for key, value in settings.items():
        arguments += [key, value]
    run(["nmcli", "connection", "modify", name, *arguments])


def is_matching(name: str, settings: dict[str, str]) -> bool:
    """Whether a connection already carries these values.

    Args:
        name: Connection name.
        settings: Property to wanted value.

    Returns:
        True when every property already reads as its wanted value, so
        rewriting and reactivating would change nothing.
    """
    return not differing_properties(name, settings)


def modify_if_needed(name: str, settings: dict[str, str]) -> bool:
    """Write properties only when at least one differs.

    Args:
        name: Connection name.
        settings: Property to wanted value.

    Returns:
        True when something was written, which is also the caller's signal
        that the connection needs reactivating.
    """
    if is_matching(name, settings):
        return False
    modify(name, settings)
    return True


def activate(name: str) -> None:
    """Bring a connection up, dropping whatever was on its interface.

    This is the expensive door: it tears the connection down and builds it
    again, which restarts DHCP and re-runs address-conflict detection. Use
    :func:`reapply_device` for anything it can carry instead.

    Args:
        name: Connection name.

    Raises:
        CommandError: If activation fails.
    """
    run(["nmcli", "connection", "up", name], timeout_s=90)


def reapply_device(device: str, *, connection: str | None = None) -> None:
    """Push a connection's changed settings onto a live interface in place.

    No teardown, so no new DHCP transaction and no conflict detection — the
    link never drops. NetworkManager cannot do this for every property, which
    is what :data:`REACTIVATION_PROPERTIES` in :mod:`neutrino_hub.modules.router.routes` enumerates.

    Falls back to a full activation if the reapply is refused. NetworkManager
    declines it for changes it considers too deep, and older versions decline
    more of them; dropping the link is worse than not dropping it, but leaving
    the setting unapplied is worse still.

    Args:
        device: Interface name.
        connection: The connection to activate if the reapply is refused.
            Without one, a refusal is reported rather than worked around.

    Raises:
        CommandError: If the settings cannot be applied at all.
    """
    result = run(["nmcli", "device", "reapply", device], timeout_s=60, is_checked=False)
    if result.is_success:
        return
    if connection is None:
        raise CommandError(
            f"could not apply the new settings to {device}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    activate(connection)


def set_unmanaged(device: str, is_unmanaged: bool) -> None:
    """Tell NetworkManager whether an interface is its business, permanently.

    ``nmcli device set managed`` lasts until the next reboot, so the durable
    half is a configuration drop-in. Both are written: the drop-in for the next
    boot, the runtime call for right now.

    Args:
        device: Interface name.
        is_unmanaged: True to hand the interface over to something else.
    """
    devices = _unmanaged_devices()
    if is_unmanaged:
        devices.add(device)
    else:
        devices.discard(device)

    if devices:
        listed = ";".join(f"interface-name:{name}" for name in sorted(devices))
        ROUTER_NM_UNMANAGED_CONF.parent.mkdir(parents=True, exist_ok=True)
        ROUTER_NM_UNMANAGED_CONF.write_text(
            "# Generated by neutrino. Do not edit; change config/ instead.\n"
            "# These interfaces are run by the gateway itself — a radio serving an\n"
            "# access point is hostapd's, not NetworkManager's.\n"
            "[keyfile]\n"
            f"unmanaged-devices={listed}\n",
            encoding="utf-8",
        )
    else:
        ROUTER_NM_UNMANAGED_CONF.unlink(missing_ok=True)

    run(["nmcli", "general", "reload", "conf"], is_checked=False)
    run(
        ["nmcli", "device", "set", device, "managed", "no" if is_unmanaged else "yes"],
        is_checked=False,
    )


def _unmanaged_devices() -> set[str]:
    if not ROUTER_NM_UNMANAGED_CONF.is_file():
        return set()
    devices = set()
    for line in ROUTER_NM_UNMANAGED_CONF.read_text(encoding="utf-8").splitlines():
        if not line.startswith("unmanaged-devices="):
            continue
        for entry in line.split("=", 1)[1].split(";"):
            _, _, name = entry.partition("interface-name:")
            if name:
                devices.add(name)
    return devices


def differing_properties(name: str, settings: dict[str, str]) -> set[str]:
    """Which of these properties a connection does not already carry.

    Args:
        name: Connection name.
        settings: Property to wanted value.

    Returns:
        The property names whose stored value differs from the wanted one.
    """
    return {
        key
        for key, value in settings.items()
        if not _is_equivalent(read_property(name, key), value)
    }


def deactivate(name: str) -> None:
    """Bring a connection down if it is up.

    Args:
        name: Connection name.
    """
    run(["nmcli", "connection", "down", name], is_checked=False)


def disconnect_device(device: str) -> None:
    """Disconnect an interface, leaving it idle.

    Args:
        device: Interface name.
    """
    run(["nmcli", "device", "disconnect", device], is_checked=False)


def _is_equivalent(current: str, wanted: str) -> bool:
    # nmcli prints an unset cloned MAC as "permanent" but accepts either that
    # or an empty string to mean it, and it prints MACs upper-case while a
    # person types them lower-case.
    unset = {"", "permanent", NO_CONNECTION}
    if current.lower() in unset and wanted.lower() in unset:
        return True
    return current.lower() == wanted.lower()
