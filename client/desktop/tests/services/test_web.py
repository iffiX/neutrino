"""The web service: every published page of a hub opens through its forward.

Open makes the entry's forward of the local port table, every connection a
``connect`` stream through the hub and none dialled to the entry's own
address, and opens the browser at ``<scheme>://<slug>.localhost:<local
port><path>``, on ``127.0.0.1`` on macOS; an entry with
``is_token_required`` takes a fresh token on every open and opens with
``?tkn=<token>``. The forward is reused, ends on Disconnect, and ends with
the client or with its hub.
"""

import socket
import threading
import urllib.parse

import pytest

from neutrino_client.exceptions import GatewayRefusedDetail
from neutrino_client.services.forward import ForwardListenerRegistry
from neutrino_client.services.web import WebServiceHandler, local_url, slug
from tests.conftest import SERVICES, FakeClientPlatform, FakeConnectHub, discard

TOKEN = "vsc-token-1"  # scan: allow
# An address no test machine has: a dial there would never answer.
DEVICE_HOST = "203.0.113.9"


@pytest.fixture
def far():
    """What the hub would dial: a server that answers each connection once."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def serve():
        while True:
            try:
                connection, _address = server.accept()
            except OSError:
                return
            connection.recv(4096)
            connection.sendall(b"HTTP/1.0 200 OK\r\n\r\nthe page")
            connection.close()

    threading.Thread(target=serve, daemon=True).start()
    yield port
    server.close()


@pytest.fixture
def hub(far):
    return FakeConnectHub(far_port=far)


@pytest.fixture
def forwards(hub):
    registry = ForwardListenerRegistry(open_connect=hub.open_connect, log=discard)
    yield registry
    registry.release()


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


def handler_on(forwards, material=None, os_name="linux"):
    platform = FakeClientPlatform()
    platform.os_name = os_name
    handler = WebServiceHandler(
        platform=platform, forwards=forwards, open_service=material, log=discard
    )
    return handler, platform


def page_entry(url, hub_id="h1", entry_id="gitea_d1", is_token_required=False):
    payload = {"url": url}
    if is_token_required:
        payload["is_token_required"] = True
    return {
        "id": entry_id,
        "type": "web",
        "hub_id": hub_id,
        "title": "page",
        "payload": payload,
        "is_healthy": True,
    }


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


def test_open_forwards_the_page_and_opens_its_slug_address(forwards, hub):
    handler, platform = handler_on(forwards)
    entry = page_entry(f"http://{DEVICE_HOST}:3000/explore?tab=repos")

    assert handler.act(entries=[entry], body={"hub_id": "h1", "id": "gitea_d1"}) == {}

    port = forwards.port_of("h1", "gitea_d1")
    assert platform.opened_urls == [
        f"http://gitea-d1.localhost:{port}/explore?tab=repos"
    ]
    assert fetch(platform.opened_urls[0]).endswith(b"the page")
    assert hub.opens == [("h1", {"id": "gitea_d1"})]


def test_the_entrys_own_port_is_the_local_port_when_free(forwards):
    handler, platform = handler_on(forwards)
    probe = socket.create_server(("127.0.0.1", 0))
    own = probe.getsockname()[1]
    probe.close()

    handler.act(
        entries=[page_entry(f"http://{DEVICE_HOST}:{own}/")],
        body={"hub_id": "h1", "id": "gitea_d1"},
    )

    assert forwards.port_of("h1", "gitea_d1") == own


def test_a_url_without_a_port_takes_its_schemes(forwards):
    handler, platform = handler_on(forwards)

    handler.act(
        entries=[page_entry("https://wiki.lan/")],
        body={"hub_id": "h1", "id": "gitea_d1"},
    )

    assert platform.opened_urls[0].startswith("https://gitea-d1.localhost:")


def test_a_token_entry_opens_with_a_fresh_token_each_time(forwards):
    material = Material()
    handler, platform = handler_on(forwards, material)
    entry = page_entry(
        f"http://{DEVICE_HOST}:8000/",
        entry_id="vscode_d1_alice",
        is_token_required=True,
    )
    body = {"hub_id": "h1", "id": "vscode_d1_alice"}

    assert handler.act(entries=[entry], body=body) == {}
    material.answer = {"token": "second"}
    assert handler.act(entries=[entry], body=body) == {}

    port = forwards.port_of("h1", "vscode_d1_alice")
    assert platform.opened_urls == [
        f"http://vscode-d1-alice.localhost:{port}/?tkn={TOKEN}",
        f"http://vscode-d1-alice.localhost:{port}/?tkn=second",
    ]
    assert material.asked == [("h1", "vscode_d1_alice")] * 2


def test_a_page_without_a_token_asks_the_hub_for_none(forwards):
    material = Material()
    handler, platform = handler_on(forwards, material)

    handler.act(entries=SERVICES, body={"hub_id": "h1", "id": "svc_wiki"})

    assert material.asked == []
    assert len(platform.opened_urls) == 1


def test_macos_opens_the_loopback_since_safari_resolves_no_localhost_name(forwards):
    handler, platform = handler_on(forwards, os_name="darwin")

    handler.act(
        entries=[page_entry(f"http://{DEVICE_HOST}:3000/")],
        body={"hub_id": "h1", "id": "gitea_d1"},
    )

    port = forwards.port_of("h1", "gitea_d1")
    assert platform.opened_urls == [f"http://127.0.0.1:{port}/"]


def test_the_slug_keeps_letters_digits_and_hyphens():
    assert slug("vscode_d1.alice@x") == "vscode-d1-alice-x"
    assert local_url("http://h:1/p?q=1", "a_b", 20000, "t", "linux") == (
        "http://a-b.localhost:20000/p?q=1&tkn=t"
    )
    assert local_url("https://h/", "a_b", 20000, "", "darwin") == (
        "https://127.0.0.1:20000/"
    )


def test_a_second_open_reuses_the_forward(forwards):
    handler, platform = handler_on(forwards)
    entry = page_entry(f"http://{DEVICE_HOST}:3000/")
    body = {"hub_id": "h1", "id": "gitea_d1"}

    handler.act(entries=[entry], body=body)
    handler.act(entries=[entry], body=body)

    assert platform.opened_urls[0] == platform.opened_urls[1]
    assert list(forwards.forwards()) == ["h1/gitea_d1"]


def test_a_disconnect_ends_the_forward(forwards):
    handler, platform = handler_on(forwards)
    entry = page_entry(f"http://{DEVICE_HOST}:3000/")
    handler.act(entries=[entry], body={"hub_id": "h1", "id": "gitea_d1"})

    assert (
        handler.act(
            entries=[entry],
            body={"hub_id": "h1", "id": "gitea_d1", "is_enabled": False},
        )
        == {}
    )

    assert forwards.forwards() == {}
    assert len(platform.opened_urls) == 1


def test_two_instances_on_one_remote_port_take_two_local_ports(forwards):
    handler, platform = handler_on(forwards)
    entries = [
        page_entry(f"http://{DEVICE_HOST}:8000/", entry_id="vscode_d1_alice"),
        page_entry(f"http://{DEVICE_HOST}:8000/", entry_id="vscode_d1_bob"),
    ]

    for entry in entries:
        handler.act(entries=entries, body={"hub_id": "h1", "id": entry["id"]})

    ports = forwards.forwards()
    assert ports["h1/vscode_d1_alice"] != ports["h1/vscode_d1_bob"]


def test_the_hubs_refusal_of_the_token_is_the_answer_and_nothing_opens(forwards):
    material = Material(error=GatewayRefusedDetail(code="vault_locked", params={}))
    handler, platform = handler_on(forwards, material)
    entry = page_entry(
        f"http://{DEVICE_HOST}:8000/",
        entry_id="vscode_d1_alice",
        is_token_required=True,
    )

    outcome = handler.act(entries=[entry], body={"hub_id": "h1", "id": entry["id"]})

    assert outcome == {"code": "vault_locked", "params": {}}
    assert platform.opened_urls == []


def test_material_without_a_token_opens_nothing(forwards):
    handler, platform = handler_on(forwards, Material(answer={}))
    entry = page_entry(
        f"http://{DEVICE_HOST}:8000/",
        entry_id="vscode_d1_alice",
        is_token_required=True,
    )

    outcome = handler.act(entries=[entry], body={"hub_id": "h1", "id": entry["id"]})

    assert outcome == {"code": "web_token_missing", "params": {}}
    assert platform.opened_urls == []


def test_an_unknown_or_bare_entry_opens_nothing(forwards):
    handler, platform = handler_on(forwards)
    bare = [{"id": "svc_bare", "type": "web", "hub_id": "h1", "payload": {}}]

    for entries, body in (
        (SERVICES, {"hub_id": "h1", "id": "nothing"}),
        (SERVICES, {"hub_id": "h2", "id": "svc_wiki"}),
        (SERVICES, {"id": "svc_wiki"}),
        (bare, {"hub_id": "h1", "id": "svc_bare"}),
    ):
        assert handler.act(entries=entries, body=body) == {
            "code": "unknown_request",
            "params": {},
        }
    assert platform.opened_urls == []
    assert forwards.forwards() == {}
