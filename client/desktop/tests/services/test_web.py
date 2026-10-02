"""The web service: a published link of one hub opens in the platform's browser.

An entry that opens only through localhost is forwarded to ``127.0.0.1``
over a real loopback socket on the port the local port table gives it, its
token taken from the hub's material, and opened there with no token in the
address; the forward puts the token in each request's ``vscode-tkn`` cookie,
closes the connection after one request, drops the server's ``Set-Cookie``
of the token, and passes a WebSocket upgrade through as bytes; the forward
is reused, ends on Disconnect, and ends with the client or with its hub.
"""

import socket
import threading
import urllib.parse

import pytest

from neutrino_client.exceptions import GatewayRefusedDetail
from neutrino_client.services.port import PortLocalTable
from neutrino_client.services.web import (
    WebServiceHandler,
    read_head,
    rewrite_request_head,
    rewrite_response_head,
)
from tests.conftest import SERVICES, FakeClientPlatform, discard


def test_open_hands_the_url_to_the_platform():
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform)

    assert handler.act(entries=SERVICES, body={"hub_id": "h1", "id": "svc_wiki"}) == {}
    assert handler.act(entries=SERVICES, body={"hub_id": "h2", "id": "svc_docs"}) == {}

    assert platform.opened_urls == ["http://w/", "http://docs/"]
    assert handler.state() == {"web_forwards": {}}


def test_an_unknown_or_bare_entry_opens_nothing():
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform)
    bare = [{"id": "svc_bare", "type": "web", "hub_id": "h1", "payload": {}}]

    assert handler.act(entries=SERVICES, body={"hub_id": "h1", "id": "nothing"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert handler.act(entries=SERVICES, body={"hub_id": "h2", "id": "svc_wiki"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert handler.act(entries=SERVICES, body={"id": "svc_wiki"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert handler.act(entries=bare, body={"hub_id": "h1", "id": "svc_bare"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert platform.opened_urls == []


# --- an entry that opens only through localhost ---

TOKEN = "vsc-token-1"  # scan: allow


@pytest.fixture
def upstream():
    """A real server on a loopback port of its own that answers each connection once."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def serve():
        while True:
            try:
                connection, _address = server.accept()
            except OSError:
                return
            connection.recv(4096)
            connection.sendall(b"HTTP/1.0 200 OK\r\n\r\nvscode")
            connection.close()

    threading.Thread(target=serve, daemon=True).start()
    yield port
    server.close()


def local_entry(port, hub_id="h1", entry_id="vscode_d1_alice"):
    return {
        "id": entry_id,
        "type": "web",
        "hub_id": hub_id,
        "title": "VS Code (alice)",
        "payload": {"url": f"http://127.0.0.1:{port}/", "is_local_only": True},
        "is_healthy": True,
    }


class Material:
    """The hub's answer on the ``service`` stream, and every ask of it."""

    def __init__(self, answer=None, error=None):
        self.answer = answer if answer is not None else {"token": TOKEN}
        self.error = error
        self.asked = []

    def __call__(self, hub_id, entry_id):
        self.asked.append((hub_id, entry_id))
        if self.error is not None:
            raise self.error
        return dict(self.answer)


def fetch(url: str) -> bytes:
    parts = urllib.parse.urlsplit(url)
    with socket.create_connection((parts.hostname, parts.port), timeout=5) as client:
        client.sendall(b"GET / HTTP/1.0\r\n\r\n")
        received = b""
        while True:
            data = client.recv(4096)
            if not data:
                return received
            received += data


def test_a_local_only_entry_is_forwarded_and_opened_without_its_token(upstream):
    platform = FakeClientPlatform()
    material = Material()
    handler = WebServiceHandler(platform=platform, open_service=material, log=discard)

    outcome = handler.act(
        entries=[local_entry(upstream)], body={"hub_id": "h1", "id": "vscode_d1_alice"}
    )

    assert outcome == {}
    assert material.asked == [("h1", "vscode_d1_alice")]
    (opened,) = platform.opened_urls
    parts = urllib.parse.urlsplit(opened)
    assert (parts.scheme, parts.hostname, parts.path) == ("http", "127.0.0.1", "/")
    assert parts.port != upstream
    assert parts.query == ""
    assert fetch(opened).endswith(b"vscode")
    assert handler.state()["web_forwards"] == {
        "h1/vscode_d1_alice": {"local_port": parts.port, "is_active": True}
    }
    handler.release()


def test_a_disconnect_ends_the_forward(upstream):
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform, open_service=Material(), log=discard)
    entries = [local_entry(upstream)]
    body = {"hub_id": "h1", "id": "vscode_d1_alice"}
    handler.act(entries=entries, body=body)

    assert handler.act(entries=entries, body=dict(body, is_enabled=False)) == {}

    assert handler.state()["web_forwards"] == {}
    with pytest.raises(OSError):
        fetch(platform.opened_urls[0])


def test_two_instances_on_one_remote_port_take_two_local_ports_kept_by_entry(
    upstream,
):
    table = PortLocalTable(is_free=_free_but(upstream))
    platform = FakeClientPlatform()
    handler = WebServiceHandler(
        platform=platform, open_service=Material(), log=discard, ports=table
    )
    entries = [local_entry(upstream, "h1"), local_entry(upstream, "h2")]
    for hub_id in ("h2", "h1"):
        handler.act(entries=entries, body={"hub_id": hub_id, "id": "vscode_d1_alice"})

    ports = [urllib.parse.urlsplit(url).port for url in platform.opened_urls]
    assert ports == [20000, 20001]
    handler.release()


# --- the heads the forward rewrites ---


def test_a_request_carries_the_token_as_its_cookie_and_closes_after_it():
    head = (
        b"GET /x HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n"
        b"Cookie: a=1; vscode-tkn=old\r\nConnection: keep-alive\r\n"
        b"cookie: b=2\r\n\r\n"
    )

    rewritten = rewrite_request_head(head, TOKEN)

    lines = rewritten.split(b"\r\n")
    assert lines[0] == b"GET /x HTTP/1.1"
    assert b"Host: 127.0.0.1:8000" in lines
    assert b"Connection: close" in lines
    assert b"Connection: keep-alive" not in lines
    assert [line for line in lines if line.lower().startswith(b"cookie")] == [
        b"Cookie: a=1; b=2; vscode-tkn=" + TOKEN.encode()
    ]
    assert rewritten.endswith(b"\r\n\r\n")


def test_a_request_without_cookies_gets_the_token_one():
    rewritten = rewrite_request_head(b"GET / HTTP/1.1\r\nHost: h\r\n\r\n", TOKEN)

    assert b"\r\nCookie: vscode-tkn=" + TOKEN.encode() + b"\r\n" in rewritten
    assert b"\r\nConnection: close\r\n" in rewritten


def test_an_upgrade_request_keeps_its_connection_header():
    head = b"GET /ws HTTP/1.1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n"

    rewritten = rewrite_request_head(head, TOKEN)

    assert b"Connection: Upgrade" in rewritten
    assert b"Connection: close" not in rewritten


def test_a_response_loses_the_token_cookie_and_keeps_the_others():
    head = (
        b"HTTP/1.1 200 OK\r\nSet-Cookie: vscode-tkn=x; Path=/; HttpOnly\r\n"
        b"set-cookie: theme=dark\r\nContent-Length: 2\r\n\r\n"
    )

    rewritten = rewrite_response_head(head)

    assert b"vscode-tkn" not in rewritten
    assert b"set-cookie: theme=dark" in rewritten
    assert rewritten.startswith(b"HTTP/1.1 200 OK\r\n")
    assert rewritten.endswith(b"Content-Length: 2\r\n\r\n")


def test_a_head_that_never_ends_is_not_read():
    left, right = socket.socketpair()
    left.sendall(b"GET / HTTP/1.1\r\n")
    left.close()

    assert read_head(right) is None
    right.close()


class Recorder:
    """A loopback server that records each request's head and answers a script.

    Attributes:
        port: Where it listens.
        heads: Every request head it read, in order.
    """

    def __init__(self, answer: bytes, is_echo: bool = False):
        self._answer = answer
        self._is_echo = is_echo
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port = self._server.getsockname()[1]
        self.heads = []
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        while True:
            try:
                connection, _address = self._server.accept()
            except OSError:
                return
            threading.Thread(
                target=self._serve, args=(connection,), daemon=True
            ).start()

    def _serve(self, connection) -> None:
        head = read_head(connection)
        if head is not None:
            self.heads.append(head[0])
            connection.sendall(self._answer)
            while self._is_echo:
                data = connection.recv(4096)
                if not data:
                    break
                connection.sendall(data)
        connection.close()


def test_the_forward_hands_the_token_and_hides_the_servers_cookie():
    recorder = Recorder(
        b"HTTP/1.1 200 OK\r\nSet-Cookie: vscode-tkn=new\r\n"
        b"Content-Length: 6\r\n\r\nvscode"
    )
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform, open_service=Material(), log=discard)
    handler.act(
        entries=[local_entry(recorder.port)],
        body={"hub_id": "h1", "id": "vscode_d1_alice"},
    )

    received = fetch(platform.opened_urls[0])

    assert received.endswith(b"vscode")
    assert b"vscode-tkn" not in received
    (head,) = recorder.heads
    assert b"Cookie: vscode-tkn=" + TOKEN.encode() in head
    assert b"Connection: close" in head
    handler.release()
    recorder.close()


def test_an_upgrade_is_passed_through_and_then_relays_bytes_both_ways():
    recorder = Recorder(
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\n\r\n",
        is_echo=True,
    )
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform, open_service=Material(), log=discard)
    handler.act(
        entries=[local_entry(recorder.port)],
        body={"hub_id": "h1", "id": "vscode_d1_alice"},
    )
    parts = urllib.parse.urlsplit(platform.opened_urls[0])

    with socket.create_connection(("127.0.0.1", parts.port), timeout=5) as client:
        client.sendall(
            b"GET /ws HTTP/1.1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n"
        )
        answer = read_head(client)
        client.sendall(b"frame one")
        echoed = b""
        while len(echoed) < len(b"frame one"):
            echoed += client.recv(4096)

    assert answer[0].startswith(b"HTTP/1.1 101 Switching Protocols")
    assert echoed == b"frame one"
    assert b"Connection: Upgrade" in recorder.heads[0]
    handler.release()
    recorder.close()


def _free_but(port):
    """An ``is_free`` that has every port free except one."""

    def is_free(candidate):
        return candidate != port

    return is_free


def test_a_second_open_reuses_the_forward_and_the_client_ending_closes_it(upstream):
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform, open_service=Material(), log=discard)
    entries = [local_entry(upstream)]
    body = {"hub_id": "h1", "id": "vscode_d1_alice"}

    handler.act(entries=entries, body=body)
    handler.act(entries=entries, body=body)

    first, second = platform.opened_urls
    assert first == second
    assert handler.release() == 1
    with pytest.raises(OSError):
        fetch(first)


def test_leaving_a_hub_closes_only_its_forwards(upstream):
    handler = WebServiceHandler(
        platform=FakeClientPlatform(), open_service=Material(), log=discard
    )
    entries = [local_entry(upstream, "h1"), local_entry(upstream, "h2")]
    for hub_id in ("h1", "h2"):
        handler.act(entries=entries, body={"hub_id": hub_id, "id": "vscode_d1_alice"})

    assert handler.release_hub("h1") == 1
    assert handler.release() == 1


def test_the_hubs_refusal_of_the_token_is_the_answer_and_nothing_opens(upstream):
    platform = FakeClientPlatform()
    refused = GatewayRefusedDetail(code="permission_denied", params={"kind": "web"})
    handler = WebServiceHandler(
        platform=platform, open_service=Material(error=refused), log=discard
    )

    outcome = handler.act(
        entries=[local_entry(upstream)], body={"hub_id": "h1", "id": "vscode_d1_alice"}
    )

    assert outcome == {"code": "permission_denied", "params": {"kind": "web"}}
    assert platform.opened_urls == []
    handler.release()


def test_material_without_a_token_opens_nothing(upstream):
    platform = FakeClientPlatform()
    handler = WebServiceHandler(
        platform=platform, open_service=Material(answer={}), log=discard
    )

    outcome = handler.act(
        entries=[local_entry(upstream)], body={"hub_id": "h1", "id": "vscode_d1_alice"}
    )

    assert outcome == {"code": "web_token_missing", "params": {}}
    assert platform.opened_urls == []
    handler.release()


def test_an_entry_that_is_not_local_only_asks_the_hub_for_nothing():
    material = Material()
    handler = WebServiceHandler(
        platform=FakeClientPlatform(), open_service=material, log=discard
    )

    handler.act(entries=SERVICES, body={"hub_id": "h1", "id": "svc_wiki"})

    assert material.asked == []
    assert handler.release() == 0
