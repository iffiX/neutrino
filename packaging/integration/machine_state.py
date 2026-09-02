"""What the machine itself says about its network, read without the panel.

The panel's API cannot answer the question a server or side_gateway install
has to answer: whether the machine is still the machine its owner had. That
is a question
about files nobody asked the hub to touch, about the manager that was already
running, and about what the kernel holds — so it is read here, from the box.
"""

import json
import re
import subprocess
import time
from pathlib import Path

# Where the distributions keep their network configuration. A hub that leaves
# every one of these byte for byte as it found them has configured nothing of
# the machine's own.
MACHINE_CONFIG_TREES = (
    "/etc/netplan",
    "/etc/NetworkManager/system-connections",
    "/etc/systemd/network",
    "/etc/network",
)
# Every manager a machine might arrive running, plus the resolver they pair
# with. Named one by one rather than counted: a stock Ubuntu arrives with nine
# units of its own masked, and counting those says nothing about the hub.
MACHINE_MANAGERS = (
    "NetworkManager",
    "systemd-networkd",
    "systemd-networkd.socket",
    "networking",
    "dhcpcd",
    "connman",
    "netctl",
    "iwd",
    "systemd-resolved",
)
MACHINE_RESOLV_PATH = Path("/etc/resolv.conf")
# The note a mode that took a machine over leaves behind, so a reset knows what
# to hand back. A server or side_gateway install writes none.
MACHINE_STOOD_DOWN_PATH = Path("/var/lib/neutrino/stood_down.json")


def run(command: list) -> str:
    """One command, for its output alone.

    Args:
        command: The argument vector.

    Returns:
        Its standard output, empty when it could not be run. Most of these
        exit non-zero for answers that are answers, so the status is ignored.
    """
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def is_active(unit: str) -> bool:
    """Whether systemd reports a unit active."""
    return run(["systemctl", "is-active", unit]).strip().splitlines()[:1] == ["active"]


def is_masked(unit: str) -> bool:
    """Whether a unit has been masked."""
    return run(["systemctl", "is-enabled", unit]).strip().splitlines()[:1] == ["masked"]


def running_manager() -> str:
    """Which network manager this machine arrived running.

    Returns:
        Its unit name, or an empty string when nothing known is running.
    """
    for unit in MACHINE_MANAGERS:
        if unit.endswith(".socket") or unit == "systemd-resolved":
            continue
        if is_active(unit):
            return unit
    return ""


def config_trees() -> dict:
    """Every network configuration file the distributions keep, by digest.

    Returns:
        One entry per file, path to md5. A tree that does not exist
        contributes nothing, which is what "unchanged" means for a machine
        that never had it.
    """
    digests = {}
    for tree in MACHINE_CONFIG_TREES:
        if not Path(tree).is_dir():
            continue
        for line in run(
            ["find", tree, "-type", "f", "-exec", "md5sum", "{}", "+"]
        ).splitlines():
            digest, _, path = line.partition("  ")
            digests[path] = digest
    return digests


# The hub's own configuration: the whole of what a set-up box is, and what a
# package must not touch. Not the generated tree beside it, which is rendered
# from this one and is supposed to change.
MACHINE_HUB_CONFIG_DIR = "/etc/neutrino/hub"


def config_digests() -> dict:
    """The hub's own configuration files, by digest.

    Returns:
        One entry per file, path to md5, empty on a box that has never been
        set up.
    """
    if not Path(MACHINE_HUB_CONFIG_DIR).is_dir():
        return {}
    digests = {}
    for line in run(
        ["find", MACHINE_HUB_CONFIG_DIR, "-type", "f", "-exec", "md5sum", "{}", "+"]
    ).splitlines():
        digest, _, path = line.partition("  ")
        digests[path] = digest
    return digests


def started_at(unit: str) -> str:
    """When systemd last brought a unit up.

    Args:
        unit: The unit name, without ``.service``.

    Returns:
        The timestamp as systemd prints it, empty when the unit is not
        running. Comparing it across a reinstall is how "was restarted" is
        told from "was left alone" — both of which leave the unit active.
    """
    return run(
        ["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", unit]
    ).strip()


# How long the panel gets to answer again after the package restarted it.
# Measured at two to three seconds on a Debian 12 VM; the ceiling is for a
# slower box rather than a hung one.
MACHINE_PANEL_RETURN_S = 60


def reinstall(package: str) -> None:
    """Install a package over the copy of it that is already there.

    Every maintainer script an upgrade runs, runs here, which is what makes
    this a test of the upgrade path without needing two releases to exist.

    Returns once the panel answers again: the package restarts it, and a
    check that ran in the second before it finished binding would be
    measuring the restart rather than the upgrade.

    Args:
        package: Path to the package file.

    Raises:
        AssertionError: When the package manager refuses it, or the panel does
            not come back.
    """
    if package.endswith(".deb"):
        command = ["dpkg", "-i", package]
    elif package.endswith(".rpm"):
        command = ["rpm", "-Uvh", "--replacepkgs", package]
    else:
        command = ["pacman", "-U", "--noconfirm", package]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, (result.stderr or result.stdout).strip()

    deadline = time.monotonic() + MACHINE_PANEL_RETURN_S
    while time.monotonic() < deadline:
        if is_active("neutrino_hub_web") and _panel_answers():
            return
        time.sleep(1.0)
    raise AssertionError("the panel never answered again after the reinstall")


def _panel_answers() -> bool:
    """Whether the panel is serving on its own port."""
    port = run(
        ["python3", "-c", PANEL_PORT_SCRIPT],
    ).strip()
    probe = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", f"http://127.0.0.1:{port or 8080}/"],
        capture_output=True,
    )
    return probe.returncode == 0


# Read from the panel's own settings rather than assumed: the port is a thing
# somebody can move, and a check that hard-codes it reports a moved panel as a
# dead one.
PANEL_PORT_SCRIPT = (
    "import json;"
    "print(json.load(open('/etc/neutrino/hub/web/settings.json'))"
    ".get('listen_port', 8080))"
)


def addresses_and_routes() -> list:
    """Every global address and default route the kernel holds.

    Returns:
        One line per address and per route, sorted.
    """
    addresses = [
        " ".join(line.split()[1:4:2])
        for line in run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"]
        ).splitlines()
    ]
    routes = run(["ip", "-4", "route", "show", "default"]).splitlines()
    return sorted(addresses) + sorted(route.strip() for route in routes)


def resolv_conf() -> str:
    """What the machine resolves through.

    Returns:
        The file's text, empty when it has none.
    """
    try:
        return MACHINE_RESOLV_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def first_interface() -> str:
    """The interface this machine is reached on.

    Returns:
        The name of the first interface holding a global address.
    """
    for line in run(["ip", "-4", "-o", "addr", "show", "scope", "global"]).splitlines():
        return line.split()[1]
    return ""


def is_answering_on(interface: str) -> bool:
    """Whether the input chain lets everything in on one interface.

    Args:
        interface: The interface's name.

    Returns:
        True when the chain carries an accept for it. Either spelling counts:
        nft prints a one-element anonymous set as a bare match, so the braces
        are there with two interfaces and gone with one.
    """
    chain = run(["nft", "list", "chain", "inet", "neutrino", "input"])
    pattern = rf'iifname (\{{[^}}]*"{re.escape(interface)}"[^}}]*\}}|"{re.escape(interface)}") accept$'
    return re.search(pattern, chain, re.MULTILINE) is not None


def firewall_table() -> str:
    """The hub's whole nftables table, as text."""
    return run(["nft", "list", "table", "inet", "neutrino"])


def units_matching(pattern: str) -> list:
    """Active units whose names match a systemd pattern.

    Args:
        pattern: A unit glob, as `systemctl list-units` takes it.

    Returns:
        One name per active unit.
    """
    listed = run(["systemctl", "list-units", "--state=active", pattern, "--no-legend"])
    return [line.split()[0] for line in listed.splitlines() if line.strip()]


def snapshot() -> dict:
    """Everything about this machine's network that a hub must not change.

    Returns:
        An object that compares equal to a later one when nothing changed.
    """
    return {
        "manager": running_manager(),
        "config_trees": config_trees(),
        "addresses_and_routes": addresses_and_routes(),
        "resolv_conf": resolv_conf(),
        "interface": first_interface(),
        "ip_forward": run(["sysctl", "-n", "net.ipv4.ip_forward"]).strip(),
    }


def write_snapshot(path: str) -> None:
    """Record this machine's state for a later comparison.

    Args:
        path: Where to write it.
    """
    Path(path).write_text(json.dumps(snapshot(), indent=2), encoding="utf-8")


def read_snapshot(path: str) -> dict:
    """Read a recorded state.

    Args:
        path: Where it was written.

    Returns:
        The recorded object.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))
