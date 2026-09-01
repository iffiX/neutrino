"""Making the rendered routing state real.

Everything with a system effect in the router layer lives here: the interface
roles pushed into NetworkManager, the default route shared between uplinks,
forwarding sysctls, the policy route TPROXY needs, and loading the nftables
ruleset. The renderers stay pure so they can be tested without root.
"""

import pwd

from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.router import links, resolver, stack
from neutrino_hub.modules.router.connections import RouterConnectionSet
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.modules.router.dhcp_client import RouterDhcpClient
from neutrino_hub.modules.router.dhcp_renderer import RouterDhcpRenderer
from neutrino_hub.modules.router.supplicant import RouterWifiClient
from neutrino_hub.modules.router.supplicant import (
    write_config as write_supplicant_config,
)
from neutrino_hub.modules.router.constants import (
    ROUTER_CONNECTIONS_FILE,
    router_dhcp_config_path,
    ROUTER_FWMARK_TPROXY,
    ROUTER_METRIC_BALANCE,
    ROUTER_METRIC_MULTIPATH,
    ROUTER_METRIC_SIDE_GATEWAY,
    ROUTER_NFT_FAMILY,
    ROUTER_NFT_TABLE,
    ROUTER_ROLE_DISABLED,
    ROUTER_ROLE_LAN,
    ROUTER_ROLE_SPLIT,
    ROUTER_ROLE_WAN,
    ROUTER_ROUTE_RULE_PRIORITY,
    ROUTER_ROUTE_TABLE,
    ROUTER_WAN_METHOD_STATIC,
)
from neutrino_hub.modules.router.interfaces import RouterInterface, RouterNetworkConfig
from neutrino_hub.modules.router.link_status import LINK_KIND_WIFI, RouterLinkStatus
from neutrino_hub.modules.router.uplink_plan import (
    MEDIUM_WIRED,
    MEDIUM_WIRELESS,
    UplinkFacts,
    UplinkPlan,
    plan_uplinks,
)
from neutrino_hub.modules.router.wifi import RouterWifiAccessPoint

XRAY_SERVICE_USER = "xray"

# Properties NetworkManager can only adopt by tearing the connection down and
# building it again. Everything else — metrics, never-default, autoconnect — it
# takes in place with `device reapply`.
#
# The distinction is not cosmetic. A reactivation restarts DHCP and re-runs
# address-conflict detection, and a gateway that ARP-probes its own address
# while a second one of its interfaces sits on the same subnet gets an answer
# from itself. NetworkManager has been seen to fail that badly enough to apply
# the address and install no routes at all, which takes the box off the
# internet. So a metric edit must never reach for this door.
REACTIVATION_PROPERTIES = frozenset(
    {
        "ipv4.method",
        "ipv4.addresses",
        "ipv4.gateway",
        "802-3-ethernet.cloned-mac-address",
    }
)


def lookup_xray_uid() -> int:
    """Resolve the uid the xray service runs as.

    The nftables anti-loop rule matches on this uid, so it is resolved once at
    apply time and handed to the renderer rather than looked up inside it.

    Returns:
        The numeric uid.

    Raises:
        CommandError: If the user does not exist yet. The installer creates it
            before any ruleset is rendered.
    """
    try:
        return pwd.getpwnam(XRAY_SERVICE_USER).pw_uid
    except KeyError as error:
        raise CommandError(
            f"system user {XRAY_SERVICE_USER!r} does not exist; "
            f"run `nhub setup` first"
        ) from error


def remove_vlan_device(name: str) -> list[str]:
    """Take a VLAN interface off the box.

    A VLAN is a kernel device and nothing else — there is no profile anywhere
    that could bring it back at the next boot, because what builds it is the
    apply that reads `config/`.

    Args:
        name: The VLAN interface name, for example ``enp1s0.10``.

    Returns:
        One line when something was removed; empty when there was nothing.
    """
    if not links.remove_vlan(name):
        return []
    return [f"{name} removed"]


def _write_dhcp_config(device: str, metric: int) -> bool:
    """Render the lease client's configuration for one uplink.

    Args:
        device: The interface.
        metric: What its default route should land at.

    Returns:
        True when the file changed, which is what tells a running client it
        has to be restarted to read it.
    """
    text = RouterDhcpRenderer(interface=device, route_metric=metric).render()
    path = router_dhcp_config_path(device)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    write_generated(path, text)
    return True


def _known_networks() -> RouterConnectionSet:
    """Every wireless network the box knows, or none when it knows none.

    Returns:
        The parsed store. A box set up before this file existed has none, and
        a radio with nothing to join is not a failure.
    """
    try:
        return RouterConnectionSet.from_dict(read_config(ROUTER_CONNECTIONS_FILE))
    except (FileNotFoundError, ValueError):
        return RouterConnectionSet()


def hand_back(network: RouterNetworkConfig) -> list[str]:
    """Stop driving this machine's network and leave it as it stands.

    What the hub started is stopped and what it wrote is undone; what the
    machine had is not put back, because it was never taken away. Addresses
    stay exactly where they are — an interface losing its address is how a
    reset takes the box off the network it was reached on.

    Args:
        network: The configuration that was being applied, which names the
            interfaces to stop driving.

    Returns:
        One line per thing stopped.
    """
    changes = []
    for interface in network.interfaces:
        device = interface.device_name
        for engine in (
            RouterDhcpClient(interface=device),
            RouterWifiClient(interface=device),
        ):
            if engine.is_running:
                engine.stop()
                changes.append(f"stopped {engine.unit}")
        access_point = RouterWifiAccessPoint(interface=device)
        if access_point.is_running:
            access_point.unpublish()
            changes.append(f"stopped {access_point.unit}")
    # The managers first, and the resolver after them: handing name resolution
    # back means pointing it at `systemd-resolved` when that is what the
    # machine had, and a masked unit answers "no such thing" to being asked
    # whether it is enabled. Asked in the other order it is never handed back
    # at all, and the box goes on resolving at a dnsmasq nobody is running.
    changes += stack.stand_up()
    if resolver.hand_back():
        changes.append("name resolution is the machine's own again")
    return changes


def build_uplink_plan(
    *, network: RouterNetworkConfig, status: RouterLinkStatus | None = None
) -> UplinkPlan:
    """Read the live links and work out what the uplinks should be doing.

    The bridge between the pure planner and the system: it gathers the facts
    the planner ranks on, so the planner itself stays testable without root or
    a network.

    Args:
        network: The parsed router configuration.
        status: An existing reader to reuse, saving a second round of
            calls when the caller already has one.

    Returns:
        The plan.
    """
    reader = status or RouterLinkStatus()
    facts = {}
    for interface in network.wan_interfaces:
        link = reader.link(interface.device_name)
        facts[interface.name] = UplinkFacts(
            name=interface.name,
            # A VLAN uplink is a wire: what the planner cares about is the
            # medium's reliability, not the tagging.
            medium=MEDIUM_WIRELESS if link.kind == LINK_KIND_WIFI else MEDIUM_WIRED,
            # An uplink is usable only when it is both up and addressed. A
            # cable in a dead socket has carrier and goes nowhere.
            is_carrying=link.is_up and link.ipv4_address is not None,
            gateway=reader.gateway_for(interface.device_name),
            cidr=link.ipv4_address,
            speed_mbps=link.speed_mbps,
        )
    return plan_uplinks(network=network, facts=facts)


class RouterInterfaceApplier:
    """Pushes interface roles into NetworkManager.

    Each interface is applied on its own and only when something actually
    differs, because activating a connection drops every session on that
    interface — including, on a LAN, the panel session that asked for the
    change. Saving a page that changes nothing must therefore change nothing.
    """

    def __init__(self, *, network: RouterNetworkConfig):
        """
        Args:
            network: The parsed router configuration.
        """
        self._network = network
        self._status = RouterLinkStatus()
        # What kind each interface is, read once: the applier asks per
        # interface and the answer does not change while it runs.
        self._kinds = {link.name: link.kind for link in self._status.all_links()}
        self._plan = build_uplink_plan(network=network, status=self._status)

    def apply_all(self) -> list[str]:
        """Apply every interface's role, then rebuild the default route.

        The order is tear-downs, then LANs, then uplinks, and each step of it
        is load-bearing:

        Disabled interfaces go first so that anything losing its role gives up
        its address before another interface reaches for one. An interface left
        attached while a sibling is being brought up on the same subnet is what
        makes a gateway answer its own address-conflict probe.

        Trunks go before the LANs and uplinks because a VLAN can only be as up
        as the port it rides on. LANs go next because they are what the panel
        and dnsmasq are reachable on, so a failure part-way through leaves the
        box still answerable rather than stranded behind a half-configured
        uplink.

        Returns:
            One line per change actually made; empty when nothing differed.
        """
        order = {
            ROUTER_ROLE_DISABLED: 0,
            ROUTER_ROLE_SPLIT: 1,
            ROUTER_ROLE_LAN: 2,
            ROUTER_ROLE_WAN: 3,
        }
        ordered = sorted(
            self._network.interfaces,
            key=lambda interface: order.get(interface.role, 3),
        )
        if not any(not interface.is_disabled for interface in self._network.interfaces):
            # Nothing holds a role, so there is nothing to make true. Not the
            # same as "disable every interface": a machine that has just been
            # told it is a router has no roles yet, and tearing every port
            # down to match would take the address the panel is answering on
            # with it. Roles are given one at a time below this panel, and
            # each is applied as it is given.
            return []
        changes = []
        if self._network.is_addressing_owned:
            # Before anything is configured, not after: two things driving one
            # interface is where every bug in this area has come from, and the
            # window where both are running is the window it happens in.
            #
            # But stopping a manager takes down what it configured, and one of
            # those interfaces is how whoever asked for this is connected. So
            # what they are addressed with is read first and put straight back
            # — the roles below then replace it wherever they differ.
            #
            # Only where there is something to stand down. Applying is not a
            # takeover: `neutrino_hub_router.service` runs it on every boot
            # and every restart, and redoing the handover each time would
            # take the addresses off and put them back for no reason — with
            # whoever is connected over one of them in the gap.
            if stack.running_managers():
                devices = tuple(
                    interface.device_name for interface in self._network.interfaces
                )
                carried = links.carried_state(devices)
                changes += stack.stand_down(
                    tuple(device for device in devices if self._is_wifi(device))
                )
                links.restore_state(carried)
        for interface in ordered:
            changes += self.apply(interface)
        changes += RouterDefaultRouteApplier(network=self._network).apply()
        changes += self._apply_resolver()
        return changes

    def _apply_resolver(self) -> list[str]:
        """Point the box at its own name service, or leave it as it is.

        Last, because it names the address a LAN has only once that LAN has
        been given it.

        Returns:
            One line when name resolution changed hands.
        """
        if not self._network.is_addressing_owned:
            return []
        # The interface rather than `primary_lan_address`, which answers
        # loopback for a box that serves nothing. That is the right answer for
        # binding a listener and the wrong one here: naming an address no
        # dnsmasq is on would leave the box resolving nothing at all.
        lan = self._network.primary_lan
        if lan is None or not lan.lan.address:
            return []
        if not resolver.point_at(lan.lan.address):
            return []
        return [f"resolving at {lan.lan.address}"]

    def apply(self, interface: RouterInterface) -> list[str]:
        """Apply one interface's role.

        Args:
            interface: The interface to configure.

        Returns:
            One line per change actually made.

        Raises:
            CommandError: If NetworkManager rejects the configuration.
        """
        if not self._network.is_addressing_owned:
            # Somebody else's machine. Its address, its route and its lease
            # are whatever put them there — a cloud image, a DHCP server, a
            # person — and the hub answers on them rather than restating them.
            # Everything that is the hub's own still happens: this interface
            # is masqueraded out of, listened on, and forwarded through.
            return []
        if interface.is_untagged:
            return self._apply_untagged(interface)
        if interface.is_lan:
            return self._apply_lan(interface)
        if interface.is_wan:
            return self._apply_wan(interface)
        if interface.is_split:
            return self._apply_split(interface)
        return self._apply_disabled(interface)

    def _apply_untagged(self, interface: RouterInterface) -> list[str]:
        """Apply a trunk's untagged main, which configures the trunk port.

        The main entry has no kernel device of its own, so its role is applied
        as if it were the parent port's: the same connection, the same
        addressing, the same clone-MAC.

        Args:
            interface: The ``<parent>.main`` entry.

        Returns:
            One line per change actually made.
        """
        if interface.is_disabled:
            return self._apply_trunk_parent(interface.vlan.parent)
        shadow = RouterInterface(
            name=interface.vlan.parent,
            role=interface.role,
            wan=interface.wan,
            lan=interface.lan,
            wifi=interface.wifi,
        )
        return self.apply(shadow)

    def _apply_split(self, interface: RouterInterface) -> list[str]:
        main = self._network.untagged_child(interface.name)
        if main is not None:
            # The port's untagged state belongs to its main entry; applying
            # that entry is what converges the port.
            return self._apply_untagged(main)
        return self._apply_trunk_parent(interface.name)

    def _apply_trunk_parent(self, device: str) -> list[str]:
        """Make a port carry tagged VLANs and nothing of its own.

        The link stays up — the VLANs are riding on it — and every address
        comes off, because the port's untagged traffic is disabled and an
        address left behind would answer on a network nobody configured.

        Args:
            device: The trunk port.

        Returns:
            One line per change actually made.
        """
        changes = []
        RouterDhcpClient(interface=device).stop()
        if links.clear_addresses(device):
            changes.append(f"{device} carrying tagged VLANs only")
        links.set_up(device)
        return changes

    def _apply_lan(self, interface: RouterInterface) -> list[str]:
        if self._is_wifi(interface.name):
            radio = RouterWifiAccessPoint(interface=interface.name)
            is_changed = radio.publish(interface=interface)
            if not is_changed:
                return []
            return [
                f"{interface.name} publishing {interface.wifi.ap_ssid} "
                f"on {interface.lan.cidr}"
            ]

        device = interface.device_name
        changes = self._ensure_vlan(interface)
        # A served network takes no lease: the address is the one somebody
        # chose, and it is what dnsmasq binds and nftables masquerades out of.
        RouterDhcpClient(interface=device).stop()
        if links.set_address(device, interface.lan.cidr):
            changes.append(f"{interface.name} serving {interface.lan.cidr}")
        links.set_up(device)

        upstream = interface.lan.upstream_gateway
        if upstream:
            # A side gateway's way out is the network's own router, on this
            # same wire. Above the uplink metrics, so a box that later gains a
            # real uplink leaves by that instead.
            links.set_default_route(device, upstream, ROUTER_METRIC_SIDE_GATEWAY)
            changes.append(f"{interface.name} reaching the internet via {upstream}")
        return changes

    def _apply_wan(self, interface: RouterInterface) -> list[str]:
        device = interface.device_name
        changes = self._ensure_vlan(interface)
        if not interface.is_vlan:
            # A VLAN inherits the trunk's hardware address; cloning belongs to
            # the physical port.
            if links.set_mac(device, interface.wan.cloned_mac):
                changes.append(f"{device} presenting {interface.wan.cloned_mac}")

        if self._is_wifi(device):
            changes += self._join_network(interface)

        links.set_up(device)
        metric = self._route_metric(interface)
        if interface.wan.method == ROUTER_WAN_METHOD_STATIC:
            RouterDhcpClient(interface=device).stop()
            cidr = f"{interface.wan.address}/{interface.wan.prefix_len}"
            if links.set_address(device, cidr):
                changes.append(f"{interface.name} uplink on {cidr}")
            if interface.wan.gateway:
                links.set_default_route(device, interface.wan.gateway, metric)
            return changes

        # Under DHCP the lease client owns the address and the route, and the
        # metric it installs them at comes from its rendered configuration —
        # which is why a changed metric is a restart rather than a route edit.
        #
        # Rendered here rather than by the pipeline that renders everything
        # else: the unit reads the file at exec, so a client started before
        # anything wrote one exits saying so and is restarted into the same
        # nothing — an uplink that never gets an address at all.
        is_rewritten = _write_dhcp_config(device, metric)
        client = RouterDhcpClient(interface=device)
        if client.is_running and is_rewritten:
            client.restart()
        elif not client.is_running:
            client.start()
        changes.append(f"{interface.name} uplink taking a lease at metric {metric}")
        # And then let go of the address the handover carried, here rather
        # than at the end of some longer run: an interface is reconfigured in
        # one place, and a machine left holding an address it has no lease for
        # is one the server will hand to somebody else.
        #
        # Only once a lease has actually arrived. Without one the carried
        # address is all this interface has, and taking it off would put the
        # uplink down rather than move it.
        if links.await_lease(device):
            changes += links.retire_carried((device,))
            return changes
        # Said rather than left to be worked out from a port that is up and
        # carries nothing. With IPv4LL off there is no invented address and no
        # route to nowhere, so what is left is the truth: nobody answered.
        return changes + [f"{interface.name} got no lease; nothing answered"]

    def _join_network(self, interface: RouterInterface) -> list[str]:
        """Have a radio associate with the network its role names.

        The supplicant decides which of the networks it holds to join, out of
        those in range. So this starts it and lets it choose; what it may
        choose from is `config/router/connections.json`, rendered beside this.

        Args:
            interface: The radio, holding the WAN role.

        Returns:
            One line saying what it is doing, or nothing when there is nothing
            to say.
        """
        RouterWifiAccessPoint(interface=interface.name).unpublish()
        # Same reason as the lease client: the supplicant reads its file at
        # exec, and one started before anything wrote it holds no networks.
        write_supplicant_config(interface.name, _known_networks())
        client = RouterWifiClient(interface=interface.name)
        if client.is_running:
            client.reconfigure()
            return []
        client.start()
        if not interface.wifi.ssid:
            # Not a failure: a radio can be given the WAN role before anybody
            # has chosen a network. The page says so and offers the scan.
            return [f"{interface.name} radio up; pick a network from the scan"]
        return [f"{interface.name} joining {interface.wifi.ssid}"]

    def _ensure_vlan(self, interface: RouterInterface) -> list[str]:
        """Build the VLAN an entry describes, when it is one.

        Args:
            interface: The interface being applied.

        Returns:
            One line when a VLAN had to be built.
        """
        if not interface.is_vlan or interface.is_untagged:
            return []
        links.set_up(interface.vlan.parent)
        if links.add_vlan(interface.vlan.parent, interface.name, interface.vlan.id):
            return [f"{interface.name} carved out of {interface.vlan.parent}"]
        return []

    def _apply_disabled(self, interface: RouterInterface) -> list[str]:
        if interface.is_vlan:
            # A disabled VLAN does not exist: unlike a physical port, there is
            # no hardware to leave idle, so its device is simply removed.
            return remove_vlan_device(interface.name)
        device = interface.device_name
        if self._is_wifi(device):
            RouterWifiAccessPoint(interface=device).unpublish()
            RouterWifiClient(interface=device).stop()
        RouterDhcpClient(interface=device).stop()
        if not links.clear_addresses(device) and not self._status.link(device).is_up:
            return []
        links.set_down(device)
        return [f"{interface.name} disabled"]

    def _route_metric(self, interface: RouterInterface) -> int:
        """The metric the plan gives this uplink's default route.

        Args:
            interface: An interface holding the WAN role.

        Returns:
            Its planned metric, or the ordinary uplink metric when the planner
            has nothing to say — a lone uplink needs no ranking.
        """
        planned = self._plan.uplink(interface.name)
        if planned is None:
            # The untagged main is applied through a shadow named after its
            # port; the plan knows it by its own entry name.
            for candidate in self._network.wan_interfaces:
                if candidate.device_name == interface.name:
                    planned = self._plan.uplink(candidate.name)
                    break
        return planned.route_metric if planned else ROUTER_METRIC_BALANCE

    def _is_wifi(self, device: str) -> bool:
        return self._kinds.get(device) == LINK_KIND_WIFI


class RouterDefaultRouteApplier:
    """Shares the default route between the balanced uplinks.

    Backup uplinks need nothing here: NetworkManager gives every uplink's own
    default route the metric of its connection, and the kernel prefers the
    lowest, so a backup at a high metric is already ignored until the balanced
    ones lose their routes entirely.

    Balancing is what the kernel will not do on its own. Two uplinks at the
    same metric are not shared between — the kernel simply picks one — so a
    single multipath route is installed below both, listing each live uplink as
    a next hop. It is rebuilt from scratch on every apply, because a next hop
    whose interface has gone away is a black hole rather than a failover.
    """

    def __init__(self, *, network: RouterNetworkConfig):
        """
        Args:
            network: The parsed router configuration.
        """
        self._network = network
        self._status = RouterLinkStatus()

    def apply(self) -> list[str]:
        """Install, replace, or remove the balancing route.

        Returns:
            One line describing the change, or nothing when there was none.
        """
        hops = self._live_hops()
        if len(hops) < 2:
            # One live uplink needs no help: its own route already wins. Clear
            # any route left from when there were two.
            if self._remove():
                return ["stopped balancing; one uplink left"]
            return []

        metric = self._metric()
        self._remove(keep=metric)
        arguments: list[str] = []
        for device, gateway in hops:
            arguments += ["nexthop", "via", gateway, "dev", device, "weight", "1"]
        run(
            [
                "ip",
                "route",
                "replace",
                "default",
                "metric",
                str(metric),
                *arguments,
            ]
        )
        names = ", ".join(device for device, _ in hops)
        return [f"balancing the uplink across {names} at metric {metric}"]

    def _metric(self) -> int:
        """Pick a metric that actually beats the uplinks' own routes.

        The preferred value is the constant, but it only means anything if it
        is below what the uplinks really carry, so an uplink route that landed
        somewhere unexpected pulls this down to one below it rather than
        leaving a balancing route that silently never wins.

        Returns:
            The metric to install the multipath route at, never below 1.
        """
        singles = [
            int(route.get("metric", 0))
            for route in self._status.default_routes()
            if not route.get("nexthops")
        ]
        if not singles:
            return ROUTER_METRIC_MULTIPATH
        return max(1, min(ROUTER_METRIC_MULTIPATH, min(singles) - 1))

    def _live_hops(self) -> list[tuple[str, str]]:
        """The next hops the plan wants traffic shared across.

        Only uplinks the plan marked active, which is at most one per upstream
        line — so two ports onto one broadband never end up as two next hops of
        the same route, splitting flows over a single line for nothing.
        """
        plan = build_uplink_plan(network=self._network, status=self._status)
        hops = []
        for uplink in plan.active:
            interface = self._network.interface(uplink.name)
            device = interface.device_name if interface else uplink.name
            gateway = uplink.facts.gateway or self._status.gateway_for(device)
            if gateway:
                hops.append((device, gateway))
        return hops

    def _remove(self, *, keep: int | None = None) -> bool:
        """Delete the balancing route wherever it ended up.

        Found by shape rather than by metric — a multipath default route on
        this box is always one of ours, and looking for it that way means a
        route installed at a different metric by an earlier version still gets
        cleaned up instead of being left behind as a second default.

        Args:
            keep: A metric not to delete, when the caller is about to replace
                the route at exactly that metric.

        Returns:
            True when a route was removed.
        """
        is_removed = False
        for route in self._status.default_routes():
            if not route.get("nexthops"):
                continue
            metric = int(route.get("metric", 0))
            if metric == keep:
                continue
            run(
                ["ip", "route", "del", "default", "metric", str(metric)],
                is_checked=False,
            )
            is_removed = True
        return is_removed


class RouterRulesetApplier:
    """Applies forwarding, policy routing, and the nftables ruleset."""

    def apply(self, ruleset: str) -> None:
        """Bring the whole routing state up.

        Order matters: the policy route must exist before the TPROXY rules are
        loaded, otherwise diverted packets have nowhere to go and the first
        connections after a reload are dropped.

        Args:
            ruleset: Rendered nftables ruleset text.

        Raises:
            CommandError: If validation or any step fails.
        """
        self.enable_forwarding()
        self.apply_policy_route()
        self.load_ruleset(ruleset)

    def enable_forwarding(self) -> None:
        """Turn on IPv4 forwarding and the sysctls a multi-homed router needs."""
        settings = {
            "net.ipv4.ip_forward": "1",
            "net.ipv4.conf.all.route_localnet": "1",
            # Answer ARP only for addresses that live on the interface the
            # request arrived on, and source ARP from the address belonging to
            # that network. Without these a box with two interfaces on one
            # subnet answers for both from either, which poisons the upstream
            # router's table and makes it unpredictable which of the two a
            # reply comes back through.
            "net.ipv4.conf.all.arp_ignore": "1",
            "net.ipv4.conf.all.arp_announce": "2",
            # Loose reverse-path filtering. With more than one uplink a reply
            # can legitimately arrive on the interface its request did not
            # leave by; strict filtering drops exactly those packets.
            "net.ipv4.conf.all.rp_filter": "2",
            # Hash multipath next hops on ports as well as addresses. The
            # kernel's default hashes on addresses alone, which means every
            # connection to one destination takes the same uplink however many
            # are balanced — measurably so: six requests to one host all left
            # by the same interface until this was turned on. Ports in the hash
            # spread connections while still pinning each one to a single path.
            "net.ipv4.fib_multipath_hash_policy": "1",
        }
        for key, value in settings.items():
            run(["sysctl", "-w", f"{key}={value}"])

    def apply_policy_route(self) -> None:
        """Create the fwmark rule and the local default route, idempotently."""
        mark = hex(ROUTER_FWMARK_TPROXY)
        table = str(ROUTER_ROUTE_TABLE)
        priority = str(ROUTER_ROUTE_RULE_PRIORITY)

        existing = run(["ip", "rule", "show"], is_checked=False).stdout
        if f"fwmark {mark} lookup {table}" not in existing:
            run(
                [
                    "ip",
                    "rule",
                    "add",
                    "fwmark",
                    mark,
                    "lookup",
                    table,
                    "pref",
                    priority,
                ]
            )

        routes = run(["ip", "route", "show", "table", table], is_checked=False).stdout
        if "local default" not in routes:
            run(
                [
                    "ip",
                    "route",
                    "add",
                    "local",
                    "default",
                    "dev",
                    "lo",
                    "table",
                    table,
                ]
            )

    def load_ruleset(self, ruleset: str) -> None:
        """Validate and then load an nftables ruleset.

        Args:
            ruleset: Rendered ruleset text.

        Raises:
            CommandError: If ``nft -c`` rejects the ruleset. The running
                firewall is left untouched in that case.
        """
        run(["nft", "-c", "-f", "-"], input_text=ruleset)
        run(["nft", "-f", "-"], input_text=ruleset)

    def flush(self) -> None:
        """Remove the neutrino table and the policy route.

        Used when tearing the gateway down; leaves the machine a plain host.
        """
        run(
            ["nft", "delete", "table", ROUTER_NFT_FAMILY, ROUTER_NFT_TABLE],
            is_checked=False,
        )
        run(
            [
                "ip",
                "rule",
                "del",
                "fwmark",
                hex(ROUTER_FWMARK_TPROXY),
                "lookup",
                str(ROUTER_ROUTE_TABLE),
            ],
            is_checked=False,
        )
