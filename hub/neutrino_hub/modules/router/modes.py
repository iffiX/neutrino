"""The shapes a machine is set up as, and what each one writes.

A shape is one answer to "what is this machine for", turned into the interface
roles the rest of the router layer already understands. None of them is a new
capability: ``router`` is an uplink and a served network, ``side_gateway`` is a
served network whose own way out is that network's real router, and ``server``
is a box that routes nothing and only answers where it is reached.

``one_arm_router`` is the fourth shape and not a fourth mode: a single trunk
port going out untagged and serving on a tag is a router, and what it writes
says ``router``. The distinction is a wizard's — it decides which questions to
ask — and it ends there.

Pure: builds a configuration object and touches nothing.
"""

import ipaddress
from dataclasses import dataclass

from neutrino_hub.modules.router.constants import (
    ROUTER_LAYOUT_ONE_ARM,
    ROUTER_MODE_ROUTER,
    ROUTER_MODE_SERVER,
    ROUTER_MODE_SIDE_GATEWAY,
    ROUTER_MODES_ADDRESSING_OWNED,
    ROUTER_MODES_KEYS,
    ROUTER_ROLE_DISABLED,
    ROUTER_ROLE_LAN,
    ROUTER_ROLE_SPLIT,
    ROUTER_ROLE_WAN,
)
from neutrino_hub.modules.router.interfaces import (
    RouterInterface,
    RouterLanSettings,
    RouterNetworkConfig,
    RouterVlanSettings,
    RouterWanSettings,
)

# --- config ---
# The address the served network gets when nobody says otherwise. Deliberately
# not 192.168.0.0/24 or 192.168.1.0/24: those are what the router upstream is
# most likely already using, and two networks with one address route nowhere.
ROUTER_MODE_DEFAULT_LAN_ADDRESS = "192.168.8.1"
ROUTER_MODE_DEFAULT_PREFIX_LEN = 24
# Where the lease pool sits inside the served network, leaving the low
# addresses for things somebody pins by hand.
ROUTER_MODE_POOL_FIRST = 100
ROUTER_MODE_POOL_LAST = 200

# What a trunk's untagged main is called on the panel and in `config/`. It is
# not a kernel device: its traffic is the trunk port's own.
ROUTER_MODE_UNTAGGED_SUFFIX = ".main"
# The tag a one-arm setup carves the served network out of, when nobody says
# otherwise. The uplink needs none: it is the untagged traffic.
ROUTER_MODE_DEFAULT_LAN_VLAN = 3


@dataclass(frozen=True)
class RouterMode:
    """One shape, and what has to be answered before it can be planned.

    Attributes:
        key: What the wizard calls it.
        stored_mode: What `config/` calls what it plans, which is the key
            itself for every shape that is a mode of its own.
        summary: One line, shown beside the key when choosing.
        port_count: How many ports it needs. A machine with fewer is not
            offered the mode at all, rather than offered it and then told.
        is_wire_needed: Whether its ports have to be wired. 802.1Q tags do
            not ride on a radio, so a trunk cannot be one.
        caution: A consequence of choosing this shape that the machine cannot
            be checked for beforehand, empty where there is none. What a shape
            *is* belongs to its summary; this is what it costs.
    """

    key: str
    summary: str
    stored_mode: str = ""
    port_count: int = 1
    is_wire_needed: bool = False
    caution: str = ""

    @property
    def mode(self) -> str:
        """What `config/` calls what this shape plans."""
        return self.stored_mode or self.key

    @property
    def is_addressing_owned(self) -> bool:
        """Whether this shape addresses the machine's interfaces.

        False for the modes that leave addressing to the machine, which
        answer on the address a port already has and change nothing about
        how it got there.
        """
        return self.mode in ROUTER_MODES_ADDRESSING_OWNED


# In the order they are offered: what changes least about the machine first,
# then what needs something of the network it plugs into, then what takes the
# machine over — with the one-wire router beside the router it is one of.
ROUTER_MODES = (
    RouterMode(
        key=ROUTER_MODE_SERVER,
        summary="Routes nothing; answers where it is reached.",
    ),
    RouterMode(
        key=ROUTER_MODE_SIDE_GATEWAY,
        summary="Forwards for hosts that name it as their gateway.",
    ),
    RouterMode(
        key=ROUTER_MODE_ROUTER,
        summary="Routes between uplinks and the networks it serves.",
        port_count=2,
    ),
    RouterMode(
        key=ROUTER_LAYOUT_ONE_ARM,
        summary="Routes on one wire: untagged out, tagged VLAN in.",
        stored_mode=ROUTER_MODE_ROUTER,
        is_wire_needed=True,
        caution="The switch it plugs into has to pass VLAN tags. On a plain "
        "switch this looks configured and carries nothing.",
    ),
)

ROUTER_MODES_BY_KEY = {mode.key: mode for mode in ROUTER_MODES}

assert ROUTER_MODES_KEYS == tuple(dict.fromkeys(mode.mode for mode in ROUTER_MODES))


def modes_for(port_count: int, wired_count: int) -> tuple:
    """The modes a machine with these ports can actually be set up as.

    Offering a mode that needs two ports to a machine with one, and refusing
    it after it is chosen, teaches nothing the list could have said first.

    Args:
        port_count: How many interfaces the machine has.
        wired_count: How many of them are wired.

    Returns:
        The modes to offer, in the order they are declared.
    """
    return tuple(
        mode
        for mode in ROUTER_MODES
        if mode.port_count <= port_count
        and not (mode.is_wire_needed and wired_count < mode.port_count)
    )


class RouterModePlanner:
    """Turns one mode and the ports chosen for it into a configuration."""

    def __init__(
        self,
        *,
        mode: str,
        wan_names: tuple = (),
        lan_names: tuple = (),
        port_names: tuple = (),
        trunk_name: str = "",
        lan_address: str = ROUTER_MODE_DEFAULT_LAN_ADDRESS,
        lan_prefix_len: int = ROUTER_MODE_DEFAULT_PREFIX_LEN,
        upstream_gateway: str | None = None,
        lan_vlan_id: int = ROUTER_MODE_DEFAULT_LAN_VLAN,
    ):
        """
        Args:
            mode: One shape, keyed as :data:`ROUTER_MODES_BY_KEY` keys it.
            wan_names: Ports carrying the uplink.
            lan_names: Ports carrying the served network.
            port_names: Every port the machine has. The modes that address
                nothing leave all of them answering, which is what they were doing before the
                hub arrived; only the panel narrows that afterwards.
            trunk_name: The port the VLANs ride on, for one-arm.
            lan_address: The gateway's own address on the served network.
            lan_prefix_len: Prefix length of the served network.
            upstream_gateway: The network's real router, for a side gateway.
            lan_vlan_id: Tag carrying the served network, for one-arm. The
                uplink needs none; it is the trunk's untagged traffic.

        Raises:
            ValueError: When the mode is not one this knows.
        """
        if mode not in ROUTER_MODES_BY_KEY:
            raise ValueError(f"no shape named {mode!r}")
        self._mode = mode
        self._wan_names = tuple(wan_names)
        self._lan_names = tuple(lan_names)
        self._port_names = tuple(port_names)
        self._trunk_name = trunk_name
        self._lan_address = lan_address
        self._lan_prefix_len = lan_prefix_len
        self._upstream_gateway = upstream_gateway
        self._lan_vlan_id = lan_vlan_id

    def plan(self) -> RouterNetworkConfig:
        """The configuration this mode and these ports describe.

        Returns:
            A network configuration ready to be validated and written.
        """
        if self._mode == ROUTER_LAYOUT_ONE_ARM:
            interfaces = self._one_arm()
        elif self._mode == ROUTER_MODE_SIDE_GATEWAY:
            interfaces = self._side_gateway()
        elif self._mode == ROUTER_MODE_SERVER:
            interfaces = self._server()
        else:
            interfaces = self._router()
        return RouterNetworkConfig(
            mode=ROUTER_MODES_BY_KEY[self._mode].mode, interfaces=interfaces
        )

    def _router(self) -> list:
        """An uplink port and a served port."""
        interfaces = [self._wan(name) for name in self._wan_names]
        interfaces += [self._lan(name) for name in self._lan_names]
        return interfaces

    def _one_arm(self) -> list:
        """A trunk port whose untagged traffic goes out and whose tags serve.

        The uplink is the port's own untagged traffic, because that is what
        arrives on the wire before anybody tags anything — the switch's native
        VLAN, or the handoff from whatever is upstream. The served network is
        a tag carved out of the same wire. Tagging both would need the switch
        to be told about two VLANs rather than one, and would leave the port
        with no way out until it was.
        """
        return [
            RouterInterface(name=self._trunk_name, role=ROUTER_ROLE_SPLIT),
            self._wan(
                f"{self._trunk_name}{ROUTER_MODE_UNTAGGED_SUFFIX}",
                vlan=RouterVlanSettings(parent=self._trunk_name, id=None),
            ),
            self._lan(
                f"{self._trunk_name}.{self._lan_vlan_id}",
                vlan=RouterVlanSettings(parent=self._trunk_name, id=self._lan_vlan_id),
            ),
        ]

    def _side_gateway(self) -> list:
        """One port on somebody else's network, forwarding for what names it."""
        joined = [
            self._lan(
                name,
                is_dhcp_enabled=False,
                upstream_gateway=self._upstream_gateway,
            )
            for name in self._lan_names
        ]
        return joined + self._bystanders(self._lan_names)

    def _server(self) -> list:
        """Every port the machine has, none of them given a job.

        A server routes nothing and serves nothing, so no port holds a role.
        What is left to say about one is whether what this box listens on
        answers there, which is not a role but a firewall.
        """
        return self._bystanders(())

    def _bystanders(self, taken: tuple) -> list:
        """The ports this mode gives no job to, left answering as they were.

        Args:
            taken: The ports the mode has already made something of.

        Returns:
            One entry per remaining port, roleless and exposed.
        """
        return [
            RouterInterface(name=name, role=ROUTER_ROLE_DISABLED, is_exposed=True)
            for name in self._port_names
            if name not in taken
        ]

    def _wan(self, name: str, *, vlan: RouterVlanSettings | None = None):
        """One uplink interface, on DHCP."""
        return RouterInterface(
            name=name,
            role=ROUTER_ROLE_WAN,
            wan=RouterWanSettings(),
            vlan=vlan,
        )

    def _lan(
        self,
        name: str,
        *,
        vlan: RouterVlanSettings | None = None,
        is_dhcp_enabled: bool = True,
        upstream_gateway: str | None = None,
    ):
        """One served interface, with a lease pool when it hands out leases."""
        start, end = self._pool()
        return RouterInterface(
            name=name,
            role=ROUTER_ROLE_LAN,
            # A served network answers by definition: it is where the panel,
            # DNS and the leases are reached, and a fence around it would fence
            # out the devices it exists for.
            is_exposed=True,
            lan=RouterLanSettings(
                address=self._lan_address,
                prefix_len=self._lan_prefix_len,
                is_dhcp_enabled=is_dhcp_enabled,
                dhcp_range_start=start if is_dhcp_enabled else "",
                dhcp_range_end=end if is_dhcp_enabled else "",
                upstream_gateway=upstream_gateway,
            ),
            vlan=vlan,
        )

    def _pool(self) -> tuple:
        """The lease pool inside the served network.

        Returns:
            First and last address, empty strings when the address given is
            not one a pool can be worked out from.
        """
        try:
            network = ipaddress.ip_network(
                f"{self._lan_address}/{self._lan_prefix_len}", strict=False
            )
        except ValueError:
            return "", ""
        hosts = list(network.hosts())
        if len(hosts) <= ROUTER_MODE_POOL_LAST:
            return str(hosts[0]), str(hosts[-1])
        first = network.network_address + ROUTER_MODE_POOL_FIRST
        last = network.network_address + ROUTER_MODE_POOL_LAST
        return str(first), str(last)
