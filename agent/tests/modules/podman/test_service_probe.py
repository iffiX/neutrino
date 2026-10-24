"""The service probe against real servers on loopback: what each answers as,
and a result kept per container start."""

import shutil
import socket
import ssl
import subprocess
import threading
import time

import pytest

from neutrino_agent.modules.podman.service_probe import (
    PodmanServiceProbe,
    detect_service,
)

LOOPBACK = "127.0.0.1"
# Short waits, so a silent server costs the suite under a second.
READ_S = 0.1
STEP_S = 0.3


class LoopbackServer:
    """Accepts on a loopback port and hands each connection to a handler in
    a thread of its own, counting the connections."""

    def __init__(self, handler, listener=None):
        self.handler = handler
        self.connections = 0
        self.listener = listener or socket.socket()
        if listener is None:
            self.listener.bind((LOOPBACK, 0))
        self.port = self.listener.getsockname()[1]
        self._thread = None

    def start(self):
        self.listener.listen(16)
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self.listener.close()

    def _accept(self):
        while True:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(
                target=self._serve, args=(connection,), daemon=True
            ).start()

    def _serve(self, connection):
        with connection:
            connection.settimeout(2)
            try:
                self.handler(connection)
            except (OSError, ssl.SSLError):
                pass


def read_request(connection):
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = connection.recv(1024)
        if not chunk:
            return b""
        request += chunk
    return request


def answer_http(connection):
    if read_request(connection):
        connection.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n")


def answer_bad_request(connection):
    if read_request(connection):
        connection.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")


def speak_first(connection):
    connection.sendall(b"SSH-2.0-OpenSSH_9.6\r\n")
    read_request(connection)


def stay_silent(connection):
    while connection.recv(1024):
        pass


def tls_answering(context):
    def answer(connection):
        with context.wrap_socket(connection, server_side=True) as secure:
            answer_http(secure)

    return answer


def plain_or_tls(context):
    """A web server with TLS on the port that answers a plain request with
    400, as nginx does."""

    def answer(connection):
        first = connection.recv(1, socket.MSG_PEEK)
        if first == b"\x16":
            tls_answering(context)(connection)
        else:
            answer_bad_request(connection)

    return answer


@pytest.fixture(scope="module")
def tls_context(tmp_path_factory):
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not installed; the https server needs a certificate")
    directory = tmp_path_factory.mktemp("certificate")
    certificate_path = directory / "certificate.pem"
    key_path = directory / "key.pem"
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
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate_path), str(key_path))
    return context


@pytest.fixture
def serving():
    servers = []

    def start(handler, listener=None):
        server = LoopbackServer(handler, listener).start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.stop()


def detect(port):
    return detect_service(LOOPBACK, port, read_s=READ_S, step_s=STEP_S)


def test_a_plain_web_server_is_http(serving):
    assert detect(serving(answer_http).port) == "http"


def test_a_web_server_with_a_self_signed_certificate_is_https(serving, tls_context):
    assert detect(serving(tls_answering(tls_context)).port) == "https"


def test_a_server_that_speaks_first_is_tcp_and_gets_no_request(serving):
    server = serving(speak_first)

    assert detect(server.port) == "tcp"
    assert server.connections == 1


def test_a_silent_server_is_tcp_after_every_step(serving):
    server = serving(stay_silent)

    assert detect(server.port) == "tcp"
    assert server.connections == 3


def test_a_tls_port_that_answers_a_plain_request_with_400_is_https(
    serving, tls_context
):
    assert detect(serving(plain_or_tls(tls_context)).port) == "https"


def test_a_plain_400_with_no_tls_behind_it_stays_http(serving):
    assert detect(serving(answer_bad_request).port) == "http"


def test_a_port_that_accepts_nothing_is_not_detected_yet():
    listener = socket.socket()
    listener.bind((LOOPBACK, 0))
    try:
        assert detect(listener.getsockname()[1]) == ""
    finally:
        listener.close()


def probe(**overrides):
    fields = {"read_s": READ_S, "step_s": STEP_S, "wait_s": 2.0}
    fields.update(overrides)
    return PodmanServiceProbe(**fields)


def test_a_result_is_kept_per_container_start_and_port(serving):
    server = serving(answer_http)
    first = ("id", "100", "", server.port)
    again = ("id", "200", "", server.port)
    detector = probe()

    assert detector.detected([(first, LOOPBACK, server.port)]) == {first: "http"}
    assert detector.detected([(first, LOOPBACK, server.port)]) == {first: "http"}
    assert server.connections == 2
    assert detector.detected([(again, LOOPBACK, server.port)]) == {again: "http"}
    assert server.connections == 4


def test_a_container_gone_from_the_targets_is_detected_again(serving):
    server = serving(answer_http)
    key = ("id", "100", "", server.port)
    detector = probe()

    detector.detected([(key, LOOPBACK, server.port)])
    assert detector.detected([]) == {}
    assert detector.detected([(key, LOOPBACK, server.port)]) == {key: "http"}
    assert server.connections == 4


def test_a_port_not_accepting_yet_is_tried_again_at_the_next_report(serving):
    listener = socket.socket()
    listener.bind((LOOPBACK, 0))
    port = listener.getsockname()[1]
    key = ("id", "100", "", port)
    detector = probe()

    assert detector.detected([(key, LOOPBACK, port)]) == {}
    serving(answer_http, listener)
    assert detector.detected([(key, LOOPBACK, port)]) == {key: "http"}


def test_a_report_waits_no_longer_than_its_bound(serving):
    """A silent port outlasts the wait; its result lands for a later report,
    and no second probe of it starts meanwhile."""
    server = serving(stay_silent)
    key = ("id", "100", "", server.port)
    detector = probe(wait_s=0.05)

    started = time.monotonic()
    assert detector.detected([(key, LOOPBACK, server.port)]) == {}
    assert time.monotonic() - started < 0.5
    deadline = time.monotonic() + 5
    found = {}
    while not found and time.monotonic() < deadline:
        found = detector.detected([(key, LOOPBACK, server.port)])
        time.sleep(0.05)
    assert found == {key: "tcp"}
    assert server.connections == 3
