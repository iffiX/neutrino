"""Codeg's hooks: the two components, each account's service, the forwarder, the journal.

What these pin: the server, its web UI and Node are found under the
``server`` and ``node`` components, by system; each instance runs
``codeg-server`` alone, with no ``--supervise``, from an environment written
from scratch naming Codeg's host, loopback port, derived token, data
directory, static directory, port bridge off, npm's prefix and cache under
the data directory, ``HOME`` on Linux and macOS, and a ``PATH`` with Node
first, the account's command directories next and the system's last, on
Windows Node then the account's npm directory and its own ``PATH``, under
``umask 077``, root-only, its output discarded on every system; the data directory is made as the
account's own, mode 700, once; the record keeps the loopback port; and the
forwarder, driven against a fake Codeg, listens on ``127.0.0.1`` alone,
trades a token once for the page that keeps the instance token and opens
the workspace, passes a request with the instance token as Bearer on
unchanged, relays a WebSocket whose subprotocol carries it both ways with
its headers, and answers 401 to a wrong token, a wrong Bearer, a wrong
subprotocol and a request with neither. The journal reads Codeg's newest
daily log, and the version is what the server prints, read once per binary.
"""

import json
import ntpath
import os
import socket
import socketserver
import stat
import threading
import time

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.codeg.config import instance_token, subprotocol_of
from neutrino_agent.modules.codeg.hooks import (
    DATA_DIR_SCRIPT,
    CodegHooks,
    data_dir,
    make_account_directory,
    newest_log,
    service_environment,
)
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.http_forward import InstanceForwarder, mint_token
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

SECRET = "instance-secret"  # scan: allow
TOKEN = instance_token(SECRET)
CONFIG = {"instances": [{"account": "ann", "port": 3101, "secret": SECRET}]}
WINDOWS_CONFIG = {
    "instances": [
        {"account": "ann", "port": 3101, "secret": SECRET, "password": "login-pw"}
    ]
}
ANN = AccountEntry(1000, 1000, "/home/ann", "/bin/bash")
MAC_ANN = AccountEntry(501, 20, "/Users/ann", "/bin/zsh")
WIN_ANN = AccountEntry(0, 0, "C:\\Users\\ann", "")
LINUX_STATE = "/var/lib/neutrino/agent/codeg"
MAC_STATE = "/Library/Application Support/Neutrino/agent/state/codeg"
WIN_STATE = "C:\\ProgramData\\Neutrino\\agent\\state\\codeg"


class Platform(AgentPlatform):
    def __init__(self, os_name="linux"):
        self.os_name = os_name


class Recorder:
    """Every command run, with one answer for the server's ``--version``."""

    def __init__(self, version="0.35.1"):
        self.calls: list = []
        self.version = version

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append((list(command), timeout_s))
        if command[-1] == "--version":
            return CommandResult(list(command), 0, self.version + "\n", "")
        return CommandResult(list(command), 0, "", "")


class PowerShell:
    def __init__(self):
        self.calls: list = []

    def __call__(self, script, document, timeout_s=120):
        self.calls.append((script, dict(document)))
        return {}


def hooks_for(os_name, module_dir, *, home="/home/ann", **kwargs) -> CodegHooks:
    tools = {
        key: kwargs.pop(key) for key in ("run", "chown", "powershell") if key in kwargs
    }
    hooks = CodegHooks(platform=Platform(os_name), log=lambda line: None, **kwargs)
    join = ntpath.join if os_name == "windows" else os.path.join
    entry = {"linux": ANN, "darwin": MAC_ANN, "windows": WIN_ANN}[os_name]
    if home != entry.home:
        entry = AccountEntry(entry.uid, entry.gid, home, entry.shell)

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return entry

    machine = ServiceMachine(
        os_name=os_name,
        module_dir=module_dir,
        record_dir=join(os.path.dirname(module_dir), "config", "codeg"),
        lookup_account=lookup,
        **tools,
    )
    hooks.bind(machine, None)
    return hooks


def install_server(module_dir: str) -> str:
    """A server component with a server file and its web directory."""
    os.makedirs(os.path.join(module_dir, "server", "web"))
    os.makedirs(os.path.join(module_dir, "node", "bin"))
    server = os.path.join(module_dir, "server", "codeg-server")
    with open(server, "w", encoding="utf-8") as stream:
        stream.write("#!/bin/sh\n")
    return server


# --- the components ---


def test_the_server_the_web_ui_and_node_are_found_under_their_components():
    linux = hooks_for("linux", LINUX_STATE)
    mac = hooks_for("darwin", MAC_STATE)
    windows = hooks_for("windows", WIN_STATE)

    assert linux.server_path == f"{LINUX_STATE}/server/codeg-server"
    assert linux.static_dir == f"{LINUX_STATE}/server/web"
    assert linux.node_dir == f"{LINUX_STATE}/node/bin"
    assert mac.server_path == f"{MAC_STATE}/server/codeg-server"
    assert mac.node_dir == f"{MAC_STATE}/node/bin"
    assert windows.server_path == f"{WIN_STATE}\\server\\codeg-server.exe"
    assert windows.static_dir == f"{WIN_STATE}\\server\\web"
    assert windows.node_dir == f"{WIN_STATE}\\node"
    assert CodegHooks.kind == "codeg"
    assert CodegHooks.download_failure_code == "codeg_download_failed"


def test_verify_is_the_server_file_and_the_version_is_what_it_prints(tmp_path):
    run = Recorder()
    hooks = hooks_for("linux", str(tmp_path / "codeg"), run=run)
    assert hooks.verify() is False
    assert hooks.module_details() == {"version": ""}

    server = install_server(str(tmp_path / "codeg"))

    assert hooks.verify() is True
    assert hooks.module_details() == {"version": "0.35.1"}
    assert hooks.module_details() == {"version": "0.35.1"}
    assert run.calls == [([server, "--version"], 30)]
    with open(server, "a", encoding="utf-8") as stream:
        stream.write("# changed\n")
    run.version = "0.36.0"
    assert hooks.module_details() == {"version": "0.36.0"}
    assert len(run.calls) == 2


# --- the configuration and the service ---


def test_a_refusal_of_the_configuration_names_what_it_is_about():
    with pytest.raises(ModuleApplyError) as caught:
        hooks_for("windows", WIN_STATE).parse(CONFIG)
    assert caught.value.code == "credential_missing"
    assert caught.value.params == {"account": "ann"}
    assert hooks_for("linux", LINUX_STATE).parse(CONFIG).instances[0].port == 3101


def test_the_record_keeps_the_loopback_port_across_applies():
    hooks = hooks_for("linux", LINUX_STATE, pick_port=lambda: 41000)
    config = hooks.parse(CONFIG)
    (instance,) = config.instances

    first = hooks.record(config, instance, {})
    again = hooks.record(config, instance, dict(first, upstream_port=41234))

    assert first == {
        "account": "ann",
        "port": 3101,
        "upstream_port": 41000,
        "secret": SECRET,
    }
    assert again["upstream_port"] == 41234
    assert hooks.forwarder_fields == ("account", "port", "upstream_port", "secret")


def test_the_service_runs_the_server_alone_from_a_root_only_discarded_environment():
    hooks = hooks_for("linux", LINUX_STATE)
    config = hooks.parse(CONFIG)
    record = {"account": "ann", "port": 3101, "upstream_port": 41000, "secret": SECRET}

    service = hooks.service(config.instances[0], ANN, record)

    assert service.command == (f"{LINUX_STATE}/server/codeg-server",)
    assert "--supervise" not in service.command
    assert service.environment == {
        "CODEG_HOST": "127.0.0.1",
        "CODEG_PORT": "41000",
        "CODEG_TOKEN": TOKEN,
        "CODEG_DATA_DIR": "/home/ann/.local/share/neutrino/agent/codeg",
        "CODEG_STATIC_DIR": f"{LINUX_STATE}/server/web",
        "CODEG_BRIDGE_PORTS": "off",
        "NPM_CONFIG_PREFIX": "/home/ann/.local/share/neutrino/agent/codeg/npm",
        "npm_config_cache": "/home/ann/.local/share/neutrino/agent/codeg/npm_cache",
        "HOME": "/home/ann",
        "PATH": f"{LINUX_STATE}/node/bin:/home/ann/.local/bin:/home/ann/bin:"
        "/usr/local/bin:/usr/bin:/bin",
    }
    assert service.umask == "077"
    assert service.is_output_discarded is True
    assert service.is_environment_secret is True
    assert service.working_directory == "~"
    assert service.listen_port == 41000
    assert service.directories == () and service.files == ()
    assert service.password == ""


def test_the_environment_follows_each_system():
    mac = service_environment(
        TOKEN,
        upstream_port=41000,
        home="/Users/ann",
        os_name="darwin",
        node_dir=f"{MAC_STATE}/node/bin",
        static_dir=f"{MAC_STATE}/server/web",
    )
    windows = service_environment(
        TOKEN,
        upstream_port=41000,
        home="C:\\Users\\ann",
        os_name="windows",
        node_dir=f"{WIN_STATE}\\node",
        static_dir=f"{WIN_STATE}\\server\\web",
        join=ntpath.join,
    )

    assert mac["CODEG_DATA_DIR"] == (
        "/Users/ann/Library/Application Support/Neutrino/agent/codeg"
    )
    assert mac["PATH"] == (
        f"{MAC_STATE}/node/bin:/Users/ann/.local/bin:/Users/ann/bin:"
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    )
    assert (
        windows["CODEG_DATA_DIR"]
        == "C:\\Users\\ann\\AppData\\Local\\Neutrino\\agent\\codeg"
    )
    assert windows["CODEG_STATIC_DIR"] == f"{WIN_STATE}\\server\\web"
    assert windows["NPM_CONFIG_PREFIX"] == (
        "C:\\Users\\ann\\AppData\\Local\\Neutrino\\agent\\codeg\\npm"
    )
    assert windows["PATH"] == f"{WIN_STATE}\\node;%APPDATA%\\npm;%PATH%"
    assert mac["HOME"] == "/Users/ann"
    assert "HOME" not in windows
    for environment in (mac, windows):
        assert environment["CODEG_TOKEN"] == TOKEN
        assert environment["CODEG_BRIDGE_PORTS"] == "off"
        assert not [name for name in environment if "ANTHROPIC" in name]


def test_a_windows_service_carries_the_login_and_the_same_shape():
    hooks = hooks_for("windows", WIN_STATE)
    config = hooks.parse(WINDOWS_CONFIG)
    record = {"account": "ann", "port": 3101, "upstream_port": 41000, "secret": SECRET}

    service = hooks.service(config.instances[0], WIN_ANN, record)

    assert service.command == (f"{WIN_STATE}\\server\\codeg-server.exe",)
    assert service.password == "login-pw"
    assert service.is_output_discarded is True
    assert service.environment["CODEG_PORT"] == "41000"


# --- the data directory ---


def test_the_data_directory_is_made_as_the_account_mode_700_once(tmp_path):
    owners = []
    home = str(tmp_path / "home" / "ann")
    os.makedirs(home)
    hooks = hooks_for(
        "linux",
        str(tmp_path / "codeg"),
        home=home,
        chown=lambda path, uid, gid: owners.append((path, uid, gid)),
    )
    config = hooks.parse(CONFIG)
    entry = AccountEntry(1000, 1001, home, "/bin/bash")

    notes = hooks.prepare(config, config.instances[0], entry)
    again = hooks.prepare(config, config.instances[0], entry)

    directory = os.path.join(home, ".local", "share", "neutrino", "agent", "codeg")
    assert notes == ["made the data directory of ann"]
    assert again == []
    assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700
    made = [path for path, _uid, _gid in owners]
    assert made == [
        os.path.join(home, ".local"),
        os.path.join(home, ".local", "share"),
        os.path.join(home, ".local", "share", "neutrino"),
        os.path.join(home, ".local", "share", "neutrino", "agent"),
        directory,
    ]
    assert {(uid, gid) for _path, uid, gid in owners} == {(1000, 1001)}
    for path in made:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o700


def test_an_existing_tree_is_left_as_it_is(tmp_path):
    owners = []
    share = tmp_path / ".local" / "share"
    share.mkdir(parents=True)
    os.chmod(share, 0o755)

    assert (
        make_account_directory(
            str(share / "neutrino"),
            AccountEntry(1000, 1000, str(tmp_path)),
            lambda path, uid, gid: owners.append(path),
        )
        is True
    )
    assert make_account_directory(str(share / "neutrino"), ANN, owners.append) is False

    assert owners == [str(share / "neutrino")]
    assert stat.S_IMODE(os.stat(share).st_mode) == 0o755


def test_on_windows_the_data_directory_is_made_through_powershell():
    powershell = PowerShell()
    hooks = hooks_for("windows", WIN_STATE, powershell=powershell)
    config = hooks.parse(WINDOWS_CONFIG)

    notes = hooks.prepare(config, config.instances[0], WIN_ANN)

    assert notes == ["made the data directory of ann"]
    ((script, document),) = powershell.calls
    assert script == DATA_DIR_SCRIPT
    assert document == {
        "account": "ann",
        "directory": "C:\\Users\\ann\\AppData\\Local\\Neutrino\\agent\\codeg",
    }
    assert "(OI)(CI)M" in DATA_DIR_SCRIPT
    assert data_dir("C:\\Users\\ann", "windows", ntpath.join) == document["directory"]


# --- the journal ---


def test_the_journal_reads_the_newest_daily_log(tmp_path):
    home = str(tmp_path / "home" / "ann")
    hooks = hooks_for("linux", str(tmp_path / "codeg"), home=home)
    record = {"account": "ann", "port": 3101, "upstream_port": 41000, "secret": SECRET}
    logs = os.path.join(home, ".local", "share", "neutrino", "agent", "codeg", "logs")

    assert hooks.journal_log(record) == ""
    os.makedirs(logs)
    assert hooks.journal_log(record) == ""
    for name in (
        "codeg-server.2026-10-09.log",
        "codeg-server.2026-10-11.log",
        "codeg-server.2026-10-10.log",
        "other.log",
        "codeg-server.2026-10-12.txt",
    ):
        open(os.path.join(logs, name), "w").close()

    assert hooks.journal_log(record) == os.path.join(
        logs, "codeg-server.2026-10-11.log"
    )
    assert hooks.journal_log(dict(record, account="bob")) == ""
    assert newest_log(os.path.join(logs, "missing")) == ""


# --- the forwarder, against a fake Codeg ---


class FakeCodeg(socketserver.ThreadingTCPServer):
    """An echo of every request's line, headers and body, and a WebSocket echo."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.requests: list = []
        super().__init__(("127.0.0.1", 0), FakeCodegConnection)
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self):
        self.shutdown()
        self.server_close()


class FakeCodegConnection(socketserver.BaseRequestHandler):
    def handle(self):
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = self.request.recv(65536)
            if not chunk:
                return
            received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        method, target, _version = lines[0].split(" ")
        headers = [
            (name.strip(), value.strip())
            for name, _, value in (line.partition(":") for line in lines[1:])
        ]
        length = int(dict((n.lower(), v) for n, v in headers).get("content-length", 0))
        while len(body) < length:
            body += self.request.recv(65536)
        self.server.requests.append((method, target, headers, body))
        if ("Upgrade", "websocket") in headers:
            self.request.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                b"Sec-WebSocket-Protocol: codeg-events\r\n\r\n"
            )
            while True:
                data = self.request.recv(65536)
                if not data:
                    return
                self.request.sendall(data.upper())
        answer = json.dumps({"echo": target, "body": body.decode()}).encode()
        self.request.sendall(
            f"HTTP/1.1 200 X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(answer)}\r\nConnection: close\r\n\r\n".encode()
            + answer
        )


@pytest.fixture
def codeg():
    server = FakeCodeg()
    yield server
    server.stop()


def record_for(upstream_port, *, port=0):
    return {
        "account": "ann",
        "port": port,
        "upstream_port": upstream_port,
        "secret": SECRET,
    }


def make_forwarder(upstream_port, *, port=None):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        chosen = port or probe.getsockname()[1]
    return InstanceForwarder(
        name="codeg",
        record=record_for(upstream_port, port=chosen),
        hooks=hooks_for("linux", LINUX_STATE),
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
def listening(codeg):
    forwarder = make_forwarder(codeg.port)
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


def fresh_token() -> str:
    return mint_token(SECRET, expiry=int(time.time()) + 60, nonce=os.urandom(16))


def test_the_forwarder_listens_on_loopback_alone(listening):
    forwarder, _port = listening

    assert forwarder.listen_address[0] == "127.0.0.1"


def test_a_token_is_traded_once_for_the_page_that_keeps_the_instance_token(
    listening, codeg
):
    _forwarder, port = listening
    token = fresh_token()

    answer = ask(port, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    again = ask(port, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())

    assert status_of(answer) == 200
    head, _, body = answer.partition(b"\r\n\r\n")
    assert b"Content-Type: text/html; charset=utf-8" in head
    assert b"Cache-Control: no-store" in head
    assert b"Referrer-Policy: no-referrer" in head
    assert b"Set-Cookie" not in head
    assert body == (
        b'<!doctype html><meta charset="utf-8"><title>Codeg</title>'
        b'<script>localStorage.setItem("codeg_token", "' + TOKEN.encode() + b'");'
        b'location.replace("/workspace");</script>'
    )
    assert status_of(again) == 401
    assert codeg.requests == []


def test_a_token_that_does_not_verify_or_expired_is_refused(listening, codeg):
    _forwarder, port = listening
    expired = mint_token(SECRET, expiry=int(time.time()) - 1, nonce=os.urandom(16))
    forged = mint_token("other", expiry=int(time.time()) + 60, nonce=os.urandom(16))

    for token in (expired, forged, "junk"):
        answer = ask(port, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert status_of(answer) == 401
    assert codeg.requests == []


def test_a_request_with_neither_a_token_nor_the_instance_token_is_refused(
    listening, codeg
):
    _forwarder, port = listening

    assert status_of(ask(port, b"GET /api/health HTTP/1.1\r\nHost: x\r\n\r\n")) == 401
    assert status_of(ask(port, b"GET /workspace HTTP/1.1\r\nHost: x\r\n\r\n")) == 401
    assert codeg.requests == []


def test_the_instance_token_as_bearer_is_passed_on_unchanged(listening, codeg):
    _forwarder, port = listening

    answer = ask(
        port,
        f"POST /api/health HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n"
        f"X-Extra: kept\r\nContent-Type: application/json\r\n"
        f"Content-Length: 2\r\n\r\n{{}}".encode(),
    )

    assert status_of(answer) == 200 and b'"echo": "/api/health"' in answer
    ((method, target, headers, body),) = codeg.requests
    assert (method, target, body) == ("POST", "/api/health", b"{}")
    assert ("Authorization", f"Bearer {TOKEN}") in headers
    assert ("X-Extra", "kept") in headers
    assert ("Host", "x") in headers


def test_a_wrong_bearer_is_refused(listening, codeg):
    _forwarder, port = listening

    for credential in (TOKEN[:-1] + "x", instance_token("other"), "", TOKEN + "x"):
        answer = ask(
            port,
            f"GET /api/x HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {credential}\r\n\r\n".encode(),
        )
        assert status_of(answer) == 401
    basic = ask(
        port,
        f"GET / HTTP/1.1\r\nHost: x\r\nAuthorization: Basic {TOKEN}\r\n\r\n".encode(),
    )
    assert status_of(basic) == 401
    assert codeg.requests == []


def test_a_websocket_with_the_subprotocol_is_relayed_both_ways_with_its_headers(
    listening, codeg
):
    _forwarder, port = listening
    protocol = subprotocol_of(TOKEN)

    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(
            f"GET /ws/events HTTP/1.1\r\nHost: x\r\n"
            f"Connection: Upgrade\r\nUpgrade: websocket\r\n"
            f"Sec-WebSocket-Protocol: codeg-events, {protocol}\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n".encode()
        )
        received = b""
        while b"\r\n\r\n" not in received:
            received += client.recv(65536)
        assert received.startswith(b"HTTP/1.1 101")
        client.sendall(b"ping")
        echoed = client.recv(65536)

    assert echoed == b"PING"
    ((_method, target, headers, _body),) = codeg.requests
    assert target == "/ws/events"
    assert ("Sec-WebSocket-Protocol", f"codeg-events, {protocol}") in headers
    assert ("Connection", "Upgrade") in headers
    assert ("Sec-WebSocket-Key", "dGhlIHNhbXBsZSBub25jZQ==") in headers


def test_a_wrong_subprotocol_or_one_without_an_upgrade_is_refused(listening, codeg):
    _forwarder, port = listening
    wrong = subprotocol_of(instance_token("other"))
    upgrade = "Connection: Upgrade\r\nUpgrade: websocket\r\n"

    for header in (
        f"Sec-WebSocket-Protocol: codeg-events, {wrong}\r\n{upgrade}",
        f"Sec-WebSocket-Protocol: {TOKEN}\r\n{upgrade}",
        f"Sec-WebSocket-Protocol: codeg-events\r\n{upgrade}",
        f"Sec-WebSocket-Protocol: {subprotocol_of(TOKEN)}\r\n",
        upgrade,
    ):
        answer = ask(
            port, f"GET /ws/events HTTP/1.1\r\nHost: x\r\n{header}\r\n".encode()
        )
        assert status_of(answer) == 401, header
    assert codeg.requests == []


def test_a_codeg_that_does_not_answer_is_502():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        silent = probe.getsockname()[1]
    forwarder = make_forwarder(silent)
    forwarder.start()
    try:
        port = wait_listening(forwarder)
        answer = ask(
            port,
            f"GET / HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n\r\n".encode(),
        )
        assert status_of(answer) == 502
    finally:
        forwarder.close()


def test_a_taken_port_is_reported(codeg):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        taken = holder.getsockname()[1]
        forwarder = make_forwarder(codeg.port, port=taken)
        forwarder.start()
        try:
            deadline = time.monotonic() + 5
            while not forwarder.failure[0] and time.monotonic() < deadline:
                time.sleep(0.02)
            assert forwarder.failure == (
                "codeg_port_taken",
                {"account": "ann", "port": taken},
            )
        finally:
            forwarder.close()
