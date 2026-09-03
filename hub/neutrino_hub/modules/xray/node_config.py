"""The node list: typed access to ``config/xray/nodes.json`` and link import.

A node is one JustMySocks (or compatible) server reachable by one protocol.
Share links are parsed here so the installer and the panel import them the
same way. The file itself holds no secret: a node's password or user id is a
``secret_id`` reference into the credential vault, sealed at import and
resolved only at render time. A freshly parsed link carries its material in
memory until the importer seals it.
"""

import base64
import binascii
import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from neutrino_hub.modules.xray.constants import (
    XRAY_NODE_ID_DIGEST,
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
        secret_id: The vault ``token`` object holding the node's secret —
            the Shadowsocks password or the VLESS user id. What is stored.
        method: Shadowsocks cipher, when the protocol is Shadowsocks.
        password: Shadowsocks password, in memory only: set by the link
            parser and by resolution, never serialized.
        uuid: VLESS user id, in memory only, on the same terms.
        flow: VLESS flow control, normally ``xtls-rprx-vision``.
        reality: Reality parameters, when the VLESS node uses Reality.
    """

    id: str
    name: str
    address: str
    is_enabled: bool
    protocol: str
    port: int
    secret_id: str | None = None
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
            "secret_id": data.get("secret_id") or None,
        }
        if protocol == SHADOWSOCKS_PROTOCOL:
            block = data.get(SHADOWSOCKS_PROTOCOL)
            if not block:
                raise ValueError(f"node {data['id']!r} has no shadowsocks block")
            return cls(
                **common,
                port=block["port"],
                method=block["method"],
            )
        if protocol == VLESS_PROTOCOL:
            block = data.get(VLESS_PROTOCOL)
            if not block:
                raise ValueError(f"node {data['id']!r} has no vless block")
            reality = block.get("reality")
            return cls(
                **common,
                port=block["port"],
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

    @property
    def has_secret_material(self) -> bool:
        """Whether the node's secret is in memory, ready to render.

        False for a stored node until resolution opens its reference — and
        for one whose reference dangles, which is what excludes it from the
        rendered config the way a disabled node is excluded.
        """
        if self.protocol == SHADOWSOCKS_PROTOCOL:
            return bool(self.password)
        return bool(self.uuid)

    def to_dict(self) -> dict:
        """Serialize back to the ``config/`` shape, material left out.

        Returns:
            A JSON-ready object matching ``nodes.json``.
        """
        data: dict = {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "is_enabled": self.is_enabled,
            "protocol": self.protocol,
            "secret_id": self.secret_id,
        }
        if self.protocol == SHADOWSOCKS_PROTOCOL:
            data[SHADOWSOCKS_PROTOCOL] = {
                "port": self.port,
                "method": self.method,
            }
        else:
            block: dict = {"port": self.port}
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
        id=_node_id_from_host(host, int(port)),
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
        id=_node_id_from_host(parsed.hostname, parsed.port),
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


def _node_id_from_host(host: str, port: int) -> str:
    """A stable identifier for one server, unique to its address and port.

    The first label of a hostname alone is not one: every node a provider
    hands out by address shares it — `203.0.113.10` and `203.0.113.11` both
    read as `203` — and the second of them is refused as a duplicate of the
    first. Two hostnames under different domains collide the same way.

    A digest of the address and port settles it, and re-adding the same link
    still lands on the same id, which is what makes adding a node twice a
    thing the panel can refuse. The label is kept in front where the address
    is a name, so the id is still something a person can recognise.

    Args:
        host: The server's hostname or address.
        port: The port it is reached on.

    Returns:
        The node's id.
    """
    digest = hashlib.sha256(f"{host}:{port}".encode()).hexdigest()[:XRAY_NODE_ID_DIGEST]
    label = host.split(".")[0]
    return digest if label.isdigit() else f"{label}_{digest}"
