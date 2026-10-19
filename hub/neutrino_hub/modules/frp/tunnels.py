"""Which of an account's tunnels the hub lists, and where each one is.

A tunnel is listed when it is TCP and its local port at the vendor is the
connection port; at OpenFrp its auto TLS is off as well, and at SakuraFrp
its node does not force access authentication.

Pure: the vendor's answers in, rows out.
"""

from dataclasses import dataclass

from neutrino_hub.modules.frp.constants import (
    FRP_OPENFRP_REGIONS,
    FRP_REGION_MAINLAND,
    FRP_REGION_OUTSIDE_MAINLAND,
    FRP_SAKURAFRP_FLAG_FORCED_AUTH,
    FRP_SAKURAFRP_FLAG_MAINLAND,
    FRP_TUNNEL_TYPE,
)


@dataclass(frozen=True)
class FrpTunnel:
    """One listed tunnel.

    Attributes:
        tunnel_id: The vendor's id, as text.
        name: The tunnel's name, which its proxy in frpc's file carries.
        node_id: The vendor's id of its node, as text.
        node_name: The node's name.
        region: ``mainland``, ``hk_mo_tw``, ``abroad`` or
            ``outside_mainland``.
        local_port: Its local port at the vendor.
        public_host: The host of its public address.
        public_port: The port of its public address.
        dial_host: Where the hub dials the node to time it; empty when the
            vendor does not say.
        dial_port: The port it dials there; 0 when not known yet.
    """

    tunnel_id: str
    name: str
    node_id: str
    node_name: str
    region: str
    local_port: int
    public_host: str
    public_port: int
    dial_host: str = ""
    dial_port: int = 0


def sakurafrp_tunnels(tunnels: list, nodes: dict, *, agent_port: int) -> list:
    """The SakuraFrp tunnels the hub lists, before their configs are read.

    Args:
        tunnels: ``GET /v4/tunnels``.
        nodes: ``GET /v4/nodes``, node id to node.
        agent_port: The connection port.

    Returns:
        :class:`FrpTunnel` rows in the vendor's order, ``dial_port`` 0 until
        the tunnel's config names the server port.
    """
    rows = []
    for tunnel in tunnels:
        if not isinstance(tunnel, dict):
            continue
        node = nodes.get(str(tunnel.get("node")))
        if not isinstance(node, dict):
            continue
        flag = _number(node.get("flag"))
        if (
            tunnel.get("type") != FRP_TUNNEL_TYPE
            or _number(tunnel.get("local_port")) != agent_port
            or flag & FRP_SAKURAFRP_FLAG_FORCED_AUTH
        ):
            continue
        host = str(node.get("host") or "")
        rows.append(
            FrpTunnel(
                tunnel_id=str(tunnel.get("id")),
                name=str(tunnel.get("name") or ""),
                node_id=str(tunnel.get("node")),
                node_name=str(node.get("name") or ""),
                region=(
                    FRP_REGION_MAINLAND
                    if flag & FRP_SAKURAFRP_FLAG_MAINLAND
                    else FRP_REGION_OUTSIDE_MAINLAND
                ),
                local_port=agent_port,
                public_host=host,
                public_port=_number(tunnel.get("remote")),
                dial_host=host,
            )
        )
    return rows


def openfrp_tunnels(proxies: list, nodes: list, *, agent_port: int) -> list:
    """The OpenFrp tunnels the hub lists.

    Args:
        proxies: ``getUserProxies``'s ``data.list``.
        nodes: ``getNodeList``'s ``data.list``.
        agent_port: The connection port.

    Returns:
        :class:`FrpTunnel` rows in the vendor's order. A row's public
        address is ``connectAddress`` split at its last colon, and its node
        is dialled at the node's ``hostname`` and ``port``.
    """
    by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
    rows = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        if (
            proxy.get("proxyType") != FRP_TUNNEL_TYPE
            or _number(proxy.get("localPort")) != agent_port
            or _is_true(proxy.get("autoTls"))
        ):
            continue
        node = by_id.get(str(proxy.get("nid")), {})
        host, _, port = str(proxy.get("connectAddress") or "").rpartition(":")
        rows.append(
            FrpTunnel(
                tunnel_id=str(proxy.get("id")),
                name=str(proxy.get("proxyName") or ""),
                node_id=str(proxy.get("nid")),
                node_name=str(node.get("name") or proxy.get("friendlyNode") or ""),
                region=FRP_OPENFRP_REGIONS.get(
                    _number(node.get("classify")), FRP_REGION_OUTSIDE_MAINLAND
                ),
                local_port=agent_port,
                public_host=host.strip("[]"),
                public_port=_number(port),
                dial_host=str(node.get("hostname") or ""),
                dial_port=_number(node.get("port")),
            )
        )
    return rows


def _number(value) -> int:
    """A vendor's number, given as a number or as text; 0 for anything else."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_true(value) -> bool:
    """Whether a vendor's flag is on: OpenFrp writes ``autoTls`` as text,
    ``"false"`` or a certificate's name, and some answers as a bool."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false")
    return bool(value)
