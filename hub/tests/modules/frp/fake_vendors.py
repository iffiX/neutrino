"""SakuraFrp and OpenFrp as recorded answers, for the frp tests.

The answers follow the shapes each vendor documents: SakuraFrp's OpenAPI
schema at api.natfrp.com/docs and OpenFrp's OPENAPI guide. The transport
keeps every request it is handed, so a test reads back the headers and the
bodies, and answers ``ConnectionError`` for an address it does not know.
"""

import json

from neutrino_hub.modules.frp.constants import (
    FRP_OPENFRP_API,
    FRP_OPENFRP_LOGIN_POLL_URL,
    FRP_OPENFRP_LOGIN_REQUEST_URL,
    FRP_SAKURAFRP_API,
)
from neutrino_hub.modules.frp.vendor_api import FrpHttpAnswer

SAKURAFRP_KEY = "wdnmdtoken666666"  # scan: allow
OPENFRP_AUTHORIZATION = (
    "OPENFRPeyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.first"  # scan: allow
)

SAKURAFRP_NODES = {
    "233": {
        "name": "宁波电信",
        "host": "frp-a.natfrp.cloud",
        "description": "",
        "vip": 0,
        "flag": (1 << 2) | (1 << 3),
    },
    "234": {
        "name": "guarded",
        "host": "frp-b.natfrp.cloud",
        "description": "",
        "vip": 0,
        "flag": (1 << 2) | (1 << 3) | (1 << 8),
    },
    "235": {
        "name": "香港",
        "host": "frp-c.natfrp.cloud",
        "description": "",
        "vip": 0,
        "flag": 1 << 2,
    },
}


def sakurafrp_tunnel(tunnel_id: int, name: str, **fields) -> dict:
    """One tunnel as ``GET /v4/tunnels`` lists it."""
    tunnel = {
        "id": tunnel_id,
        "name": name,
        "type": "tcp",
        "node": 233,
        "online": False,
        "status": 0,
        "status_reason": None,
        "note": "",
        "extra": "",
        "remote": "41234",
        "local_ip": "127.0.0.1",
        "local_port": 8443,
        "export": "",
    }
    tunnel.update(fields)
    return tunnel


SAKURAFRP_TUNNELS = [
    sakurafrp_tunnel(114514, "neutrino"),
    sakurafrp_tunnel(114515, "web", type="http", remote="example.tld"),
    sakurafrp_tunnel(114516, "ssh", local_port=22, remote="41235"),
    sakurafrp_tunnel(114517, "guarded", node=234, remote="41236"),
    sakurafrp_tunnel(114518, "hk", node=235, remote="41237"),
    sakurafrp_tunnel(114519, "game", type="udp", remote="41238"),
]

# What POST /v4/tunnel/config answers for upstream frpc, with every part a
# vendor's text may hold that the hub leaves out.
SAKURAFRP_CONFIG = """serverAddr = "frp-a.natfrp.cloud"
serverPort = 7001
user = "a1b2c3d4.neutrino"
includes = ["/etc/frp/extra.toml"]
webServer.addr = "0.0.0.0"
webServer.port = 7400

[auth]
method = "token"
token = "SakuraFrpNodeToken"  # scan: allow

[metadatas]
sakura = "neutrino"

[transport]
protocol = "tcp"
tls.enable = true
heartbeatInterval = 30

[[proxies]]
name = "neutrino"
type = "tcp"
localIP = "192.168.1.9"
localPort = 8443
remotePort = 41234
transport.useEncryption = true
metadatas.tunnel = "114514"

[proxies.plugin]
type = "static_file"
localPath = "/"

[[proxies]]
name = "other"
type = "tcp"
localPort = 22
remotePort = 41299

[[visitors]]
name = "visitor"
type = "stcp"
serverName = "secret"
"""

OPENFRP_NODES = [
    {
        "id": 41,
        "name": "重庆联通-2",
        "hostname": "cn-cq-plc-1.of-7af93c01.shop",
        "port": 8120,
        "classify": 1,
        "group": "normal;vip;svip",
        "needRealname": True,
        "status": 200,
    },
    {
        "id": 6,
        "name": "日本-1",
        "hostname": "jp-1.of-7af93c01.shop",
        "port": 8121,
        "classify": 3,
        "group": "normal;vip",
        "needRealname": False,
        "status": 200,
    },
    {
        "id": 2,
        "name": "香港-2「BGP」",
        "hostname": "您无权查询此节点的地址",
        "port": "您无权查询此节点的地址",
        "classify": 2,
        "group": "vip;svip",
        "needRealname": True,
        "status": 200,
    },
]


def openfrp_proxy(proxy_id: int, name: str, **fields) -> dict:
    """One tunnel as ``getUserProxies`` lists it."""
    proxy = {
        "autoTls": "false",
        "connectAddress": "cn-cq-plc-1.of-7af93c01.shop:51607",
        "forceHttps": False,
        "friendlyNode": "重庆联通-2",
        "id": proxy_id,
        "lastUpdate": 1687449600900,
        "localIp": "127.0.0.1",
        "localPort": 8443,
        "nid": 41,
        "online": False,
        "proxyName": name,
        "proxyProtocolVersion": False,
        "proxyType": "tcp",
        "remotePort": 51607,
        "status": True,
        "uid": 19198,
        "useCompression": False,
        "useEncryption": False,
        "lastLogin": None,
    }
    proxy.update(fields)
    return proxy


OPENFRP_PROXIES = [
    openfrp_proxy(120623, "neutrino"),
    openfrp_proxy(120624, "tls", autoTls="true"),
    openfrp_proxy(120625, "named_cert", autoTls="example.pem"),
    openfrp_proxy(120626, "mc", localPort=25565),
    openfrp_proxy(
        120627,
        "tokyo",
        nid=6,
        friendlyNode="日本-1",
        connectAddress="jp-1.of-7af93c01.shop:40001",
    ),
    openfrp_proxy(32933, "homo_web", proxyType="https", connectAddress="homo.com"),
]

OPENFRP_NODE_CONFIG = """serverAddr = "cn-cq-plc-1.of-7af93c01.shop"
serverPort = 8120
user = "e900d8f2498202114ec2e9b0597dfb66"  # scan: allow

[metadatas]
token = "e900d8f2498202114ec2e9b0597dfb66"  # scan: allow

[[proxies]]
name = "mc"
type = "tcp"
localIP = "127.0.0.1"
localPort = 25565
remotePort = 51608

[[proxies]]
name = "neutrino"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8443
remotePort = 51607
"""


def answer(body, *, status: int = 200, headers: "dict | None" = None):
    """One recorded answer, a JSON body unless given as bytes or text."""
    if isinstance(body, bytes):
        data = body
    elif isinstance(body, str):
        data = body.encode()
    else:
        data = json.dumps(body, ensure_ascii=False).encode()
    return FrpHttpAnswer(status=status, headers=dict(headers or {}), body=data)


def openfrp_answer(data, **keywords):
    """An OpenFrp API answer: ``{data, flag, msg}``."""
    return answer({"data": data, "flag": True, "msg": "OK"}, **keywords)


class FakeVendors:
    """Both vendors behind one transport, answering from recorded bodies.

    Attributes:
        requests: Every ``(method, url, headers, body)`` handed over.
        answers: ``(method, url)`` to an answer, a list of answers taken in
            turn, or a callable taking the request.
    """

    def __init__(self):
        self.requests: list = []
        self.answers: dict = {
            ("GET", f"{FRP_SAKURAFRP_API}/user/info"): answer(
                {"id": 10, "name": "DemoUser", "token": SAKURAFRP_KEY}
            ),
            ("GET", f"{FRP_SAKURAFRP_API}/tunnels"): answer(SAKURAFRP_TUNNELS),
            ("GET", f"{FRP_SAKURAFRP_API}/nodes"): answer(SAKURAFRP_NODES),
            ("POST", f"{FRP_SAKURAFRP_API}/tunnel/config"): answer(SAKURAFRP_CONFIG),
            ("POST", f"{FRP_OPENFRP_API}/getUserProxies"): openfrp_answer(
                {"total": len(OPENFRP_PROXIES), "list": OPENFRP_PROXIES}
            ),
            ("POST", f"{FRP_OPENFRP_API}/getNodeList"): openfrp_answer(
                {"total": len(OPENFRP_NODES), "list": OPENFRP_NODES}
            ),
            ("POST", f"{FRP_OPENFRP_API}/getNodeConf"): openfrp_answer(
                OPENFRP_NODE_CONFIG
            ),
            ("POST", FRP_OPENFRP_LOGIN_REQUEST_URL): answer(
                {
                    "code": 200,
                    "msg": "query ok",
                    "data": {
                        "authorization_url": (
                            "https://console.openfrp.net/usercenter?argoaccess=9a23"
                        ),
                        "request_uuid": "9a23ed00-07e6-4f11-bcfd-b0216e3bcacf",
                    },
                }
            ),
            ("GET", FRP_OPENFRP_LOGIN_POLL_URL): answer(b"", status=204),
        }

    def __call__(self, method: str, url: str, *, headers: dict, body):
        self.requests.append((method, url, dict(headers), body))
        held = self.answers.get((method, url.split("?", 1)[0]))
        if held is None:
            raise ConnectionError(f"no route to {url}")
        if isinstance(held, list):
            return held.pop(0) if len(held) > 1 else held[0]
        if callable(held):
            return held(method, url, headers, body)
        return held

    def urls(self) -> list:
        """The addresses asked, in order, without their queries."""
        return [url.split("?", 1)[0] for _, url, _, _ in self.requests]
