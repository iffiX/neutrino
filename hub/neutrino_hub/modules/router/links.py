"""Putting addresses, links and VLANs on this machine, with `ip`.

The same command on every distribution, and the one the routing half of this
layer already used: the default route, the `fwmark` rule and table 100 have
always been installed this way. This is the addressing half catching up.

Every call is idempotent by construction. `address replace` writes an address
whether or not one is there, `link set up` on an interface already up changes
nothing, and a VLAN that exists is not created again — so applying a
configuration twice is applying it once, which is what lets the panel save a
page that changed nothing without dropping the session that asked.

Not pure: everything here changes the machine.
"""

import json
import time

from neutrino_hub.utils.subprocess_run import run

# --- config ---
# `ip` is at a different path on each family and PATH under a unit is neither
# reliably, so it is found rather than named. The command itself is identical
# everywhere, which is the whole reason this layer is `ip` and not a manager.
LINKS_COMMAND = "ip"
# Long enough for a link to come up and its carrier to settle, short enough
# that a cable nobody plugged in does not hold an apply open.
LINKS_TIMEOUT_S = 20
# How long an uplink is given to be handed a lease before the handover
# moves on without one. A DHCP server on the same wire answers in well
# under this; one that does not is a link to keep the old address on.
LINKS_LEASE_TIMEOUT_S = 15
LINKS_LEASE_POLL_S = 0.5


def addresses_on(interface: str) -> list[str]:
    """Every global IPv4 address an interface carries.

    Args:
        interface: Interface name.

    Returns:
        Addresses in CIDR form, empty when the interface has none or is not
        there — both of which read the same to a caller about to set one.
    """
    result = run(
        [
            LINKS_COMMAND,
            "-4",
            "-json",
            "addr",
            "show",
            "dev",
            interface,
            "scope",
            "global",
        ],
        is_checked=False,
    )
    if not result.is_success:
        return []
    found = []
    for entry in json.loads(result.stdout or "[]"):
        for address in entry.get("addr_info", []):
            found.append(f"{address['local']}/{address['prefixlen']}")
    return found


def set_address(interface: str, cidr: str) -> bool:
    """Give an interface one address, and only that one.

    The address is replaced rather than added, and anything else global is
    taken off: an interface that was an uplink a moment ago still carries what
    DHCP gave it upstream, and two addresses on one port is a box that answers
    on an address nobody configured.

    Args:
        interface: Interface name.
        cidr: The address with its prefix, ``192.168.8.1/24``.

    Returns:
        True when something changed, so a caller knows whether to restart what
        binds to it.

    Raises:
        subprocess.CalledProcessError: When the address cannot be set.
    """
    existing = addresses_on(interface)
    if existing == [cidr]:
        return False
    run([LINKS_COMMAND, "address", "replace", cidr, "dev", interface])
    for address in existing:
        if address != cidr:
            run(
                [LINKS_COMMAND, "address", "del", address, "dev", interface],
                is_checked=False,
            )
    return True


def clear_addresses(interface: str) -> bool:
    """Take every address off an interface.

    Args:
        interface: Interface name.

    Returns:
        True when there was something to take off.
    """
    if not addresses_on(interface):
        return False
    run([LINKS_COMMAND, "address", "flush", "dev", interface], is_checked=False)
    return True


def set_up(interface: str) -> None:
    """Bring an interface up.

    Args:
        interface: Interface name.

    Raises:
        subprocess.CalledProcessError: When the interface will not come up.
    """
    run([LINKS_COMMAND, "link", "set", interface, "up"], timeout_s=LINKS_TIMEOUT_S)


def set_down(interface: str) -> None:
    """Take an interface down, if it is there.

    Args:
        interface: Interface name.
    """
    run(
        [LINKS_COMMAND, "link", "set", interface, "down"],
        timeout_s=LINKS_TIMEOUT_S,
        is_checked=False,
    )


def set_mac(interface: str, mac_address: str | None) -> bool:
    """Present a different hardware address upstream.

    Some networks — campus, hotel — register a device by its MAC, and moving
    the registration to the gateway is easier than registering it again.

    Args:
        interface: Interface name.
        mac_address: The address to present, or None to leave the real one.

    Returns:
        True when it was changed. The interface has to be down to take a new
        address, so this brings it down and back up.

    Raises:
        subprocess.CalledProcessError: When the address is refused.
    """
    if not mac_address:
        return False
    if mac_address.lower() in (item.lower() for item in _current_mac(interface)):
        return False
    set_down(interface)
    try:
        run([LINKS_COMMAND, "link", "set", interface, "address", mac_address])
    finally:
        set_up(interface)
    return True


def exists(interface: str) -> bool:
    """Whether the kernel has an interface of this name.

    Args:
        interface: Interface name.

    Returns:
        True when it is there.
    """
    return run(
        [LINKS_COMMAND, "link", "show", "dev", interface], is_checked=False
    ).is_success


def add_vlan(parent: str, name: str, vlan_id: int) -> bool:
    """Build a VLAN on a trunk port.

    Args:
        parent: The trunk the tag rides on.
        name: What to call it, by convention ``<parent>.<id>``.
        vlan_id: The 802.1Q tag.

    Returns:
        True when it had to be built.

    Raises:
        subprocess.CalledProcessError: When the kernel refuses it, most
            often because the parent is not there.
    """
    if exists(name):
        return False
    run(
        [
            LINKS_COMMAND,
            "link",
            "add",
            "link",
            parent,
            "name",
            name,
            "type",
            "vlan",
            "id",
            str(vlan_id),
        ]
    )
    return True


def remove_vlan(name: str) -> bool:
    """Take a VLAN away.

    Args:
        name: The VLAN interface's name.

    Returns:
        True when there was one to take away.
    """
    if not exists(name):
        return False
    run([LINKS_COMMAND, "link", "delete", name], is_checked=False)
    return True


def carried_state(interfaces: tuple) -> dict:
    """What each interface is addressed with right now.

    Read before the manager driving them is stopped, so it can be put straight
    back: stopping a manager takes down what it configured, and an interface
    that goes dark takes the session watching it with it.

    Args:
        interfaces: The interfaces about to be taken over.

    Returns:
        Interface name to its addresses and the next hop of its default route.
    """
    routes = _default_routes()
    return {
        name: {"addresses": addresses_on(name), "gateway": routes.get(name, "")}
        for name in interfaces
    }


def restore_state(carried: dict) -> None:
    """Put back what an interface had a moment ago.

    Not a configuration step: this is the same addressing the machine already
    had, replaced onto the same interfaces, so that the gap between one
    manager stopping and the hub starting is too short to drop a connection.
    What the roles actually want is applied straight afterwards and replaces
    this wherever the two differ.

    Args:
        carried: What :func:`carried_state` read.
    """
    for name, held in carried.items():
        for address in held["addresses"]:
            run(
                [LINKS_COMMAND, "address", "replace", address, "dev", name],
                is_checked=False,
            )
        if held["addresses"]:
            run([LINKS_COMMAND, "link", "set", name, "up"], is_checked=False)
        if held["gateway"]:
            run(
                [
                    LINKS_COMMAND,
                    "route",
                    "replace",
                    "default",
                    "via",
                    held["gateway"],
                    "dev",
                    name,
                ],
                is_checked=False,
            )


def await_lease(interface: str, *, timeout_s: int = LINKS_LEASE_TIMEOUT_S) -> bool:
    """Wait for the lease client to put an address on an interface.

    Args:
        interface: The uplink.
        timeout_s: How long to wait.

    Returns:
        True when a leased address appeared. False is not a failure: the
        interface keeps the address it was carrying, and the next apply looks
        again.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        leased, _ = _addresses_by_origin(interface)
        if leased:
            return True
        time.sleep(LINKS_LEASE_POLL_S)
    return False


def retire_carried(interfaces: tuple) -> list[str]:
    """Let go of the addresses the handover carried, once a lease has replaced
    them.

    An interface taken over under DHCP ends up with two addresses for a while:
    the one it arrived with, put back so the handover did not go dark, and the
    one the lease client was given. The first is not ours to keep — the server
    still has it out to whoever held it before, and it will hand it to somebody
    else when that lease runs out.

    Told apart by asking the kernel rather than by remembering: an address from
    a lease is `dynamic` with a lifetime, and one put on by hand is not. So
    nothing has to be tracked across a process, and an interface whose lease
    has not arrived yet keeps what it has.

    Args:
        interfaces: The interfaces to look at.

    Returns:
        One line per address let go.
    """
    released = []
    for name in interfaces:
        leased, carried = _addresses_by_origin(name)
        if not leased:
            # No lease yet, so the carried address is still the only one this
            # interface has. Taking it off now would take the interface down.
            continue
        for address in carried:
            run(
                [LINKS_COMMAND, "address", "del", address, "dev", name],
                is_checked=False,
            )
            released.append(f"{name} let go of {address}, now on {leased[0]}")
    return released


def _addresses_by_origin(interface: str) -> tuple[list, list]:
    """Which of an interface's addresses came from a lease, and which by hand.

    Args:
        interface: Interface name.

    Returns:
        The leased addresses and the rest, both in CIDR form.
    """
    result = run(
        [
            LINKS_COMMAND,
            "-4",
            "-json",
            "addr",
            "show",
            "dev",
            interface,
            "scope",
            "global",
        ],
        is_checked=False,
    )
    if not result.is_success:
        return [], []
    leased, carried = [], []
    for entry in json.loads(result.stdout or "[]"):
        for address in entry.get("addr_info", []):
            cidr = f"{address['local']}/{address['prefixlen']}"
            (leased if address.get("dynamic") else carried).append(cidr)
    return leased, carried


def _default_routes() -> dict:
    """Which interface each default route leaves by, and through what.

    Returns:
        Interface name to next hop.
    """
    result = run(
        [LINKS_COMMAND, "-4", "-json", "route", "show", "default"], is_checked=False
    )
    if not result.is_success:
        return {}
    found = {}
    for route in json.loads(result.stdout or "[]"):
        if route.get("dev") and route.get("gateway"):
            found.setdefault(route["dev"], str(route["gateway"]))
        for hop in route.get("nexthops", []):
            if hop.get("dev") and hop.get("gateway"):
                found.setdefault(hop["dev"], str(hop["gateway"]))
    return found


def set_default_route(interface: str, gateway: str, metric: int) -> None:
    """Point the box's way out at one next hop through one interface.

    Only for a static uplink: under DHCP the lease client installs the route
    itself, at the metric its configuration names.

    Args:
        interface: The uplink.
        gateway: The next hop.
        metric: What to install it at, which is how uplinks are ranked.

    Raises:
        subprocess.CalledProcessError: When the route cannot be installed.
    """
    run(
        [
            LINKS_COMMAND,
            "route",
            "replace",
            "default",
            "via",
            gateway,
            "dev",
            interface,
            "metric",
            str(metric),
        ]
    )


def _current_mac(interface: str) -> list[str]:
    """The hardware address an interface is presenting right now.

    Args:
        interface: Interface name.

    Returns:
        A one-item list, or nothing when the interface is not there.
    """
    result = run(
        [LINKS_COMMAND, "-json", "link", "show", "dev", interface], is_checked=False
    )
    if not result.is_success:
        return []
    return [
        entry["address"]
        for entry in json.loads(result.stdout or "[]")
        if entry.get("address")
    ]
