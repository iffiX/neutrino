"""Running the TUN device on macOS and Windows: its plan, its child, its routes.

Each routing pass there renders the plan from the scopes and from what the
machine says now, keeps it in the plan file, and hands tun2socks's start
line to the process controller, enabled while the plan stands and disabled
when it does not. Inside the service a keeper follows the plan file: once
tun2socks has opened the device it brings the address, the forwarding and
the routes up, and when tun2socks ends it withdraws exactly what it added.
The supervisor ends tun2socks before xray stops, restarts or is found
ended, so the machine is never left routing into a device nothing reads.
Linux diverts with nftables and never comes here.

Not pure: reads the system, resolves names, runs the appliers, writes the
plan and state files.
"""

import ipaddress
import socket
import json
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

import psutil

from neutrino_hub.modules.easytier.constants import EASYTIER_DEFAULT_CONFIG_SERVER
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.netbird.ops import NetbirdStatusReader
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import (
    device_addresses,
    system_default_routes,
)
from neutrino_hub.modules.tun.applied_state import (
    TunAppliedState,
    forget_applied,
    read_applied,
    write_applied,
)
from neutrino_hub.modules.tun.constants import (
    TUN_BINARY_PATH,
    TUN_DEVICE_NAMES,
    TUN_DIVERTED_PREFIXES,
    TUN_PLAN_PATH,
    TUN_RETRY_S,
    TUN_STATE_PATH,
    TUN_SUPERVISED_NAME,
)
from neutrino_hub.modules.tun.darwin_applier import TunDarwinApplier
from neutrino_hub.modules.tun.renderer import (
    TunPlan,
    is_tun_wanted,
    render_start_line,
    render_tun_plan,
)
from neutrino_hub.modules.tun.windows_applier import TunWindowsApplier
from neutrino_hub.modules.xray.constants import (
    XRAY_LOCAL_SOCKS_PORT,
    XRAY_SCOPE_OVERLAY,
)
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_probe import resolve_direct
from neutrino_hub.modules.xray.node_secrets import resolve_node_secrets
from neutrino_hub.platforms.constants import PLATFORM_OS_WINDOWS
from neutrino_hub.platforms.detect import hub_os, is_linux, process_controller
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.utils.subprocess_run import command_failure_text


def plan_tun(network: RouterNetworkConfig, routing: dict) -> "TunPlan | None":
    """The plan for this machine now, or None when nothing diverts through it.

    Args:
        network: The parsed router configuration, carrying the overlays'
            devices found at run time.
        routing: Parsed ``config/xray/routing.json``.

    Returns:
        The plan; None on Linux, with both TUN scopes off, with no exit
        node to send to, or with no default route to keep the direct routes
        on.

    Raises:
        ValueError: When the node list is not JSON.
    """
    if is_linux():
        return None
    node_list = XrayNodeList.from_dict(_config("xray/nodes.json"))
    resolve_node_secrets(node_list)
    has_exit = any(
        node.is_enabled and node.has_secret_material for node in node_list.nodes
    )
    if not is_tun_wanted(routing, has_exit=has_exit):
        return None
    device = TUN_DEVICE_NAMES[hub_os()]
    uplink = _uplink(device)
    if uplink is None:
        return None
    direct = routing.get("direct_dns", {})
    server = str(direct.get("address", "223.5.5.5"))
    port = int(direct.get("port", 53))
    names = [node.address for node in node_list.nodes]
    names.append(urllib.parse.urlsplit(node_list.reference_url).hostname or "")
    names += _overlay_server_hosts(network)
    kept_out = [server]
    for name in dict.fromkeys(names):
        address = _resolved(name, server=server, port=port)
        if address:
            kept_out.append(address)
    forwarding = []
    if routing.get(XRAY_SCOPE_OVERLAY, False):
        present = _present_devices()
        forwarding = [
            name for name in network.exposed_overlay_device_names if name in present
        ]
        if forwarding and hub_os() == PLATFORM_OS_WINDOWS:
            forwarding.append(device)
    return render_tun_plan(
        device=device,
        start_argv=render_start_line(
            binary=str(TUN_BINARY_PATH),
            device=device,
            socks_port=XRAY_LOCAL_SOCKS_PORT,
        ),
        uplink=uplink["dev"],
        gateway=uplink.get("gateway", ""),
        local_networks=[
            cidr for name, cidr in device_addresses().items() if name != device
        ],
        kept_out=kept_out,
        forwarding_devices=forwarding,
    )


def converge_tun(
    network: RouterNetworkConfig,
    routing: dict,
    *,
    controller=None,
    plan_path: Path = TUN_PLAN_PATH,
    state_path: Path = TUN_STATE_PATH,
) -> list:
    """Keep the plan and run tun2socks while it stands; stop it when it does not.

    Args:
        network: The parsed router configuration, carrying the overlays'
            devices found at run time.
        routing: Parsed ``config/xray/routing.json``.
        controller: The process controller; None is this process's.
        plan_path: Where the plan is kept.
        state_path: Where the service keeps what it applied.

    Returns:
        One line when the plan changed or the device went away; empty
        otherwise, and always on Linux.

    Raises:
        OSError: When the plan or ``services.json`` cannot be written, or the
            service could not add a route of the plan it applied last.
        ValueError: When the node list is not JSON.
    """
    if is_linux():
        return []
    controller = controller if controller is not None else process_controller()
    plan = plan_tun(network, routing)
    kept = read_plan(plan_path)
    if plan is None:
        notes = []
        if kept is not None:
            plan_path.unlink(missing_ok=True)
            notes.append(f"tun device {kept.device} taken down")
        if controller.is_enabled(TUN_SUPERVISED_NAME):
            controller.disable(TUN_SUPERVISED_NAME)
        return notes
    notes = []
    if kept != plan:
        write_generated(plan_path, json.dumps(plan.to_dict(), indent=2) + "\n")
        notes.append(
            f"tun device {plan.device} takes the default route, "
            f"{len(plan.routes) - len(TUN_DIVERTED_PREFIXES)} addresses kept out"
        )
    if kept != plan or not controller.is_enabled(TUN_SUPERVISED_NAME):
        controller.set_start_line(TUN_SUPERVISED_NAME, list(plan.start_argv), {}, None)
        controller.enable(TUN_SUPERVISED_NAME)
    applied = read_applied(state_path)
    if applied is not None and applied.plan == plan.to_dict() and applied.failures:
        raise OSError("; ".join(applied.failures))
    return notes


def egress_interface(routing: dict) -> str:
    """The uplink xray's direct and node outbounds are bound to while the TUN runs.

    Args:
        routing: Parsed ``config/xray/routing.json``.

    Returns:
        The interface of the machine's default route outside Linux with a
        TUN scope on; empty otherwise.
    """
    if is_linux() or not is_tun_wanted(routing, has_exit=True):
        return ""
    uplink = _uplink(TUN_DEVICE_NAMES[hub_os()])
    return uplink["dev"] if uplink is not None else ""


def read_plan(path: Path = TUN_PLAN_PATH) -> "TunPlan | None":
    """The plan the last routing pass kept.

    Args:
        path: The plan file.

    Returns:
        The plan, or None when none is kept or it cannot be read.
    """
    try:
        return TunPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def tun_applier():
    """The applier of this system.

    Returns:
        A :class:`TunWindowsApplier` on Windows, a :class:`TunDarwinApplier`
        elsewhere.
    """
    if hub_os() == PLATFORM_OS_WINDOWS:
        return TunWindowsApplier()
    return TunDarwinApplier()


def withdraw_tun(*, state_path: Path = TUN_STATE_PATH) -> list:
    """Withdraw whatever a service that ended left applied, as a start does.

    Args:
        state_path: Where the service keeps what it applied.

    Returns:
        One line per route withdrawn; empty when nothing was applied.

    Raises:
        OSError: When PowerShell cannot run on Windows, or the state file
            cannot be deleted.
    """
    if is_linux():
        return []
    return TunRouteKeeper(
        is_running=_never_running, state_path=state_path, applier=tun_applier()
    ).withdraw()


class TunRouteKeeper:
    """Keeps the TUN device's routes what the plan says while tun2socks runs.

    The service's supervisor calls :meth:`tick` after each of its ticks and
    :meth:`child_ended` whenever a child's process ends.
    """

    def __init__(
        self,
        *,
        is_running,
        applier=None,
        plan_path: Path = TUN_PLAN_PATH,
        state_path: Path = TUN_STATE_PATH,
        devices=None,
        clock=None,
        log=print,
    ):
        """
        Args:
            is_running: Called with a child's name; whether it runs now.
            applier: Brings a plan up and withdraws it; None is this
                system's.
            plan_path: Where the routing pass keeps the plan.
            state_path: Where what was applied is kept.
            devices: Returns the names of the interfaces the machine has
                now; None asks psutil.
            clock: Returns the time in seconds; None is ``time.monotonic``.
            log: Called with each line worth a person's reading.
        """
        self._is_running = is_running
        self._applier = applier if applier is not None else tun_applier()
        self._plan_path = Path(plan_path)
        self._state_path = Path(state_path)
        self._devices = devices if devices is not None else _present_devices
        self._clock = clock or time.monotonic
        self._log = log
        self._lock = threading.Lock()
        self._tried: "dict | None" = None
        self._retry_at = 0.0

    def tick(self) -> None:
        """Bring the plan up once tun2socks opened the device; withdraw a stale one.

        A bring-up that cannot run is logged and not tried again for the same
        plan until tun2socks starts again; a withdrawal that cannot run is
        logged and tried again after ``TUN_RETRY_S``.

        Raises:
            OSError: When the state cannot be kept.
        """
        is_up = self._is_running(TUN_SUPERVISED_NAME)
        with self._lock:
            plan = read_plan(self._plan_path)
            wanted = plan.to_dict() if plan is not None else None
            applied = read_applied(self._state_path)
            if applied is not None and (not is_up or applied.plan != wanted):
                if self._clock() < self._retry_at:
                    return
                if not self._withdraw_logged(applied):
                    return
                applied = None
            if plan is None or not is_up or applied is not None:
                return
            if self._tried == wanted or plan.device not in self._devices():
                return
            self._tried = wanted
            try:
                state = self._applier.bring_up(plan, keep=self._keep)
            except (OSError, subprocess.SubprocessError) as error:
                self._log(
                    f"tun: {plan.device} not brought up: {command_failure_text(error)}"
                )
                return
            self._keep(state)
            for failure in state.failures:
                self._log(f"tun: {failure}")
            self._log(f"tun: {plan.device} up with {len(state.routes)} routes")

    def child_ended(self, name: str) -> None:
        """Withdraw the routes once tun2socks ended, whatever ended it.

        A withdrawal that cannot run is logged, and the next tick tries it
        again.

        Args:
            name: The child whose process ended.
        """
        if name != TUN_SUPERVISED_NAME:
            return
        with self._lock:
            self._tried = None
            applied = read_applied(self._state_path)
            if applied is not None:
                self._withdraw_logged(applied)

    def withdraw(self) -> list:
        """Withdraw everything kept as applied.

        Returns:
            One line per route withdrawn.

        Raises:
            OSError: When the state cannot be deleted, or PowerShell cannot
                run.
        """
        with self._lock:
            self._tried = None
            applied = read_applied(self._state_path)
            if applied is None:
                return []
            return self._withdraw(applied)

    def _withdraw(self, applied: TunAppliedState) -> list:
        """Take the applied routes away and forget them."""
        try:
            notes = self._applier.withdraw(applied)
        except subprocess.SubprocessError as error:
            raise OSError(command_failure_text(error)) from error
        forget_applied(self._state_path)
        if notes:
            self._log(f"tun: {len(notes)} changes withdrawn")
        return notes

    def _withdraw_logged(self, applied: TunAppliedState) -> bool:
        """Withdraw, logging a failure and waiting before the next try."""
        try:
            self._withdraw(applied)
        except OSError as error:
            self._retry_at = self._clock() + TUN_RETRY_S
            self._log(f"tun: routes not withdrawn: {error}")
            return False
        self._retry_at = 0.0
        return True

    def _keep(self, state: TunAppliedState) -> None:
        """Keep what was applied so far."""
        write_applied(self._state_path, state)


def _uplink(device: str) -> "dict | None":
    """The machine's default route that is not onto the TUN device."""
    for route in system_default_routes():
        if route.get("dev") and route["dev"] != device:
            return route
    return None


def _resolved(name: str, *, server: str, port: int) -> str:
    """One name as an IPv4 address; empty when no resolver has one.

    The direct resolver is asked first, the system's when it has no answer:
    an exit left without its host route would still leave by the uplink,
    bound to it, but the route is what keeps it there when the binding
    cannot.
    """
    if not name:
        return ""
    try:
        return str(ipaddress.ip_address(name))
    except ValueError:
        pass
    try:
        address = resolve_direct(name, server=server, port=port) or ""
    except OSError:
        address = ""
    if address:
        return address
    try:
        found = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return ""
    return str(found[0][4][0]) if found else ""


def _overlay_server_hosts(network: RouterNetworkConfig) -> list:
    """The hosts of the running overlays' servers.

    NetBird's management plane, signal server and relays as its daemon
    reports them; EasyTier's peers and its console.
    """
    providers = enabled_providers(network)
    urls = []
    if OVERLAY_NETBIRD in providers:
        urls += NetbirdStatusReader().survey().server_urls
    if OVERLAY_EASYTIER in providers:
        config = read_easytier()
        urls += list(config.peers)
        if config.is_console_mode and config.has_config_server:
            try:
                console = config.config_server()
            except ValueError:
                console = ""
            urls.append(console if "://" in console else EASYTIER_DEFAULT_CONFIG_SERVER)
    hosts = []
    for url in urls:
        try:
            host = urllib.parse.urlsplit(str(url)).hostname
        except ValueError:
            continue
        if host:
            hosts.append(host)
    return hosts


def _config(name: str) -> dict:
    """One configuration file; empty before setup wrote it."""
    try:
        return read_config(name)
    except FileNotFoundError:
        return {}


def _present_devices() -> set:
    """The interfaces the machine has now."""
    return set(psutil.net_if_stats())


def _never_running(name: str) -> bool:
    """Nothing runs: the service has not started its children yet."""
    return False
