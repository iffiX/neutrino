"""What each network interface is for: the role model behind the Network page.

An interface is a WAN uplink, a LAN the gateway serves, or unused, and its role
decides which block of its settings applies. The renderers read roles rather
than fixed ``wan_interface`` and ``lan_interface`` names, which is what lets the
box have two LANs, or reach the internet over Wi-Fi, with no schema change.

Every interface keeps all three settings blocks whatever its current role, so
switching a port from LAN to WAN and back does not lose the addresses that were
typed in for the other role.

Pure: this module parses and shapes configuration. Making a role real —
NetworkManager, routes, the firewall — is :mod:`neutrino_hub.modules.router.routes`.
"""

import ipaddress
from dataclasses import dataclass, field

from neutrino_hub.modules.overlay.constants import OVERLAY_ENGINES
from neutrino_hub.modules.router.constants import (
    ROUTER_INTENT_AUTO,
    ROUTER_INTENT_BACKUP_ONLY,
    ROUTER_INTENT_PRIMARY,
    ROUTER_INTENTS,
    ROUTER_MODE_ROUTER,
    ROUTER_MODES_ADDRESSING_OWNED,
    ROUTER_MODES_KEYS,
    ROUTER_OVERLAY_KEYS,
    ROUTER_OVERLAY_NETBIRD,
    ROUTER_POLICIES,
    ROUTER_POLICY_FAILOVER,
    ROUTER_ROLE_DISABLED,
    ROUTER_ROLE_LAN,
    ROUTER_ROLE_SPLIT,
    ROUTER_ROLE_WAN,
    ROUTER_ROLES,
    ROUTER_WAN_METHOD_DHCP,
    ROUTER_WAN_METHOD_STATIC,
    ROUTER_WAN_METHODS,
)

DEFAULT_DHCP_LEASE_TIME = "12h"
DEFAULT_AP_BAND = "bg"


@dataclass
class RouterWanSettings:
    """How an interface reaches the internet when its role is ``wan``.

    There is no "which uplink wins" field here. Ordering is worked out from
    what the box can see — which uplinks share one upstream line, which are
    wired, how fast each negotiated — because those are facts, and asking
    someone to restate them as a ranking is asking them to keep a second copy
    in sync by hand. ``intent`` carries only the part that cannot be inferred.

    Attributes:
        method: ``dhcp`` or ``static``.
        address: Static IPv4 address, unused under DHCP.
        prefix_len: Static prefix length.
        gateway: Static next hop, unused under DHCP.
        intent: ``auto`` to let the gateway place this uplink, ``primary`` to
            pin it first, ``backup_only`` to keep it dark until nothing else
            is left.
        cloned_mac: MAC to present upstream, for networks that register a
            device by hardware address. None keeps the real one.
    """

    method: str = ROUTER_WAN_METHOD_DHCP
    address: str | None = None
    prefix_len: int = 24
    gateway: str | None = None
    intent: str = ROUTER_INTENT_AUTO
    cloned_mac: str | None = None

    @property
    def is_backup_only(self) -> bool:
        """Whether this uplink stays dark while any other one works."""
        return self.intent == ROUTER_INTENT_BACKUP_ONLY

    @property
    def is_pinned_primary(self) -> bool:
        """Whether this uplink is pinned ahead of the ranking."""
        return self.intent == ROUTER_INTENT_PRIMARY

    @classmethod
    def from_dict(cls, data: dict) -> "RouterWanSettings":
        """Parse one WAN settings block.

        Args:
            data: The ``wan`` object from an interface entry.

        Returns:
            The parsed settings, with unknown enum values falling back to the
            defaults rather than raising — a hand-edited config with a typo
            should still leave the box routable.
        """
        method = str(data.get("method", ROUTER_WAN_METHOD_DHCP))
        return cls(
            method=method if method in ROUTER_WAN_METHODS else ROUTER_WAN_METHOD_DHCP,
            address=_optional_text(data.get("address")),
            prefix_len=int(data.get("prefix_len", 24)),
            gateway=_optional_text(data.get("gateway")),
            intent=_read_intent(data),
            cloned_mac=_optional_text(data.get("cloned_mac")),
        )

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/network.json``.
        """
        return {
            "method": self.method,
            "address": self.address,
            "prefix_len": self.prefix_len,
            "gateway": self.gateway,
            "intent": self.intent,
            "cloned_mac": self.cloned_mac,
        }


def _read_intent(data: dict) -> str:
    """Read an uplink's intent.

    Args:
        data: The ``wan`` object from an interface entry.

    Returns:
        One of the intent constants. Anything else reads as ``auto``: an
        uplink nobody has an opinion about is one the gateway places itself.
    """
    text = str(data.get("intent", ROUTER_INTENT_AUTO))
    return text if text in ROUTER_INTENTS else ROUTER_INTENT_AUTO


@dataclass
class RouterLanSettings:
    """The network an interface serves when its role is ``lan``.

    Attributes:
        address: The gateway's own address on this network.
        prefix_len: Prefix length of the network.
        is_dhcp_enabled: Whether dnsmasq hands out leases here.
        dhcp_range_start: First address of the pool.
        dhcp_range_end: Last address of the pool.
        dhcp_lease_time: A dnsmasq duration such as ``12h``.
        upstream_gateway: The network's real router, for side-gateway mode:
            the box joins an existing LAN, devices point their gateway at it,
            and its own way out is this router on the very same wire. None is
            the ordinary LAN that owns its network.
    """

    address: str = ""
    prefix_len: int = 24
    is_dhcp_enabled: bool = True
    dhcp_range_start: str = ""
    dhcp_range_end: str = ""
    dhcp_lease_time: str = DEFAULT_DHCP_LEASE_TIME
    upstream_gateway: str | None = None

    @property
    def cidr(self) -> str:
        """The network in ``address/prefix`` form."""
        return f"{self.address}/{self.prefix_len}"

    @property
    def is_side_gateway(self) -> bool:
        """Whether this network doubles as the box's way out."""
        return bool(self.upstream_gateway)

    @classmethod
    def from_dict(cls, data: dict) -> "RouterLanSettings":
        """Parse one LAN settings block.

        Args:
            data: The ``lan`` object from an interface entry.

        Returns:
            The parsed settings.
        """
        upstream = data.get("upstream_gateway")
        return cls(
            address=str(data.get("address", "")),
            prefix_len=int(data.get("prefix_len", 24)),
            is_dhcp_enabled=bool(data.get("is_dhcp_enabled", True)),
            dhcp_range_start=str(data.get("dhcp_range_start", "")),
            dhcp_range_end=str(data.get("dhcp_range_end", "")),
            dhcp_lease_time=str(data.get("dhcp_lease_time", DEFAULT_DHCP_LEASE_TIME)),
            upstream_gateway=str(upstream).strip() or None if upstream else None,
        )

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/network.json``.
        """
        return {
            "address": self.address,
            "prefix_len": self.prefix_len,
            "is_dhcp_enabled": self.is_dhcp_enabled,
            "dhcp_range_start": self.dhcp_range_start,
            "dhcp_range_end": self.dhcp_range_end,
            "dhcp_lease_time": self.dhcp_lease_time,
            "upstream_gateway": self.upstream_gateway,
        }


@dataclass
class RouterWifiSettings:
    """The radio settings of a wireless interface, for either role.

    Joining a network and publishing one are different enough to need separate
    fields, and both are kept so switching roles does not erase the other.

    The passphrase of a *joined* network is deliberately absent: NetworkManager
    stores it in the connection it creates, so keeping a second copy here would
    only be one more place for a secret to leak from.

    Attributes:
        ssid: The network this interface joins in the ``wan`` role.
        ap_ssid: The network it publishes in the ``lan`` role.
        ap_passphrase: WPA2 passphrase for the published network. Empty means
            an open network, which the panel warns about rather than forbids.
        ap_band: ``bg`` for 2.4 GHz or ``a`` for 5 GHz.
    """

    ssid: str = ""
    ap_ssid: str = ""
    ap_passphrase: str = ""
    ap_band: str = DEFAULT_AP_BAND

    @classmethod
    def from_dict(cls, data: dict) -> "RouterWifiSettings":
        """Parse one Wi-Fi settings block.

        Args:
            data: The ``wifi`` object from an interface entry.

        Returns:
            The parsed settings.
        """
        return cls(
            ssid=str(data.get("ssid", "")),
            ap_ssid=str(data.get("ap_ssid", "")),
            ap_passphrase=str(data.get("ap_passphrase", "")),
            ap_band=str(data.get("ap_band", DEFAULT_AP_BAND)),
        )

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/network.json``.
        """
        return {
            "ssid": self.ssid,
            "ap_ssid": self.ap_ssid,
            "ap_passphrase": self.ap_passphrase,
            "ap_band": self.ap_band,
        }


@dataclass
class RouterVlanSettings:
    """What makes an interface ride on a trunk port.

    Kept explicit rather than parsed out of the ``parent.id`` name: the name is
    the kernel's convention, and deriving identity from a naming convention is
    one rename away from being wrong.

    Attributes:
        parent: The trunk interface this rides on.
        id: The 802.1Q tag, 1 to 4094 — or None for the trunk's untagged
            traffic, which the panel shows as ``<parent>.main``. The main
            entry is not a kernel device of its own; it configures the trunk
            port itself.
    """

    parent: str
    id: int | None

    @classmethod
    def from_dict(cls, data: dict) -> "RouterVlanSettings":
        """Parse one VLAN block.

        Args:
            data: The ``vlan`` object from an interface entry.

        Returns:
            The parsed settings.
        """
        raw_id = data.get("id")
        return cls(
            parent=str(data["parent"]),
            id=int(raw_id) if raw_id is not None else None,
        )

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/network.json``.
        """
        return {"parent": self.parent, "id": self.id}


@dataclass
class RouterInterface:
    """One interface and everything the gateway knows to do with it.

    Attributes:
        name: Kernel interface name, for example ``enp1s0`` — or
            ``enp1s0.10`` for a VLAN, following the kernel's own convention.
        role: One of ``wan``, ``lan``, ``split``, ``disabled``.
        is_exposed: Whether what this box listens on answers on this
            interface. One answer for the whole interface rather than a port
            list: every service here binds every address and settles its own
            port, so what is left to decide is which wires reach them.
        wan: Settings used while the role is ``wan``.
        lan: Settings used while the role is ``lan``.
        wifi: Radio settings, used in either role on a wireless interface.
        vlan: Present when this interface is a VLAN riding on a trunk port;
            None for a physical interface.
    """

    name: str
    role: str = ROUTER_ROLE_DISABLED
    is_exposed: bool = False
    wan: RouterWanSettings = field(default_factory=RouterWanSettings)
    lan: RouterLanSettings = field(default_factory=RouterLanSettings)
    wifi: RouterWifiSettings = field(default_factory=RouterWifiSettings)
    vlan: RouterVlanSettings | None = None

    @property
    def is_wan(self) -> bool:
        """Whether this interface is currently an uplink."""
        return self.role == ROUTER_ROLE_WAN

    @property
    def is_lan(self) -> bool:
        """Whether this interface currently serves a network."""
        return self.role == ROUTER_ROLE_LAN

    @property
    def is_split(self) -> bool:
        """Whether this interface is a trunk carrying only tagged VLANs."""
        return self.role == ROUTER_ROLE_SPLIT

    @property
    def is_disabled(self) -> bool:
        """Whether this interface is left alone."""
        return self.role == ROUTER_ROLE_DISABLED

    @property
    def is_vlan(self) -> bool:
        """Whether this interface rides on a trunk rather than being a port."""
        return self.vlan is not None

    @property
    def is_untagged(self) -> bool:
        """Whether this is a trunk's untagged main, not a tagged VLAN."""
        return self.vlan is not None and self.vlan.id is None

    @property
    def device_name(self) -> str:
        """The kernel interface this entry configures.

        The untagged main has no device of its own — its traffic lives on the
        trunk port — so everything that talks to the system (nftables,
        dnsmasq, scans, NetworkManager) must address the parent.

        Returns:
            The parent's name for an untagged main, this entry's name
            otherwise.
        """
        if self.is_untagged:
            return self.vlan.parent
        return self.name

    @classmethod
    def from_dict(cls, data: dict) -> "RouterInterface":
        """Parse one interface entry.

        Args:
            data: An entry of the ``interfaces`` list.

        Returns:
            The parsed interface. An unrecognised role reads as ``disabled``,
            which is the safe direction to fail in: an interface the gateway
            does not understand is one it should not be routing through.
        """
        role = str(data.get("role", ROUTER_ROLE_DISABLED))
        vlan = data.get("vlan")
        return cls(
            name=str(data["name"]),
            role=role if role in ROUTER_ROLES else ROUTER_ROLE_DISABLED,
            is_exposed=bool(data.get("is_exposed", False)),
            wan=RouterWanSettings.from_dict(data.get("wan") or {}),
            lan=RouterLanSettings.from_dict(data.get("lan") or {}),
            wifi=RouterWifiSettings.from_dict(data.get("wifi") or {}),
            vlan=RouterVlanSettings.from_dict(vlan) if vlan else None,
        )

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/network.json``.
        """
        return {
            "name": self.name,
            "role": self.role,
            "is_exposed": self.is_exposed,
            "wan": self.wan.to_dict(),
            "lan": self.lan.to_dict(),
            "wifi": self.wifi.to_dict(),
            "vlan": self.vlan.to_dict() if self.vlan else None,
        }


def _network_of(cidr: str) -> str:
    """The network an address with a prefix belongs to.

    Args:
        cidr: An address in CIDR form.

    Returns:
        The network in CIDR form, empty when the text is not one.
    """
    try:
        return str(ipaddress.ip_network(cidr, strict=False))
    except ValueError:
        return ""


@dataclass
class RouterOverlay:
    """One overlay network this box is a member of.

    A member, not a port: nobody plugs an overlay in, and the box does not
    address it. What is left to decide is the same single question an
    interface answers, so it carries the same field and no others.

    Attributes:
        provider: Who runs the overlay, one of
            :data:`ROUTER_OVERLAY_KEYS`.
        is_exposed: Whether this box answers on the overlay, and whether the
            served networks reach it. One switch for both, because closing an
            overlay means cutting it off rather than going quiet on it while
            still forwarding into the LAN.
    """

    provider: str
    is_exposed: bool = True

    @property
    def device_name(self) -> str:
        """The kernel interface the provider brings up."""
        return OVERLAY_ENGINES[self.provider].device_name

    @property
    def title(self) -> str:
        """What the overlay is called where a person reads it."""
        return OVERLAY_ENGINES[self.provider].title

    @property
    def peer_port(self) -> int:
        """The UDP port the overlay's own peers knock on."""
        return OVERLAY_ENGINES[self.provider].peer_port

    @classmethod
    def from_dict(cls, data: dict) -> "RouterOverlay":
        """Parse one overlay entry.

        Args:
            data: An entry of the ``overlays`` list.

        Returns:
            The parsed overlay, exposed unless the entry says otherwise.
        """
        return cls(
            provider=str(data["provider"]),
            is_exposed=bool(data.get("is_exposed", True)),
        )

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/network.json``.
        """
        return {"provider": self.provider, "is_exposed": self.is_exposed}


@dataclass
class RouterNetworkConfig:
    """The whole of ``config/router/network.json``.

    Attributes:
        mode: What the whole machine is set up as, one of
            :data:`ROUTER_MODES_KEYS`. It decides which panel the page draws
            and whether the hub addresses anything at all.
        interfaces: Every interface the gateway has an opinion about, in the
            order the panel shows them.
        uplink_policy: ``failover`` to keep one uplink carrying everything, or
            ``balance`` to spread across the distinct upstream lines. Opt-in
            rather than inferred: guessing it would put traffic on a metered
            link whose owner forgot to mark it.
        overlays: The overlay networks this box is a member of. A sibling of
            ``interfaces`` rather than an entry in it: switching modes
            rebuilds that list, and an overlay in there would be dropped by a
            change that has nothing to do with it.
        is_inter_lan_allowed: Whether devices on one served network can reach
            devices on another. One switch for all of them rather than a
            per-pair matrix: the whole point of turning it off is "my VLANs
            are fences", and that intent has no per-pair version worth the
            complexity.
    """

    mode: str = ROUTER_MODE_ROUTER
    interfaces: list[RouterInterface] = field(default_factory=list)
    overlays: list[RouterOverlay] = field(default_factory=list)
    uplink_policy: str = ROUTER_POLICY_FAILOVER
    is_inter_lan_allowed: bool = True

    @property
    def is_addressing_owned(self) -> bool:
        """Whether the hub addresses this box's interfaces at all.

        A machine is wholly one or the other, and which it is was settled by
        the mode. Sharing an interface with another manager is where every bug
        in this area has come from, so there is no half-managed state to ask
        an interface about.
        """
        return self.mode in ROUTER_MODES_ADDRESSING_OWNED

    @property
    def exposed_device_names(self) -> list[str]:
        """The kernel devices what this box listens on answers on.

        Returns:
            One name per exposed interface, deduplicated: a trunk and its
            untagged main are one device, and naming it twice would render an
            nft set with a repeated element.
        """
        return _unique(
            interface.device_name
            for interface in self.interfaces
            if interface.is_exposed
        )

    @property
    def overlay_device_names(self) -> list[str]:
        """The kernel devices the configured overlays ride on."""
        return _unique(overlay.device_name for overlay in self.overlays)

    @property
    def exposed_overlay_device_names(self) -> list[str]:
        """The overlay devices this box answers on and forwards to."""
        return _unique(
            overlay.device_name for overlay in self.overlays if overlay.is_exposed
        )

    @property
    def exposed_overlay_peer_ports(self) -> list[int]:
        """The UDP ports the exposed overlays' peers knock on, ascending."""
        return sorted(
            {overlay.peer_port for overlay in self.overlays if overlay.is_exposed}
        )

    def local_networks(self, addresses: dict) -> list:
        """Every network this machine is on, whatever shape it is.

        Not the same question as which interfaces have the LAN role: a box
        that routes nothing still sits on somebody's network, and that is the
        network it can be reached on and can offer an overlay a route to. The
        overlays' own devices are left out — they are the thing being offered
        a route, not a route to offer.

        Args:
            addresses: Device name to address with its prefix, as
                :func:`neutrino_hub.modules.router.link_status.device_addresses`
                answers.

        Returns:
            ``(cidr, interface)`` pairs, the configured served networks first
            and in configuration order, then whatever else this box holds an
            address on.
        """
        overlays = set(self.overlay_device_names)
        found: list = []
        seen: set = set()
        for interface in self.interfaces:
            if not interface.is_lan or not interface.lan.address:
                continue
            cidr = _network_of(interface.lan.cidr)
            if cidr and cidr not in seen:
                seen.add(cidr)
                found.append((cidr, interface.name))
        for name, address in sorted(addresses.items()):
            if name in overlays:
                continue
            cidr = _network_of(address)
            if cidr and cidr not in seen:
                seen.add(cidr)
                found.append((cidr, name))
        return found

    def overlay(self, provider: str) -> "RouterOverlay | None":
        """Find one overlay by provider.

        Args:
            provider: The provider key.

        Returns:
            The overlay, or None when this box is not configured for it.
        """
        for overlay in self.overlays:
            if overlay.provider == provider:
                return overlay
        return None

    @property
    def wan_interfaces(self) -> list[RouterInterface]:
        """The uplinks, in configuration order.

        Deliberately unranked. Which uplink should carry traffic depends on
        what the links are actually doing, which this object does not know;
        :mod:`neutrino_hub.modules.router.uplink_plan` works it out from a live snapshot.

        Returns:
            Interfaces with the ``wan`` role.
        """
        return [interface for interface in self.interfaces if interface.is_wan]

    @property
    def lan_interfaces(self) -> list[RouterInterface]:
        """The networks the gateway serves, in configuration order."""
        return [interface for interface in self.interfaces if interface.is_lan]

    @property
    def side_gateway_lans(self) -> list[RouterInterface]:
        """The served networks that double as the box's way out."""
        return [
            interface
            for interface in self.lan_interfaces
            if interface.lan.is_side_gateway
        ]

    @property
    def primary_lan(self) -> RouterInterface | None:
        """The first LAN, or None when the box serves none.

        This is the address services bind to when they need one address rather
        than all of them — the SOCKS listener, Gitea. A second LAN still
        reaches them, because the gateway routes between its own networks.

        Returns:
            The first LAN interface, or None.
        """
        lans = self.lan_interfaces
        return lans[0] if lans else None

    @property
    def primary_lan_address(self) -> str:
        """The one address to use where only one will do.

        The SOCKS listener binds here, and the panel names it as its own URL
        when telling a device where the gateway is.

        Returns:
            The first LAN's address, or loopback when the box serves no network
            — a service reachable from nowhere is still better than one bound
            to every interface, uplink included.
        """
        lan = self.primary_lan
        return lan.lan.address if lan and lan.lan.address else "127.0.0.1"

    @property
    def device_facing_interfaces(self) -> "list[RouterInterface]":
        """The interfaces this hub's own devices can be on.

        The served networks, then anything exposed that is not an uplink: a
        ``server`` sits on somebody's LAN, and its exposed port faces the
        same machines a router's served port does. Uplinks never count —
        the upstream network is not this hub's to sweep.

        Returns:
            Interfaces in configuration order, one per kernel device.
        """
        facing = list(self.lan_interfaces)
        names = {interface.device_name for interface in facing}
        for interface in self.interfaces:
            if interface.is_wan or not interface.is_exposed:
                continue
            if interface.device_name in names:
                continue
            facing.append(interface)
            names.add(interface.device_name)
        return facing

    @property
    def device_facing_device_names(self) -> list[str]:
        """Kernel devices carrying the networks devices can be on."""
        return _unique(
            interface.device_name for interface in self.device_facing_interfaces
        )

    @property
    def wan_names(self) -> list[str]:
        """Interface names of the uplinks, in preference order."""
        return [interface.name for interface in self.wan_interfaces]

    @property
    def lan_names(self) -> list[str]:
        """Interface names of the served networks."""
        return [interface.name for interface in self.lan_interfaces]

    @property
    def wan_device_names(self) -> list[str]:
        """Kernel devices carrying the uplinks, for the system-facing layers."""
        return _unique(interface.device_name for interface in self.wan_interfaces)

    @property
    def lan_device_names(self) -> list[str]:
        """Kernel devices carrying the served networks."""
        return _unique(interface.device_name for interface in self.lan_interfaces)

    def untagged_child(self, parent: str) -> "RouterInterface | None":
        """Find a trunk's untagged main entry.

        Args:
            parent: The trunk interface's name.

        Returns:
            The main entry, or None when the trunk has none yet.
        """
        for interface in self.interfaces:
            if (
                interface.vlan is not None
                and interface.vlan.parent == parent
                and interface.vlan.id is None
            ):
                return interface
        return None

    def interface(self, name: str) -> RouterInterface | None:
        """Find one interface by name.

        Args:
            name: Kernel interface name.

        Returns:
            The interface, or None when it is not in the configuration.
        """
        for interface in self.interfaces:
            if interface.name == name:
                return interface
        return None

    def interface_or_new(self, name: str) -> RouterInterface:
        """This interface as configured, or a fresh one with no job.

        A port the box has and the configuration does not still has to be
        shown, and a port nobody has said anything about answers nothing: an
        interface appearing on its own is not a reason to open it.

        Args:
            name: Kernel interface name.

        Returns:
            The stored interface, or a new roleless one.
        """
        return self.interface(name) or RouterInterface(name=name)

    def vlan_children(self, parent: str) -> list[RouterInterface]:
        """The VLANs riding on one trunk port, in configuration order.

        Args:
            parent: The trunk interface's name.

        Returns:
            Every interface whose ``vlan.parent`` is this port.
        """
        return [
            interface
            for interface in self.interfaces
            if interface.vlan is not None and interface.vlan.parent == parent
        ]

    def remove(self, name: str) -> bool:
        """Drop one interface from the configuration.

        Args:
            name: Kernel interface name.

        Returns:
            True when an entry was removed.
        """
        for index, interface in enumerate(self.interfaces):
            if interface.name == name:
                del self.interfaces[index]
                return True
        return False

    def keep_single_primary(self, name: str) -> list[str]:
        """Make one uplink the pinned primary and demote any other.

        Pinning means "put this one first", which two uplinks cannot both be.
        Rather than refuse the second, the most recent choice wins and the older
        one goes back to being placed automatically — pinning a different uplink
        is a change of mind, not a mistake to be argued with.

        Args:
            name: The interface whose pin is being kept.

        Returns:
            The names demoted back to automatic, which the caller can report.
        """
        demoted = []
        for interface in self.interfaces:
            if interface.name == name or not interface.wan.is_pinned_primary:
                continue
            interface.wan.intent = ROUTER_INTENT_AUTO
            demoted.append(interface.name)
        return demoted

    def replace(self, interface: RouterInterface) -> None:
        """Insert or overwrite one interface's configuration.

        Args:
            interface: The interface to store, keyed by its name.
        """
        for index, existing in enumerate(self.interfaces):
            if existing.name == interface.name:
                self.interfaces[index] = interface
                return
        self.interfaces.append(interface)

    @classmethod
    def from_dict(cls, data: dict) -> "RouterNetworkConfig":
        """Parse the router configuration.

        Args:
            data: Parsed ``config/router/network.json``.

        Returns:
            The configuration.
        """
        policy = str(data.get("uplink_policy", ROUTER_POLICY_FAILOVER))
        mode = str(data.get("mode", ROUTER_MODE_ROUTER))
        # A configuration written before overlays were a thing gets the
        # NetBird entry, exposed: that is what the firewall did unconditionally
        # until now, and it was the only overlay a hub could run, so the day
        # the new hub starts changes nothing about who can reach the box.
        # Whoever first turns the switch off decides that.
        stored = data.get("overlays")
        overlays = [{"provider": ROUTER_OVERLAY_NETBIRD}] if stored is None else stored
        return cls(
            mode=mode if mode in ROUTER_MODES_KEYS else ROUTER_MODE_ROUTER,
            interfaces=[
                RouterInterface.from_dict(entry)
                for entry in data.get("interfaces", [])
                if entry.get("name")
            ],
            overlays=[
                RouterOverlay.from_dict(entry)
                for entry in overlays
                if entry.get("provider") in ROUTER_OVERLAY_KEYS
            ],
            uplink_policy=(
                policy if policy in ROUTER_POLICIES else ROUTER_POLICY_FAILOVER
            ),
            is_inter_lan_allowed=bool(data.get("is_inter_lan_allowed", True)),
        )

    def to_dict(self) -> dict:
        """Serialize the whole configuration.

        Returns:
            A plain object ready for ``config/router/network.json``.
        """
        return {
            "mode": self.mode,
            "interfaces": [interface.to_dict() for interface in self.interfaces],
            "overlays": [overlay.to_dict() for overlay in self.overlays],
            "uplink_policy": self.uplink_policy,
            "is_inter_lan_allowed": self.is_inter_lan_allowed,
        }


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique(names) -> list[str]:
    seen = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


__all__ = [
    "RouterInterface",
    "RouterLanSettings",
    "RouterNetworkConfig",
    "RouterVlanSettings",
    "RouterWanSettings",
    "RouterWifiSettings",
    "ROUTER_ROLE_DISABLED",
    "ROUTER_ROLE_LAN",
    "ROUTER_ROLE_SPLIT",
    "ROUTER_ROLE_WAN",
    "ROUTER_WAN_METHOD_DHCP",
    "ROUTER_WAN_METHOD_STATIC",
    "ROUTER_INTENT_AUTO",
    "ROUTER_INTENT_BACKUP_ONLY",
    "ROUTER_INTENT_PRIMARY",
]
