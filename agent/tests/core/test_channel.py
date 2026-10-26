"""A binding of 0.5 taking the hub's key over the pinned TLS, and every status.

The pin runs against a real TLS socket whose certificate is generated at
test runtime with the ``openssl`` binary, so no key material lives in the
repository: the right fingerprint asks for the key, the wrong one is refused
before a single request byte is sent. The move of the binding is pinned
end to end against that server: the agent's own public key sent, the hub's
key and the agent's written, the fingerprint dropped and every address
rewritten as ``tcp``. The status mappings replace ``_request`` with a
canned answer, so each status and body shape is judged in-process.
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

import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.constants import CHANNEL_KEY_SET_PATH
from neutrino_agent.core.channel import HubKeyHttpClient
from neutrino_agent.core.static_key import public_key_of
from neutrino_agent.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)

WRONG_FINGERPRINT = "0" * 64
HUB_KEY = "ab" * 32


class RecordingHandler(BaseHTTPRequestHandler):
    """Answers every POST with one canned JSON body and records the path."""

    requests: list = []
    hosts: list = []
    status = 200
    answer = b'{"key": "' + HUB_KEY.encode() + b'"}'

    def do_GET(self):
        RecordingHandler.requests.append((self.path, b""))
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        RecordingHandler.requests.append((self.path, body))
        RecordingHandler.hosts.append(self.headers.get("Host"))
        answer = RecordingHandler.answer
        self.send_response(RecordingHandler.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, format, *args):
        """Keep the test output quiet."""


class QuietTlsServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """A connection dropped after the handshake is the refusal working."""


class QuietTlsServerIpv6(QuietTlsServer):
    address_family = socket.AF_INET6


@pytest.fixture
def tls_server(tmp_path):
    """A live TLS server and the fingerprint of its runtime-generated certificate."""
    yield from serving_tls(tmp_path, QuietTlsServer, "127.0.0.1")


@pytest.fixture
def tls_server_ipv6(tmp_path):
    """The TLS server on the IPv6 loopback, its URL's host in brackets."""
    yield from serving_tls(tmp_path, QuietTlsServerIpv6, "::1")


def serving_tls(tmp_path, server_class, host):
    """Run a live TLS server on a host; yield its URL and fingerprint."""
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
    RecordingHandler.hosts = []
    RecordingHandler.status = 200
    RecordingHandler.answer = b'{"key": "' + HUB_KEY.encode() + b'"}'
    server = server_class((host, 0), RecordingHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        named = f"[{host}]" if ":" in host else host
        yield f"https://{named}:{server.server_address[1]}", fingerprint
    finally:
        server.shutdown()
        server.server_close()


def legacy(config_path, url, fingerprint, urls=None) -> None:
    """A binding of 0.5, pinned by a fingerprint, with no hub key."""
    binding = {
        "gateway_url": url,
        "id": "d1",
        "token": "t1",
        "fingerprint": fingerprint,
        "machine_id": "m1",
    }
    if urls is not None:
        binding["gateway_urls"] = urls
    config_path.write_text(json.dumps(binding))


def test_the_pinned_fingerprint_asks_for_the_key(tls_server):
    url, fingerprint = tls_server

    key = HubKeyHttpClient(gateway_url=url, fingerprint=fingerprint).set_key(
        "d1", "t1", "cd" * 32
    )

    assert key == HUB_KEY
    ((path, body),) = RecordingHandler.requests
    assert path == CHANNEL_KEY_SET_PATH
    assert json.loads(body) == {"id": "d1", "token": "t1", "public_key": "cd" * 32}


def test_the_pinned_connection_floors_at_tls_1_2():
    from neutrino_agent.core.channel import _pinned_context

    assert _pinned_context().minimum_version == ssl.TLSVersion.TLSv1_2


def test_a_wrong_fingerprint_is_refused_before_anything_is_sent(tls_server):
    url, _ = tls_server
    client = HubKeyHttpClient(gateway_url=url, fingerprint=WRONG_FINGERPRINT)

    with pytest.raises(GatewayUntrusted):
        client.set_key("d1", "t1", "cd" * 32)
    assert RecordingHandler.requests == []


def test_an_https_url_without_a_pin_sends_nothing(tls_server):
    url, _ = tls_server

    with pytest.raises(GatewayUntrusted):
        HubKeyHttpClient(gateway_url=url).set_key("d1", "t1", "cd" * 32)
    assert RecordingHandler.requests == []


def test_a_binding_of_0_5_moves_to_the_hubs_key(tls_server, config_path):
    url, fingerprint = tls_server
    port = url.rsplit(":", 1)[1]
    legacy(config_path, url, fingerprint, urls=["https://192.0.2.1:8443", url])

    assert enrollment.take_hub_key() == {}

    binding = enrollment.load_binding()
    sent = json.loads(RecordingHandler.requests[-1][1])
    assert sent["public_key"] == public_key_of(binding["private_key"])
    assert binding["hub_key"] == HUB_KEY
    assert binding["gateway_url"] == f"tcp://127.0.0.1:{port}"
    assert binding["gateway_urls"] == [
        "tcp://192.0.2.1:8443",
        f"tcp://127.0.0.1:{port}",
    ]
    assert "fingerprint" not in json.loads(config_path.read_text())
    assert (config_path.stat().st_mode & 0o777) == 0o600


def test_binding_unknown_from_the_legacy_listener_unbinds(tls_server, config_path):
    url, fingerprint = tls_server
    RecordingHandler.status = 401
    RecordingHandler.answer = b'{"detail": {"code": "binding_unknown"}}'
    legacy(config_path, url, fingerprint)

    assert enrollment.take_hub_key() == {"code": "binding_unknown", "params": {}}
    assert not config_path.exists()


def test_no_address_giving_a_key_is_hub_key_missing(tls_server, config_path):
    url, _ = tls_server
    legacy(config_path, url, WRONG_FINGERPRINT, urls=["tcp://192.0.2.1:8443"])

    assert enrollment.take_hub_key() == {"code": "hub_key_missing", "params": {}}
    assert enrollment.load_legacy_binding()["fingerprint"] == WRONG_FINGERPRINT


def test_a_binding_with_a_key_takes_none(config_path):
    from tests.conftest import bind

    bind(config_path)

    assert enrollment.take_hub_key() == {}
    assert enrollment.load_legacy_binding() == {}


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://192.0.2.1:8443", "tcp://192.0.2.1:8443"),
        ("https://hub.lan", "tcp://hub.lan:443"),
        ("https://[fd00::1]:8443", "tcp://[fd00::1]:8443"),
        ("tcp://192.0.2.1:8443", "tcp://192.0.2.1:8443"),
    ],
)
def test_a_0_5_address_is_rewritten_with_the_same_host_and_port(url, expected):
    assert enrollment.transport_url(url) == expected


def canned_client(status, data=b"", headers=None):
    """A client whose one request answers with the given status and body."""
    made = HubKeyHttpClient(gateway_url="http://hub")
    made._request = lambda method, url, body=None, headers=None: (
        status,
        data,
        headers or {},
    )
    return made


@pytest.mark.parametrize("status", [400, 401, 403, 409])
def test_an_error_status_with_a_code_raises_the_detail(status):
    body = json.dumps({"detail": {"code": "binding_unknown", "params": {"a": 1}}})

    with pytest.raises(GatewayRefusedDetail) as caught:
        canned_client(status, body.encode()).set_key("d", "t", "k")

    assert (caught.value.code, caught.value.params) == ("binding_unknown", {"a": 1})


@pytest.mark.parametrize("body", [b"", b"not json", b'{"detail": "words"}'])
def test_an_error_status_without_a_code_raises_unreachable(body):
    with pytest.raises(GatewayUnreachable):
        canned_client(500, body).set_key("d", "t", "k")


@pytest.mark.parametrize("data", [b"not json", b"", b'{"key": ""}', b"[]"])
def test_a_success_naming_no_key_raises_unreachable(data):
    with pytest.raises(GatewayUnreachable):
        canned_client(200, data).set_key("d", "t", "k")


def test_a_dead_port_raises_unreachable():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = HubKeyHttpClient(gateway_url=f"http://127.0.0.1:{port}")

    with pytest.raises(GatewayUnreachable):
        client.set_key("d", "t", "k")


def test_an_ipv6_hub_is_reached_at_its_bracketed_address(tls_server_ipv6):
    url, fingerprint = tls_server_ipv6

    key = HubKeyHttpClient(gateway_url=url, fingerprint=fingerprint).set_key(
        "d1", "t1", "cd" * 32
    )

    assert key == HUB_KEY
    assert RecordingHandler.hosts[0].startswith("[::1]")
