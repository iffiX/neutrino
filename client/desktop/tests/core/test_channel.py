"""The channel's judgments: the certificate pin, and every status mapping.

The pin runs against a real TLS socket whose certificate is generated at
test runtime with the ``openssl`` binary: the right fingerprint talks, the
wrong one is refused before a single request byte is sent, and a bound
client connecting against the wrong certificate unbinds the way a refused
token does. The status mappings replace ``_request`` with a canned answer:
a 409 naming a protocol number the hub does not speak is the typed
protocol refusal with its three numbers. A scanned link is stored pending
without a word to the hub; the first round that reaches it joins at once,
and another certificate is untrusted.
"""

import hashlib
import json
import shutil
import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import neutrino_client.core.enrollment as enrollment
import neutrino_client.core.session as session_module
from neutrino_client.constants import (
    CLIENT_BACKOFF_MAX_S,
    CLIENT_JOIN_PATH,
    CLIENT_LEAVE_PATH,
)
from neutrino_client.core.channel import GatewayHttpChannel
from neutrino_client.core.resident import ClientResident
from neutrino_client.core.session import ClientHubSession
from neutrino_client.exceptions import (
    GatewayProtocolRefused,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)
from tests.conftest import FakeClientPlatform, bind, discard, link_for
from tests.core.test_session import WELCOME, SocketScript

WRONG_FINGERPRINT = "0" * 64


class RecordingHandler(BaseHTTPRequestHandler):
    """Answers every request with its canned body and records the path."""

    requests: list = []
    post_answer: bytes = b"{}"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        RecordingHandler.requests.append((self.path, body))
        answer = RecordingHandler.post_answer
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, format, *args):
        """Keep the test output quiet."""


class QuietTlsServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """A connection dropped after the handshake is the refusal working."""


@pytest.fixture
def tls_server(tmp_path):
    """A live TLS server and the fingerprint of its runtime-generated certificate."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not installed; the pin needs a certificate")
    certificate_path = tmp_path / "certificate.pem"
    key_path = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(certificate_path),
            "-days",
            "2",
            "-nodes",
            "-subj",
            "/CN=test",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    der = ssl.PEM_cert_to_DER_cert(certificate_path.read_text(encoding="utf-8"))
    fingerprint = hashlib.sha256(der).hexdigest()

    RecordingHandler.requests = []
    RecordingHandler.post_answer = b"{}"
    server = QuietTlsServer(("127.0.0.1", 0), RecordingHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_address[1]}", fingerprint
    finally:
        server.shutdown()
        server.server_close()


def test_the_pinned_fingerprint_talks_and_sends_the_body_as_it_is(tls_server):
    url, fingerprint = tls_server
    channel = GatewayHttpChannel(gateway_url=url, fingerprint=fingerprint)

    reply = channel.post(CLIENT_LEAVE_PATH, {"id": "c1", "token": "tok"})

    assert reply == {}
    assert len(RecordingHandler.requests) == 1
    path, body = RecordingHandler.requests[0]
    assert path == CLIENT_LEAVE_PATH
    assert json.loads(body) == {"id": "c1", "token": "tok"}


def test_the_pinned_connection_floors_at_tls_1_2():
    from neutrino_client.core.channel import _PinnedHttpsConnection

    connection = _PinnedHttpsConnection(
        "127.0.0.1", 1, fingerprint="0" * 64, timeout=1.0
    )
    assert connection._context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_a_wrong_fingerprint_is_refused_before_anything_is_sent(tls_server):
    url, _ = tls_server
    channel = GatewayHttpChannel(gateway_url=url, fingerprint=WRONG_FINGERPRINT)

    with pytest.raises(GatewayUntrusted):
        channel.post(CLIENT_LEAVE_PATH, {"id": "c1", "token": "tok"})

    assert RecordingHandler.requests == []


def test_an_https_url_without_a_pin_sends_nothing(tls_server):
    url, _ = tls_server
    channel = GatewayHttpChannel(gateway_url=url)

    with pytest.raises(GatewayUntrusted):
        channel.post(CLIENT_LEAVE_PATH, {"id": "c1", "token": "tok"})

    assert RecordingHandler.requests == []


def test_a_mismatched_pin_keeps_the_binding_and_asks_again_a_minute_later(
    tls_server, config_path
):
    url, _ = tls_server
    bind(config_path, url=url, fingerprint=WRONG_FINGERPRINT)
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
    (session,) = resident._sessions.values()

    delays = [session.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert resident.is_connected() is True
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert resident.hubs()[0]["last_error"] == {"code": "hub_untrusted", "params": {}}
    assert RecordingHandler.requests == []


def test_a_wrong_fingerprint_spends_no_ticket(tls_server, config_path):
    url, _ = tls_server
    link = link_for({"urls": [url], "token": "ticket", "fp": WRONG_FINGERPRINT})
    binding = enrollment.enroll(link)

    with pytest.raises(GatewayUntrusted):
        enrollment.complete_join(binding, url)

    assert RecordingHandler.requests == []
    assert enrollment.bindings() == [binding]


def test_a_refusal_names_the_hubs_code():
    made = canned_channel(401, b'{"detail": {"code": "ticket_spent", "params": {}}}')

    with pytest.raises(GatewayRefused) as refused:
        made.post("/api/channel/join", {})

    assert (refused.value.code, refused.value.params) == ("ticket_spent", {})


def canned_channel(status, data=b"", headers=None):
    """A channel whose one answer is canned at the ``_request`` seam."""
    made = GatewayHttpChannel(gateway_url="http://hub")
    named = {name.lower(): value for name, value in (headers or {}).items()}

    def request(method, url, *, body=None, headers=None):
        return status, data, named

    made._request = request
    return made


@pytest.mark.parametrize("status", [401, 403])
def test_post_status_401_or_403_raises_refused(status):
    with pytest.raises(GatewayRefused):
        canned_channel(status).post(CLIENT_LEAVE_PATH, {})


@pytest.mark.parametrize("code", ["protocol_too_old", "protocol_too_new"])
def test_post_409_naming_the_protocol_raises_the_refusal_with_its_numbers(code):
    body = json.dumps(
        {"detail": {"code": code, "params": {"peer": 1, "hub": 3, "min": 2}}}
    ).encode()

    with pytest.raises(GatewayProtocolRefused) as caught:
        canned_channel(409, body).post(CLIENT_JOIN_PATH, {})

    assert caught.value.code == code
    assert (caught.value.peer, caught.value.hub, caught.value.minimum) == (1, 3, 2)
    assert isinstance(caught.value, GatewayRefused)


def test_a_protocol_refusal_without_numbers_reads_them_as_zero():
    body = json.dumps({"detail": {"code": "protocol_too_new", "params": {}}}).encode()

    with pytest.raises(GatewayProtocolRefused) as caught:
        canned_channel(409, body).post(CLIENT_JOIN_PATH, {})

    assert (caught.value.peer, caught.value.hub, caught.value.minimum) == (0, 0, 0)


def test_post_409_with_another_code_raises_the_typed_detail():
    body = json.dumps(
        {"detail": {"code": "rdp_not_shared", "params": {"id": "rdp_s9"}}}
    ).encode()

    with pytest.raises(GatewayRefusedDetail) as caught:
        canned_channel(409, body).post(CLIENT_JOIN_PATH, {})

    assert caught.value.code == "rdp_not_shared"
    assert caught.value.params == {"id": "rdp_s9"}
    assert isinstance(caught.value, GatewayUnreachable)


@pytest.mark.parametrize(
    "body", [b"", b"not json", b'{"detail": "words"}', b'{"detail": {}}']
)
def test_post_409_without_a_code_raises_unreachable(body):
    with pytest.raises(GatewayUnreachable):
        canned_channel(409, body).post(CLIENT_JOIN_PATH, {})


@pytest.mark.parametrize("status", [400, 404, 418, 500, 503])
def test_post_other_error_statuses_raise_unreachable(status):
    with pytest.raises(GatewayUnreachable):
        canned_channel(status).post(CLIENT_JOIN_PATH, {})


def test_post_invalid_json_in_a_success_raises_unreachable():
    with pytest.raises(GatewayUnreachable):
        canned_channel(200, b"not json").post(CLIENT_JOIN_PATH, {})


def test_post_an_empty_success_body_reads_as_an_empty_object():
    assert canned_channel(200, b"  ").post(CLIENT_LEAVE_PATH, {}) == {}


def test_post_a_dead_port_raises_unreachable():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    made = GatewayHttpChannel(gateway_url=f"http://127.0.0.1:{port}")

    with pytest.raises(GatewayUnreachable):
        made.post(CLIENT_JOIN_PATH, {})


# --- the link a QR code carries ---


NETBIRD = {
    "provider": "netbird",
    "setup_key": "KEY-1",  # scan: allow
    "management_url": "https://api.netbird.io",
    "fqdn": "hub.netbird.cloud",
    "hub_address": "100.64.0.1",
}


def scanned_link(url: str, fingerprint: str, ticket: str = "c1") -> str:
    """The whole link a QR code carries, naming the server's address."""
    return link_for(
        {
            "urls": [url, "https://10.0.0.1:8443"],
            "token": ticket,
            "fp": fingerprint,
            "overlays": [NETBIRD],
        }
    )


def dead_url() -> str:
    """An address on this machine where nothing listens."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return f"https://127.0.0.1:{port}"


def scanned_session(link: str) -> ClientHubSession:
    """The binding a scanned link stores, and the session over it."""
    enrollment.enroll(link)
    (binding,) = enrollment.bindings()
    return ClientHubSession(
        binding=binding, hostname="box", platform_tuple={}, log=discard
    )


def test_a_scanned_link_is_stored_pending_at_once_and_asks_nothing(tls_server):
    url, fingerprint = tls_server

    binding = enrollment.enroll(scanned_link(url, fingerprint))

    assert binding["gateway_url"] == url
    assert binding["gateway_urls"] == [url, "https://10.0.0.1:8443"]
    assert (binding["ticket"], binding["fingerprint"]) == ("c1", fingerprint)
    assert binding["is_pending"] is True and "is_object_pending" not in binding
    assert binding["overlays"] == [NETBIRD] and binding["token"] == ""
    assert enrollment.bindings() == [binding]
    assert RecordingHandler.requests == []


def test_a_scanned_link_whose_hub_does_not_answer_stays_pending(config_path):
    session = scanned_session(scanned_link(dead_url(), WRONG_FINGERPRINT))

    session.run_once()

    assert session.connection() == "pending"
    (stored,) = json.loads(config_path.read_text())["bindings"]
    assert stored["is_pending"] is True and stored["overlays"] == [NETBIRD]


def test_a_round_that_reaches_the_hub_joins_with_nothing_fetched_first(
    tls_server, monkeypatch, config_path
):
    url, fingerprint = tls_server
    RecordingHandler.post_answer = b'{"id": "h-c1", "token": "tok"}'
    session = scanned_session(scanned_link(url, fingerprint))
    sockets = SocketScript([WELCOME])
    monkeypatch.setattr(session_module, "WebSocketClient", sockets)

    session.run_once()

    paths = [path for path, _ in RecordingHandler.requests]
    assert paths == [CLIENT_JOIN_PATH]
    assert json.loads(RecordingHandler.requests[0][1])["ticket"] == "c1"
    (stored,) = json.loads(config_path.read_text())["bindings"]
    assert (stored["id"], stored["token"]) == ("h-c1", "tok")
    assert stored["overlays"] == [NETBIRD] and "ticket" not in stored
    assert sockets.made[0].sent[0]["type"] == "hello"


def test_a_scanned_link_on_another_certificate_is_untrusted_and_asks_nothing(
    tls_server, monkeypatch
):
    url, _ = tls_server
    session = scanned_session(scanned_link(url, WRONG_FINGERPRINT))
    sockets = SocketScript([WELCOME])
    monkeypatch.setattr(session_module, "WebSocketClient", sockets)

    session.run_once()

    assert session.last_error() == {"code": "hub_untrusted", "params": {}}
    assert session.connection() == "pending"
    assert RecordingHandler.requests == []
