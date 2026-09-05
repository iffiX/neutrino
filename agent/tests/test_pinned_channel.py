"""Fingerprint pinning against a real TLS socket.

The certificate is generated at test runtime with the ``openssl`` binary —
no key material lives in the repository. What these pin: the right
fingerprint talks, the wrong one is refused before a single request byte is
sent, and a bound agent beating against the wrong certificate unbinds the
way a refused token does.
"""

import base64
import hashlib
import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.core.loop import Agent
from neutrino_agent.core.channel import GatewayHttpChannel, GatewayUntrusted

WRONG_FINGERPRINT = "0" * 64


class RecordingHandler(BaseHTTPRequestHandler):
    """Answers every POST with an empty JSON object and records the path."""

    requests: list = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        RecordingHandler.requests.append((self.path, body))
        answer = b"{}"
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


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(path))
    return path


def link_for(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def discard(message: str) -> None:
    """Swallow the agent's log lines."""


def test_the_pinned_fingerprint_talks(tls_server):
    url, fingerprint = tls_server
    channel = GatewayHttpChannel(gateway_url=url, token="tok", fingerprint=fingerprint)

    reply = channel.post("/api/agent/heartbeat", {"hostname": "box"})

    assert reply == {}
    assert len(RecordingHandler.requests) == 1
    path, body = RecordingHandler.requests[0]
    assert path == "/api/agent/heartbeat"
    assert json.loads(body)["token"] == "tok"


def test_the_pinned_connection_floors_at_tls_1_2():
    from neutrino_agent.core.channel import _PinnedHttpsConnection

    connection = _PinnedHttpsConnection(
        "127.0.0.1", 1, fingerprint="0" * 64, timeout=1.0
    )
    assert connection._context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_a_wrong_fingerprint_is_refused_before_anything_is_sent(tls_server):
    url, _ = tls_server
    channel = GatewayHttpChannel(
        gateway_url=url, token="tok", fingerprint=WRONG_FINGERPRINT
    )

    with pytest.raises(GatewayUntrusted):
        channel.post("/api/agent/heartbeat", {"hostname": "box"})

    assert RecordingHandler.requests == []


def test_an_https_url_without_a_pin_sends_nothing(tls_server):
    url, _ = tls_server
    channel = GatewayHttpChannel(gateway_url=url, token="tok")

    with pytest.raises(GatewayUntrusted):
        channel.post("/api/agent/heartbeat", {"hostname": "box"})

    assert RecordingHandler.requests == []


def test_three_mismatched_beats_unbind_the_machine(tls_server, config_path):
    """A hub reset or reinstalled answers with a new certificate for good, so
    three beats against the wrong one drop the binding — with nothing ever
    sent, and the reason naming the changed identity."""
    url, _ = tls_server
    config_path.write_text(
        json.dumps(
            {"gateway_url": url, "token": "tok", "fingerprint": WRONG_FINGERPRINT}
        )
    )
    agent = Agent(log=discard)

    for _ in range(3):
        agent.run_once()

    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert agent.last_error() == {
        "code": "self_unbound",
        "params": {"cause": "hub_untrusted"},
    }
    assert RecordingHandler.requests == []


def test_two_mismatched_beats_keep_the_binding(tls_server, config_path):
    url, _ = tls_server
    config_path.write_text(
        json.dumps(
            {"gateway_url": url, "token": "tok", "fingerprint": WRONG_FINGERPRINT}
        )
    )
    agent = Agent(log=discard)

    for _ in range(2):
        agent.run_once()

    assert agent._channel is not None
    assert "gateway_url" in json.loads(config_path.read_text())
    assert agent.last_error()["code"] == "hub_untrusted"
    assert RecordingHandler.requests == []


def test_the_pinned_agent_beats(tls_server, config_path):
    url, fingerprint = tls_server
    config_path.write_text(
        json.dumps({"gateway_url": url, "token": "tok", "fingerprint": fingerprint})
    )
    agent = Agent(log=discard)

    agent.run_once()

    assert agent.last_error() is None
    assert len(RecordingHandler.requests) == 1


def test_a_wrong_fingerprint_link_is_refused_at_enrollment(tls_server, config_path):
    url, _ = tls_server
    link = link_for({"urls": [url], "token": "ticket", "fp": WRONG_FINGERPRINT})

    with pytest.raises(enrollment.EnrollmentError) as refusal:
        enrollment.enroll(link)

    assert "certificate" in str(refusal.value)
    assert RecordingHandler.requests == []
    assert "gateway_url" not in enrollment.load_config()
