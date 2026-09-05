"""Shared runtime objects the panel's routes work through.

One instance is built at startup and reached from every route. It owns the live
things (session store, running jobs, pending client commands) and knows how to
re-render and apply the configuration, so no route shells out to systemd or nft
by itself.
"""

import asyncio
import ipaddress
from collections import deque

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
from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.gitea.ops import GiteaConfigApplier, GiteaSecretStore
from neutrino_hub.modules.gitea.renderer import GiteaConfigRenderer
from neutrino_hub.modules.podman import ops as podman_ops
from neutrino_hub.modules.podman.config import PodmanConfig
from neutrino_hub.modules.podman.ops import PodmanRegistriesApplier
from neutrino_hub.modules.podman.renderer import PodmanRegistriesRenderer
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiServedModelCache
from neutrino_hub.modules.devices.catalog import DeviceCatalogCache
from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.ops import SambaConfigApplier, SambaUserManager
from neutrino_hub.modules.router.link_status import RouterLinkStatus
from neutrino_hub.modules.samba.renderer import (
    SambaConfigRenderer,
    allowed_subnets,
)
from neutrino_hub.modules.services.probe import DeclaredServiceProbe
from neutrino_hub.modules.services.published import PublishedServiceCache
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
from neutrino_hub.system.listening_ports import ListeningPortReader
from neutrino_hub.web.constants import (
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_PROXY_SCOPE_HUB,
    WEB_PROXY_SCOPE_LAN,
    WEB_PROXY_SCOPE_LAN_AND_HUB,
    WEB_PROXY_SCOPE_OFF,
    WEB_PROXY_SCOPE_PORTS,
    WEB_PROXY_SCOPE_UNUSED,
)
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config, write_config, write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run
from neutrino_hub.web.auth import SessionStore, session_secret
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
)

DNSMASQ_SERVICE_NAME = SYSTEM_CORE_UNITS["dnsmasq"]
PENDING_COMMAND_LIMIT = 32


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
        self.tasks = TaskStreamRegistry()
        self.services = SystemdServiceController()
        self.listening_ports = ListeningPortReader()
        self.stats = XrayStatsClient()
        self.node_probe = XrayNodeProbe()
        self.declared_probe = DeclaredServiceProbe()
        self.served_models = CliproxyApiServedModelCache()
        self.published_services = PublishedServiceCache(
            declared_probe=self.declared_probe,
            served_models=self.served_models,
            units=self.services,
        )
        self.device_catalog = DeviceCatalogCache(services=self.published_services)
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
        # The most recent error each agent reported, keyed by MAC:
        # ``{"code", "params"}``.
        self.client_last_error: dict[str, dict] = {}
        # The last outcome of each queued command, keyed by MAC then command
        # id, so the drawer can show how a reboot went after the stream closed.
        self.client_command_results: dict[str, dict] = {}
        # Enrollment tickets a machine can join with, by token. Held in memory
        # and short-lived on purpose: a join secret that survives a restart is
        # a join secret lying around, and generating another takes one click.
        self.enrollments: dict[str, dict] = {}
        self._apply_lock = asyncio.Lock()
        self._pending_commands: dict[str, deque] = {}

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

    def samba(self) -> SambaConfig:
        """Read the current share configuration.

        Returns:
            Parsed ``config/samba/samba.json``.
        """
        return SambaConfig.from_dict(read_config("samba/samba.json"))

    def write_samba(self, config: SambaConfig) -> None:
        """Store a changed share configuration.

        Args:
            config: The configuration to write. Validated before it lands, so
                ``config/`` never holds a file the renderer would refuse.
        """
        config.validate()
        write_config("samba/samba.json", config.to_dict())

    async def apply_samba(self) -> str:
        """Render the share configuration, converge accounts, and load it.

        Returns:
            A short description of what was applied.

        Raises:
            CommandError: If rendering or applying fails. The running server
                keeps its previous configuration when validation fails.
        """
        async with self._apply_lock:
            return await asyncio.to_thread(self._apply_samba_blocking)

    def podman(self) -> PodmanConfig:
        """Read the declared containers.

        Returns:
            Parsed ``config/podman/podman.json``.
        """
        return PodmanConfig.from_dict(read_config("podman/podman.json"))

    def write_podman(self, config: PodmanConfig) -> None:
        """Store changed container declarations.

        Args:
            config: The configuration to write. Validated before it lands, so
                ``config/`` never holds a file the renderer would refuse.
        """
        config.validate()
        write_config("podman/podman.json", config.to_dict())

    async def apply_podman(self) -> str:
        """Render the Quadlet files and reconcile systemd with them.

        Returns:
            A short description of what was applied.

        Raises:
            CommandError: If systemd refuses a unit.
        """
        async with self._apply_lock:
            return await asyncio.to_thread(self._apply_podman_blocking)

    def gitea(self) -> GiteaConfig:
        """Read the current git server configuration.

        Returns:
            Parsed ``config/gitea/gitea.json``.
        """
        return GiteaConfig.from_dict(read_config("gitea/gitea.json"))

    def write_gitea(self, config: GiteaConfig) -> None:
        """Store a changed git server configuration.

        Args:
            config: The configuration to write. Validated before it lands, so
                ``config/`` never holds a file the renderer would refuse.
        """
        config.validate()
        write_config("gitea/gitea.json", config.to_dict())

    async def apply_gitea(self) -> str:
        """Render ``app.ini`` and restart a running server on it.

        Returns:
            A short description of what was applied.

        Raises:
            CommandError: If rendering or applying fails.
        """
        async with self._apply_lock:
            return await asyncio.to_thread(self._apply_gitea_blocking)

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

    def queue_client_command(self, mac_address: str, command: dict) -> None:
        """Queue a command for a device's agent to pick up.

        Args:
            mac_address: The device's MAC.
            command: The command object handed back on the next heartbeat.
        """
        queue = self._pending_commands.setdefault(
            mac_address.lower(), deque(maxlen=PENDING_COMMAND_LIMIT)
        )
        queue.append(command)

    def forget_client_state(self, mac_address: str) -> None:
        """Drop everything held in memory about one device.

        Called when the device is forgotten. A queue that outlives its record
        is delivered to whatever machine appears on that MAC next, and the
        metrics and modules would otherwise be drawn beside a device that has
        only just been enrolled.

        Args:
            mac_address: The device's MAC.
        """
        key = mac_address.lower()
        self._pending_commands.pop(key, None)
        self.client_metrics.pop(key, None)
        self.client_hostname.pop(key, None)
        self.client_modules.pop(key, None)
        self.client_platform.pop(key, None)
        self.client_accounts.pop(key, None)
        self.client_last_error.pop(key, None)
        self.client_command_results.pop(key, None)

    def take_client_commands(self, mac_address: str) -> list[dict]:
        """Drain the queued commands for one device.

        Args:
            mac_address: The device's MAC.

        Returns:
            Every queued command, oldest first; the queue is left empty.
        """
        queue = self._pending_commands.get(mac_address.lower())
        if not queue:
            return []
        commands = list(queue)
        queue.clear()
        return commands

    def _agent_port(self) -> int:
        """The agent channel's port, from the settings or the default."""
        return int(
            self.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
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

        self.is_config_dirty = False
        summary = "; ".join(changes) if changes else "no interface change"
        return f"applied network ({summary})"

    def _apply_samba_blocking(self) -> str:
        config = self.samba()
        config.validate()
        # The LAN subnets go into hosts allow, the second fence behind the
        # firewall's own; both change together when the LAN does. Normalised to
        # the network address — cidr is the gateway's own host form.
        network = self.network()
        links = {
            link.name: link.ipv4_address or ""
            for link in RouterLinkStatus().all_links()
        }
        if network.mode == "server":
            reachable = [address for address in links.values() if address]
        else:
            reachable = [links.get(name, "") for name in network.exposed_device_names()]
        subnets = allowed_subnets(
            [interface.lan.cidr for interface in network.lan_interfaces],
            reachable,
        )
        rendered = SambaConfigRenderer(config=config, lan_subnets=subnets).render()
        # Configuration first: smbpasswd itself reads smb.conf, and the link
        # to a valid one is the applier's to place.
        summary = SambaConfigApplier().apply(rendered, config=config)
        notes = SambaUserManager().converge(config.users)
        if notes:
            summary += "; " + "; ".join(notes)
        return summary

    def _apply_podman_blocking(self) -> str:
        config = self.podman()
        config.validate()
        renderer = podman_ops.container_renderer(config)
        mirror_note = PodmanRegistriesApplier().apply(
            PodmanRegistriesRenderer(config=config).render()
        )
        autostart = [
            container.name for container in config.containers if container.is_autostart
        ]
        note = podman_ops.container_applier().apply(
            renderer.render(), autostart_names=autostart
        )
        return f"{note}; {mirror_note}"

    def _apply_gitea_blocking(self) -> str:
        config = self.gitea()
        config.validate()
        rendered = GiteaConfigRenderer(
            config=config,
            lan_address=self.network().primary_lan_address,
            secrets=GiteaSecretStore().load(),
        ).render()
        return GiteaConfigApplier().apply(rendered)


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
