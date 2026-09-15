"""The channel's judgments: the certificate pin, and every status mapping.

The pin runs against a real TLS socket whose certificate is generated at
test runtime with the ``openssl`` binary, so no key material lives in the
repository: the right fingerprint talks, the wrong one is refused before a
single request byte is sent, and a bound agent beating against the wrong
certificate keeps its binding and says so. The status mappings replace
``_request`` with a canned answer, so each status and body shape is judged
in-process.
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
from neutrino_agent.constants import (
    AGENT_BACKOFF_MAX_S,
    AGENT_WS_PATH,
    CHANNEL_JOIN_PATH,
    CHANNEL_LEAVE_PATH,
)
from neutrino_agent.core.channel import BindingHttpClient
from neutrino_agent.core.loop import Agent
from neutrino_agent.exceptions import (
    EnrollmentError,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)
from tests.conftest import bind, discard, link_for

WRONG_FINGERPRINT = "0" * 64
JOIN_PAYLOAD = {
    "ticket": "ticket",
    "role": "agent",
    "protocol": 1,
    "machine_id": "m",
    "name": "box",
    "software": "neutrino_agent/0.0.0",
    "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
}


class RecordingHandler(BaseHTTPRequestHandler):
    """Answers every POST with one canned JSON body and records the path."""

    requests: list = []
    answer = b'{"id": "d1", "token": "t1"}'

    def do_GET(self):
        RecordingHandler.requests.append((self.path, b""))
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        RecordingHandler.requests.append((self.path, body))
        answer = RecordingHandler.answer
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


def test_the_pinned_fingerprint_joins(tls_server):
    url, fingerprint = tls_server
    client = BindingHttpClient(gateway_url=url, fingerprint=fingerprint)

    reply = client.join(JOIN_PAYLOAD)

    assert reply == {"id": "d1", "token": "t1"}
    ((path, body),) = RecordingHandler.requests
    assert path == CHANNEL_JOIN_PATH
    assert json.loads(body) == JOIN_PAYLOAD


def test_the_pinned_fingerprint_leaves(tls_server):
    url, fingerprint = tls_server
    client = BindingHttpClient(gateway_url=url, fingerprint=fingerprint)

    client.leave("d1", "t1")

    ((path, body),) = RecordingHandler.requests
    assert path == CHANNEL_LEAVE_PATH
    assert json.loads(body) == {"id": "d1", "token": "t1"}


def test_the_pinned_connection_floors_at_tls_1_2():
    from neutrino_agent.core.channel import _PinnedHttpsConnection

    connection = _PinnedHttpsConnection(
        "127.0.0.1", 1, fingerprint="0" * 64, timeout=1.0
    )
    assert connection._context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_a_wrong_fingerprint_is_refused_before_anything_is_sent(tls_server):
    url, _ = tls_server
    client = BindingHttpClient(gateway_url=url, fingerprint=WRONG_FINGERPRINT)

    with pytest.raises(GatewayUntrusted):
        client.join(JOIN_PAYLOAD)

    assert RecordingHandler.requests == []


def test_an_https_url_without_a_pin_sends_nothing(tls_server):
    url, _ = tls_server
    client = BindingHttpClient(gateway_url=url)

    with pytest.raises(GatewayUntrusted):
        client.leave("d1", "t1")

    assert RecordingHandler.requests == []


def test_a_wrong_pin_keeps_the_binding_and_names_the_changed_identity(
    tls_server, config_path
):
    """A hub reset or reinstalled answers with a new certificate for good;
    the binding stays, nothing is ever sent, and status says what answers."""
    url, _ = tls_server
    bind(config_path, url=url, fingerprint=WRONG_FINGERPRINT)
    agent = Agent(log=discard)

    delays = [agent.run_once() for _ in range(3)]

    assert delays == [AGENT_BACKOFF_MAX_S] * 3
    assert enrollment.is_bound()
    assert agent.last_error() == {"code": "hub_untrusted", "params": {}}
    assert RecordingHandler.requests == []


def test_the_pinned_agent_reaches_the_hub(tls_server, config_path):
    """With the right pin the upgrade request leaves the machine; this server
    speaks no websocket, so the answer is a refusal to upgrade rather than a
    changed identity."""
    url, fingerprint = tls_server
    bind(config_path, url=url, fingerprint=fingerprint)
    agent = Agent(log=discard)

    agent.probe()

    assert agent.last_error()["code"] == "hub_unreachable"
    (request,) = RecordingHandler.requests
    assert request[0] == AGENT_WS_PATH


def test_a_wrong_fingerprint_link_is_refused_at_enrollment(tls_server, config_path):
    url, _ = tls_server
    link = link_for(
        {"urls": [url], "token": "ticket", "fp": WRONG_FINGERPRINT, "role": "agent"}
    )

    with pytest.raises(EnrollmentError) as refusal:
        enrollment.enroll(link)

    assert "certificate" in str(refusal.value)
    assert RecordingHandler.requests == []
    assert not enrollment.is_bound()


def canned_client(status, data=b"", headers=None):
    """A client whose one answer is canned at the ``_request`` seam.

    Header names are lower-cased the way ``_request`` hands them up.
    """
    made = BindingHttpClient(gateway_url="http://hub")
    named = {name.lower(): value for name, value in (headers or {}).items()}

    def request(method, url, *, body=None, headers=None):
        return status, data, named

    made._request = request
    return made


def refusal(code: str, params=None) -> bytes:
    return json.dumps({"detail": {"code": code, "params": params or {}}}).encode()


@pytest.mark.parametrize("status", [401, 403, 404, 409, 422, 500])
def test_an_error_status_with_a_code_raises_the_detail(status):
    with pytest.raises(GatewayRefusedDetail) as caught:
        canned_client(status, refusal("ticket_spent")).join(JOIN_PAYLOAD)

    assert caught.value.code == "ticket_spent"
    assert caught.value.params == {}


def test_a_protocol_refusal_carries_its_numbers():
    body = refusal("protocol_too_new", {"peer": 2, "hub": 1, "min": 1})

    with pytest.raises(GatewayRefusedDetail) as caught:
        canned_client(409, body).join(JOIN_PAYLOAD)

    assert caught.value.code == "protocol_too_new"
    assert caught.value.params == {"peer": 2, "hub": 1, "min": 1}


def test_a_detail_without_params_reads_as_empty_params():
    body = json.dumps({"detail": {"code": "ticket_spent", "params": "words"}}).encode()

    with pytest.raises(GatewayRefusedDetail) as caught:
        canned_client(401, body).join(JOIN_PAYLOAD)

    assert caught.value.params == {}


@pytest.mark.parametrize(
    "body",
    [b"", b"not json", b'{"detail": "words"}', b'{"detail": {}}', b'{"detail": [1]}'],
)
def test_an_error_status_without_a_code_raises_unreachable(body):
    with pytest.raises(GatewayUnreachable) as caught:
        canned_client(409, body).join(JOIN_PAYLOAD)

    assert not isinstance(caught.value, GatewayRefusedDetail)


@pytest.mark.parametrize("status", [400, 401, 404, 418, 500, 503])
def test_other_error_statuses_raise_unreachable(status):
    with pytest.raises(GatewayUnreachable) as caught:
        canned_client(status).leave("d1", "t1")

    assert not isinstance(caught.value, GatewayRefusedDetail)


def test_invalid_json_in_a_success_raises_unreachable():
    with pytest.raises(GatewayUnreachable):
        canned_client(200, b"not json").join(JOIN_PAYLOAD)


def test_an_empty_success_body_reads_as_an_empty_object():
    assert canned_client(200, b"  ").join(JOIN_PAYLOAD) == {}


def test_a_leave_ignores_the_reply_body():
    assert canned_client(200, b'{"anything": 1}').leave("d1", "t1") is None


def test_a_dead_port_raises_unreachable():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    made = BindingHttpClient(gateway_url=f"http://127.0.0.1:{port}")

    with pytest.raises(GatewayUnreachable):
        made.join(JOIN_PAYLOAD)
