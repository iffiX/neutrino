"""Stop what the hub runs on this box.

    sudo nhub stop                              # everything it started
    sudo nhub stop --only-web                   # one of them
    sudo nhub stop --only-xray
    sudo nhub stop --only-cliproxyapi
    sudo nhub stop --only-dnsmasq
    sudo nhub stop --only-router
    sudo nhub stop --only-supplicant --interface wlp3s0
    sudo nhub stop --only-dhcpcd --interface enp2s0

The mirror of ``nhub run``, and spelled the way it is: the same ``--only-``
flags, the same names, and ``--interface`` for the two engines that run one
per interface. ``--only-router`` is the one name ``run`` has no use for — the
routing state is a unit that finishes rather than a process to watch.

With no ``--only`` it stops all of them, the per-interface engines included:
a box left holding a DHCP lease it asked for is a box the hub has not stopped
running, whatever the panel is doing.

What it leaves alone is the optional modules. Samba serves shares whether or
not this box routes anything, so a plain ``nhub stop`` is the hub going quiet
rather than the machine going down.

Nothing is disabled, so everything comes back at the next boot. Removing the
hub is the package manager's business, and undoing a setup is ``nhub reset``.
"""

import argparse
import sys

from neutrino_hub.modules.router.dhcp_client import RouterDhcpClient
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.supplicant import RouterWifiClient
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.utils.subprocess_run import CommandError

# The order they are stopped in, which is the order they sit on each other.
# The panel first because it is what a person is holding: stopping it while
# the proxy underneath is already gone means a page that hangs rather than one
# that closes. The routing state last, because it is what the rest ran on.
STOP_ORDER = ("web", "cliproxyapi", "dnsmasq", "xray", "router")
# The two that run one unit per interface, named as `run` names them.
STOP_PER_INTERFACE = ("supplicant", "dhcpcd")


def main() -> int:
    """Stop what was asked for.

    Returns:
        Process exit status; 1 when something refused to stop.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--interface",
        default=None,
        help="which interface, for the per-interface engines",
    )
    group = parser.add_mutually_exclusive_group()
    for name in STOP_ORDER + STOP_PER_INTERFACE:
        group.add_argument(
            f"--only-{name}",
            dest="only",
            action="store_const",
            const=name,
            help=f"stop only the {name} service",
        )
    arguments = parser.parse_args()

    if arguments.only in STOP_PER_INTERFACE:
        if not arguments.interface:
            print(f"error: --only-{arguments.only} needs --interface", file=sys.stderr)
            return 1
        return stop_engine(arguments.only, arguments.interface)
    if arguments.only:
        return stop([arguments.only])
    return stop_everything()


def stop_everything() -> int:
    """Stop every service the hub runs, engines included.

    Returns:
        0 when everything is stopped, 1 when any of it refused.
    """
    status = stop(list(STOP_ORDER))
    for name, interface in _configured_engines():
        status = stop_engine(name, interface) or status
    return status


def stop(names: list) -> int:
    """Stop each named service, and say what happened to it.

    Args:
        names: The hub's own service names, in the order to stop them.

    Returns:
        0 when every one of them is stopped, 1 when any refused.
    """
    controller = SystemdServiceController()
    is_failed = False
    for name in names:
        status = controller.status(name)
        if not status.is_installed:
            continue
        if not status.is_active:
            print(f"  {name}: already stopped")
            continue
        try:
            controller.control(name, "stop")
        except CommandError as error:
            # Reported rather than raised: one unit that will not stop must
            # not hide what happened to the others, and `systemctl status`
            # says more about it than a traceback here could.
            print(f"  {name}: did not stop: {error}", file=sys.stderr)
            is_failed = True
            continue
        print(f"  {name}: stopped")
    return 1 if is_failed else 0


def stop_engine(name: str, interface: str) -> int:
    """Stop one per-interface engine.

    These are templated units rather than managed services, so they are
    addressed by the classes that start them rather than through the
    controller the panel uses.

    Args:
        name: ``supplicant`` or ``dhcpcd``.
        interface: The interface it runs on.

    Returns:
        0 when it is stopped or was never running, 1 when it refused.
    """
    engine = (
        RouterWifiClient(interface=interface)
        if name == "supplicant"
        else RouterDhcpClient(interface=interface)
    )
    if not engine.is_running:
        return 0
    try:
        engine.stop()
    except CommandError as error:
        print(f"  {engine.unit}: did not stop: {error}", file=sys.stderr)
        return 1
    print(f"  {engine.unit}: stopped")
    return 0


def _configured_engines() -> list:
    """Every per-interface engine this box's configuration names.

    Read from `config/` rather than from systemd, because that is the record
    of which interfaces the hub was driving. A box whose configuration has
    already been replaced has none, which is correct: there is nothing left
    saying what it was running.

    Returns:
        ``(name, interface)`` pairs, empty when nothing is configured.
    """
    try:
        network = RouterNetworkConfig.from_dict(read_config("router/network.json"))
    except (FileNotFoundError, ValueError):
        return []
    return [
        (name, interface.device_name)
        for interface in network.interfaces
        for name in STOP_PER_INTERFACE
    ]


if __name__ == "__main__":
    sys.exit(main())
