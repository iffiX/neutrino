"""Start the hub's units on this box.

    sudo nhub start                              # every unit boot would start
    sudo nhub start --only-web                   # one of them
    sudo nhub start --only-xray
    sudo nhub start --only-cliproxyapi
    sudo nhub start --only-dnsmasq
    sudo nhub start --only-router
    sudo nhub start --only-supplicant --interface wlp3s0
    sudo nhub start --only-dhcpcd --interface enp2s0
    sudo nhub start --yes                        # without asking first

The pair of ``nhub stop``, with the same ``--only-`` flags and the same
``--interface`` for the two engines that run one per interface. ``nhub run``
is the process each unit runs in the foreground.

With no ``--only`` it starts every unit of the hub that is enabled, in the
reverse of the order ``stop`` stops them; the routing state's pass starts the
per-interface engines itself. A unit already running is left as it is.

On macOS and Windows it starts the hub's one service, which runs every
daemon; the ``--only`` forms are Linux's.
"""

import argparse
import subprocess
import sys

from neutrino_hub.cli.stop import STOP_ORDER, STOP_PER_INTERFACE
from neutrino_hub.modules.router.dhcp_client import RouterDhcpClient
from neutrino_hub.modules.router.supplicant import RouterWifiClient
from neutrino_hub.platforms.constants import PLATFORM_SERVICE_RUNNING
from neutrino_hub.platforms.detect import hub_platform, is_linux
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.subprocess_run import command_failure_text

# --- config ---
# The routing state first, the panel last: each stands on the one before it.
START_ORDER = tuple(reversed(STOP_ORDER))


def main() -> int:
    """Start what was asked for, once the person says yes.

    Returns:
        Process exit status; 1 when the answer was no or something refused
        to start.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--interface",
        default=None,
        help="which interface, for the per-interface engines",
    )
    parser.add_argument("--yes", action="store_true", help="start without asking first")
    group = parser.add_mutually_exclusive_group()
    for name in START_ORDER + STOP_PER_INTERFACE:
        group.add_argument(
            f"--only-{name}",
            dest="only",
            action="store_const",
            const=name,
            help=f"start only the {name} service",
        )
    arguments = parser.parse_args()

    if not is_linux():
        if arguments.only:
            print(
                f"error: --only-{arguments.only} names a systemd unit; "
                "nhub start starts the hub's service here",
                file=sys.stderr,
            )
            return 2
        if not arguments.yes and not _asked("Start the hub's service?"):
            return 1
        return start_service()
    if arguments.only in STOP_PER_INTERFACE and not arguments.interface:
        print(f"error: --only-{arguments.only} needs --interface", file=sys.stderr)
        return 1
    what = arguments.only or "the hub's units"
    if arguments.interface and arguments.only in STOP_PER_INTERFACE:
        what = f"{arguments.only} on {arguments.interface}"
    if not arguments.yes and not _asked(f"Start {what}?"):
        return 1
    if arguments.only in STOP_PER_INTERFACE:
        return start_engine(arguments.only, arguments.interface)
    if arguments.only:
        return start([arguments.only], is_enabled_only=False)
    return start(list(START_ORDER), is_enabled_only=True)


def start(names: list, *, is_enabled_only: bool) -> int:
    """Start each named service, and say what happened to it.

    Args:
        names: The hub's own service names, in the order to start them.
        is_enabled_only: Whether a unit that is not enabled is skipped, as
            boot would skip it.

    Returns:
        0 when every one of them is running, 1 when any refused.
    """
    controller = SystemdServiceController()
    is_failed = False
    for name in names:
        status = controller.status(name)
        if not status.is_installed or (is_enabled_only and not status.is_enabled):
            continue
        if status.is_active:
            print(f"  {name}: already running")
            continue
        try:
            controller.control(name, "start")
        except (subprocess.SubprocessError, OSError) as error:
            print(
                f"  {name}: did not start: {command_failure_text(error)}",
                file=sys.stderr,
            )
            is_failed = True
            continue
        print(f"  {name}: started")
    return 1 if is_failed else 0


def start_service() -> int:
    """Start the hub's one service on macOS and Windows.

    Returns:
        0 when it runs or was started, 1 when it refused.
    """
    platform = hub_platform()
    if platform.service_state() == PLATFORM_SERVICE_RUNNING:
        print("  hub service: already running")
        return 0
    try:
        platform.start_service()
    except (subprocess.SubprocessError, OSError) as error:
        print(
            f"  hub service: did not start: {command_failure_text(error)}",
            file=sys.stderr,
        )
        return 1
    print("  hub service: started")
    return 0


def start_engine(name: str, interface: str) -> int:
    """Start one per-interface engine.

    Args:
        name: ``supplicant`` or ``dhcpcd``.
        interface: The interface it runs on.

    Returns:
        0 when it is running or was asked for.
    """
    engine = (
        RouterWifiClient(interface=interface)
        if name == "supplicant"
        else RouterDhcpClient(interface=interface)
    )
    if engine.is_running:
        print(f"  {engine.unit}: already running")
        return 0
    engine.start()
    print(f"  {engine.unit}: started")
    return 0


def _asked(question: str) -> bool:
    """One yes-or-no question on the terminal."""
    answer = input(f"{question} [y/N] ").strip().lower()
    return answer in ("y", "yes")


if __name__ == "__main__":
    sys.exit(main())
