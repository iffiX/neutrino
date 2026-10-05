"""Join a hub as a client, open one ``connect`` stream, and say what came back.

A tester runs this on any machine that reaches a hub's agent port, with a
client link made on the hub's Clients page. The link is read from a file or
from standard input, never from the command line, and never printed. The
probe joins, reads the services its state lists, opens ``connect`` to one
entry or to the hub's panel, and prints one JSON line. It leaves the hub
before it ends, which deletes the client row the link made.

    python3 connect_probe.py --link-file link.txt --list
    python3 connect_probe.py --link-file link.txt --entry gitea_<device id>
    python3 connect_probe.py --link-file link.txt --panel
    python3 connect_probe.py --link-file link.txt --entry samba_<id>_media --raw
    python3 connect_probe.py --link-file link.txt --entry podman_<id>_dns_53_udp --udp
    cat link.txt | python3 connect_probe.py --entry ai

Without ``--raw`` the probe sends ``GET / HTTP/1.1`` and reports the status
line of the answer. With ``--raw`` it sends nothing, since an SMB or a
RustDesk port answers only after the client speaks, and reports whether the
stream stayed open for two seconds and the first bytes the far end sent.
With ``--udp`` the entry is a UDP port: the probe sends one DNS query for
``--dns-name`` as a datagram from one source and reports the first datagram
that comes back to that source. A DNS server answers it, and an echo
service sends it back, so either proves the round trip.

Standard library only; the socket and the pinned TLS are the agent's own,
imported from ``agent/`` in this checkout or from an installed agent.
"""

import argparse
import base64
import glob
import json
import os
import platform
import queue
import socket
import sys
import threading
import time
import urllib.parse
import uuid
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
# Where the agent package is: the checkout beside this script, else the
# installed agent's own environment on a box.
AGENT_PACKAGE_PLACES = (
    os.path.join(HERE, "..", "..", "agent"),
    "/opt/neutrino/agent/python/lib/python3.*/site-packages",
    "/opt/neutrino_agent/python/lib/python3.*/site-packages",
)


def agent_package_place() -> str:
    """The first directory holding the ``neutrino_agent`` package, empty for none."""
    for pattern in AGENT_PACKAGE_PLACES:
        for place in sorted(glob.glob(pattern)):
            if os.path.isfile(os.path.join(place, "neutrino_agent", "__init__.py")):
                return place
    return ""


if agent_package_place():
    sys.path.append(agent_package_place())

from neutrino_agent.constants import AGENT_WS_PATH, PROTOCOL  # noqa: E402
from neutrino_agent.core.channel import BindingHttpClient  # noqa: E402
from neutrino_agent.core.ws_client import WebSocketClient  # noqa: E402
from neutrino_agent.exceptions import (  # noqa: E402
    GatewayUnreachable,
    GatewayUntrusted,
    SocketClosed,
)

LINK_PREFIX = "neutrino://enroll/"
CLIENT_ROLE = "client"
SOFTWARE = "neutrino_client/0.0.0+probe"
STREAM_ID = 1
CREDIT_BYTES = 1024 * 1024
STATE_TIMEOUT_S = 15.0
ANSWER_TIMEOUT_S = 15.0
RAW_WINDOW_S = 2.0
FIRST_BYTES_SHOWN = 64
HTTP_REQUEST = b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
# A UDP frame: the source port the datagram left from, big-endian, first.
UDP_SOURCE = 40001
UDP_SOURCE_BYTES = 2
DNS_QUERY_ID = 0x4E55
DNS_NAME_DEFAULT = "neutrino.invalid"


def read_link(path: str) -> str:
    """The link, from a file or from standard input when the path is ``-``."""
    if path == "-":
        return sys.stdin.read().strip()
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read().strip()


def parse_client_link(link: str) -> tuple:
    """``(urls, ticket, fingerprint)`` of a client link.

    Raises:
        ValueError: When the text is no link, or a link for another role.
    """
    text = link[len(LINK_PREFIX) :] if link.startswith(LINK_PREFIX) else link
    padded = text + "=" * (-len(text) % 4)
    payload = json.loads(zlib.decompress(base64.urlsafe_b64decode(padded.encode())))
    if payload.get("role") != CLIENT_ROLE:
        raise ValueError(f"link_not_for_client: {payload.get('role')!r}")
    urls = [str(url).rstrip("/") for url in payload.get("urls") or []]
    return urls, str(payload.get("token", "")), str(payload.get("fp", "")).lower()


def join(urls: list, ticket: str, fingerprint: str) -> tuple:
    """Spend the ticket at the first address that answers.

    Returns:
        ``(gateway_url, binding_id, token)``.

    Raises:
        GatewayUnreachable: When no address answered.
    """
    body = {
        "ticket": ticket,
        "role": CLIENT_ROLE,
        "protocol": PROTOCOL,
        "machine_id": uuid.uuid4().hex,
        "name": f"connect-probe-{socket.gethostname()}",
        "software": SOFTWARE,
        "platform": {"os": sys.platform, "family": "", "arch": platform.machine()},
    }
    last: Exception = GatewayUnreachable("the link names no address")
    for url in urls:
        try:
            answer = BindingHttpClient(gateway_url=url, fingerprint=fingerprint).join(
                body
            )
        except (GatewayUnreachable, GatewayUntrusted) as error:
            last = error
            continue
        return url, str(answer["id"]), str(answer["token"])
    raise last


class Channel:
    """The client's socket, read on a thread into a queue."""

    def __init__(self, gateway_url: str, fingerprint: str):
        parts = urllib.parse.urlsplit(gateway_url)
        self.client = WebSocketClient(
            host=parts.hostname or "",
            port=parts.port or 443,
            path=AGENT_WS_PATH,
            fingerprint=fingerprint,
        )
        self.inbound: queue.Queue = queue.Queue()

    def open(self, binding_id: str, token: str) -> dict:
        """Connect, say hello, and return the welcome."""
        self.client.connect()
        self.send(
            {
                "type": "hello",
                "protocol": PROTOCOL,
                "role": CLIENT_ROLE,
                "id": binding_id,
                "name": "connect-probe",
                "software": SOFTWARE,
                "token": token,
            }
        )
        kind, payload = self.client.recv()
        welcome = json.loads(payload) if kind == "text" else {}
        if welcome.get("type") != "welcome":
            raise GatewayUnreachable(f"refused: {welcome.get('code', kind)}")
        threading.Thread(target=self._read, daemon=True).start()
        return welcome

    def send(self, message: dict) -> None:
        self.client.send_text(json.dumps(message))

    def next(self, timeout: float):
        """The next message, ``("text", dict)`` or ``("binary", bytes)``, or None."""
        try:
            return self.inbound.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    def close(self) -> None:
        self.client.close()

    def _read(self) -> None:
        while True:
            try:
                kind, payload = self.client.recv()
            except (SocketClosed, GatewayUnreachable):
                self.inbound.put(("gone", None))
                return
            if kind == "text":
                self.inbound.put(("text", json.loads(payload)))
            else:
                self.inbound.put(("binary", bytes(payload)))


def take_state(channel: Channel) -> dict:
    """Ask for the whole state and return it."""
    channel.send(
        {
            "type": "report",
            "state_hash": "",
            "machine": {"hostname": socket.gethostname(), "platform": {}},
            "is_refresh": True,
        }
    )
    deadline = time.monotonic() + STATE_TIMEOUT_S
    while time.monotonic() < deadline:
        item = channel.next(deadline - time.monotonic())
        if item is None or item[0] == "gone":
            break
        if item[0] == "text" and item[1].get("type") == "state":
            return item[1]
        if item[0] == "text" and item[1].get("type") == "refused":
            raise GatewayUnreachable(f"refused: {item[1].get('code')}")
    raise GatewayUnreachable("no state arrived")


def probe(channel: Channel, open_args: dict, *, is_raw: bool) -> dict:
    """Open one ``connect`` stream and report what it carried."""
    channel.send({"type": "open", "stream": STREAM_ID, "kind": "connect", **open_args})
    channel.send({"type": "credit", "stream": STREAM_ID, "bytes": CREDIT_BYTES})
    if not is_raw:
        channel.client.send_bytes(STREAM_ID.to_bytes(4, "big") + HTTP_REQUEST)
    received = b""
    window = RAW_WINDOW_S if is_raw else ANSWER_TIMEOUT_S
    deadline = time.monotonic() + window
    close = None
    while time.monotonic() < deadline:
        item = channel.next(deadline - time.monotonic())
        if item is None:
            break
        kind, payload = item
        if kind == "gone":
            close = {"code": "socket_closed", "params": {}}
            break
        if kind == "binary" and int.from_bytes(payload[:4], "big") == STREAM_ID:
            data = payload[4:]
            received += data
            channel.send({"type": "credit", "stream": STREAM_ID, "bytes": len(data)})
            if not is_raw and b"\r\n" in received:
                break
            continue
        if kind == "text" and payload.get("stream") == STREAM_ID:
            if payload.get("type") == "close":
                close = {
                    "code": str(payload.get("code", "") or ""),
                    "params": payload.get("params") or {},
                }
                break
    result = {
        "bytes": len(received),
        "first_bytes": received[:FIRST_BYTES_SHOWN].decode("latin-1"),
    }
    if close is not None and close["code"]:
        return {**result, "ok": False, **close}
    if is_raw:
        return {
            **result,
            "ok": close is None,
            "stayed_open_s": RAW_WINDOW_S if close is None else 0,
        }
    status_line = received.split(b"\r\n", 1)[0].decode("latin-1")
    return {
        **result,
        "ok": status_line.startswith("HTTP/"),
        "status_line": status_line,
    }


def dns_query(name: str) -> bytes:
    """One DNS query for the name's A record, recursion asked."""
    header = DNS_QUERY_ID.to_bytes(2, "big") + bytes([1, 0, 0, 1, 0, 0, 0, 0, 0, 0])
    labels = b"".join(
        bytes([len(label)]) + label.encode("ascii")
        for label in name.strip(".").split(".")
        if label
    )
    return header + labels + b"\x00" + (1).to_bytes(2, "big") + (1).to_bytes(2, "big")


def probe_udp(channel: Channel, open_args: dict, *, name: str) -> dict:
    """Open one UDP ``connect`` stream, send one query, report the reply."""
    channel.send({"type": "open", "stream": STREAM_ID, "kind": "connect", **open_args})
    channel.send({"type": "credit", "stream": STREAM_ID, "bytes": CREDIT_BYTES})
    query = dns_query(name)
    channel.client.send_bytes(
        STREAM_ID.to_bytes(4, "big")
        + UDP_SOURCE.to_bytes(UDP_SOURCE_BYTES, "big")
        + query
    )
    deadline = time.monotonic() + ANSWER_TIMEOUT_S
    while time.monotonic() < deadline:
        item = channel.next(deadline - time.monotonic())
        if item is None:
            break
        kind, payload = item
        if kind == "gone":
            return {"ok": False, "code": "socket_closed", "params": {}}
        if kind == "binary" and int.from_bytes(payload[:4], "big") == STREAM_ID:
            frame = payload[4:]
            source = int.from_bytes(frame[:UDP_SOURCE_BYTES], "big")
            datagram = frame[UDP_SOURCE_BYTES:]
            channel.send({"type": "credit", "stream": STREAM_ID, "bytes": len(frame)})
            return {
                "ok": source == UDP_SOURCE and datagram[:2] == query[:2],
                "source": source,
                "bytes": len(datagram),
                "is_echo": datagram == query,
                "dns_rcode": datagram[3] & 0x0F if len(datagram) >= 4 else None,
            }
        if (
            kind == "text"
            and payload.get("stream") == STREAM_ID
            and payload.get("type") == "close"
        ):
            return {
                "ok": False,
                "code": str(payload.get("code", "") or ""),
                "params": payload.get("params") or {},
            }
    return {"ok": False, "code": "no_reply", "params": {}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--link-file", default="-", help="file holding the client link; - for stdin"
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--entry", help="the id of a services entry to connect to")
    target.add_argument("--panel", action="store_true", help="connect to the panel")
    target.add_argument("--list", action="store_true", help="only list the entries")
    parser.add_argument(
        "--raw", action="store_true", help="send nothing; report the first bytes"
    )
    parser.add_argument(
        "--udp", action="store_true", help="the entry is a UDP port; send one query"
    )
    parser.add_argument(
        "--dns-name", default=DNS_NAME_DEFAULT, help="the name --udp asks for"
    )
    arguments = parser.parse_args()
    report: dict = {"ok": False}
    try:
        urls, ticket, fingerprint = parse_client_link(read_link(arguments.link_file))
    except (OSError, ValueError, zlib.error) as error:
        print(json.dumps({"ok": False, "code": "link_unreadable", "error": str(error)}))
        return 2
    try:
        gateway_url, binding_id, token = join(urls, ticket, fingerprint)
    except (GatewayUnreachable, GatewayUntrusted) as error:
        print(json.dumps({"ok": False, "code": "join_failed", "error": str(error)}))
        return 1
    channel = Channel(gateway_url, fingerprint)
    try:
        channel.open(binding_id, token)
        state = take_state(channel)
        report = {
            "ok": True,
            "gateway_url": gateway_url,
            "reached_through": state.get("reached_through", ""),
            "is_panel_allowed": state.get("is_panel_allowed", False),
            "services": [
                {
                    "id": entry.get("id"),
                    "type": entry.get("type"),
                    "protocol": (entry.get("payload") or {}).get("protocol", ""),
                }
                for entry in state.get("services") or []
            ],
        }
        if arguments.entry or arguments.panel:
            open_args = (
                {"is_panel": True} if arguments.panel else {"id": arguments.entry}
            )
            report["target"] = "panel" if arguments.panel else arguments.entry
            if arguments.udp:
                report.update(probe_udp(channel, open_args, name=arguments.dns_name))
            else:
                report.update(probe(channel, open_args, is_raw=arguments.raw))
    except (GatewayUnreachable, GatewayUntrusted, SocketClosed, OSError) as error:
        report = {**report, "ok": False, "code": "channel_failed", "error": str(error)}
    finally:
        channel.close()
        try:
            BindingHttpClient(gateway_url=gateway_url, fingerprint=fingerprint).leave(
                binding_id, token
            )
        except (GatewayUnreachable, GatewayUntrusted):
            report["leave"] = "failed"
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
