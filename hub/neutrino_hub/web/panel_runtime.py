"""Shared runtime objects the panel's routes work through.

One instance is built at startup and reached from every route. It owns the live
things (session store, running jobs, the agents' sockets) and knows how to
re-render and apply the configuration, so no route shells out to systemd or nft
by itself.
"""

import asyncio
import ipaddress
import re
import subprocess

from neutrino_hub.modules.router.dnsmasq_renderer import RouterDnsmasqRenderer
from neutrino_hub.modules.router.connections import RouterConnectionSet
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import RouterLinkStatus
from neutrino_hub.modules.router.controller import (
    RouterStateController,
    failure_text,
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
    WEB_EVENT_AI_USAGE,
    WEB_EVENT_CLIENTS,
    WEB_EVENT_CONFIG,
    WEB_EVENT_DEVICES,
    WEB_EVENT_NODES,
    WEB_EVENT_SERVICES,
    WEB_EVENT_TASK,
    WEB_PROXY_SCOPE_HUB,
    WEB_PROXY_SCOPE_JOINER,
    WEB_PROXY_SCOPE_LAN,
    WEB_PROXY_SCOPE_OFF,
    WEB_PROXY_SCOPE_OVERLAY,
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
from neutrino_hub.utils.subprocess_run import command_failure_text, run
from neutrino_hub.web.auth import SessionStore, session_secret
from neutrino_hub.web import channel_state
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.link_sampler import PanelLinkSampler
from neutrino_hub.modules.devices.agent_module_cache import AgentModuleCache
from neutrino_hub.modules.devices.agent_package import AgentPackageCache
from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
)
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.web.task_stream import TaskStreamRegistry
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.constants import XRAY_SCOPE_SWITCHES
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_secrets import resolve_node_secrets
from neutrino_hub.modules.xray.node_probe import XrayNodeProbe
from neutrino_hub.modules.xray.stats_client import XrayStatsClient

from neutrino_hub.modules.router.constants import (
    ROUTER_DNSMASQ_PATH,
    ROUTER_NFT_PATH,
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
        self.node_probe = XrayNodeProbe(resolver_of=self._direct_resolver)
        self.declared_probe = DeclaredServiceProbe()
        self.served_models = CliproxyApiServedModelCache()
        # What each managed machine last said about sharing its desktop.
        # Runtime only: a share is the machine's own word, refreshed every
        # beat, and a hub restart simply waits for the next one.
        self.device_shares = DeviceShareRegistry()
        # Every managed machine's live socket, and the streams on it.
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        self.agent_sessions.on_presence_change = self._publish_devices
        # Every client program's live socket, keyed by client id.
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.client_sessions.on_presence_change = self._publish_clients
        # The address each client reaches this hub on, resolved when its
        # socket opened; its catalog and its gateway URL are composed with it.
        self.client_catalog_host: dict[str, str] = {}
        # Where each device is, keyed by id: the address its socket leaves
        # by, or the peer address when the report names none, refreshed
        # every report.
        self.device_address: dict[str, str] = {}
        # What each device should host, one directory per device under
        # config/, composed into the state its agent applies.
        self.desired_states = DesiredStateStore()
        self.published_services = PublishedServiceCache(
            declared_probe=self.declared_probe,
            served_models=self.served_models,
            units=self.services,
            device_shares=self.device_shares,
            agent_sessions=self.agent_sessions,
            device_addresses=self.device_address,
            desired_states=self.desired_states,
            on_fingerprint_change=self._services_changed,
        )
        self.device_catalog = DeviceCatalogCache(services=self.published_services)
        # The bytes a module's ``package`` stream serves, fetched once and
        # kept; the agent installs them by the recipe its state carries.
        self.agent_modules = AgentModuleCache()
        # The hub's own agent packages, seeded by its package and topped up
        # from the release for a platform it was not built for.
        self.agent_packages = AgentPackageCache()
        self.is_config_dirty = False
        # Latest agent metrics, keyed by device id. Runtime only: these are
        # stale the moment the panel restarts, so they are never written to
        # config/.
        self.device_metrics: dict[str, dict] = {}
        # Latest per-module reconcile state an agent reported, keyed by
        # device id. Runtime only, for the same reason as the metrics.
        self.device_modules: dict[str, dict] = {}
        # The platform tuple an agent last reported, keyed by device id, so
        # the panel can show only the modules that platform can install.
        self.device_platform: dict[str, dict] = {}
        # The hostname each agent last reported, keyed by device id. Runtime
        # only, like the metrics.
        self.device_hostname: dict[str, str] = {}
        # The human accounts each agent last reported, keyed by device id.
        self.device_accounts: dict[str, list] = {}
        # The interfaces each agent last reported, keyed by device id:
        # ``[{"name", "mac", "addresses"}]``.
        self.device_interfaces: dict[str, list] = {}
        # The address each device reaches this hub on, resolved when its
        # socket opened; the services view composes the same catalog with it.
        self.device_hub_host: dict[str, str] = {}
        # The most recent error each agent reported, keyed by device id:
        # ``{"code", "params"}``.
        self.device_last_error: dict[str, dict] = {}
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

    def _direct_resolver(self) -> tuple:
        """The direct resolver, for the lookups the proxy makes for itself."""
        direct = self.routing().get("direct_dns") or {}
        return str(direct.get("address", "223.5.5.5")), int(direct.get("port", 53))

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
        network = self.network()
        try:
            ruleset = ROUTER_NFT_PATH.read_text(encoding="utf-8")
        except OSError:
            is_lan_diverted = routing.get("is_proxy_enabled", True) and bool(
                network.lan_interfaces
            )
            is_overlay_diverted = routing.get(
                "is_overlay_proxy_enabled", False
            ) and bool(network.exposed_overlay_device_names)
            is_hub_diverted = bool(routing.get("is_local_proxy_enabled", False))
        else:
            # The hub's own diversion hairpins through loopback, which is the
            # one tproxy statement naming that interface; the forwarded one
            # does not, and the interfaces it takes from are the set on the
            # line before it.
            diversions = [
                line for line in ruleset.splitlines() if "tproxy ip to" in line
            ]
            is_forwarded = any('iifname "lo"' not in line for line in diversions)
            taken = _diverted_interface_names(ruleset)
            overlays = set(network.exposed_overlay_device_names)
            is_overlay_diverted = is_forwarded and bool(taken & overlays)
            is_lan_diverted = is_forwarded and (not taken or bool(taken - overlays))
            is_hub_diverted = any('iifname "lo"' in line for line in diversions)
        parts = [
            word
            for word, is_on in (
                (WEB_PROXY_SCOPE_LAN, is_lan_diverted),
                (WEB_PROXY_SCOPE_OVERLAY, is_overlay_diverted),
                (WEB_PROXY_SCOPE_HUB, is_hub_diverted),
            )
            if is_on
        ]
        if parts:
            return WEB_PROXY_SCOPE_JOINER.join(parts)
        is_port_proxied = any(
            entry.get("is_proxied") for entry in routing.get("socks_ports", [])
        )
        if is_port_proxied and self.node_list().enabled_nodes:
            return WEB_PROXY_SCOPE_PORTS
        if (
            routing.get("is_proxy_enabled", True)
            or routing.get("is_overlay_proxy_enabled", False)
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
            subprocess.CalledProcessError: If a command an apply runs fails.
                The running services keep their previous configuration when
                validation fails.
            RuntimeError: If xray refused what it was handed, or the box is
                not set up yet.
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
            subprocess.CalledProcessError: If a command an apply runs fails.
            RuntimeError: If the box is not set up yet.
            ValueError: If ``only`` names no configured interface.
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
        key = device if isinstance(device, str) else device.id
        desired, state_hash = self.desired_states.compose(
            key,
            self.device_platform.get(key, {}),
            address=self.device_address.get(key, ""),
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
        channel_state.push_state(self, CHANNEL_ROLE_AGENT, key)

    def forget_device(self, device_id: str) -> None:
        """Drop everything held in memory about one device.

        Called when the device is forgotten. Its socket, if one is open, is
        refused with ``binding_unknown``: the binding it spoke for is gone.

        Args:
            device_id: The device.
        """
        key = device_id
        self.device_metrics.pop(key, None)
        self.device_hostname.pop(key, None)
        self.device_modules.pop(key, None)
        self.device_platform.pop(key, None)
        self.device_accounts.pop(key, None)
        self.device_interfaces.pop(key, None)
        self.device_address.pop(key, None)
        self.device_hub_host.pop(key, None)
        self.device_last_error.pop(key, None)
        self.device_shares.withdraw(key)
        self.desired_states.forget(key)
        self.agent_sessions.refuse_from_thread(key, CHANNEL_CODE_BINDING_UNKNOWN)

    def forget_client(self, client_id: str) -> None:
        """Drop everything held in memory about one client.

        Its socket, if one is open, is refused with ``binding_unknown``.

        Args:
            client_id: The client.
        """
        self.client_catalog_host.pop(client_id, None)
        self.client_sessions.refuse_from_thread(client_id, CHANNEL_CODE_BINDING_UNKNOWN)

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

    def _apply_all_blocking(self) -> str:
        network = self.network()
        node_list = self.node_list()
        routing = self._settled_routing(node_list)

        resolve_node_secrets(node_list)
        xray_config = XrayConfigRenderer(
            node_list=node_list,
            routing=routing,
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
        except (subprocess.SubprocessError, OSError, RuntimeError) as error:
            xray_failure = command_failure_text(error)

        results = self._router_controller().reconcile()
        write_generated(ROUTER_DNSMASQ_PATH, dnsmasq_config)
        run(["systemctl", "restart", DNSMASQ_SERVICE_NAME])

        if xray_failure:
            raise RuntimeError(
                f"{xray_failure}. The firewall and DNS were applied without it."
            )
        router_failure = failure_text(results)
        if router_failure:
            raise RuntimeError(router_failure)

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
        is_scoped = any(routing.get(switch, False) for switch in XRAY_SCOPE_SWITCHES)
        if is_scoped and not node_list.enabled_nodes:
            for switch in XRAY_SCOPE_SWITCHES:
                routing[switch] = False
            write_config("xray/routing.json", routing)
        return routing

    def _apply_network_blocking(self, only: str | None) -> str:
        network = self.network()
        dnsmasq_config = RouterDnsmasqRenderer(
            network=network, routing=self.routing()
        ).render()

        # The interface must carry its new address before dnsmasq is told to
        # bind it, or the restart fails with nothing to listen on. This is also
        # the step that drops the connection the request arrived on, when a LAN
        # address is what changed.
        results = self._router_controller().reconcile(only=only)
        write_generated(ROUTER_DNSMASQ_PATH, dnsmasq_config)
        run(["systemctl", "restart", DNSMASQ_SERVICE_NAME])
        changes = [line for result in results for line in result.changes]
        changes += self._push_desired_states()
        router_failure = failure_text(results)
        if router_failure:
            raise RuntimeError(router_failure)

        self.is_config_dirty = False
        summary = "; ".join(changes) if changes else "no interface change"
        return f"applied network ({summary})"

    def _router_controller(self) -> RouterStateController:
        """The one pass every apply of the routing state runs."""
        return RouterStateController()

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
        """Say the device list moved, and recompose what devices publish."""
        self.events.publish(WEB_EVENT_DEVICES)
        self.published_services.schedule_refresh()

    def _publish_clients(self) -> None:
        """Say the client list moved."""
        self.events.publish(WEB_EVENT_CLIENTS)

    def _services_changed(self) -> None:
        """Say the published list composes differently, and hand it on."""
        self.events.publish(WEB_EVENT_SERVICES)
        channel_state.push_states(self, CHANNEL_ROLE_CLIENT)

    def _publish_config_write(self, relative_path: str) -> None:
        """Say one file under ``config/`` was written."""
        self.events.publish(WEB_EVENT_CONFIG, relative_path)

    def _publish_task(self, task_id: str) -> None:
        """Say a background job started or finished."""
        self.events.publish(WEB_EVENT_TASK, task_id)


def generated_dir_exists() -> bool:
    """Whether the generated-config directory has been created.

    Returns:
        True once the installer has run at least once.
    """
    return UTILS_GENERATED_DIR.is_dir()


__all__ = ["PanelRuntime", "generated_dir_exists"]


def _diverted_interface_names(ruleset: str) -> set:
    """The interfaces the applied ruleset diverts forwarded traffic from.

    Args:
        ruleset: The ruleset text as it was loaded.

    Returns:
        The names in the ``iifname != { ... } return`` statement ahead of
        the forwarded tproxy, empty when there is none.
    """
    for line in ruleset.splitlines():
        if "iifname !=" in line and line.strip().endswith("return"):
            return set(re.findall(r'"([^"]+)"', line))
    return set()
