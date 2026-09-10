"""The channel's judgments: the certificate pin, and every status mapping.

The pin runs against a real TLS socket whose certificate is generated at
test runtime with the ``openssl`` binary — no key material lives in the
repository: the right fingerprint talks, the wrong one is refused before a
single request byte is sent, and a bound agent beating against the wrong
certificate unbinds the way a refused token does. The status mappings
replace ``_request`` with a canned answer, so each status and body shape is
judged in-process.
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
from neutrino_agent.constants import AGENT_WS_PATH
from neutrino_agent.core.loop import Agent
from neutrino_agent.core.channel import GatewayHttpChannel
from neutrino_agent.exceptions import (
    EnrollmentError,
    GatewayRefused,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
    GatewayWireStale,
)
from tests.conftest import discard, link_for

WRONG_FINGERPRINT = "0" * 64


class RecordingHandler(BaseHTTPRequestHandler):
    """Answers every POST with an empty JSON object and records the path."""

    requests: list = []

    def do_GET(self):
        RecordingHandler.requests.append((self.path, b""))
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

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


def test_the_pinned_agent_reaches_the_hub(tls_server, config_path):
    """With the right pin the upgrade request leaves the machine; this server
    speaks no websocket, so the answer is a refusal to upgrade rather than a
    changed identity."""
    url, fingerprint = tls_server
    config_path.write_text(
        json.dumps({"gateway_url": url, "token": "tok", "fingerprint": fingerprint})
    )
    agent = Agent(log=discard)

    agent.probe()

    assert agent.last_error()["code"] == "hub_unreachable"
    (request,) = RecordingHandler.requests
    assert request[0] == AGENT_WS_PATH


def test_a_wrong_fingerprint_link_is_refused_at_enrollment(tls_server, config_path):
    url, _ = tls_server
    link = link_for({"urls": [url], "token": "ticket", "fp": WRONG_FINGERPRINT})

    with pytest.raises(EnrollmentError) as refusal:
        enrollment.enroll(link)

    assert "certificate" in str(refusal.value)
    assert RecordingHandler.requests == []
    assert "gateway_url" not in enrollment.load_config()


def canned_channel(status, data=b"", headers=None):
    """A channel whose one answer is canned at the ``_request`` seam.

    Header names are lower-cased the way ``_request`` hands them up.
    """
    made = GatewayHttpChannel(gateway_url="http://hub", token="tok")
    named = {name.lower(): value for name, value in (headers or {}).items()}

    def request(method, url, *, body=None, headers=None):
        return status, data, named

    made._request = request
    return made


@pytest.mark.parametrize("status", [401, 403])
def test_post_status_401_or_403_raises_refused(status):
    with pytest.raises(GatewayRefused):
        canned_channel(status).post("/api/agent/heartbeat", {})


def test_post_409_wire_stale_raises_wire_stale_with_both_generations():
    body = json.dumps(
        {
            "detail": {
                "code": "agent_wire_stale",
                "params": {"hub_wire": 3, "agent_wire": 2},
            }
        }
    ).encode()

    with pytest.raises(GatewayWireStale) as caught:
        canned_channel(409, body).post("/api/agent/heartbeat", {})

    assert caught.value.hub_wire == 3
    assert caught.value.agent_wire == 2


def test_post_409_wire_stale_without_params_defaults_the_generations():
    body = json.dumps({"detail": {"code": "agent_wire_stale"}}).encode()

    with pytest.raises(GatewayWireStale) as caught:
        canned_channel(409, body).post("/api/agent/heartbeat", {})

    assert caught.value.hub_wire == 0
    assert caught.value.agent_wire == 0


def test_post_409_agent_newer_raises_version_refused_with_both_versions():
    body = json.dumps(
        {
            "detail": {
                "code": "agent_newer_than_hub",
                "params": {"hub_version": "0.1.0", "agent_version": "0.2.0"},
            }
        }
    ).encode()

    with pytest.raises(GatewayVersionRefused) as caught:
        canned_channel(409, body).post("/api/agent/heartbeat", {})

    assert caught.value.hub_version == "0.1.0"
    assert caught.value.agent_version == "0.2.0"


def test_post_409_with_another_code_raises_unreachable_naming_it():
    body = json.dumps({"detail": {"code": "somebody_new"}}).encode()

    with pytest.raises(GatewayUnreachable) as caught:
        canned_channel(409, body).post("/api/agent/heartbeat", {})

    assert "somebody_new" in str(caught.value)


@pytest.mark.parametrize(
    "body", [b"", b"not json", b'{"detail": "words"}', b'{"detail": {}}']
)
def test_post_409_without_a_code_raises_unreachable(body):
    with pytest.raises(GatewayUnreachable):
        canned_channel(409, body).post("/api/agent/heartbeat", {})


@pytest.mark.parametrize("status", [400, 404, 418, 500, 503])
def test_post_other_error_statuses_raise_unreachable(status):
    with pytest.raises(GatewayUnreachable):
        canned_channel(status).post("/api/agent/heartbeat", {})


def test_post_invalid_json_in_a_success_raises_unreachable():
    with pytest.raises(GatewayUnreachable):
        canned_channel(200, b"not json").post("/api/agent/heartbeat", {})


def test_post_an_empty_success_body_reads_as_an_empty_object():
    assert canned_channel(200, b"  ").post("/api/agent/heartbeat", {}) == {}


def test_post_download_writes_the_bytes_and_returns_the_checksum(tmp_path):
    made = canned_channel(200, b"pkg", headers={"X-Checksum-Sha256": "abc123"})
    destination = tmp_path / "update.deb"

    named = made.post_download("/api/agent/package", {}, str(destination))

    assert named == "abc123"
    assert destination.read_bytes() == b"pkg"


def test_post_download_without_a_checksum_header_returns_empty(tmp_path):
    made = canned_channel(200, b"pkg")
    destination = tmp_path / "update.deb"

    assert made.post_download("/api/agent/package", {}, str(destination)) == ""


def test_post_download_an_unwritable_destination_raises_unreachable(tmp_path):
    made = canned_channel(200, b"pkg")
    destination = tmp_path / "missing" / "update.deb"

    with pytest.raises(GatewayUnreachable):
        made.post_download("/api/agent/package", {}, str(destination))


def test_post_download_a_refused_status_raises_refused(tmp_path):
    with pytest.raises(GatewayRefused):
        canned_channel(401).post_download(
            "/api/agent/package", {}, str(tmp_path / "update.deb")
        )


def test_post_a_dead_port_raises_unreachable():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    made = GatewayHttpChannel(gateway_url=f"http://127.0.0.1:{port}", token="tok")

    with pytest.raises(GatewayUnreachable):
        made.post("/api/agent/heartbeat", {})
