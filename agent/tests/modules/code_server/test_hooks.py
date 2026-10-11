"""code-server's hooks: the release, each instance's socket, the login cookie.

What these pin: the release's one directory lands as ``release``, read-only,
a new one replaces the one before, and an archive that is not a release is
the module's own download failure; the version is read from the release; a
socket path the system cannot bind is refused before anything is written;
each instance runs the launcher as the account on its socket with
code-server's own login off, in the account's own run directory, with the
account's home and shell in a Mac's environment; and the forwarder, driven
against a fake code-server on a socket, listens on ``127.0.0.1`` alone,
trades a token once for a cookie of the port's own name and a redirect to
the same address without the token, refuses a token that does not verify
or a cookie that is forged or expired, passes a request with a good cookie
on with its body, relays a WebSocket both ways, and answers 502 for a
code-server that does not answer.
"""

import io
import os
import shutil
import socket
import socketserver
import stat
import tarfile
import tempfile
import threading
import time

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server.config import cookie_key
from neutrino_agent.modules.code_server.hooks import (
    CodeServerHooks,
    address_without_token,
    cookie_name,
    installed_version,
    is_login_valid,
    launcher_path,
    mint_login,
    node_path,
    unpack_release,
)
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.http_forward import InstanceForwarder, mint_token
from neutrino_agent.platforms.base import AgentPlatform

SECRET = "instance-secret"  # scan: allow
NOW = 1_800_000_000
CONFIG = {"instances": [{"account": "ann", "port": 8443, "secret": SECRET}]}
ANN = AccountEntry(1001, 1002, "/home/ann", "/bin/bash")
MAC_ANN = AccountEntry(501, 20, "/Users/ann", "")


class Platform(AgentPlatform):
    def __init__(self, os_name="linux"):
        self.os_name = os_name


def release_archive(path, version="4.140.0", *, top=None) -> str:
    top = top or f"code-server-{version}-linux-amd64"
    members = {
        f"{top}/bin/code-server": b"#!/bin/sh\n",
        f"{top}/lib/node": b"\x7fELF",
        f"{top}/package.json": (
            '{"name": "code-server", "version": "%s"}' % version
        ).encode(),
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    return str(path)


def hooks_for(os_name, module_dir, **kwargs) -> CodeServerHooks:
    hooks = CodeServerHooks(platform=Platform(os_name), log=lambda line: None, **kwargs)
    machine = ServiceMachine(
        os_name=os_name,
        module_dir=module_dir,
        record_dir=os.path.join(os.path.dirname(module_dir), "config", "code_server"),
        lookup_account=lambda account: ANN,
    )
    hooks.bind(machine, None)
    return hooks


# --- the release ---


def test_the_release_lands_as_release_read_only(tmp_path):
    root = str(tmp_path / "code_server")

    target = unpack_release(
        release_archive(tmp_path / "a.tar.gz"), package_kind="tar", root=root
    )

    assert target == os.path.join(root, "release")
    assert os.path.isfile(launcher_path(root))
    assert os.path.isfile(node_path(root))
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o555
    assert installed_version(root) == "4.140.0"
    assert sorted(os.listdir(root)) == ["release"]


def test_a_new_release_replaces_the_one_before_through_the_hooks(tmp_path):
    hooks = hooks_for("linux", str(tmp_path / "code_server"))
    assert hooks.verify() is False

    hooks.install(release_archive(tmp_path / "a.tar.gz"), "tar")
    hooks.install(release_archive(tmp_path / "b.tar.gz", "4.141.0"), "tar")

    assert hooks.verify() is True
    assert hooks.module_details() == {"version": "4.141.0"}


@pytest.mark.parametrize("kind", ["tar", "zip", "rar"])
def test_an_archive_that_is_not_one_is_a_failed_download(tmp_path, kind):
    junk = tmp_path / "junk"
    junk.write_bytes(b"not an archive")

    with pytest.raises(ModuleApplyError) as caught:
        unpack_release(str(junk), package_kind=kind, root=str(tmp_path / "r"))

    assert caught.value.code == "code_server_download_failed"


def test_an_archive_without_one_release_is_refused(tmp_path):
    archive = release_archive(tmp_path / "a.tar.gz", top="node-v22")

    with pytest.raises(ModuleApplyError) as caught:
        unpack_release(archive, package_kind="tar", root=str(tmp_path / "r"))

    assert caught.value.code == "code_server_download_failed"
    assert installed_version(str(tmp_path / "r")) == ""


# --- the configuration and the service ---


def test_a_socket_path_the_system_cannot_bind_is_refused():
    linux = hooks_for("linux", "/var/lib/neutrino/agent/code_server")
    mac = hooks_for(
        "darwin", "/Library/Application Support/Neutrino/agent/state/code_server"
    )

    linux.parse({"instances": [{"account": "a" * 50, "port": 8443, "secret": "s"}]})
    mac.parse({"instances": [{"account": "a" * 20, "port": 8443, "secret": "s"}]})
    for hooks, account in ((linux, "a" * 51), (mac, "a" * 21)):
        with pytest.raises(ModuleApplyError) as caught:
            hooks.parse(
                {"instances": [{"account": account, "port": 8443, "secret": "s"}]}
            )
        assert caught.value.code == "account_invalid"
        assert caught.value.params == {"account": account}


def test_a_missing_secret_is_refused_by_name():
    with pytest.raises(ModuleApplyError) as caught:
        hooks_for("linux", "/m").parse(
            {"instances": [{"account": "ann", "port": 8443, "secret": ""}]}
        )

    assert caught.value.code == "secret_missing"


def test_an_instance_runs_without_its_own_login_on_its_socket_in_its_run_directory():
    hooks = hooks_for("linux", "/m")
    config = hooks.parse(CONFIG)

    service = hooks.service(
        config.instances[0], ANN, hooks.record(config, config.instances[0], {})
    )

    assert service.command == (
        "/m/release/bin/code-server",
        "--socket",
        "/m/run/ann/code_server.sock",
        "--auth",
        "none",
        "--socket-mode",
        "600",
        "--disable-telemetry",
        "--disable-update-check",
    )
    assert service.environment == {}
    assert service.working_directory == "~"
    assert service.directories == ("/m/run/ann",)
    assert service.files == ()
    assert hooks.record(config, config.instances[0], {}) == {
        "account": "ann",
        "port": 8443,
        "secret": SECRET,
    }


def test_a_mac_instance_carries_the_accounts_home_and_shell():
    hooks = hooks_for("darwin", "/m")
    config = hooks.parse(CONFIG)

    with_shell = hooks.service(
        config.instances[0], AccountEntry(501, 20, "/Users/ann", "/bin/bash"), {}
    )
    without = hooks.service(config.instances[0], MAC_ANN, {})

    assert with_shell.environment == {
        "HOME": "/Users/ann",
        "USER": "ann",
        "LOGNAME": "ann",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    assert without.environment["SHELL"] == "/bin/zsh"


# --- the forwarder, against a fake code-server on a socket ---


class FakeCodeServer(socketserver.ThreadingUnixStreamServer):
    """An echo of every request, and a WebSocket echo, on a Unix socket."""

    daemon_threads = True

    def __init__(self, path):
        self.requests: list = []
        super().__init__(path, FakeCodeServerConnection)
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def stop(self):
        self.shutdown()
        self.server_close()


class FakeCodeServerConnection(socketserver.BaseRequestHandler):
    def handle(self):
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = self.request.recv(65536)
            if not chunk:
                return
            received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        self.server.requests.append(head + b"\r\n\r\n" + body)
        if b"Upgrade: websocket" in head:
            self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
            while True:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                self.request.sendall(chunk.upper())
            return
        payload = head + b"\r\n\r\n" + body
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + payload
        )


@pytest.fixture
def module_dir():
    directory = tempfile.mkdtemp(prefix="cs", dir="/tmp")
    os.makedirs(os.path.join(directory, "run", "ann"))
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def code_server(module_dir):
    server = FakeCodeServer(os.path.join(module_dir, "run", "ann", "code_server.sock"))
    yield server
    server.stop()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def make_forwarder(module_dir, *, clock=time.time, port=None):
    hooks = hooks_for("linux", module_dir, clock=clock)
    record = {"account": "ann", "port": port or free_port(), "secret": SECRET}
    return InstanceForwarder(
        name="code_server",
        record=record,
        hooks=hooks,
        clock=clock,
        log=lambda line: None,
        ready_poll_s=0.05,
        retry_s=0.05,
    )


def wait_listening(forwarder, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if forwarder.is_listening:
            return forwarder.listen_address[1]
        time.sleep(0.02)
    raise AssertionError(f"never listened: {forwarder.failure}")


@pytest.fixture
def listening(code_server, module_dir):
    forwarder = make_forwarder(module_dir)
    forwarder.start()
    port = wait_listening(forwarder)
    yield forwarder, port
    forwarder.close()


def ask(port, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(request)
        received = b""
        while True:
            data = client.recv(65536)
            if not data:
                return received
            received += data


def status_of(answer: bytes) -> int:
    return int(answer.split(b" ", 2)[1])


def header_of(answer: bytes, name: bytes) -> str:
    for line in answer.split(b"\r\n\r\n")[0].split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == name:
            return value.strip().decode()
    return ""


def good_cookie(port, *, expiry=None):
    expiry = int(time.time()) + 3600 if expiry is None else expiry
    return f"{cookie_name(port)}={mint_login(cookie_key(SECRET), expiry)}"


def test_the_forwarder_listens_on_loopback_alone(listening):
    forwarder, _port = listening

    assert forwarder.listen_address[0] == "127.0.0.1"


def test_a_token_is_traded_once_for_a_cookie_and_a_redirect(listening, code_server):
    forwarder, port = listening
    token = mint_token(SECRET, expiry=int(time.time()) + 60, nonce=os.urandom(16))

    first = ask(port, f"GET /app?x=1&tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    second = ask(port, f"GET /app?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())

    assert status_of(first) == 302
    assert header_of(first, b"location") == "/app?x=1"
    cookie = header_of(first, b"set-cookie")
    assert cookie.startswith(f"{cookie_name(port)}=")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert header_of(first, b"cache-control") == "no-store"
    assert status_of(second) == 401
    assert code_server.requests == []


def test_a_token_that_does_not_verify_or_expired_is_refused(listening):
    _forwarder, port = listening
    expired = mint_token(SECRET, expiry=int(time.time()) - 1, nonce=os.urandom(16))
    forged = mint_token("other", expiry=int(time.time()) + 60, nonce=os.urandom(16))

    for token in (expired, forged, "junk"):
        answer = ask(port, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert status_of(answer) == 401


def test_a_request_with_neither_a_token_nor_a_cookie_is_refused(listening, code_server):
    _forwarder, port = listening

    assert status_of(ask(port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")) == 401
    assert code_server.requests == []


def test_a_forged_or_expired_cookie_is_refused(listening):
    _forwarder, port = listening
    expired = good_cookie(port, expiry=int(time.time()) - 1)
    forged = f"{cookie_name(port)}={mint_login(cookie_key('other'), NOW + 10**6)}"

    for cookie in (expired, forged, f"{cookie_name(port)}=junk"):
        request = f"GET / HTTP/1.1\r\nCookie: {cookie}\r\n\r\n".encode()
        assert status_of(ask(port, request)) == 401


def test_a_request_with_a_good_cookie_reaches_the_socket_unchanged(
    listening, code_server
):
    _forwarder, port = listening
    cookie = good_cookie(port)
    request = (
        f"POST /api HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n"
        f"Content-Length: 5\r\n\r\nhello"
    ).encode()

    answer = ask(port, request)

    assert status_of(answer) == 200
    assert answer.endswith(b"Connection: close\r\n\r\nhello")
    (seen,) = code_server.requests
    assert seen.startswith(b"POST /api HTTP/1.1\r\n")
    assert f"Cookie: {cookie}".encode() in seen


def test_a_websocket_with_a_good_cookie_is_relayed_both_ways(listening, code_server):
    _forwarder, port = listening
    cookie = good_cookie(port)

    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(
            f"GET /ws HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n"
            "Connection: Upgrade\r\nUpgrade: websocket\r\n\r\n".encode()
        )
        received = b""
        while b"\r\n\r\n" not in received:
            received += client.recv(65536)
        assert received.startswith(b"HTTP/1.1 101")
        client.sendall(b"ping")
        echoed = client.recv(65536)

    assert echoed == b"PING"


def test_a_code_server_that_does_not_answer_is_502(module_dir):
    forwarder = make_forwarder(module_dir)
    forwarder.start()
    try:
        port = wait_listening(forwarder)
        cookie = good_cookie(forwarder.port)
        request = f"GET / HTTP/1.1\r\nCookie: {cookie}\r\n\r\n".encode()
        assert status_of(ask(port, request)) == 502
    finally:
        forwarder.close()


def test_a_taken_port_is_reported(module_dir):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        taken = holder.getsockname()[1]
        forwarder = make_forwarder(module_dir, port=taken)
        forwarder.start()
        try:
            deadline = time.monotonic() + 5
            while not forwarder.failure[0] and time.monotonic() < deadline:
                time.sleep(0.02)
            assert forwarder.failure == (
                "code_server_port_taken",
                {"account": "ann", "port": taken},
            )
            assert forwarder.is_listening is False
        finally:
            forwarder.close()


def test_a_token_s_redirect_keeps_the_rest_of_the_address():
    assert address_without_token("/", {"tkn": ["a"]}) == "/"
    assert address_without_token("", {"tkn": ["a"]}) == "/"
    assert address_without_token("/p", {"a": ["1"], "tkn": ["x"], "b": ["2"]}) == (
        "/p?a=1&b=2"
    )


def test_a_login_verifies_only_under_its_key_and_before_its_expiry():
    key = cookie_key(SECRET)

    assert is_login_valid(mint_login(key, NOW + 60), key, NOW) is True
    assert is_login_valid(mint_login(key, NOW - 1), key, NOW) is False
    assert is_login_valid(mint_login(cookie_key("other"), NOW + 60), key, NOW) is False
    assert is_login_valid("junk", key, NOW) is False


def test_a_forwarder_follows_the_account_the_port_and_the_secret(module_dir):
    forwarder = make_forwarder(module_dir, port=8443)
    record = {"account": "ann", "port": 8443, "secret": SECRET}

    assert forwarder.matches(record)
    assert not forwarder.matches(dict(record, port=8444))
    assert not forwarder.matches(dict(record, secret="t"))
