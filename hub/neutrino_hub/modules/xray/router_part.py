"""The proxy's part of the router's renderers, given through the edition table.

The nftables ruleset diverts traffic into xray's TPROXY socket with the
chains and the mark below, and dnsmasq forwards to xray's DNS inbound while
the served networks' traffic is proxied. A tree without the proxy renders
neither.

Pure, but for reading ``config/xray/routing.json`` and the xray account.
"""

# Unix's alone; the proxy core's account exists on Linux alone.
try:
    import pwd
except ImportError:
    pwd = None

from neutrino_hub.modules.router.constants import (
    ROUTER_FWMARK_TPROXY,
    ROUTER_FWMARK_XRAY_EGRESS,
)
from neutrino_hub.modules.xray.constants import (
    XRAY_DNS_LISTEN,
    XRAY_DNS_PORT,
    XRAY_ROUTING_FILE,
    XRAY_TPROXY_LISTEN,
    XRAY_TPROXY_PORT,
)
from neutrino_hub.modules.xray.resolvers import direct_resolvers
from neutrino_hub.system.constants import SYSTEM_XRAY_USER
from neutrino_hub.utils.json_file import read_config


def read_routing() -> dict:
    """Read the proxy's routing options.

    Returns:
        Parsed ``config/xray/routing.json``.

    Raises:
        FileNotFoundError: When the box is not set up.
        ValueError: When the file is not valid JSON.
    """
    return read_config(XRAY_ROUTING_FILE)


def lookup_xray_uid() -> int:
    """Resolve the uid the xray service runs as.

    The nftables anti-loop rule matches on this uid, so it is resolved once at
    apply time and handed to the renderer rather than looked up inside it.

    Returns:
        The numeric uid.

    Raises:
        RuntimeError: If the user does not exist yet. The installer creates
            it before any ruleset is rendered. Outside Linux there is none.
    """
    if pwd is None:
        raise RuntimeError(f"system user {SYSTEM_XRAY_USER!r} exists on Linux alone")
    try:
        return pwd.getpwnam(SYSTEM_XRAY_USER).pw_uid
    except KeyError as error:
        raise RuntimeError(
            f"system user {SYSTEM_XRAY_USER!r} does not exist; "
            f"run `nhub setup` first"
        ) from error


def dnsmasq_upstream(routing: dict, network_resolvers: list[dict]) -> list | None:
    """Where dnsmasq forwards while the LAN scope is on.

    LAN queries belong to the LAN scope, so they go where LAN traffic goes.
    With it on, the only upstream is the xray DNS inbound, so a name is
    resolved at the exit node and no plaintext query ever leaves by an
    uplink. With it off, sending queries through xray anyway would be both
    pointless and fragile, so the router's own upstream applies.

    Args:
        routing: Parsed ``config/xray/routing.json``.
        network_resolvers: The network's resolvers, as ``{address, port}``.

    Returns:
        The upstream lines, ending in a blank line; None while the LAN scope
        is off.
    """
    if not routing.get("is_proxy_enabled", True):
        return None
    lines = [
        "# The first upstream is the xray DNS inbound, so queries resolve at",
        "# the exit node instead of leaking to whatever DNS the WAN handed us.",
        "no-resolv",
    ]
    if routing.get("is_direct_fallback_enabled", False):
        lines += [
            "#",
            "# And a second one behind it, tried only when the first does not",
            "# answer: a dead exit is a dead resolver, and without this the",
            "# LAN loses every name rather than the proxied ones. strict-order",
            "# is what makes it a fallback instead of a race — dnsmasq would",
            "# otherwise ask both and leak every query to the direct resolver.",
            "#",
            "# The direct resolvers rather than the remote ones: the remote",
            "# is reached in plaintext once the proxy is out of the path,",
            "# which is exactly where it is answered wrongly.",
            "strict-order",
        ]
    lines.append(f"server={XRAY_DNS_LISTEN}#{XRAY_DNS_PORT}")
    if routing.get("is_direct_fallback_enabled", False):
        direct = direct_resolvers(routing, network_resolvers)
        lines += [f"server={entry['address']}#{entry['port']}" for entry in direct]
    lines.append("")
    return lines


class XrayNftPart:
    """The chains and rules of the ruleset that divert traffic into xray.

    Three independent scopes: the networks the box serves, the overlay
    members using it as their exit node, and the box itself. None implies
    another, so a server can proxy its own traffic while forwarding nobody's.
    """

    def __init__(
        self,
        *,
        routing: dict,
        xray_uid: int,
        lan_devices: list,
        exposed_overlay_devices: list,
        engine_cgroups: list,
    ):
        """
        Args:
            routing: Parsed ``config/xray/routing.json``; only the three scope
                switches are read here.
            xray_uid: Numeric uid the xray service runs as. Traffic from this
                uid is never diverted, which is what stops the proxy from
                looping into itself.
            lan_devices: The served networks' devices.
            exposed_overlay_devices: The exposed overlays' devices.
            engine_cgroups: The overlay engines' cgroups present now, each a
                path under the cgroup root. Their packets leave directly while
                the local proxy is on.
        """
        self._lans = list(lan_devices)
        self._exposed_overlays = list(exposed_overlay_devices)
        self._is_lan_proxy_enabled = routing.get("is_proxy_enabled", True)
        self._is_overlay_proxy_enabled = routing.get("is_overlay_proxy_enabled", False)
        self._is_local_proxy_enabled = routing.get("is_local_proxy_enabled", False)
        self._xray_uid = xray_uid
        self._engine_cgroups = list(engine_cgroups)

    def prerouting(self, interface_set) -> str:
        """The ``prerouting`` chain, which diverts into the TPROXY socket.

        Args:
            interface_set: Renders a list of interface names as an nft set.

        Returns:
            The chain's text.
        """
        target = f"{XRAY_TPROXY_LISTEN}:{XRAY_TPROXY_PORT}"
        lines = [
            "    chain prerouting {",
            "        # One step after mangle: an overlay daemon marks every new",
            "        # connection from a network it routes at mangle itself, and two",
            "        # chains at one priority run in the order they were registered,",
            "        # which either reload changes. Running later keeps the mark the",
            "        # policy route looks for on the diverted packet.",
            "        type filter hook prerouting priority mangle + 1; policy accept;",
            "",
            "        # Packets of an established transparent session: mark for local",
            "        # delivery and let the existing socket pick them up.",
            "        meta l4proto { tcp, udp } socket transparent 1 "
            f"meta mark set {hex(ROUTER_FWMARK_TPROXY)} accept",
            "",
        ]
        if self._is_local_proxy_enabled:
            lines += [
                "        # Gateway-originated traffic looped back by the output chain.",
                f'        iifname "lo" meta mark {hex(ROUTER_FWMARK_TPROXY)} '
                "meta l4proto { tcp, udp } "
                f"tproxy ip to {target} accept",
                "",
            ]
        diverted = self.diverted_interfaces
        if not diverted:
            lines += [
                "        # Nothing forwarded is sent to the proxy: it is forwarded",
                "        # and masqueraded like any router's.",
                "    }\n",
            ]
            return "\n".join(lines)
        lines += [
            "        # Everything below is forwarded traffic being proxied: the",
            "        # served networks, and the overlays whose members exit here.",
            f"        iifname != {interface_set(diverted)} return",
            "        ip daddr @reserved_v4 return",
            "        meta l4proto { tcp, udp } "
            f"tproxy ip to {target} meta mark set {hex(ROUTER_FWMARK_TPROXY)} accept",
            "    }\n",
        ]
        return "\n".join(lines)

    def output(self) -> str:
        """The ``output`` chain, which loops the box's own traffic back to TPROXY.

        Returns:
            The chain's text; an empty chain while the local proxy is off.
        """
        if not self._is_local_proxy_enabled:
            return (
                "    # Local proxy is off: the gateway's own traffic leaves directly.\n"
                "    chain output {\n"
                "        type route hook output priority mangle; policy accept;\n"
                "    }\n"
            )
        return "\n".join(
            [
                "    chain output {",
                "        type route hook output priority mangle; policy accept;",
                "",
                "        # Anti-loop: xray's own egress must never re-enter the proxy.",
                f"        meta skuid {self._xray_uid} return",
                f"        meta mark {hex(ROUTER_FWMARK_XRAY_EGRESS)} return",
                "        ip daddr @reserved_v4 return",
                "",
                *self._engine_accepts(),
                "        # Mark the rest; the fwmark rule reroutes it to lo for TPROXY.",
                "        meta l4proto { tcp, udp } "
                f"meta mark set {hex(ROUTER_FWMARK_TPROXY)}",
                "    }\n",
            ]
        )

    def input_lines(self) -> list:
        """The ``input`` chain's accept for what TPROXY diverted.

        Returns:
            The lines; empty while nothing forwarded is diverted.
        """
        if not self.diverted_interfaces:
            return []
        return [
            "        # What TPROXY diverted is xray's to take, from any served",
            "        # network, exposed or not: the mark is set on the way in",
            "        # and on nothing else.",
            f"        meta mark {hex(ROUTER_FWMARK_TPROXY)} accept",
        ]

    @property
    def diverted_interfaces(self) -> list[str]:
        """The interfaces whose forwarded traffic the proxy takes."""
        names = []
        if self._is_lan_proxy_enabled:
            names += self._lans
        if self._is_overlay_proxy_enabled:
            names += self._exposed_overlays
        return names

    def _engine_accepts(self) -> list:
        """The output chain's accepts for the hub's own overlay engines.

        Returns:
            One line per engine cgroup and a blank line after them; empty
            when no engine cgroup is present.
        """
        if not self._engine_cgroups:
            return []
        lines = ["        # The hub's own overlay engines reach their peers directly."]
        for path in self._engine_cgroups:
            level = len(path.strip("/").split("/"))
            lines.append(f'        socket cgroupv2 level {level} "{path}" accept')
        return lines + [""]
