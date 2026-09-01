"""The manager this machine ran before, and standing it down.

In router mode the hub drives the interfaces itself, and two things driving
one interface is where every bug in this area has come from. So whatever was
driving them is stopped.

**Only units are touched.** Nothing here reads, copies, empties or restores
another manager's configuration: a stopped manager's files are inert, so there
is nothing to put back and nothing to get wrong putting it back. What is
recorded is what the hub did — which units it stood down — so that handing the
machine back is starting exactly those and no others.

Not pure: probes and drives systemd.
"""

import json

from neutrino_hub.modules.router.constants import ROUTER_STACK_RECORD_PATH
from neutrino_hub.utils.subprocess_run import run

# --- config ---
# Every manager that configures an interface, and the units each one is. A
# machine trips none of these, or one, or several; nothing here keys off the
# distribution, because a Raspberry Pi trips `dhcpcd` on one release and
# nothing on the next and that is the same code path.
#
# The table is in design/network.md.
STACK_MANAGERS = {
    "NetworkManager": ("NetworkManager.service",),
    # The socket is named as well as the service: `systemd-networkd.service`
    # is `TriggeredBy` its own socket, so stopping the service alone lets the
    # socket start it again moments later — a machine left with two managers
    # after a takeover that reported success.
    "systemd-networkd": ("systemd-networkd.service", "systemd-networkd.socket"),
    "ifupdown": ("networking.service",),
    "dhcpcd": ("dhcpcd.service",),
    "connman": ("connman.service",),
    "netctl": ("netctl.service",),
    # It and `wpa_supplicant` cannot share a radio.
    "iwd": ("iwd.service",),
    # Not a manager of interfaces, but it holds port 53, which is the one port
    # the hub's own dnsmasq has to have.
    "systemd-resolved": ("systemd-resolved.service",),
}

# The machine's own supplicant on one radio. Debian's `wpa_supplicant.service`
# is not this: measured on Debian 12 it runs `wpa_supplicant -u` with no `-i`
# and no `-c`, so it owns no interface and waits on D-Bus for a manager to
# name one — and it is left alone. What would fight for a radio is the
# templated unit systemd-networkd and ifupdown start per interface.
STACK_SUPPLICANT_UNIT = "wpa_supplicant@{interface}.service"


def running_managers() -> list[str]:
    """Which of the known managers are up on this machine right now.

    Returns:
        Their names, in the order the table declares them.
    """
    return [
        name
        for name, units in STACK_MANAGERS.items()
        if any(_is_active(unit) for unit in units)
    ]


def stand_down(interfaces: tuple = ()) -> list[str]:
    """Stop every manager that would fight the hub for an interface.

    Masked rather than disabled: a socket-activated unit comes straight back
    from a disable, and masking is what socket activation cannot defeat.

    Args:
        interfaces: The radios the hub is taking. Each one's own supplicant
            unit is stood down with the managers, because that is the process
            that actually holds a radio — the machine-wide one holds none.

    Returns:
        One line per thing stopped.
    """
    stopped = _recorded()
    changes = []
    for name in running_managers():
        for unit in STACK_MANAGERS[name]:
            run(["systemctl", "mask", "--now", unit], is_checked=False)
            if unit not in stopped:
                stopped.append(unit)
        changes.append(f"stopped {name}")
    for interface in interfaces:
        unit = STACK_SUPPLICANT_UNIT.format(interface=interface)
        if not _is_active(unit):
            continue
        run(["systemctl", "mask", "--now", unit], is_checked=False)
        if unit not in stopped:
            stopped.append(unit)
        changes.append(f"stopped {unit}")
    _record(stopped)
    return changes


def stand_up() -> list[str]:
    """Start again exactly what was stood down, and nothing else.

    From the record rather than from what is installed: a machine that had
    NetworkManager installed and switched off is a machine to hand back that
    way, and starting everything present would leave it running something
    nobody asked for.

    Returns:
        One line per manager started.
    """
    stopped = _recorded()
    if not stopped:
        return []
    for unit in stopped:
        # Unmasking comes first: a masked unit can be neither enabled nor
        # started, and the error for trying says nothing useful.
        run(["systemctl", "unmask", unit], is_checked=False)
    for unit in stopped:
        run(["systemctl", "enable", "--now", unit], is_checked=False)
    ROUTER_STACK_RECORD_PATH.unlink(missing_ok=True)
    return [f"started {unit}" for unit in stopped]


def _is_active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], is_checked=False).is_success


def _recorded() -> list[str]:
    """What the hub has already stood down on this machine.

    Returns:
        The unit names, empty when nothing has been.
    """
    try:
        return list(json.loads(ROUTER_STACK_RECORD_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def _record(units: list[str]) -> None:
    """Write down what has been stood down.

    Args:
        units: Every unit the hub stopped, including ones stopped earlier.
    """
    ROUTER_STACK_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROUTER_STACK_RECORD_PATH.write_text(
        json.dumps(sorted(set(units)), indent=2) + "\n", encoding="utf-8"
    )
