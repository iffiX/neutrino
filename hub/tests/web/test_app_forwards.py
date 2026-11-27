"""The hub's app forwards, over real loopback sockets and a fake far end.

What these pin: each request's head is written for the app, ``Host`` as
``127.0.0.1:<port>``, the forward's own ``Origin`` the same way and another
answered 403, every ``neutrino_session_`` cookie taken out and the others
kept, a second request on a kept connection read the same way, a body passed
by its length, ``Transfer-Encoding`` answered 411, an ``Upgrade`` carried
both ways; an ``https`` entry's TLS ended with the given context and opened
to the far end unchecked; the first free port of the range taken and a held
one skipped, an ``OSError`` with none free; a forward listening on ``[::1]``
beside its IPv4 address at the same port, a port whose ``[::1]`` is held
skipped, and a machine with no IPv6 loopback listening on IPv4 alone; a press keeping the forward it
has; a forward idle past the idle time closed with the transport forward it
started, and one with an open connection kept.
"""

import asyncio
import datetime
import socket
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from neutrino_hub.utils.loopback_listen import bind_ipv6_loopback, has_ipv6_loopback
from neutrino_hub.web.app_forwards import (
    AppForwardTable,
    AppForwardTarget,
    rewrite_request_head,
)

needs_ipv6 = pytest.mark.skipif(
    not has_ipv6_loopback(), reason="the machine has no IPv6 loopback"
)

PORT = 19000
DEVICE = "d1"
APP_PORT = 8444


class FakeHubForwards:
    """The transport's loopback forwards: each machine port is a local server."""

    def __init__(self, listen: str):
        self.listen = listen
        self.asked: list = []
        self.stopped: list = []

    def address(self, binding_id, port):
        self.asked.append((binding_id, port))
        return self.listen

    def stop(self, binding_id, port):
        self.stopped.append((binding_id, port))
        return True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FarEnd:
    """The app behind the forward: it records what it reads and answers each
    request with a fixed body, or echoes once a connection upgraded."""

    def __init__(self):
        self.heads: list = []
        self.bodies: list = []

    async def serve(self, reader, writer):
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                self.heads.append(head)
                length = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                if b"upgrade: websocket" in head.lower():
                    writer.write(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
                    await writer.drain()
                    data = await reader.read(5)
                    writer.write(data[::-1])
                    await writer.drain()
                    continue
                self.bodies.append(await reader.readexactly(length))
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


def free_range(count: int = 4) -> int:
    """The first port of ``count`` free ports in a row on loopback."""
    for first in range(39100, 40000, count):
        sockets = []
        try:
            for port in range(first, first + count):
                held = socket.socket()
                sockets.append(held)
                held.bind(("127.0.0.1", port))
            return first
        except OSError:
            continue
        finally:
            for held in sockets:
                held.close()
    raise OSError("no free ports")


def self_signed(tmp_path) -> tuple:
    """A certificate and key for 127.0.0.1, as files."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def server_context(cert_path, key_path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


def unchecked_client() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def far_end_server(far: FarEnd, context=None):
    server = await asyncio.start_server(far.serve, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    return server, f"127.0.0.1:{port}"


def table_for(
    forwards,
    first: int,
    *,
    clock=None,
    tls=None,
    count: int = 4,
    is_ipv6=has_ipv6_loopback,
):
    return AppForwardTable(
        hub_forwards=forwards,
        tls_context_of=lambda: tls,
        listen_host="127.0.0.1",
        clock=clock or Clock(),
        port_min=first,
        port_max=first + count - 1,
        idle_s=60,
        sweep_s=3600,
        is_ipv6=is_ipv6,
    )


async def ask(
    port: int, requests: list, *, context=None, host: str = "127.0.0.1"
) -> bytes:
    """Send requests on one connection and read until it closes or quiets."""
    reader, writer = await asyncio.open_connection(
        host, port, ssl=context, server_hostname="" if context else None
    )
    answers = b""
    for request in requests:
        writer.write(request)
        await writer.drain()
        try:
            answers += await asyncio.wait_for(reader.read(4096), 2)
        except asyncio.TimeoutError:
            break
    writer.close()
    return answers


def test_a_head_is_written_for_the_app():
    head = (
        b"POST /x HTTP/1.1\r\nHost: 192.168.1.10:19000\r\n"
        b"Origin: http://192.168.1.10:19000\r\n"
        b"Cookie: neutrino_session_abc=s; neutrino_0123=a; neutrino_session_=t; k=v\r\n"
        b"Content-Length: 3\r\n\r\n"
    )

    written = rewrite_request_head(head, scheme="http", port=PORT)

    assert written.status == 0
    assert written.length == 3
    assert written.head == (
        b"POST /x HTTP/1.1\r\nHost: 127.0.0.1:19000\r\n"
        b"Origin: http://127.0.0.1:19000\r\n"
        b"Cookie: neutrino_0123=a; k=v\r\n"
        b"Content-Length: 3\r\n\r\n"
    )


def test_another_origin_is_refused_403():
    head = b"GET / HTTP/1.1\r\nHost: hub:19000\r\nOrigin: http://evil.example\r\n\r\n"

    assert rewrite_request_head(head, scheme="http", port=PORT).status == 403


def test_an_https_origin_drops_its_default_port():
    head = b"GET / HTTP/1.1\r\nHost: hub\r\nOrigin: https://hub:443\r\n\r\n"

    written = rewrite_request_head(head, scheme="https", port=PORT)

    assert b"Origin: https://127.0.0.1:19000\r\n" in written.head


def test_a_cookie_of_the_panel_alone_leaves_no_cookie_line():
    head = b"GET / HTTP/1.1\r\nHost: h\r\nCookie: neutrino_session_x=1\r\n\r\n"

    assert b"Cookie" not in rewrite_request_head(head, scheme="http", port=PORT).head


@pytest.mark.parametrize(
    "line",
    [b"Transfer-Encoding: chunked", b"Content-Length: many", b"Content-Length: -1"],
)
def test_a_body_with_no_length_is_refused_411(line):
    head = b"POST / HTTP/1.1\r\nHost: h\r\n" + line + b"\r\n\r\n"

    assert rewrite_request_head(head, scheme="http", port=PORT).status == 411


def test_an_upgrade_is_told_by_its_two_headers():
    head = (
        b"GET /ws HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\n"
        b"Connection: keep-alive, Upgrade\r\n\r\n"
    )
    plain = b"GET / HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\n\r\n"

    assert rewrite_request_head(head, scheme="http", port=PORT).is_upgrade
    assert not rewrite_request_head(plain, scheme="http", port=PORT).is_upgrade


def test_requests_on_a_kept_connection_reach_the_app_written_for_it():
    async def scenario():
        far = FarEnd()
        server, listen = await far_end_server(far)
        forwards = FakeHubForwards(listen)
        first = free_range()
        table = table_for(forwards, first)
        target = AppForwardTarget("e", "http", DEVICE, "", APP_PORT)
        port = await table.open(target)
        answers = await ask(
            port,
            [
                b"GET / HTTP/1.1\r\nHost: hub:1\r\nCookie: neutrino_session_a=b\r\n\r\n",
                b"POST /p HTTP/1.1\r\nHost: hub:1\r\nContent-Length: 4\r\n\r\nbody",
            ],
        )
        await table.close_all()
        server.close()
        return port, first, answers, far, forwards

    port, first, answers, far, forwards = asyncio.run(scenario())

    assert port == first
    assert answers.count(b"HTTP/1.1 200 OK") == 2
    assert [head.split(b"\r\n")[1] for head in far.heads] == [
        f"Host: 127.0.0.1:{port}".encode()
    ] * 2
    assert b"neutrino_session_" not in far.heads[0]
    assert far.bodies == [b"", b"body"]
    assert forwards.asked == [(DEVICE, APP_PORT)]
    assert forwards.stopped == [(DEVICE, APP_PORT)]


def test_a_refused_request_is_answered_by_the_forward_and_reaches_no_app():
    async def scenario():
        far = FarEnd()
        server, listen = await far_end_server(far)
        table = table_for(FakeHubForwards(listen), free_range())
        port = await table.open(AppForwardTarget("e", "http", DEVICE, "", APP_PORT))
        answers = await ask(
            port,
            [b"GET / HTTP/1.1\r\nHost: hub:1\r\nOrigin: http://other\r\n\r\n"],
        )
        await table.close_all()
        server.close()
        return answers, far

    answers, far = asyncio.run(scenario())

    assert answers.startswith(b"HTTP/1.1 403 Forbidden")
    assert far.heads == []


def test_an_upgrade_carries_bytes_both_ways_after_its_head():
    async def scenario():
        far = FarEnd()
        server, listen = await far_end_server(far)
        table = table_for(FakeHubForwards(listen), free_range())
        port = await table.open(AppForwardTarget("e", "http", DEVICE, "", APP_PORT))
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            b"GET /ws HTTP/1.1\r\nHost: hub:1\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\n\r\n"
        )
        await writer.drain()
        switched = await reader.readuntil(b"\r\n\r\n")
        writer.write(b"hello")
        await writer.drain()
        echoed = await asyncio.wait_for(reader.readexactly(5), 2)
        writer.close()
        await table.close_all()
        server.close()
        return switched, echoed

    switched, echoed = asyncio.run(scenario())

    assert switched.startswith(b"HTTP/1.1 101")
    assert echoed == b"olleh"


def test_an_https_entry_ends_tls_at_the_forward_and_opens_tls_to_the_app(tmp_path):
    async def scenario():
        cert_path, key_path = self_signed(tmp_path)
        far = FarEnd()
        server, listen = await far_end_server(far, server_context(cert_path, key_path))
        host, _, number = listen.rpartition(":")
        table = table_for(
            FakeHubForwards(listen),
            free_range(),
            tls=server_context(cert_path, key_path),
        )
        port = await table.open(AppForwardTarget("e", "https", "", host, int(number)))
        answers = await ask(
            port,
            [b"GET / HTTP/1.1\r\nHost: hub\r\nOrigin: https://hub\r\n\r\n"],
            context=unchecked_client(),
        )
        await table.close_all()
        server.close()
        return answers, far, port

    answers, far, port = asyncio.run(scenario())

    assert answers.startswith(b"HTTP/1.1 200 OK")
    assert f"Origin: https://127.0.0.1:{port}".encode() in far.heads[0]


def test_an_https_entry_with_no_tls_context_is_refused():
    async def scenario():
        table = table_for(FakeHubForwards("127.0.0.1:1"), free_range())
        await table.open(AppForwardTarget("e", "https", "", "h", 443))

    with pytest.raises(RuntimeError):
        asyncio.run(scenario())


def test_a_held_port_is_skipped_and_a_full_range_is_an_os_error():
    async def scenario():
        first = free_range(2)
        held = socket.socket()
        held.bind(("127.0.0.1", first))
        held.listen()
        table = table_for(FakeHubForwards("127.0.0.1:1"), first, count=2)
        try:
            port = await table.open(AppForwardTarget("a", "http", "", "h", 80))
            again = await table.open(AppForwardTarget("a", "http", "", "h", 80))
            with pytest.raises(OSError):
                await table.open(AppForwardTarget("b", "http", "", "h", 80))
        finally:
            held.close()
            await table.close_all()
        return first, port, again

    first, port, again = asyncio.run(scenario())

    assert port == again == first + 1


@needs_ipv6
def test_a_forward_also_listens_on_the_ipv6_loopback_at_its_port():
    async def scenario():
        far = FarEnd()
        server, listen = await far_end_server(far)
        table = table_for(FakeHubForwards(listen), free_range())
        port = await table.open(AppForwardTarget("e", "http", DEVICE, "", APP_PORT))
        answers = await ask(
            port,
            [b"GET / HTTP/1.1\r\nHost: localhost:1\r\n\r\n"],
            host="::1",
        )
        await table.close_all()
        server.close()
        return port, answers, far

    port, answers, far = asyncio.run(scenario())

    assert answers.startswith(b"HTTP/1.1 200 OK")
    assert far.heads[0].split(b"\r\n")[1] == f"Host: 127.0.0.1:{port}".encode()


@needs_ipv6
def test_a_port_whose_ipv6_loopback_is_held_is_skipped():
    async def scenario():
        first = free_range(2)
        held = bind_ipv6_loopback(first)
        held.listen()
        table = table_for(FakeHubForwards("127.0.0.1:1"), first, count=2)
        try:
            port = await table.open(AppForwardTarget("a", "http", "", "h", 80))
        finally:
            held.close()
            await table.close_all()
        return first, port

    first, port = asyncio.run(scenario())

    assert port == first + 1


def test_a_machine_with_no_ipv6_loopback_listens_on_the_ipv4_address_alone():
    async def scenario():
        table = table_for(
            FakeHubForwards("127.0.0.1:1"), free_range(), is_ipv6=_no_ipv6
        )
        port = await table.open(AppForwardTarget("a", "http", "", "h", 80))
        bound = [held.getsockname()[0] for held in table._forwards["a"].server.sockets]
        await table.close_all()
        return bound

    assert asyncio.run(scenario()) == ["127.0.0.1"]


def _no_ipv6() -> bool:
    return False


def test_an_idle_forward_ends_and_a_busy_one_stays():
    async def scenario():
        far = FarEnd()
        server, listen = await far_end_server(far)
        forwards = FakeHubForwards(listen)
        clock = Clock()
        table = table_for(forwards, free_range(), clock=clock)
        idle = await table.open(AppForwardTarget("idle", "http", DEVICE, "", 1))
        busy = await table.open(AppForwardTarget("busy", "http", DEVICE, "", 2))
        reader, writer = await asyncio.open_connection("127.0.0.1", busy)
        writer.write(b"GET / HTTP/1.1\r\nHost: h\r\n\r\n")
        await writer.drain()
        await reader.readuntil(b"ok")
        clock.now += 59
        early = await table.sweep()
        clock.now += 2
        ended = await table.sweep()
        kept = table.port_of("busy")
        writer.close()
        await asyncio.sleep(0.1)
        clock.now += 61
        later = await table.sweep()
        await table.close_all()
        server.close()
        return early, ended, kept, busy, later, forwards, idle

    early, ended, kept, busy, later, forwards, idle = asyncio.run(scenario())

    assert early == []
    assert ended == ["idle"]
    assert kept == busy
    assert later == ["busy"]
    assert forwards.stopped == [(DEVICE, 1), (DEVICE, 2)]
