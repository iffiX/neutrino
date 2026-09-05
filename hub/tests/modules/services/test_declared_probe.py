"""The declared-service probes, against listeners this test runs itself.

Three states share one shape and must not share one rendering: a service
nobody has probed yet, a service that answered, and one that was probed and
did not answer. Only the last is a failure, and it says why.
"""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from neutrino_hub.modules.services.config import DeclaredService
from neutrino_hub.modules.services.probe import DeclaredServiceProbe

PROBE_TIMEOUT_S = 1.0


def declared(kind: str, port: int, **extra) -> DeclaredService:
    """One declared service pointing at this machine.

    Args:
        kind: The service kind.
        port: Where the test's listener answers.

    Returns:
        The record, with the http defaults an added record would carry.
    """
    fields = {"scheme": "http", "path": "/"} if kind == "http" else {}
    return DeclaredService(
        id=f"{kind}_{port}",
        name=kind,
        kind=kind,
        host="127.0.0.1",
        port=port,
        **{**fields, **extra},
    )


@pytest.fixture()
def tcp_listener():
    server = socket.create_server(("127.0.0.1", 0))
    try:
        yield server.getsockname()[1]
    finally:
        server.close()


class _PageHandler(BaseHTTPRequestHandler):
    """Answers /down the way a broken server does, /locked with a refusal."""

    def do_GET(self):
        if self.path == "/down":
            body = b"no"
            self.send_response(503)
        elif self.path == "/locked":
            body = b"who are you"
            self.send_response(401)
        else:
            body = b"hello"
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *arguments):
        return


@pytest.fixture()
def http_listener():
    server = HTTPServer(("127.0.0.1", 0), _PageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _closed_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as server:
        return server.getsockname()[1]


@pytest.mark.parametrize("kind", ["samba", "generic_tcp"])
def test_a_listening_port_reads_healthy(tcp_listener, kind):
    result = DeclaredServiceProbe(timeout_s=PROBE_TIMEOUT_S).probe(
        declared(kind, tcp_listener)
    )
    assert result.is_healthy is True
    assert result.detail_code is None
    assert result.checked_at


def test_a_closed_port_reads_connect_failed():
    result = DeclaredServiceProbe(timeout_s=PROBE_TIMEOUT_S).probe(
        declared("generic_tcp", _closed_port())
    )
    assert result.is_healthy is False
    assert result.detail_code == "connect_failed"


def test_an_http_answer_below_500_reads_healthy(http_listener):
    """A 401 comes from something alive enough to refuse."""
    result = DeclaredServiceProbe(timeout_s=PROBE_TIMEOUT_S).probe(
        declared("http", http_listener, path="/locked")
    )
    assert result.is_healthy is True


def test_an_http_server_error_reads_server_error(http_listener):
    result = DeclaredServiceProbe(timeout_s=PROBE_TIMEOUT_S).probe(
        declared("http", http_listener, path="/down")
    )
    assert result.is_healthy is False
    assert result.detail_code == "server_error"


def test_an_http_probe_that_reaches_nothing_reads_connect_failed():
    result = DeclaredServiceProbe(timeout_s=PROBE_TIMEOUT_S).probe(
        declared("http", _closed_port())
    )
    assert result.is_healthy is False
    assert result.detail_code == "connect_failed"


def test_a_service_never_probed_reads_as_unknown(monkeypatch):
    probe = DeclaredServiceProbe()
    monkeypatch.setattr(
        DeclaredServiceProbe,
        "refresh",
        lambda self, services: setattr(self, "_probed_at", time.monotonic()),
    )
    probe.results([])

    results = probe.results([declared("generic_tcp", 1)])

    assert results[0].is_healthy is None
    assert results[0].checked_at is None
    assert results[0].detail_code is None


def test_the_first_read_probes_however_young_the_machine_is(monkeypatch):
    probe = DeclaredServiceProbe()
    monkeypatch.setattr(time, "monotonic", lambda: 3.0)
    probed: list = []
    monkeypatch.setattr(
        DeclaredServiceProbe,
        "refresh",
        lambda self, services: probed.append(services) or [],
    )

    probe.results([declared("generic_tcp", 1)])

    assert len(probed) == 1


def test_a_second_read_inside_the_window_does_not_probe_again(monkeypatch):
    probe = DeclaredServiceProbe()
    service = declared("generic_tcp", 1)
    monkeypatch.setattr(
        DeclaredServiceProbe,
        "refresh",
        lambda self, services: setattr(self, "_probed_at", time.monotonic()),
    )
    probe.results([service])
    probed: list = []
    monkeypatch.setattr(
        DeclaredServiceProbe, "refresh", lambda self, services: probed.append(services)
    )

    probe.results([service])

    assert probed == []


def test_a_read_after_the_window_probes_again(monkeypatch):
    probe = DeclaredServiceProbe()
    service = declared("generic_tcp", 1)
    now = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    monkeypatch.setattr(
        DeclaredServiceProbe,
        "refresh",
        lambda self, services: setattr(self, "_probed_at", time.monotonic()),
    )
    probe.results([service])
    probed: list = []
    monkeypatch.setattr(
        DeclaredServiceProbe, "refresh", lambda self, services: probed.append(services)
    )

    now = 111.0
    probe.results([service])

    assert len(probed) == 1


def test_probing_one_service_replaces_its_cached_result(tcp_listener):
    probe = DeclaredServiceProbe(timeout_s=PROBE_TIMEOUT_S)
    service = declared("generic_tcp", tcp_listener)
    probe.refresh([service])
    assert probe.cached(service.id).is_healthy is True

    down = declared("generic_tcp", _closed_port())
    down.id = service.id
    result = probe.probe(down)

    assert result.is_healthy is False
    assert probe.cached(service.id).is_healthy is False
