"""Shared runtime objects the panel's routes work through.

One instance is built at startup and reached from every route. It owns the live
things (session store, running jobs, the agents' sockets) and knows how to
re-render and apply the configuration, so no route shells out to systemd or nft
by itself.
"""

import asyncio
import ipaddress

from neutrino_hub.modules.netbird.ops import NetbirdInboundGate
from neutrino_hub.modules.router.dnsmasq_renderer import RouterDnsmasqRenderer
from neutrino_hub.modules.router.connections import RouterConnectionSet
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import RouterLinkStatus
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.modules.router.routes import (
    RouterDefaultRouteApplier,
    RouterInterfaceApplier,
    RouterRulesetApplier,
    lookup_xray_uid,
)
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiServedModelCache
from neutrino_hub.modules.devices.catalog import DeviceCatalogCache
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.modules.router.share_fence import share_subnets
from neutrino_hub.modules.services.probe import DeclaredServiceProbe
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.modules.services.published import PublishedServiceCache
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.system.listening_ports import ListeningPortReader
from neutrino_hub.web.constants import (
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_EVENT_AI_USAGE,
    WEB_EVENT_CONFIG,
    WEB_EVENT_DEVICES,
    WEB_EVENT_MODULE_ORDER,
    WEB_EVENT_NODES,
    WEB_EVENT_SERVICES,
    WEB_EVENT_TASK,
    WEB_PROXY_SCOPE_HUB,
    WEB_PROXY_SCOPE_LAN,
    WEB_PROXY_SCOPE_LAN_AND_HUB,
    WEB_PROXY_SCOPE_OFF,
    WEB_PROXY_SCOPE_PORTS,
    WEB_PROXY_SCOPE_UNUSED,
)
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import (
    read_config,
    set_config_write_hook,
    write_config,
    write_generated,
)
from neutrino_hub.utils.subprocess_run import CommandError, run
from neutrino_hub.web.auth import SessionStore, session_secret
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.link_sampler import PanelLinkSampler
from neutrino_hub.modules.devices.agent_module_cache import AgentModuleCache
from neutrino_hub.modules.devices.agent_module_controller import (
    ORDER_DONE,
    ORDER_FAILED,
    AgentModuleController,
    AgentModuleOrder,
)
from neutrino_hub.modules.devices.agent_package import AgentPackageCache
from neutrino_hub.modules.devices.agent_sessions import (
    AgentOfflineError,
    AgentSessionRegistry,
    StreamRefusedError,
)
from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_ORDER_TIMEOUT_S,
    AGENT_MODULE_OUTPUT_LIMIT_BYTES,
    AGENT_WS_CLOSE_UNKNOWN_TOKEN,
)
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.web.task_stream import TaskStreamRegistry
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_secrets import resolve_node_secrets
from neutrino_hub.modules.xray.node_probe import XrayNodeProbe
from neutrino_hub.modules.xray.stats_client import XrayStatsClient

from neutrino_hub.modules.router.constants import (
    ROUTER_DNSMASQ_PATH,
    ROUTER_NFT_PATH,
    ROUTER_OVERLAY_NETBIRD,
)

DNSMASQ_SERVICE_NAME = SYSTEM_CORE_UNITS["dnsmasq"]


class PanelRuntime:
    """Everything the routes share, plus the render-and-apply pipeline."""

    def __init__(self):
        settings = read_config("web/settings.json")
        self.settings = settings
        self.session_secret = session_secret()
        self.sessions = SessionStore(
            password_hash=settings.get("admin_password_hash", ""),
            session_ttl_hours=settings.get("session_ttl_hours", 168),
        )
        # The one channel the panel hears about everything on. Built first,
        # since what follows publishes through it.
        self.events = PanelEventBus()
        self.tasks = TaskStreamRegistry(on_change=self._publish_task)
        self.services = SystemdServiceController()
        self.listening_ports = ListeningPortReader()
        self.stats = XrayStatsClient()
        self.node_probe = XrayNodeProbe()
        self.declared_probe = DeclaredServiceProbe()
        self.served_models = CliproxyApiServedModelCache()
        # What each managed machine last said about sharing its desktop.
        # Runtime only: a share is the machine's own word, refreshed every
        # beat, and a hub restart simply waits for the next one.
        self.device_shares = DeviceShareRegistry()
        # Every managed machine's live socket, and the streams on it.
        self.agent_sessions = AgentSessionRegistry()
        self.agent_sessions.on_presence_change = self._publish_devices
        # Where each agent's channel comes from, as this hub's own socket
        # sees it, refreshed every report. A machine that moves is at its
        # new address the moment it reports from there.
        self.client_address: dict[str, str] = {}
        # What each device should host, one directory per device under
        # config/, composed into the state its agent applies.
        self.desired_states = DesiredStateStore()
        self.published_services = PublishedServiceCache(
            declared_probe=self.declared_probe,
            served_models=self.served_models,
            units=self.services,
            device_shares=self.device_shares,
            agent_sessions=self.agent_sessions,
            device_addresses=self.client_address,
            desired_states=self.desired_states,
            on_fingerprint_change=self._publish_services,
        )
        self.device_catalog = DeviceCatalogCache(services=self.published_services)
        # The hub is the only thing that fetches and installs a module: one
        # cache for the bytes, one lock per device, and one controller that
        # is the single door every install goes through.
        self.agent_modules = AgentModuleCache()
        # The hub's own agent packages, seeded by its package and topped up
        # from the release for a platform it was not built for.
        self.agent_packages = AgentPackageCache()
        self.device_install_locks = DeviceInstallLocks()
        self.agent_module_orders = AgentModuleController(
            cache=self.agent_modules,
            locks=self.device_install_locks,
            dispatch=self._dispatch_order,
            on_change=self._publish_module_order,
        )
        self.is_config_dirty = False
        # Latest agent metrics, keyed by MAC. Runtime only: these are stale the
        # moment the panel restarts, so they are never written to config/.
        self.client_metrics: dict[str, dict] = {}
        # Latest per-module reconcile state an agent reported, keyed by MAC.
        # Runtime only, for the same reason as the metrics.
        self.client_modules: dict[str, dict] = {}
        # The platform tuple an agent last reported, keyed by MAC, so the panel
        # can show only the modules that platform can install.
        self.client_platform: dict[str, dict] = {}
        # The hostname each agent last reported, keyed by MAC. Runtime only,
        # like the metrics.
        self.client_hostname: dict[str, str] = {}
        # The human accounts each agent last reported, keyed by MAC.
        self.client_accounts: dict[str, list] = {}
        # The address each device reaches this hub on, resolved when its
        # socket opened; the services view composes the same catalog with it.
        self.client_device_host: dict[str, str] = {}
        # The most recent error each agent reported, keyed by MAC:
        # ``{"code", "params"}``.
        self.client_last_error: dict[str, dict] = {}
        # Enrollment tickets a machine can join with, by token. Held in memory
        # and short-lived on purpose: a join secret that survives a restart is
        # a join secret lying around, and generating another takes one click.
        self.enrollments: dict[str, dict] = {}
        # A cable, a lease or a radio moving is a change nothing writes, so
        # it is sampled. The application starts it; a CLI run builds a runtime
        # and never wants the thread.
        self.link_sampler = PanelLinkSampler(runtime=self)
        # What the nodes panel last drew, so a cycle reading the same numbers
        # tells nobody. One place, since a collector lives per open socket.
        self._node_readings: dict = {}
        self._apply_lock = asyncio.Lock()
        set_config_write_hook(self._publish_config_write)

    def network(self) -> RouterNetworkConfig:
        """Read the current router configuration.

        Returns:
            Parsed ``config/router/network.json``, with the pre-roles shape
            migrated on the way through.
        """
        return RouterNetworkConfig.from_dict(read_config("router/network.json"))

    def write_network(self, network: RouterNetworkConfig) -> None:
        """Store the router configuration.

        Args:
            network: The configuration to write. Always the whole file: it is
                small, and a partial write would leave the roles inconsistent
                with each other.
        """
        write_config("router/network.json", network.to_dict())

    def connections(self) -> RouterConnectionSet:
        """Read the wireless networks this box knows how to join.

        Returns:
            Parsed ``config/router/connections.json``.
        """
        return RouterConnectionSet.from_dict(read_config("router/connections.json"))

    def write_connections(self, connections: RouterConnectionSet) -> None:
        """Store the wireless networks.

        Args:
            connections: The whole set, always: it is small, and a partial
                write would leave the supplicant with half a list.
        """
        write_config("router/connections.json", connections.to_dict())

    def routing(self) -> dict:
        """Read the current routing configuration.

        Returns:
            Parsed ``config/xray/routing.json``.
        """
        return read_config("xray/routing.json")

    def node_list(self) -> XrayNodeList:
        """Read the current node list.

        Returns:
            Parsed ``config/xray/nodes.json``.
        """
        return XrayNodeList.from_dict(read_config("xray/nodes.json"))

    def link_status(self) -> RouterLinkStatus:
        """Build a reader for the live state of the interfaces.

        Returns:
            A reader; it takes no configuration because it reports what the
            system is doing, not what the config asked for.
        """
        return RouterLinkStatus()

    def proxy_scope(self) -> str:
        """Which traffic the proxy is actually taking right now.

        The diversion states are read from the ruleset that was last applied
        rather than from ``config/``, because the two disagree for as long as
        a change is saved and not yet applied. The file is written after the
        load succeeds, so it is what the kernel holds and not what it was
        about to be handed — and the status strip has to answer "where is my
        traffic going", which during that window the config would answer with
        where it is *about* to go.

        Returns:
            One of the ``WEB_PROXY_SCOPE_*`` answers. A server whose proxy
            serves only its SOCKS ports is ``ports``, not ``lan``: reporting
            a diversion there would answer a question that mode never poses.
            When nothing has been applied yet, the configured intention is
            the best available answer.
        """
        routing = self.routing()
        try:
            ruleset = ROUTER_NFT_PATH.read_text(encoding="utf-8")
        except OSError:
            is_lan_diverted = routing.get("is_proxy_enabled", True) and bool(
                self.network().lan_interfaces
            )
            is_hub_diverted = bool(routing.get("is_local_proxy_enabled", False))
        else:
            # The hub's own diversion hairpins through loopback, which is the
            # one tproxy statement naming that interface; the LAN's does not.
            diversions = [
                line for line in ruleset.splitlines() if "tproxy ip to" in line
            ]
            is_lan_diverted = any('iifname "lo"' not in line for line in diversions)
            is_hub_diverted = any('iifname "lo"' in line for line in diversions)
        if is_lan_diverted and is_hub_diverted:
            return WEB_PROXY_SCOPE_LAN_AND_HUB
        if is_lan_diverted:
            return WEB_PROXY_SCOPE_LAN
        if is_hub_diverted:
            return WEB_PROXY_SCOPE_HUB
        is_port_proxied = any(
            entry.get("is_proxied") for entry in routing.get("socks_ports", [])
        )
        if is_port_proxied and self.node_list().enabled_nodes:
            return WEB_PROXY_SCOPE_PORTS
        if (
            routing.get("is_proxy_enabled", True)
            or routing.get("is_local_proxy_enabled", False)
            or is_port_proxied
        ):
            return WEB_PROXY_SCOPE_UNUSED
        return WEB_PROXY_SCOPE_OFF

    def uplink_address(self) -> str | None:
        """The address this box reaches the internet from.

        Returns:
            The first configured WAN that has an address — with several
            uplinks it is the one nearest the front of the list — or, in the
            modes that give no port the WAN role, the address of the interface
            carrying the default route. None when the box has no way out. The
            strip shows this as "the WAN address", and it has to answer in
            every mode: a server has no uplink and still got here somehow.
        """
        status = RouterLinkStatus()
        for interface in self.network().wan_interfaces:
            link = status.link(interface.device_name)
            if link.ipv4_address:
                return link.ipv4_address
        for route in status.default_routes():
            hops = route.get("nexthops") or [route]
            for hop in hops:
                device = hop.get("dev")
                if not device:
                    continue
                link = status.link(str(device))
                if link.ipv4_address:
                    return link.ipv4_address
        return None

    async def apply_all(self) -> str:
        """Re-render every generated config and apply it.

        Serialized behind a lock: two browser tabs hitting Apply at once must
        not interleave an xray restart with an nftables reload.

        Returns:
            A short description of what was applied.

        Raises:
            CommandError: If rendering or applying fails. The running services
                keep their previous configuration when validation fails.
            ValueError: If the configuration itself is invalid.
        """
        async with self._apply_lock:
            return await asyncio.to_thread(self._apply_all_blocking)

    async def apply_network(self, *, only: str | None = None) -> str:
        """Re-render the router and DHCP, and make the interface roles real.

        The interface work is the part the render pipeline cannot do:
        NetworkManager owns the addresses, so role, address and clone-MAC
        changes are pushed to it here.

        Args:
            only: Apply just this interface's role, leaving the others as they
                are. The firewall and DHCP are still re-rendered from the whole
                configuration, because a single role change alters both. None
                applies every interface.

        Returns:
            A short description of what was applied.

        Raises:
            CommandError: If rendering or applying fails.
        """
        async with self._apply_lock:
            return await asyncio.to_thread(self._apply_network_blocking, only)

    def desired_state_for(self, device) -> tuple[str, dict]:
        """What a device should host, and the hash the agent compares against.

        Args:
            device: The device asking, or its key.

        Returns:
            The hash and the state.
        """
        key = (device if isinstance(device, str) else device.mac_address).lower()
        desired, state_hash = self.desired_states.compose(
            key,
            self.client_platform.get(key, {}),
            address=self.client_address.get(key, ""),
            allowed_subnets=self.share_subnets(),
        )
        return state_hash, desired

    def share_subnets(self) -> list:
        """The networks a device's shares answer, from this hub's own fence.

        Returns:
            Network addresses, served networks first.
        """
        links = {
            link.name: link.ipv4_address or ""
            for link in RouterLinkStatus().all_links()
        }
        return share_subnets(
            network=self.network(),
            link_addresses=links,
            device_addresses=device_addresses(),
        )

    def push_desired_state(self, key: str) -> None:
        """Send one device the state it should hold now.

        Args:
            key: The device.

        Raises:
            AgentOfflineError: When the device has no channel.
            StreamRefusedError: When the socket did not take it in time.
        """
        state_hash, desired = self.desired_state_for(key)
        self.agent_sessions.push_state_from_thread(key, state_hash, desired)

    def forget_client_state(self, mac_address: str) -> None:
        """Drop everything held in memory about one device.

        Called when the device is forgotten. Its socket, if one is open, is
        closed with the unknown-token code: the token it authenticated with
        is gone.

        Args:
            mac_address: The device's MAC.
        """
        key = mac_address.lower()
        self.client_metrics.pop(key, None)
        self.client_hostname.pop(key, None)
        self.client_modules.pop(key, None)
        self.client_platform.pop(key, None)
        self.client_accounts.pop(key, None)
        self.client_address.pop(key, None)
        self.client_device_host.pop(key, None)
        self.client_last_error.pop(key, None)
        self.device_shares.withdraw(key)
        self.agent_module_orders.forget(key)
        self.desired_states.forget(key)
        self.agent_sessions.close_from_thread(
            key, AGENT_WS_CLOSE_UNKNOWN_TOKEN, "unknown_token"
        )

    def publish_node_readings(self, readings: dict) -> None:
        """Say the nodes' live readings moved, where they have.

        Args:
            readings: What the nodes panel draws, by outbound tag.
        """
        if readings == self._node_readings:
            return
        self._node_readings = readings
        self.events.publish(WEB_EVENT_NODES)

    def publish_ai_usage(self) -> None:
        """Say the AI gateway's counters or served list moved."""
        self.events.publish(WEB_EVENT_AI_USAGE)

    def _agent_port(self) -> int:
        """The agent channel's port, from the settings or the default."""
        return int(
            self.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
        )

    def _dispatch_order(self, order: AgentModuleOrder) -> None:
        """Run one module order over the device's socket, to its close.

        Args:
            order: The order the controller handed down; closed here with
                the machine's word, or with ``agent_offline`` when it has
                no channel.
        """
        controller = self.agent_module_orders

        def collect(line: str) -> None:
            order.output = (order.output + line + "\n")[
                -AGENT_MODULE_OUTPUT_LIMIT_BYTES:
            ]

        try:
            info = self.agent_sessions.run_order_from_thread(
                order.mac_address,
                order.to_wire(),
                on_line=collect,
                timeout=AGENT_MODULE_ORDER_TIMEOUT_S,
            )
        except (AgentOfflineError, StreamRefusedError) as error:
            controller.record_result(
                mac_address=order.mac_address,
                order_id=order.id,
                state=ORDER_FAILED,
                code=error.code,
                params=dict(error.params),
                output=order.output,
            )
            return
        output = str(info.get("output", "") or "") or order.output
        controller.record_result(
            mac_address=order.mac_address,
            order_id=order.id,
            state=ORDER_DONE if info.get("state") == ORDER_DONE else ORDER_FAILED,
            code=str(info.get("code", "") or ""),
            params=dict(info.get("params") or {}),
            output=output[-AGENT_MODULE_OUTPUT_LIMIT_BYTES:],
        )

    def _apply_all_blocking(self) -> str:
        network = self.network()
        node_list = self.node_list()
        routing = self._settled_routing(node_list)

        resolve_node_secrets(node_list)
        xray_config = XrayConfigRenderer(
            node_list=node_list,
            routing=routing,
        ).render()
        nft_ruleset = RouterNftRenderer(
            network=network,
            routing=routing,
            xray_uid=lookup_xray_uid(),
            agent_port=self._agent_port(),
        ).render()
        dnsmasq_config = RouterDnsmasqRenderer(
            network=network, routing=routing
        ).render()

        # A refused xray configuration does not stop the other two. The
        # firewall is what makes the LAN reachable and dnsmasq is what answers
        # its queries, and neither has anything to do with why xray said no.
        xray_failure = ""
        try:
            XrayConfigApplier().apply(xray_config)
        except CommandError as error:
            xray_failure = str(error)

        RouterRulesetApplier().apply(nft_ruleset, is_forwarding=_is_forwarding(network))
        write_generated(ROUTER_NFT_PATH, nft_ruleset)
        write_generated(ROUTER_DNSMASQ_PATH, dnsmasq_config)
        run(["systemctl", "restart", DNSMASQ_SERVICE_NAME])
        _converge_overlays(network)

        if xray_failure:
            raise CommandError(
                f"{xray_failure}. The firewall and DNS were applied without it."
            )

        self.is_config_dirty = False
        return (
            f"applied {len(node_list.enabled_nodes)} nodes, "
            f"strategy {node_list.strategy}"
        )

    def _settled_routing(self, node_list: XrayNodeList) -> dict:
        """The routing options, with the scopes switched off if they cannot run.

        A scope with no enabled node has nothing to leave through and renders
        as off. Writing that back means the panel and the box agree about it
        rather than the page showing switches that do nothing.

        Args:
            node_list: The nodes as they are now.

        Returns:
            The routing options as they will be rendered.
        """
        routing = self.routing()
        is_scoped = routing.get("is_proxy_enabled", True) or routing.get(
            "is_local_proxy_enabled", False
        )
        if is_scoped and not node_list.enabled_nodes:
            routing["is_proxy_enabled"] = False
            routing["is_local_proxy_enabled"] = False
            write_config("xray/routing.json", routing)
        return routing

    def _apply_network_blocking(self, only: str | None) -> str:
        network = self.network()
        routing = self.routing()

        nft_ruleset = RouterNftRenderer(
            network=network,
            routing=routing,
            xray_uid=lookup_xray_uid(),
            agent_port=self._agent_port(),
        ).render()
        dnsmasq_config = RouterDnsmasqRenderer(
            network=network, routing=routing
        ).render()

        RouterRulesetApplier().apply(nft_ruleset, is_forwarding=_is_forwarding(network))
        write_generated(ROUTER_NFT_PATH, nft_ruleset)
        write_generated(ROUTER_DNSMASQ_PATH, dnsmasq_config)

        # The interface must carry its new address before dnsmasq is told to
        # bind it, or the restart fails with nothing to listen on. This is also
        # the step that drops the connection the request arrived on, when a LAN
        # address is what changed.
        applier = RouterInterfaceApplier(network=network)
        if only is None:
            changes = applier.apply_all()
        else:
            interface = network.interface(only)
            if interface is None:
                raise CommandError(f"{only!r} is not a configured interface")
            changes = applier.apply(interface)
            changes += RouterDefaultRouteApplier(network=network).apply()
            # The same tail the whole-network apply ends with. A LAN given
            # its role from the page is still the address this box resolves
            # at, and leaving it out is how a router ends up asking whatever
            # its uplink handed it.
            changes += applier.apply_resolver()
        run(["systemctl", "restart", DNSMASQ_SERVICE_NAME])
        changes += _converge_overlays(network)
        changes += self._push_desired_states()

        self.is_config_dirty = False
        summary = "; ".join(changes) if changes else "no interface change"
        return f"applied network ({summary})"

    def _push_desired_states(self) -> list[str]:
        """Hand every online device the state the network now composes.

        The shares' ``allowed_subnets`` and a git server's address derive
        from the network, so a network change that never reached a device
        would leave its shares refusing a network that was just opened.

        Returns:
            A note for the summary, empty when no device is online. A
            device that would not take the push is named rather than
            raised: the network is already applied by this point.
        """
        pushed = []
        refused = []
        for key in self.agent_sessions.keys():
            try:
                self.push_desired_state(key)
            except (AgentOfflineError, StreamRefusedError):
                refused.append(key)
                continue
            pushed.append(key)
        notes = []
        if pushed:
            notes.append(f"desired state pushed to {len(pushed)} devices")
        if refused:
            notes.append(f"desired state not pushed to {', '.join(refused)}")
        return notes

    def _publish_devices(self) -> None:
        """Say the device list moved."""
        self.events.publish(WEB_EVENT_DEVICES)

    def _publish_module_order(self, mac_address: str) -> None:
        """Say an order on one device moved."""
        self.events.publish(WEB_EVENT_MODULE_ORDER, mac_address)

    def _publish_services(self) -> None:
        """Say the published service list composes differently."""
        self.events.publish(WEB_EVENT_SERVICES)

    def _publish_config_write(self, relative_path: str) -> None:
        """Say one file under ``config/`` was written."""
        self.events.publish(WEB_EVENT_CONFIG, relative_path)

    def _publish_task(self, task_id: str) -> None:
        """Say a background job started or finished."""
        self.events.publish(WEB_EVENT_TASK, task_id)


def _converge_overlays(network: RouterNetworkConfig) -> list[str]:
    """Tell each overlay's own daemon what the exposure switch says.

    Rendering the rules is not enough for an overlay. NetBird's client puts an
    accept for its interface back at the top of this hub's input chain within
    seconds of any reload, so a closed overlay that was only rendered stays
    open, and the switch reads as a lie. Its own setting is what holds, and it
    is set here for the same reason the ruleset is loaded here.

    Args:
        network: The parsed router configuration.

    Returns:
        Notes for the apply summary, empty when every daemon already agreed.
        A daemon that refuses is reported rather than raised: the ruleset is
        already loaded by this point, and the overlay's own state is not what
        the rest of the network depends on.
    """
    notes = []
    for overlay in network.overlays:
        if overlay.provider != ROUTER_OVERLAY_NETBIRD:
            continue
        try:
            note = NetbirdInboundGate().converge(is_blocked=not overlay.is_exposed)
        except CommandError as error:
            notes.append(f"{overlay.title} not set: {error}")
            continue
        if note:
            notes.append(f"{overlay.title}: {note}")
    return notes


def _is_forwarding(network: RouterNetworkConfig) -> bool:
    """Whether any interface holds a role that routes.

    Args:
        network: The parsed router configuration.

    Returns:
        True when something forwards, which is what earns the forwarding
        sysctls; a box with no roles is somebody's machine and keeps its own.
    """
    return bool(network.lan_interfaces or network.wan_interfaces)


def generated_dir_exists() -> bool:
    """Whether the generated-config directory has been created.

    Returns:
        True once the installer has run at least once.
    """
    return UTILS_GENERATED_DIR.is_dir()


__all__ = ["PanelRuntime", "generated_dir_exists", "CommandError"]
