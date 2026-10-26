"""Join a hub as a client through a transport, open one ``connect`` stream, and say what came back.

A tester runs this on any machine that reaches a hub's agent port and has
the agent package, with a client link made on the hub's Clients page. The
link is read from a file or from standard input, never from the command
line, and never printed. The probe starts a ``neutrino_transport`` of its
own, joins through it, dials, reads the services its state lists, opens
``connect`` to one entry or to the hub's panel, and prints one JSON line.
It leaves the hub before it ends, which deletes the client row the link
made.

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

Standard library only; the local channel and the transport program are the
agent's own, imported from ``agent/`` in this checkout or from an installed
agent, whose ``bin`` holds the program. ``NEUTRINO_TRANSPORT_BIN`` names
another program.
"""

import argparse
import base64
import binascii
import functools
import glob
import json
import os
import queue
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
# Where the agent package is: the checkout beside this script, else the
# installed agent's own environment on a box.
AGENT_PACKAGE_PLACES = (
    os.path.join(HERE, "..", "..", "agent"),
    "/opt/neutrino/agent/python/lib/python3.*/site-packages",
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

from neutrino_agent.constants import PROTOCOL  # noqa: E402
from neutrino_agent.core.enrollment import clean_urls, psk_of  # noqa: E402
from neutrino_agent.core.static_key import make_private_key  # noqa: E402
from neutrino_agent.exceptions import GatewayUnreachable  # noqa: E402
from neutrino_agent.platforms.detect import (  # noqa: E402
    detect_platform,
    platform_tuple,
)
from neutrino_agent.transport.connection import open_local  # noqa: E402
from neutrino_agent.transport.constants import (  # noqa: E402
    TRANSPORT_JOIN_TIMEOUT_S,
    TRANSPORT_OP_OPEN,
    TRANSPORT_RECORD_BYTES_MAX,
    TRANSPORT_RECORD_DATA,
    TRANSPORT_RECORD_DATAGRAM,
    TRANSPORT_RECORD_EOF,
)
from neutrino_agent.transport.control import (  # noqa: E402
    TransportControlClient,
    encode_line,
)
from neutrino_agent.transport.process import (  # noqa: E402
    TransportProcess,
    program_path,
)
from neutrino_agent.transport.records import (  # noqa: E402
    RECORD_HEAD,
    decode_item,
    encode_record,
)

LINK_PREFIX = "neutrino://enroll/"
CLIENT_ROLE = "client"
SOFTWARE = "neutrino_client/0.0.0+probe"
SESSION_TIMEOUT_S = 30.0
WELCOME_TIMEOUT_S = 15.0
STATE_TIMEOUT_S = 15.0
ANSWER_TIMEOUT_S = 15.0
RAW_WINDOW_S = 2.0
FIRST_BYTES_SHOWN = 64
HTTP_REQUEST = b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
# A UDP record: the source port the datagram left from, big-endian, first.
UDP_SOURCE = 40001
UDP_SOURCE_BYTES = 2
DNS_QUERY_ID = 0x4E55
DNS_NAME_DEFAULT = "neutrino.invalid"
# Where the probe's transport listens: a directory of this process's own.
LISTENER_NAME = "transport.sock"


def read_link(path: str) -> str:
    """The link, from a file or from standard input when the path is ``-``."""
    if path == "-":
        return sys.stdin.read().strip()
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read().strip()


def parse_client_link(link: str) -> tuple:
    """``(addresses, ticket, hub_key)`` of a client link.

    Raises:
        ValueError: When the text is no link, a link for another role, or
            one with no address, ticket or key.
    """
    text = link.strip()
    text = text[len(LINK_PREFIX) :] if text.startswith(LINK_PREFIX) else text
    try:
        padded = text + "=" * (-len(text) % 4)
        payload = json.loads(zlib.decompress(base64.urlsafe_b64decode(padded.encode())))
    except (binascii.Error, zlib.error, UnicodeDecodeError) as error:
        raise ValueError(f"link_unreadable: {error}") from error
    if payload.get("role") != CLIENT_ROLE:
        raise ValueError(f"link_not_for_client: {payload.get('role')!r}")
    addresses = clean_urls(payload.get("urls"))
    ticket = str(payload.get("token", ""))
    hub_key = str(payload.get("key", "")).strip().lower()
    if not addresses or not ticket or not hub_key:
        raise ValueError("link_incomplete: no address, ticket or key")
    return addresses, ticket, hub_key


class Stream:
    """One stream on the hub's session, on a local connection of its own.

    The far side's answer to the ``open`` is the first record; after an
    ``accept`` a TCP ``connect`` carries raw bytes, and every other stream
    carries records. Both are read on a thread into a queue.
    """

    def __init__(self, connection):
        self._connection = connection
        self.inbound: queue.Queue = queue.Queue()
        self.answer = self._read_record()

    @property
    def is_accepted(self) -> bool:
        return self.answer[0] == "accept"

    def close_of_answer(self) -> dict:
        """The refusing close as ``{code, params}``; empty for an accept."""
        if self.answer[0] != "close":
            return {}
        return {"code": self.answer[1], "params": self.answer[2]}

    def start_raw(self) -> None:
        """Read raw bytes, as a TCP ``connect`` carries them after its accept."""
        threading.Thread(target=self._read_raw, daemon=True).start()

    def start_records(self) -> None:
        """Read records, as every other stream carries them."""
        threading.Thread(target=self._read_records, daemon=True).start()

    def send_raw(self, data: bytes) -> None:
        self._connection.sendall(data)

    def send_record(self, kind: int, payload: bytes = b"") -> None:
        self._connection.sendall(encode_record(kind, payload))

    def next(self, timeout: float):
        """The next item, or None after ``timeout`` seconds.

        An item is ``("bytes", data)`` on a raw stream; ``("data", bytes)``,
        ``("stderr", bytes)``, ``("eof",)``, ``("datagram", bytes)`` or
        ``("close", code, params)`` on a record stream; ``("gone",)`` once the
        connection ended.
        """
        try:
            return self.inbound.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    def close(self) -> None:
        self._connection.close()

    def _read_exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self._connection.recv(size - len(data))
            if not chunk:
                raise ConnectionError("the stream's connection ended")
            data += chunk
        return data

    def _read_record(self) -> tuple:
        try:
            kind, length = RECORD_HEAD.unpack(self._read_exact(RECORD_HEAD.size))
            payload = self._read_exact(length) if length else b""
        except (OSError, ConnectionError) as error:
            return ("close", "stream_closed", {"detail": str(error)})
        if kind == TRANSPORT_RECORD_DATAGRAM:
            return ("datagram", payload)
        item = decode_item(kind, payload)
        if item is None:
            return ("close", "record_unknown", {"kind": kind})
        return item

    def _read_raw(self) -> None:
        while True:
            try:
                data = self._connection.recv(TRANSPORT_RECORD_BYTES_MAX)
            except OSError:
                data = b""
            if not data:
                self.inbound.put(("gone",))
                return
            self.inbound.put(("bytes", data))

    def _read_records(self) -> None:
        while True:
            item = self._read_record()
            self.inbound.put(item)
            if item[0] == "close":
                self.inbound.put(("gone",))
                return


class Client:
    """A client of one hub: a transport of this process's own, joined and dialled."""

    def __init__(self, log=None):
        self._log = log or (lambda line: None)
        self._platform = detect_platform()
        self._directory = tempfile.mkdtemp(prefix="neutrino_probe_")
        os.chmod(self._directory, 0o700)
        self._process = TransportProcess(
            program=program_path(self._platform),
            listen=os.path.join(self._directory, LISTENER_NAME),
            log=self._log,
        )
        self._control = None
        self.events: queue.Queue = queue.Queue()
        self.frames: queue.Queue = queue.Queue()
        self.private_key = make_private_key()
        self.hub_key = ""
        self.addresses: list = []
        self.binding_id = ""
        self.token = ""

    def start(self) -> None:
        """Start the transport and open its control connection.

        Raises:
            OSError: When the program cannot start or does not answer.
        """
        self._process.start()
        self._control = TransportControlClient(
            connect=functools.partial(open_local, self._process.listen),
            secret=self._process.secret,
            on_event=self.events.put,
            on_frame=self.frames.put,
            on_question=self._refuse_question,
            log=self._log,
        )
        self._control.start()

    def join(self, addresses: list, ticket: str, hub_key: str) -> None:
        """Spend the ticket through the transport and keep the binding.

        Raises:
            GatewayUnreachable: When the transport or the hub refused, with
                the code in the message.
        """
        self.addresses = list(addresses)
        self.hub_key = hub_key
        answer = self._control.command(
            "join",
            timeout_s=TRANSPORT_JOIN_TIMEOUT_S,
            hub_key=hub_key,
            private_key=self.private_key,
            addresses=self.addresses,
            ticket=ticket,
            role=CLIENT_ROLE,
            protocol=PROTOCOL,
            machine_id=uuid.uuid4().hex,
            name=f"connect-probe-{socket.gethostname()}",
            software=SOFTWARE,
            platform=platform_tuple(),
        )
        if answer.get("code"):
            raise GatewayUnreachable(
                f"refused: {answer['code']} {answer.get('params')}"
            )
        self.binding_id = str(answer.get("binding_id", "") or "")
        self.token = str(answer.get("token", "") or "")
        if not self.binding_id or not self.token:
            raise GatewayUnreachable("the hub sent no binding back")

    def dial(self) -> dict:
        """Dial the hub, say hello, and return the welcome.

        Returns:
            The ``welcome`` frame, with ``address``, the address the session
            reached.

        Raises:
            GatewayUnreachable: When no session opens, or the hub refuses.
        """
        answer = self._control.command("dial", **self._session_fields())
        if answer.get("code"):
            raise GatewayUnreachable(
                f"refused: {answer['code']} {answer.get('params')}"
            )
        opened = self._wait_event("session_open", SESSION_TIMEOUT_S)
        self.send_frame(
            {
                "type": "hello",
                "protocol": PROTOCOL,
                "role": CLIENT_ROLE,
                "id": self.binding_id,
                "name": "connect-probe",
                "software": SOFTWARE,
            }
        )
        welcome = self._wait_frame("welcome", WELCOME_TIMEOUT_S)
        return {**welcome, "address": str(opened.get("address", ""))}

    def send_frame(self, frame: dict) -> None:
        self._control.send_frame(frame)

    def take_state(self) -> dict:
        """Ask for the whole state and return it.

        Raises:
            GatewayUnreachable: When none arrives or the hub refuses.
        """
        self.send_frame(
            {
                "type": "report",
                "state_hash": "",
                "machine": {
                    "hostname": socket.gethostname(),
                    "platform": platform_tuple(),
                    "os_machine_id": "",
                },
                "is_refresh": True,
            }
        )
        return self._wait_frame("state", STATE_TIMEOUT_S)

    def open(self, open_record: dict) -> Stream:
        """Open one stream on the hub's session.

        Args:
            open_record: ``{kind, ...args}``.

        Returns:
            The stream, its answer read.

        Raises:
            GatewayUnreachable: When the transport does not answer.
        """
        try:
            connection = open_local(self._process.listen)
            connection.sendall(
                encode_line(
                    {
                        "secret": self._process.secret,
                        "op": TRANSPORT_OP_OPEN,
                        "binding": self.binding_id,
                        "open": open_record,
                    }
                )
            )
        except OSError as error:
            raise GatewayUnreachable(f"the transport does not answer: {error}")
        return Stream(connection)

    def leave(self) -> dict:
        """Give the binding back to the hub.

        Returns:
            ``{}``, or ``{code, params}`` when the hub or the transport refused.
        """
        try:
            return self._control.command("leave", **self._session_fields())
        except GatewayUnreachable as error:
            return {"code": "hub_unreachable", "params": {"detail": str(error)}}

    def close(self) -> None:
        if self._control is not None:
            self._control.close()
        self._process.stop()
        shutil.rmtree(self._directory, ignore_errors=True)

    def _session_fields(self) -> dict:
        return {
            "hub_key": self.hub_key,
            "private_key": self.private_key,
            "psk": psk_of(self.token),
            "role": CLIENT_ROLE,
            "protocol": PROTOCOL,
            "addresses": self.addresses,
        }

    def _wait_event(self, name: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                break
            if event.get("event") == name:
                return event
            if event.get("event") in ("round_end", "session_end") and event.get("code"):
                raise GatewayUnreachable(
                    f"refused: {event.get('code')} {event.get('params')}"
                )
        raise GatewayUnreachable(f"no {name} within {timeout:.0f} s")

    def _wait_frame(self, name: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                frame = self.frames.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                break
            if frame.get("type") == name:
                return frame
            if frame.get("type") == "refused":
                raise GatewayUnreachable(
                    f"refused: {frame.get('code')} {frame.get('params')}"
                )
        raise GatewayUnreachable(f"no {name} within {timeout:.0f} s")

    @staticmethod
    def _refuse_question(question: dict) -> dict:
        return {
            "code": "port_not_published",
            "params": {"port": question.get("port", 0)},
        }


def probe(client: Client, open_args: dict, *, is_raw: bool) -> dict:
    """Open one TCP ``connect`` stream and report what it carried."""
    stream = client.open({"kind": "connect", **open_args})
    received = b""
    is_gone = False
    try:
        if not stream.is_accepted:
            return {
                "ok": False,
                "bytes": 0,
                "first_bytes": "",
                **stream.close_of_answer(),
            }
        stream.start_raw()
        if not is_raw:
            stream.send_raw(HTTP_REQUEST)
        window = RAW_WINDOW_S if is_raw else ANSWER_TIMEOUT_S
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            item = stream.next(deadline - time.monotonic())
            if item is None:
                break
            if item[0] == "gone":
                is_gone = True
                break
            received += item[1]
            if not is_raw and b"\r\n" in received:
                break
    finally:
        stream.close()
    result = {
        "bytes": len(received),
        "first_bytes": received[:FIRST_BYTES_SHOWN].decode("latin-1"),
    }
    if is_raw:
        return {
            **result,
            "ok": not is_gone,
            "stayed_open_s": 0 if is_gone else RAW_WINDOW_S,
        }
    status_line = received.split(b"\r\n", 1)[0].decode("latin-1")
    return {**result, "ok": status_line.startswith("HTTP/"), "status_line": status_line}


def dns_query(name: str) -> bytes:
    """One DNS query for the name's A record, recursion asked."""
    header = DNS_QUERY_ID.to_bytes(2, "big") + bytes([1, 0, 0, 1, 0, 0, 0, 0, 0, 0])
    labels = b"".join(
        bytes([len(label)]) + label.encode("ascii")
        for label in name.strip(".").split(".")
        if label
    )
    return header + labels + b"\x00" + (1).to_bytes(2, "big") + (1).to_bytes(2, "big")


def probe_udp(client: Client, open_args: dict, *, name: str) -> dict:
    """Open one UDP ``connect`` stream, send one query, report the reply."""
    stream = client.open({"kind": "connect", **open_args})
    try:
        if not stream.is_accepted:
            return {"ok": False, **stream.close_of_answer()}
        stream.start_records()
        query = dns_query(name)
        stream.send_record(
            TRANSPORT_RECORD_DATAGRAM,
            UDP_SOURCE.to_bytes(UDP_SOURCE_BYTES, "big") + query,
        )
        deadline = time.monotonic() + ANSWER_TIMEOUT_S
        while time.monotonic() < deadline:
            item = stream.next(deadline - time.monotonic())
            if item is None:
                break
            if item[0] == "gone":
                return {"ok": False, "code": "stream_closed", "params": {}}
            if item[0] == "close":
                return {"ok": False, "code": item[1], "params": item[2]}
            if item[0] != "datagram":
                continue
            frame = item[1]
            source = int.from_bytes(frame[:UDP_SOURCE_BYTES], "big")
            datagram = frame[UDP_SOURCE_BYTES:]
            return {
                "ok": source == UDP_SOURCE and datagram[:2] == query[:2],
                "source": source,
                "bytes": len(datagram),
                "is_echo": datagram == query,
                "dns_rcode": datagram[3] & 0x0F if len(datagram) >= 4 else None,
            }
    finally:
        stream.close()
    return {"ok": False, "code": "no_reply", "params": {}}


def run_exec(client: Client, open_args: dict, stdin: bytes, timeout_s: float) -> tuple:
    """Open one ``exec``, send the stdin and ``eof``, and read to the close.

    Returns:
        The bytes by output, ``{"data": ..., "stderr": ...}``, and the
        close's ``{code, params}``.
    """
    stream = client.open({"kind": "exec", **open_args})
    received = {"data": b"", "stderr": b""}
    try:
        if not stream.is_accepted:
            return received, stream.close_of_answer()
        stream.start_records()
        if stdin:
            stream.send_record(TRANSPORT_RECORD_DATA, stdin)
        stream.send_record(TRANSPORT_RECORD_EOF)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            item = stream.next(deadline - time.monotonic())
            if item is None:
                break
            if item[0] == "gone":
                return received, {"code": "stream_closed", "params": {}}
            if item[0] == "close":
                return received, {"code": item[1], "params": item[2]}
            if item[0] in received:
                received[item[0]] += item[1]
    finally:
        stream.close()
    raise AssertionError(f"no close within {timeout_s} s: {received}")


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
        addresses, ticket, hub_key = parse_client_link(read_link(arguments.link_file))
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "code": "link_unreadable", "error": str(error)}))
        return 2
    try:
        client = Client()
        client.start()
    except OSError as error:
        print(
            json.dumps({"ok": False, "code": "transport_failed", "error": str(error)})
        )
        return 1
    try:
        client.join(addresses, ticket, hub_key)
    except GatewayUnreachable as error:
        client.close()
        print(json.dumps({"ok": False, "code": "join_failed", "error": str(error)}))
        return 1
    try:
        welcome = client.dial()
        state = client.take_state()
        report = {
            "ok": True,
            "address": welcome["address"],
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
                report.update(probe_udp(client, open_args, name=arguments.dns_name))
            else:
                report.update(probe(client, open_args, is_raw=arguments.raw))
    except (GatewayUnreachable, OSError) as error:
        report = {**report, "ok": False, "code": "channel_failed", "error": str(error)}
    finally:
        left = client.leave()
        if left.get("code"):
            report["leave"] = left
        client.close()
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
