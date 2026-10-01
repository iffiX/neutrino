"""Setup reaches its own panel by the scheme the panel serves.

The enrolment link for this machine's agent is asked of the panel on
loopback. Over HTTPS that call trusts the hub's own authority and nothing
else, and the address setup prints names the scheme too.
"""

import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from neutrino_hub.cli import setup
from neutrino_hub.web.panel_tls import ensure_authority, write_served_leaf
from tests.conftest import unlock_vault


class Answer(BaseHTTPRequestHandler):
    """Answers every POST with one JSON body."""

    def do_POST(self):  # noqa: N802 - the name http.server calls
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({"is_authenticated": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *arguments):
        return None


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """A loopback HTTPS server serving a certificate the authority signed."""
    unlock_vault(monkeypatch, tmp_path)
    authority = {
        "certificate_path": tmp_path / "authority.pem",
        "sealed_key_path": tmp_path / "authority_key.sealed",
    }
    ensure_authority(**authority, host_name="argon")
    certificate = tmp_path / "leaf.pem"
    key = tmp_path / "leaf_key.pem"
    write_served_leaf(
        ["127.0.0.1"],
        **authority,
        served_certificate_path=certificate,
        served_key_path=key,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate), str(key))
    server = HTTPServer(("127.0.0.1", 0), Answer)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], authority["certificate_path"]
    server.shutdown()
    server.server_close()


def test_a_post_over_https_trusts_the_hub_authority(panel, monkeypatch):
    port, authority = panel
    monkeypatch.setattr(setup, "WEB_PANEL_TLS_AUTHORITY_PATH", authority)

    answer = setup._post(f"https://127.0.0.1:{port}/api/hub/auth/login", {})

    assert json.loads(answer.read()) == {"is_authenticated": True}


def test_a_post_over_https_refuses_a_panel_the_authority_did_not_sign(
    panel, monkeypatch, tmp_path
):
    port, _ = panel
    other = {
        "certificate_path": tmp_path / "other.pem",
        "sealed_key_path": tmp_path / "other_key.sealed",
    }
    ensure_authority(**other, host_name="argon")
    monkeypatch.setattr(
        setup, "WEB_PANEL_TLS_AUTHORITY_PATH", other["certificate_path"]
    )

    with pytest.raises(OSError):
        setup._post(f"https://127.0.0.1:{port}/api/hub/auth/login", {})


@pytest.mark.parametrize(
    "is_https, https_port, expected",
    [
        (False, 443, "http://192.168.8.1:8080"),
        (True, 443, "https://192.168.8.1"),
        (True, 8443, "https://192.168.8.1:8443"),
    ],
)
def test_the_printed_address_is_the_port_a_browser_ends_up_on(
    monkeypatch, is_https, https_port, expected
):
    monkeypatch.setattr(setup, "is_https_enabled", lambda: is_https)
    monkeypatch.setattr(setup, "_configured_port", lambda: 8080)
    monkeypatch.setattr(setup, "_configured_https_port", lambda: https_port)
    monkeypatch.setattr(setup, "_panel_host", lambda: "192.168.8.1")

    assert setup._panel_url() == expected
    assert setup._panel_http_url() == "http://192.168.8.1:8080"


@pytest.mark.parametrize(
    "is_https, expected",
    [(False, "http://127.0.0.1:8080"), (True, "https://127.0.0.1:8443")],
)
def test_loopback_reaches_the_port_that_serves_the_panel(
    monkeypatch, is_https, expected
):
    monkeypatch.setattr(setup, "is_https_enabled", lambda: is_https)
    monkeypatch.setattr(setup, "_configured_port", lambda: 8080)
    monkeypatch.setattr(setup, "_configured_https_port", lambda: 8443)

    assert setup._loopback_url() == expected
