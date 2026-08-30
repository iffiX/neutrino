"""Making the rendered routing state real.

Everything with a system effect in the router layer lives here: the interface
roles pushed into NetworkManager, the default route shared between uplinks,
forwarding sysctls, the policy route TPROXY needs, and loading the nftables
ruleset. The renderers stay pure so they can be tested without root.
"""

import pwd

from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.router import network_manager
from neutrino_hub.modules.router.constants import (
    ROUTER_FWMARK_TPROXY,
    ROUTER_METRIC_BALANCE,
    ROUTER_METRIC_MULTIPATH,
    ROUTER_METRIC_SIDE_GATEWAY,
    ROUTER_NFT_FAMILY,
    ROUTER_NFT_TABLE,
    ROUTER_NM_CONNECTION_PREFIX,
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
from neutrino_hub.modules.router.wifi import RouterWifiRadio

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
            f"run scripts/install/main.py first"
        ) from error


def remove_vlan_device(name: str) -> list[str]:
    """Take a VLAN interface off the box, connection and device together.

    Deleting the NetworkManager connection removes the kernel device with it;
    every saved connection bound to the device goes, so a profile left by an
    earlier configuration cannot resurrect the VLAN at the next boot.

    Args:
        name: The VLAN interface name, for example ``enp1s0.10``.

    Returns:
        One line when something was removed; empty when there was nothing.
    """
    connections = network_manager.connections_for_device(name)
    for connection in connections:
        network_manager.deactivate(connection)
        run(["nmcli", "connection", "delete", connection], is_checked=False)
    if not connections:
        return []
    return [f"{name} removed"]


def build_uplink_plan(
    *, network: RouterNetworkConfig, status: RouterLinkStatus | None = None
) -> UplinkPlan:
    """Read the live links and work out what the uplinks should be doing.

    The bridge between the pure planner and the system: it gathers the facts
    the planner ranks on, so the planner itself stays testable without root or
    a network.

    Args:
        network: The parsed router configuration.
        status: An existing reader to reuse, saving a second round of nmcli
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
        self._kinds = network_manager.device_kinds()
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
        changes = []
        for interface in ordered:
            changes += self.apply(interface)
        changes += RouterDefaultRouteApplier(network=self._network).apply()
        return changes

    def apply(self, interface: RouterInterface) -> list[str]:
        """Apply one interface's role.

        Args:
            interface: The interface to configure.

        Returns:
            One line per change actually made.

        Raises:
            CommandError: If NetworkManager rejects the configuration.
        """
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
        connection = self._ethernet_connection(device)
        settings = {
            # No address on purpose: the untagged main is disabled, so the
            # port carries tagged VLANs and nothing else. The link itself
            # stays up — the VLANs are riding on it.
            "ipv4.method": "disabled",
            "ipv4.addresses": "",
            "ipv4.gateway": "",
            "ipv4.never-default": "yes",
            "ipv6.method": "disabled",
            "connection.autoconnect": "yes",
        }
        if not self._reconfigure(device, connection, settings):
            return []
        return [f"{device} carrying tagged VLANs only"]

    def _apply_lan(self, interface: RouterInterface) -> list[str]:
        if self._is_wifi(interface.name):
            radio = RouterWifiRadio(interface=interface.name)
            is_changed = radio.publish(interface=interface)
            if not is_changed:
                return []
            return [
                f"{interface.name} publishing {interface.wifi.ap_ssid} "
                f"on {interface.lan.cidr}"
            ]

        connection = (
            self._vlan_connection(interface)
            if interface.is_vlan
            else self._ethernet_connection(interface.name)
        )
        upstream = interface.lan.upstream_gateway
        settings = {
            "ipv4.method": "manual",
            "ipv4.addresses": interface.lan.cidr,
            # A LAN must never offer itself as the way out — unless it is a
            # side gateway, where the network's real router on this same wire
            # is exactly the way out.
            "ipv4.gateway": upstream or "",
            "ipv4.never-default": "no" if upstream else "yes",
            "connection.autoconnect": "yes",
        }
        if upstream:
            settings["ipv4.route-metric"] = str(ROUTER_METRIC_SIDE_GATEWAY)
        if not self._reconfigure(interface.name, connection, settings):
            return []
        if upstream:
            return [f"{interface.name} serving {interface.lan.cidr} via {upstream}"]
        return [f"{interface.name} serving {interface.lan.cidr}"]

    def _apply_wan(self, interface: RouterInterface) -> list[str]:
        settings = {
            "ipv4.never-default": "no",
            "ipv4.route-metric": str(self._route_metric(interface)),
            "connection.autoconnect": "yes",
            # Turn off duplicate-address detection on the uplinks. A gateway
            # routinely has two of its own interfaces on one upstream network —
            # a wired port and a radio plugged into the same home broadband —
            # and then the ARP probe for an address is answered by the box
            # itself. NetworkManager reports that self-conflict and can end the
            # activation with the address applied and not one route installed,
            # which is an uplink that looks configured and carries nothing.
            # Nothing is given up: on DHCP the server is authoritative about
            # who holds what, and on a static uplink the address was chosen
            # deliberately.
            "ipv4.dad-timeout": "0",
        }

        if self._is_wifi(interface.name):
            radio = RouterWifiRadio(interface=interface.name)
            radio.unpublish()
            connection = network_manager.connection_for_device(interface.name)
            notes = []
            if connection is None and interface.wifi.ssid:
                # The radio remembers which network it joins, so coming back
                # to the WAN role rejoins it rather than sitting dark until
                # someone picks the same network from the scan again. Failing
                # to rejoin — out of range, forgotten profile — is not a
                # failure of the role change itself.
                try:
                    connection = radio.join(ssid=interface.wifi.ssid, passphrase=None)
                    notes.append(f"{interface.name} rejoined {interface.wifi.ssid}")
                except CommandError:
                    notes.append(
                        f"{interface.name} could not rejoin "
                        f"{interface.wifi.ssid}; pick a network from the scan"
                    )
            if connection is None:
                # Not a failure: an interface can be assigned the WAN role
                # before anyone has chosen which network it should join. The
                # page says so and offers the scan.
                return notes
            if not self._reconfigure(interface.name, connection, settings):
                return notes
            metric = self._route_metric(interface)
            return notes + [f"{interface.name} uplink metric {metric}"]

        connection = (
            self._vlan_connection(interface)
            if interface.is_vlan
            else self._ethernet_connection(interface.name)
        )
        if interface.wan.method == ROUTER_WAN_METHOD_STATIC:
            settings["ipv4.method"] = "manual"
            settings["ipv4.addresses"] = (
                f"{interface.wan.address}/{interface.wan.prefix_len}"
            )
            settings["ipv4.gateway"] = interface.wan.gateway or ""
        else:
            settings["ipv4.method"] = "auto"
            settings["ipv4.addresses"] = ""
            settings["ipv4.gateway"] = ""
        if not interface.is_vlan:
            # A VLAN inherits the trunk's hardware address; cloning belongs to
            # the physical port.
            settings["802-3-ethernet.cloned-mac-address"] = (
                interface.wan.cloned_mac or "permanent"
            )
        if not self._reconfigure(interface.name, connection, settings):
            return []
        return [
            f"{interface.name} uplink reconfigured",
            *self._verify_uplink(interface.name, connection),
        ]

    def _verify_uplink(self, device: str, connection: str) -> list[str]:
        """Check an uplink came out of the apply able to carry traffic.

        The failure this exists for is specific and silent: NetworkManager
        finishes the activation, the interface holds its address, and not one
        route was installed — no default route, not even the on-link one. The
        box is off the internet while every command that ran reported success.

        Reactivating by hand clears it, so that is what is done here, once. A
        second failure is reported rather than retried: at that point something
        is wrong that repeating will not fix, and a panel that says so is worth
        more than one that silently returns success over a dead uplink.

        Args:
            device: Interface name.
            connection: The connection that was activated.

        Returns:
            A line describing the recovery, or nothing when the uplink is fine.

        Raises:
            CommandError: If the uplink still has no route after one retry.
        """
        if self._has_route(device):
            return []
        network_manager.activate(connection)
        if self._has_route(device):
            return [f"{device} came up without routes; reactivating fixed it"]
        raise CommandError(
            f"{device} activated but has no IPv4 route, so it cannot carry "
            f"traffic; check `nmcli device show {device}` and the "
            f"NetworkManager journal"
        )

    def _has_route(self, device: str) -> bool:
        result = run(["ip", "-4", "route", "show", "dev", device], is_checked=False)
        return result.is_success and bool(result.stdout.strip())

    def _apply_disabled(self, interface: RouterInterface) -> list[str]:
        if interface.is_vlan:
            # A disabled VLAN does not exist: unlike a physical port, there is
            # no hardware to leave idle, so its device is simply removed.
            return remove_vlan_device(interface.name)
        link = self._status.link(interface.name)
        if self._is_wifi(interface.name):
            RouterWifiRadio(interface=interface.name).stand_down()
        else:
            for name in network_manager.connections_for_device(interface.name):
                network_manager.modify_if_needed(name, {"connection.autoconnect": "no"})
        if not link.is_up and link.connection is None:
            return []
        network_manager.disconnect_device(interface.name)
        return [f"{interface.name} disabled"]

    def _reconfigure(
        self, device: str, connection: str, settings: dict[str, str]
    ) -> bool:
        """Write settings, and bring them into effect the cheapest way that works.

        Three outcomes, in rising order of disruption. Nothing differs and the
        connection is already up: do nothing at all. Only in-place properties
        differ: write them and reapply, which the link never notices. An
        addressing property differs, or the connection is not up: reactivate,
        which drops the link and is the only path that can.

        Args:
            device: Interface name.
            connection: The connection to write to.
            settings: Wanted properties.

        Returns:
            True when anything was changed.
        """
        differing = network_manager.differing_properties(connection, settings)
        is_active = network_manager.connection_for_device(device) == connection
        if not differing and is_active:
            return False

        network_manager.modify(connection, settings)
        if is_active and not (differing & REACTIVATION_PROPERTIES):
            network_manager.reapply_device(device, connection=connection)
            return True

        network_manager.activate(connection)
        return True

    def _vlan_connection(self, interface: RouterInterface) -> str:
        """Find or create the connection that realises a VLAN interface.

        Creating the connection is what creates the kernel device: a VLAN has
        no existence before NetworkManager is told to tag for it.

        Args:
            interface: An interface carrying a ``vlan`` block.

        Returns:
            The connection name.
        """
        saved = network_manager.connections_for_device(interface.name)
        if saved:
            return saved[0]
        name = f"{ROUTER_NM_CONNECTION_PREFIX}{interface.name}"
        if not network_manager.connection_exists(name):
            run(
                [
                    "nmcli",
                    "connection",
                    "add",
                    "type",
                    "vlan",
                    "ifname",
                    interface.name,
                    "con-name",
                    name,
                    "dev",
                    interface.vlan.parent,
                    "id",
                    str(interface.vlan.id),
                ]
            )
        return name

    def _ethernet_connection(self, device: str) -> str:
        """Find or create the connection this wired interface is configured by.

        An interface the machine was installed with already has a connection —
        netplan's, or one NetworkManager made on first boot — and reusing it
        keeps the box to a single profile per port. Only an interface with
        none gets one created here, under the gateway's own name prefix.

        Args:
            device: Interface name.

        Returns:
            The connection name.
        """
        active = network_manager.connection_for_device(device)
        if active is not None:
            return active
        saved = network_manager.connections_for_device(device)
        if saved:
            return saved[0]
        name = f"{ROUTER_NM_CONNECTION_PREFIX}{device}"
        if not network_manager.connection_exists(name):
            run(
                [
                    "nmcli",
                    "connection",
                    "add",
                    "type",
                    "ethernet",
                    "ifname",
                    device,
                    "con-name",
                    name,
                ]
            )
        return name

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
