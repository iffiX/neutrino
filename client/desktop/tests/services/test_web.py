"""The web service: a published link of one hub opens in the platform's browser.

An entry that opens only through localhost is forwarded as bytes to
``127.0.0.1`` over a real loopback socket on the port the local port table
gives it, its token taken from the hub's material, and opened on the entry's
own ``.localhost`` name with the token in the address, on ``127.0.0.1`` on
macOS; the forward is reused, ends on Disconnect, and ends with the client
or with its hub.
"""

import socket
import threading
import urllib.parse

import pytest

from neutrino_client.exceptions import GatewayRefusedDetail
from neutrino_client.services.port import PortLocalTable
from neutrino_client.services.web import WebServiceHandler, local_url
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
    with socket.create_connection(("127.0.0.1", parts.port), timeout=5) as client:
        client.sendall(b"GET / HTTP/1.0\r\n\r\n")
        received = b""
        while True:
            data = client.recv(4096)
            if not data:
                return received
            received += data


def test_a_local_only_entry_is_forwarded_and_opened_on_its_own_name(upstream):
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
    assert (parts.scheme, parts.hostname, parts.path) == (
        "http",
        "vscode-d1-alice.localhost",
        "/",
    )
    assert parts.port != upstream
    assert urllib.parse.parse_qs(parts.query) == {"tkn": [TOKEN]}
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


def test_the_slug_keeps_letters_digits_and_hyphens_and_macos_opens_the_loopback():
    assert (
        local_url("vscode_d1.alice", 20000, "", "t", "linux")
        == "http://vscode-d1-alice.localhost:20000/?tkn=t"
    )
    assert (
        local_url("Code-2", 8000, "/x", "a b", "windows")
        == "http://Code-2.localhost:8000/x?tkn=a+b"
    )
    assert (
        local_url("vscode_d1", 8000, "/", "t", "darwin")
        == "http://127.0.0.1:8000/?tkn=t"
    )


def test_the_forward_relays_bytes_untouched():
    received = []
    server = socket.create_server(("127.0.0.1", 0))

    def serve():
        connection, _address = server.accept()
        data = connection.recv(4096)
        received.append(data)
        connection.sendall(b"HTTP/1.1 200 OK\r\nSet-Cookie: vscode-tkn=x\r\n\r\nok")
        connection.close()

    threading.Thread(target=serve, daemon=True).start()
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform, open_service=Material(), log=discard)
    handler.act(
        entries=[local_entry(server.getsockname()[1])],
        body={"hub_id": "h1", "id": "vscode_d1_alice"},
    )
    port = urllib.parse.urlsplit(platform.opened_urls[0]).port

    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(b"GET / HTTP/1.1\r\nCookie: vscode-tkn=mine\r\n\r\n")
        answer = b""
        while True:
            data = client.recv(4096)
            if not data:
                break
            answer += data

    assert received == [b"GET / HTTP/1.1\r\nCookie: vscode-tkn=mine\r\n\r\n"]
    assert answer == b"HTTP/1.1 200 OK\r\nSet-Cookie: vscode-tkn=x\r\n\r\nok"
    handler.release()
    server.close()


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


# --- an entry that opens with a token ---


def token_entry(hub_id="h1", entry_id="cloudcli_d1_alice"):
    return {
        "id": entry_id,
        "type": "web",
        "hub_id": hub_id,
        "title": "CloudCLI (alice)",
        "payload": {
            "url": "http://192.168.100.7:3001/",
            "is_local_only": False,
            "is_token_required": True,
        },
        "is_healthy": True,
    }


def test_a_token_entry_opens_its_own_address_with_a_fresh_token():
    platform = FakeClientPlatform()
    material = Material(answer={"token": "a+b/c"})
    handler = WebServiceHandler(platform=platform, open_service=material, log=discard)

    assert (
        handler.act(
            entries=[token_entry()], body={"hub_id": "h1", "id": "cloudcli_d1_alice"}
        )
        == {}
    )
    assert (
        handler.act(
            entries=[token_entry()], body={"hub_id": "h1", "id": "cloudcli_d1_alice"}
        )
        == {}
    )

    assert material.asked == [("h1", "cloudcli_d1_alice")] * 2
    assert platform.opened_urls == ["http://192.168.100.7:3001/?tkn=a%2Bb%2Fc"] * 2
    assert handler.state() == {"web_forwards": {}}


def test_a_token_entry_without_a_token_writes_the_code():
    platform = FakeClientPlatform()
    handler = WebServiceHandler(
        platform=platform, open_service=Material(answer={}), log=discard
    )

    assert handler.act(
        entries=[token_entry()], body={"hub_id": "h1", "id": "cloudcli_d1_alice"}
    ) == {
        "code": "web_token_missing",
        "params": {},
    }
    assert platform.opened_urls == []


def test_a_refused_token_writes_the_hubs_code():
    platform = FakeClientPlatform()
    refused = GatewayRefusedDetail(code="permission_denied", params={"kind": "web"})
    handler = WebServiceHandler(
        platform=platform, open_service=Material(error=refused), log=discard
    )

    outcome = handler.act(
        entries=[token_entry()], body={"hub_id": "h1", "id": "cloudcli_d1_alice"}
    )

    assert outcome["code"] == "permission_denied"
    assert platform.opened_urls == []


def test_the_token_joins_the_address_own_query():
    from neutrino_client.services.web import token_url

    assert token_url("http://h:3001", "t") == "http://h:3001/?tkn=t"
    assert token_url("http://h:3001/x?a=1", "t") == "http://h:3001/x?a=1&tkn=t"
