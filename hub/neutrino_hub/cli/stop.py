"""Stop what the hub runs on this box.

    sudo nhub stop                              # everything it started
    sudo nhub stop --only-web                   # one of them
    sudo nhub stop --only-relay
    sudo nhub stop --only-xray                  # where the tree carries the proxy
    sudo nhub stop --only-cliproxyapi
    sudo nhub stop --only-dnsmasq
    sudo nhub stop --only-router
    sudo nhub stop --only-supplicant --interface wlp3s0
    sudo nhub stop --only-dhcpcd --interface enp2s0
    sudo nhub stop --yes                        # without asking first

The pair of ``nhub start``, and spelled the way ``nhub run`` is: the same
``--only-`` flags, the same names, and ``--interface`` for the two engines
that run one per interface. ``--only-router`` is the one name ``run`` has no use for — the
routing state is a unit that finishes rather than a process to watch.

With no ``--only`` it stops all of them, the per-interface engines included:
a box left holding a DHCP lease it asked for is a box the hub has not stopped
running, whatever the panel is doing.

What it leaves alone is the optional modules and the overlay engines. Samba
serves shares whether or not this box routes anything, and an overlay is how
the box is reached from outside, so a plain ``nhub stop`` is the hub going
quiet rather than the machine going down. The relay is stopped with the
panel: it publishes the panel's port on a public server, and a hub that has
gone quiet publishes nothing.

Nothing is disabled, so everything comes back at the next boot. Removing the
hub is the package manager's business, and undoing a setup is ``nhub reset``.

On macOS and Windows it stops the hub's one service, and with it every
daemon the service runs; the ``--only`` forms are Linux's.
"""

import argparse
import subprocess
import sys

from neutrino_hub import edition
from neutrino_hub.modules.router.dhcp_client import RouterDhcpClient
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.supplicant import RouterWifiClient
from neutrino_hub.platforms.constants import PLATFORM_SERVICE_STOPPED
from neutrino_hub.platforms.detect import hub_platform, is_linux
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.utils.subprocess_run import command_failure_text

# The order they are stopped in, which is the order they sit on each other.
# The panel first because it is what a person is holding: stopping it while
# the proxy underneath is already gone means a page that hangs rather than one
# that closes. The routing state last, because it is what the rest ran on.
# The relay right after the panel whose port it publishes. The proxy core's
# unit is the proxy's, from the edition table.
STOP_ORDER = (
    "web",
    "relay",
    "cliproxyapi",
    "dnsmasq",
    *edition.hooks("services"),
    "router",
)
# The two that run one unit per interface, named as `run` names them.
STOP_PER_INTERFACE = ("supplicant", "dhcpcd")
# What a command that asks says when there is no terminal to ask on.
CLI_NO_TERMINAL_LINE = (
    "error: no terminal to answer on; run it again with --yes to go ahead "
    "without asking"
)


def main() -> int:
    """Stop what was asked for, once the person says yes.

    Returns:
        Process exit status; 1 when the answer was no or something refused
        to stop.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--interface",
        default=None,
        help="which interface, for the per-interface engines",
    )
    parser.add_argument("--yes", action="store_true", help="stop without asking first")
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

    if arguments.only and not is_linux():
        print(
            f"error: --only-{arguments.only} names a systemd unit; "
            "nhub stop stops the hub's service here",
            file=sys.stderr,
        )
        return 2
    if arguments.only in STOP_PER_INTERFACE and not arguments.interface:
        print(f"error: --only-{arguments.only} needs --interface", file=sys.stderr)
        return 1
    if not is_linux():
        what = "the hub's service"
    elif arguments.only in STOP_PER_INTERFACE:
        what = f"{arguments.only} on {arguments.interface}"
    else:
        what = arguments.only or "the hub's units"
    if not arguments.yes and not is_confirmed_on_terminal(f"Stop {what}?"):
        return 1
    if arguments.only in STOP_PER_INTERFACE:
        return stop_engine(arguments.only, arguments.interface)
    if arguments.only:
        return stop([arguments.only])
    return stop_everything()


def stop_everything() -> int:
    """Stop every service the hub runs, engines included.

    Returns:
        0 when everything is stopped, 1 when any of it refused.
    """
    if not is_linux():
        return stop_service()
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
        except (subprocess.SubprocessError, OSError) as error:
            # Reported rather than raised: one unit that will not stop must
            # not hide what happened to the others, and `systemctl status`
            # says more about it than a traceback here could.
            print(
                f"  {name}: did not stop: {command_failure_text(error)}",
                file=sys.stderr,
            )
            is_failed = True
            continue
        print(f"  {name}: stopped")
    return 1 if is_failed else 0


def stop_service() -> int:
    """Stop the hub's one service on macOS and Windows, its children with it.

    Returns:
        0 when it is stopped, 1 when it refused.
    """
    platform = hub_platform()
    if platform.service_state() == PLATFORM_SERVICE_STOPPED:
        print("  hub service: already stopped")
        return 0
    try:
        platform.stop_service()
    except (subprocess.SubprocessError, OSError) as error:
        print(
            f"  hub service: did not stop: {command_failure_text(error)}",
            file=sys.stderr,
        )
        return 1
    print("  hub service: stopped")
    return 0


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
    except (subprocess.SubprocessError, OSError) as error:
        print(
            f"  {engine.unit}: did not stop: {command_failure_text(error)}",
            file=sys.stderr,
        )
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


def is_confirmed_on_terminal(question: str) -> bool:
    """Ask one yes-or-no question on the terminal.

    With no terminal on stdin nothing is asked: one line on stderr says that
    ``--yes`` goes ahead without asking.

    Args:
        question: The question, without ``[y/N]``.

    Returns:
        True only for ``y`` or ``yes``; no input and no terminal are a no.
    """
    if sys.stdin is None or not sys.stdin.isatty():
        print(CLI_NO_TERMINAL_LINE, file=sys.stderr)
        return False
    try:
        answer = input(f"{question} [y/N] ")
    except EOFError:
        print()
        return False
    return answer.strip().lower() in ("y", "yes")


if __name__ == "__main__":
    sys.exit(main())
