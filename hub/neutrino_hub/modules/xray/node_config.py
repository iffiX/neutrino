"""The node list: typed access to ``config/xray/nodes.json`` and link import.

A node is one JustMySocks (or compatible) server reachable by one protocol.
Share links are parsed here so the installer and the panel import them the same
way.
"""

import base64
import binascii
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from neutrino_hub.modules.xray.constants import (
    XRAY_BALANCER_STRATEGIES,
    XRAY_NODE_TAG_PREFIX,
)

SHADOWSOCKS_PROTOCOL = "shadowsocks"
VLESS_PROTOCOL = "vless"


def parse_share_link(link: str) -> "XrayNodeConfig":
    """Parse one ``ss://`` or ``vless://`` share link into a node.

    Args:
        link: A share link as copied from the provider's dashboard.

    Returns:
        The parsed node, with ``id`` derived from the server hostname.

    Raises:
        ValueError: If the scheme is unsupported or the link is malformed.
    """
    link = link.strip()
    if link.startswith("ss://"):
        return _parse_shadowsocks_link(link)
    if link.startswith("vless://"):
        return _parse_vless_link(link)
    raise ValueError(f"unsupported share link scheme: {link[:16]!r}")


@dataclass
class XrayRealitySettings:
    """Reality handshake parameters of a VLESS node.

    Attributes:
        public_key: The ``pbk`` parameter.
        short_id: The ``sid`` parameter.
        server_name: The ``sni`` parameter presented in the handshake.
        fingerprint: The TLS fingerprint to imitate, for example ``chrome``.
    """

    public_key: str
    short_id: str
    server_name: str
    fingerprint: str

    @classmethod
    def from_dict(cls, data: dict) -> "XrayRealitySettings":
        """Build from the parsed JSON block.

        Args:
            data: The ``reality`` object of a node.

        Returns:
            The parsed settings.
        """
        return cls(
            public_key=data["public_key"],
            short_id=data["short_id"],
            server_name=data["server_name"],
            fingerprint=data.get("fingerprint", "chrome"),
        )

    def to_dict(self) -> dict:
        """Serialize back to the ``config/`` shape.

        Returns:
            A JSON-ready object.
        """
        return {
            "public_key": self.public_key,
            "short_id": self.short_id,
            "server_name": self.server_name,
            "fingerprint": self.fingerprint,
        }


@dataclass
class XrayNodeConfig:
    """One proxy server the balancer can select.

    Attributes:
        id: Stable identifier used in the outbound tag and the panel.
        name: Human-readable label.
        address: Server hostname or address.
        is_enabled: Disabled nodes are left out of the rendered config.
        protocol: Either ``shadowsocks`` or ``vless``.
        port: Server port for the active protocol.
        method: Shadowsocks cipher, when the protocol is Shadowsocks.
        password: Shadowsocks password, when the protocol is Shadowsocks.
        uuid: VLESS user id, when the protocol is VLESS.
        flow: VLESS flow control, normally ``xtls-rprx-vision``.
        reality: Reality parameters, when the VLESS node uses Reality.
    """

    id: str
    name: str
    address: str
    is_enabled: bool
    protocol: str
    port: int
    method: str | None = None
    password: str | None = None
    uuid: str | None = None
    flow: str | None = None
    reality: XrayRealitySettings | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "XrayNodeConfig":
        """Build one node from its ``config/xray/nodes.json`` entry.

        Args:
            data: One element of the ``nodes`` array.

        Returns:
            The parsed node.

        Raises:
            ValueError: If the protocol is unknown or its block is missing.
        """
        protocol = data["protocol"]
        common = {
            "id": data["id"],
            "name": data.get("name", data["id"]),
            "address": data["address"],
            "is_enabled": data.get("is_enabled", True),
            "protocol": protocol,
        }
        if protocol == SHADOWSOCKS_PROTOCOL:
            block = data.get(SHADOWSOCKS_PROTOCOL)
            if not block:
                raise ValueError(f"node {data['id']!r} has no shadowsocks block")
            return cls(
                **common,
                port=block["port"],
                method=block["method"],
                password=block["password"],
            )
        if protocol == VLESS_PROTOCOL:
            block = data.get(VLESS_PROTOCOL)
            if not block:
                raise ValueError(f"node {data['id']!r} has no vless block")
            reality = block.get("reality")
            return cls(
                **common,
                port=block["port"],
                uuid=block["uuid"],
                flow=block.get("flow"),
                reality=XrayRealitySettings.from_dict(reality) if reality else None,
            )
        raise ValueError(f"node {data['id']!r} has unsupported protocol {protocol!r}")

    @property
    def tag(self) -> str:
        """Outbound tag for this node.

        The balancer selects by this prefix, so every node tag starts with it.
        """
        return f"{XRAY_NODE_TAG_PREFIX}{self.id}"

    @property
    def has_reality(self) -> bool:
        """Whether this node negotiates Reality."""
        return self.reality is not None

    def to_dict(self) -> dict:
        """Serialize back to the ``config/`` shape.

        Returns:
            A JSON-ready object matching ``nodes.json``.
        """
        data: dict = {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "is_enabled": self.is_enabled,
            "protocol": self.protocol,
        }
        if self.protocol == SHADOWSOCKS_PROTOCOL:
            data[SHADOWSOCKS_PROTOCOL] = {
                "port": self.port,
                "method": self.method,
                "password": self.password,
            }
        else:
            block: dict = {"port": self.port, "uuid": self.uuid}
            if self.flow:
                block["flow"] = self.flow
            if self.reality:
                block["reality"] = self.reality.to_dict()
            data[VLESS_PROTOCOL] = block
        return data


@dataclass
class XrayNodeList:
    """The whole node list plus the balancer settings.

    Attributes:
        nodes: Every configured node, enabled or not.
        strategy: Balancer strategy name.
        probe_url: URL the observatory fetches to measure latency.
        probe_interval_s: Seconds between observatory probes.
    """

    nodes: list[XrayNodeConfig]
    strategy: str
    probe_url: str
    probe_interval_s: int

    @classmethod
    def from_dict(cls, data: dict) -> "XrayNodeList":
        """Build from parsed ``config/xray/nodes.json``.

        Args:
            data: The whole parsed file.

        Returns:
            The parsed list.

        Raises:
            ValueError: If the balancer strategy is not one xray supports.
        """
        balancer = data.get("balancer", {})
        strategy = balancer.get("strategy", "leastPing")
        if strategy not in XRAY_BALANCER_STRATEGIES:
            raise ValueError(
                f"unknown balancer strategy {strategy!r}; "
                f"expected one of {', '.join(XRAY_BALANCER_STRATEGIES)}"
            )
        return cls(
            nodes=[XrayNodeConfig.from_dict(entry) for entry in data.get("nodes", [])],
            strategy=strategy,
            probe_url=balancer.get("probe_url", "https://www.gstatic.com/generate_204"),
            probe_interval_s=balancer.get("probe_interval_s", 60),
        )

    @property
    def enabled_nodes(self) -> list[XrayNodeConfig]:
        """Only the nodes that should appear in the rendered config."""
        return [node for node in self.nodes if node.is_enabled]

    @property
    def is_observatory_needed(self) -> bool:
        """Whether latency probing has to run for the chosen strategy."""
        return self.strategy == "leastPing"

    def to_dict(self) -> dict:
        """Serialize back to the ``config/`` shape.

        Returns:
            A JSON-ready object matching ``nodes.json``.
        """
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "balancer": {
                "strategy": self.strategy,
                "probe_url": self.probe_url,
                "probe_interval_s": self.probe_interval_s,
            },
        }


def _parse_shadowsocks_link(link: str) -> XrayNodeConfig:
    body, _, fragment = link[len("ss://") :].partition("#")
    name = unquote(fragment) if fragment else ""
    if "@" in body:
        credentials, _, host_part = body.rpartition("@")
        method, password = _decode_shadowsocks_credentials(credentials)
    else:
        decoded = _decode_base64(body)
        credentials, _, host_part = decoded.rpartition("@")
        method, _, password = credentials.partition(":")
    host, _, port = host_part.partition(":")
    if not host or not port:
        raise ValueError(f"shadowsocks link has no host:port: {link[:32]!r}")
    return XrayNodeConfig(
        id=_node_id_from_host(host),
        name=name or host,
        address=host,
        is_enabled=True,
        protocol=SHADOWSOCKS_PROTOCOL,
        port=int(port),
        method=method,
        password=password,
    )


def _parse_vless_link(link: str) -> XrayNodeConfig:
    parsed = urlparse(link)
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"vless link has no host:port: {link[:32]!r}")
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    reality = None
    if query.get("security") == "reality":
        reality = XrayRealitySettings(
            public_key=query.get("pbk", ""),
            short_id=query.get("sid", ""),
            server_name=query.get("sni", ""),
            fingerprint=query.get("fp", "chrome"),
        )
    name = unquote(parsed.fragment) if parsed.fragment else ""
    return XrayNodeConfig(
        id=_node_id_from_host(parsed.hostname),
        name=name or parsed.hostname,
        address=parsed.hostname,
        is_enabled=True,
        protocol=VLESS_PROTOCOL,
        port=parsed.port,
        uuid=unquote(parsed.username or ""),
        flow=query.get("flow"),
        reality=reality,
    )


def _decode_shadowsocks_credentials(credentials: str) -> tuple[str, str]:
    if ":" in credentials:
        method, _, password = credentials.partition(":")
        return method, password
    decoded = _decode_base64(credentials)
    method, _, password = decoded.partition(":")
    return method, password


def _decode_base64(text: str) -> str:
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ValueError(f"cannot decode base64 segment {text[:24]!r}") from error


def _node_id_from_host(host: str) -> str:
    return host.split(".")[0]
