"""Hermes WebUI's hooks: the forwarder's login, the gateway keys, the health read, a version change.

What these pin, against a faked ``podman`` and a webui on loopback: a token
that verifies is traded for the webui's ``hermes_session`` cookie and a
redirect to ``/``, the cookie passed on with ``Host`` and ``Origin``
unchanged, 401 for ``/api/auth/login`` whatever it holds and for a request
with neither; the four gateway keys written with ``hermes config set``
once ``config.yaml`` exists and again when the base URL changes, never
``model.default``; ``installing`` until the keys and ``/health`` hold, the
start waiting meanwhile; a version change making ``agent`` and ``app``
again and keeping ``home`` and ``workspace``; and the record that brings
the forwarder back after a restart.
"""

import json
import os
import socket
import socketserver
import threading
import time

import pytest

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.hermes_webui import hooks as hooks_module
from neutrino_agent.modules.hermes_webui.hooks import (
    HermesWebuiHooks,
    gateway_keys,
    normal_path,
    session_cookie,
)
from neutrino_agent.modules.shared.http_forward import InstanceForwarder, mint_token
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

SECRET = "token-secret-of-the-module"
PASSWORD = "webui-password"
CONFIG = {"port": 8787, "secret": SECRET, "password": PASSWORD}
PODMAN = "/usr/bin/podman"
URL = "http://host.containers.internal:8317"
COOKIE = "hermes_session=abc123; HttpOnly; Max-Age=2592000; Path=/; SameSite=Lax"


class FakeContainers:
    """The Containers runner as the hooks reach it."""

    def __init__(self, *, upstream=41234):
        self.upstream = upstream
        self.driven: list = []
        self.names = {
            "hermes_webui": ["neutrino_hermes_webui_agent", "neutrino_hermes_webui"]
        }

    def podman_command(self):
        return (PODMAN,)

    def page_port(self, module, name):
        assert (module, name) == ("hermes_webui", "neutrino_hermes_webui")
        return self.upstream

    def hub_names(self):
        return dict(self.names)

    def drive_hub_containers(self, names, action):
        self.driven.append((list(names), action))


class FakePodman:
    """podman's answers: the agent container's environment, config.yaml, config set."""

    def __init__(self, *, url=URL, is_running=True, has_config=False):
        self.url = url
        self.is_running = is_running
        self.has_config = has_config
        self.calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        verb = command[1]
        if verb == "inspect":
            entry = {
                "State": {"Running": self.is_running},
                "Config": {
                    "Env": [
                        "PATH=/usr/bin",
                        f"NEUTRINO_GATEWAY_URL={self.url}",
                        "NEUTRINO_GATEWAY_KEY=k",
                    ]
                },
            }
            return CommandResult(list(command), 0, json.dumps([entry]), "")
        if verb == "exec" and "test" in command:
            return CommandResult(list(command), 0 if self.has_config else 1, "", "")
        return CommandResult(list(command), 0, "", "")

    def config_sets(self) -> list:
        return [call for call in self.calls if "config" in call and "set" in call]


class FakeForwarder:
    def __init__(self, *, name, record, hooks, log):
        self.record = dict(record)
        self.is_started = False
        self.is_closed = False

    def matches(self, record):
        return all(
            record.get(field) == self.record.get(field)
            for field in ("port", "secret", "password", "upstream_port")
        )

    def start(self):
        self.is_started = True

    def close(self):
        self.is_closed = True


class Box:
    """The hooks with their fakes, the health status set by the test."""

    def __init__(self, tmp_path, *, podman=None, containers=None):
        self.podman = podman or FakePodman()
        self.containers = containers or FakeContainers()
        self.status = 503
        self.forwarders: list = []
        self.lines: list = []
        self.record_dir = str(tmp_path / "hermes_webui")
        self.hooks = self.make()

    def make(self) -> HermesWebuiHooks:
        return HermesWebuiHooks(
            platform=AgentPlatform(),
            name="hermes_webui",
            containers=self.containers,
            log=self.lines.append,
            run_command=self.podman,
            health=self.health,
            login=self.login,
            forwarder_factory=self.forwarder,
            record_dir=self.record_dir,
        )

    def health(self, port):
        assert port == self.containers.upstream
        return self.status

    def login(self, port, password):
        return 200, [("Set-Cookie", COOKIE)]

    def forwarder(self, **kwargs):
        made = FakeForwarder(**kwargs)
        self.forwarders.append(made)
        return made

    def record(self) -> dict:
        path = os.path.join(self.record_dir, "hermes_webui.json")
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def test_a_port_outside_the_range_is_refused(box):
    with pytest.raises(ModuleApplyError) as refused:
        box.hooks.apply({**CONFIG, "port": 80})

    assert refused.value.code == "port_invalid"


def test_before_config_yaml_exists_the_start_waits_and_writes_no_key(box):
    box.hooks.installed("0.52.492")
    box.hooks.apply(CONFIG)

    with pytest.raises(ModuleInstallPending):
        box.hooks.start()

    assert box.podman.config_sets() == []
    assert box.hooks.is_installing() is True
    (forwarder,) = box.forwarders
    assert forwarder.is_started
    assert (forwarder.record["port"], forwarder.record["upstream_port"]) == (
        8787,
        41234,
    )
    assert box.record()["is_ready"] is False


def test_once_config_yaml_exists_the_four_keys_are_written_with_hermes_config_set(
    box,
):
    box.podman.has_config = True
    box.status = 200
    box.hooks.installed("0.52.492")
    box.hooks.apply(CONFIG)

    box.hooks.start()

    assert box.podman.config_sets() == [
        [
            PODMAN,
            "exec",
            "-u",
            "hermes",
            "-e",
            "HERMES_HOME=/opt/data",
            "neutrino_hermes_webui_agent",
            "hermes",
            "config",
            "set",
            key,
            value,
        ]
        for key, value in (
            ("model.provider", "custom"),
            ("model.base_url", URL + "/v1"),
            ("model.key_env", "NEUTRINO_GATEWAY_KEY"),
            ("model.api_key", "${NEUTRINO_GATEWAY_KEY}"),
        )
    ]
    assert not any("model.default" in call for call in box.podman.calls)
    assert box.record()["base_url"] == URL + "/v1"
    assert box.record()["is_ready"] is True
    assert box.hooks.is_installing() is False


def test_the_module_reads_installing_until_health_answers_200_once(box):
    box.podman.has_config = True
    box.hooks.installed("0.52.492")
    box.hooks.apply(CONFIG)

    with pytest.raises(ModuleInstallPending):
        box.hooks.start()
    assert box.hooks.is_installing() is True
    assert len(box.podman.config_sets()) == 4

    box.status = 200
    box.hooks.start()

    assert box.hooks.is_installing() is False
    assert len(box.podman.config_sets()) == 4
    box.status = 500
    box.hooks.start()
    assert box.hooks.is_running() is False


def test_a_base_url_that_changes_writes_the_keys_again(box):
    box.podman.has_config = True
    box.status = 200
    box.hooks.installed("0.52.492")
    box.hooks.apply(CONFIG)
    box.hooks.start()

    box.podman.url = "http://host.containers.internal:8400"
    box.hooks.start()

    sets = box.podman.config_sets()
    assert len(sets) == 8
    assert sets[5][-2:] == ["model.base_url", "http://host.containers.internal:8400/v1"]
    assert box.record()["base_url"] == "http://host.containers.internal:8400/v1"


def test_an_agent_container_not_running_writes_nothing_and_waits(box):
    box.podman.has_config = True
    box.podman.is_running = False
    box.status = 200
    box.hooks.installed("0.52.492")
    box.hooks.apply(CONFIG)

    with pytest.raises(ModuleInstallPending):
        box.hooks.start()

    assert box.podman.config_sets() == []


def test_a_version_change_makes_agent_and_app_again_and_keeps_home_and_workspace(
    box,
):
    box.hooks.installed("0.52.492")
    box.podman.calls.clear()

    box.hooks.installed("0.53.1")

    assert box.containers.driven == [
        (["neutrino_hermes_webui_agent", "neutrino_hermes_webui"], "stop")
    ]
    assert box.podman.calls == [
        [PODMAN, "volume", "rm", "-f", "neutrino_hermes_webui_agent"],
        [PODMAN, "volume", "create", "neutrino_hermes_webui_agent"],
        [PODMAN, "volume", "rm", "-f", "neutrino_hermes_webui_app"],
        [PODMAN, "volume", "create", "neutrino_hermes_webui_app"],
    ]
    assert (box.record()["version"], box.record()["is_ready"]) == ("0.53.1", False)


def test_the_first_install_and_the_same_version_again_reset_nothing(box):
    box.hooks.installed("0.52.492")
    box.hooks.installed("0.52.492")

    assert box.containers.driven == []
    assert box.podman.calls == []


def test_running_is_health_answering_200_at_the_published_port(box):
    box.hooks.apply(CONFIG)
    with pytest.raises(ModuleInstallPending):
        box.hooks.start()

    box.status = 200
    assert box.hooks.is_running() is True
    box.status = 0
    assert box.hooks.is_running() is False
    assert box.hooks.details() == {"port": 8787}


def test_stop_closes_the_forwarder_and_remove_forgets_the_record(box):
    box.hooks.apply(CONFIG)
    with pytest.raises(ModuleInstallPending):
        box.hooks.start()
    (forwarder,) = box.forwarders

    box.hooks.stop()

    assert forwarder.is_closed
    assert box.record()["is_stopped"] is True
    box.hooks.remove()
    assert not os.path.exists(box.record_dir)


def test_a_new_port_starts_another_forwarder(box):
    box.hooks.apply(CONFIG)
    with pytest.raises(ModuleInstallPending):
        box.hooks.start()

    box.hooks.apply({**CONFIG, "port": 9100})
    with pytest.raises(ModuleInstallPending):
        box.hooks.start()

    first, second = box.forwarders
    assert first.is_closed and second.is_started
    assert second.record["port"] == 9100


def test_after_a_restart_the_record_brings_the_forwarder_back(box):
    box.podman.has_config = True
    box.status = 200
    box.hooks.installed("0.52.492")
    box.hooks.apply(CONFIG)
    box.hooks.start()

    restarted = box.make()
    assert restarted.is_running() is True

    assert len(box.forwarders) == 2
    assert box.forwarders[1].is_started
    assert restarted.details() == {"port": 8787}


def test_a_stopped_module_s_forwarder_stays_down_after_a_restart(box):
    box.hooks.apply(CONFIG)
    with pytest.raises(ModuleInstallPending):
        box.hooks.start()
    box.hooks.stop()

    box.make().is_running()

    assert len(box.forwarders) == 1


@pytest.mark.parametrize(
    "path",
    ["/api/auth/login", "//api/auth/login", "/api/auth/login/", "/x/../api/auth/login"],
)
def test_the_login_route_is_matched_however_it_is_spelled(path):
    assert normal_path(path) == "/api/auth/login"


def test_the_session_cookie_is_the_one_the_webui_set():
    assert session_cookie([("Set-Cookie", "other=1"), ("set-cookie", COOKIE)]) == (
        COOKIE
    )
    assert session_cookie([("Content-Type", "x")]) == ""


def test_the_keys_name_the_custom_provider_and_the_key_s_variable():
    assert gateway_keys("http://h:1/v1") == [
        ("model.provider", "custom"),
        ("model.base_url", "http://h:1/v1"),
        ("model.key_env", "NEUTRINO_GATEWAY_KEY"),
        ("model.api_key", "${NEUTRINO_GATEWAY_KEY}"),
    ]


# --- the forwarder, against a fake webui ---


class FakeWebui(socketserver.ThreadingTCPServer):
    """A webui that signs in a JSON password with no Origin, and echoes the rest."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.requests: list = []
        super().__init__(("127.0.0.1", 0), FakeWebuiConnection)
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self):
        self.shutdown()
        self.server_close()


class FakeWebuiConnection(socketserver.BaseRequestHandler):
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
        headers = {
            name.strip().lower(): value.strip()
            for name, _, value in (line.partition(":") for line in lines[1:])
        }
        length = int(headers.get("content-length", 0))
        while len(body) < length:
            body += self.request.recv(65536)
        self.server.requests.append((method, target, headers, body))
        if target == "/api/auth/login":
            is_good = (
                method == "POST"
                and "origin" not in headers
                and json.loads(body or b"{}").get("password") == PASSWORD
            )
            status = "200 OK" if is_good else "401 Unauthorized"
            cookie = f"Set-Cookie: {COOKIE}\r\n" if is_good else ""
            self.request.sendall(
                f"HTTP/1.1 {status}\r\n{cookie}Content-Length: 2\r\n"
                "Connection: close\r\n\r\n{}".encode()
            )
            return
        answer = json.dumps({"host": headers.get("host", "")}).encode()
        self.request.sendall(
            f"HTTP/1.1 200 OK\r\nContent-Length: {len(answer)}\r\n"
            "Connection: close\r\n\r\n".encode() + answer
        )


@pytest.fixture
def webui():
    server = FakeWebui()
    yield server
    server.stop()


@pytest.fixture
def page(webui, tmp_path):
    hooks = HermesWebuiHooks(
        platform=AgentPlatform(),
        name="hermes_webui",
        containers=FakeContainers(upstream=webui.port),
        log=lambda line: None,
        record_dir=str(tmp_path / "record"),
    )
    forwarder = InstanceForwarder(
        name="hermes_webui",
        record={
            "account": "",
            "port": 0,
            "secret": SECRET,
            "password": PASSWORD,
            "upstream_port": webui.port,
        },
        hooks=hooks,
        log=lambda line: None,
        ready_poll_s=0.05,
        retry_s=0.05,
    )
    forwarder.start()
    deadline = time.monotonic() + 5
    while not forwarder.is_listening and time.monotonic() < deadline:
        time.sleep(0.02)
    yield forwarder.listen_address[1]
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


def fresh_token(secret=SECRET) -> str:
    return mint_token(secret, expiry=int(time.time()) + 60, nonce=os.urandom(16))


def test_a_token_is_traded_for_the_webui_s_cookie_and_a_redirect(page, webui):
    token = fresh_token()

    answer = ask(page, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    again = ask(page, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())

    assert status_of(answer) == 302
    assert header_of(answer, b"location") == "/"
    assert header_of(answer, b"set-cookie") == COOKIE
    assert status_of(again) == 401
    (login,) = webui.requests
    assert (login[0], login[1], json.loads(login[3])) == (
        "POST",
        "/api/auth/login",
        {"password": PASSWORD},
    )


def test_the_cookie_is_passed_on_with_host_and_origin_unchanged(page, webui):
    answer = ask(
        page,
        b"POST /api/chat HTTP/1.1\r\nHost: 127.0.0.1:47001\r\n"
        b"Origin: http://127.0.0.1:47001\r\nCookie: hermes_session=abc123\r\n"
        b"Content-Length: 2\r\n\r\n{}",
    )

    assert status_of(answer) == 200
    assert json.loads(answer.split(b"\r\n\r\n", 1)[1]) == {"host": "127.0.0.1:47001"}
    method, target, headers, _body = webui.requests[-1]
    assert (method, target) == ("POST", "/api/chat")
    assert headers["origin"] == "http://127.0.0.1:47001"
    assert headers["cookie"] == "hermes_session=abc123"


@pytest.mark.parametrize(
    "request_bytes",
    [
        b"POST /api/auth/login HTTP/1.1\r\nHost: x\r\nCookie: hermes_session=abc"
        b"\r\nContent-Length: 2\r\n\r\n{}",
        b"GET /api/auth/login?tkn=whatever HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET /%2Fapi/auth/login HTTP/1.1\r\nHost: x\r\nCookie: hermes_session=a\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET /share/abc HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET /?tkn=forged HTTP/1.1\r\nHost: x\r\n\r\n",
    ],
)
def test_the_login_route_and_a_request_with_neither_are_401(page, webui, request_bytes):
    answer = ask(page, request_bytes)

    assert status_of(answer) == 401
    assert webui.requests == []


def test_a_token_of_another_secret_is_401(page, webui):
    answer = ask(
        page, f"GET /?tkn={fresh_token('other')} HTTP/1.1\r\nHost: x\r\n\r\n".encode()
    )

    assert status_of(answer) == 401


def test_a_webui_that_refuses_the_password_is_502(webui, tmp_path, monkeypatch):
    hooks = HermesWebuiHooks(
        platform=AgentPlatform(),
        name="hermes_webui",
        containers=FakeContainers(upstream=webui.port),
        log=lambda line: None,
        record_dir=str(tmp_path / "record"),
    )
    record = {"port": 0, "secret": SECRET, "password": "wrong"}
    record["upstream_port"] = webui.port

    class Request:
        path = "/"
        token = "t"

        def take_token(self):
            return True

        def cookie_values(self, name):
            return []

    assert hooks.admit(Request(), record).status == 502


def test_an_empty_secret_admits_no_token(tmp_path):
    hooks = HermesWebuiHooks(
        platform=AgentPlatform(),
        name="hermes_webui",
        containers=FakeContainers(),
        log=lambda line: None,
        record_dir=str(tmp_path / "record"),
    )

    class Request:
        path = "/"
        token = "t"

        def take_token(self):
            return True

        def cookie_values(self, name):
            return []

    assert hooks.admit(Request(), {"secret": "", "upstream_port": 1}).status == 401


def test_the_forwarder_tries_a_held_port_again_every_report_interval():
    made = hooks_module._forwarder(
        name="hermes_webui",
        record={"account": "hermes_webui", "port": 8787},
        hooks=None,
        log=lambda line: None,
    )

    assert made._retry_s == 5
    assert made.account == ""
