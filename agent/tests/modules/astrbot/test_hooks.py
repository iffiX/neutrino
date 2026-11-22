"""AstrBot's hooks: the settings file, the gateway's provider, the first start, the forwarder.

What these pin, against a faked ``podman``, the volume's real scripts run
over a folder, and an AstrBot on loopback: ``cmd_config.json`` written whole
into a volume that holds none, with the six ``dashboard`` keys, the
gateway's source keyed ``$NEUTRINO_GATEWAY_KEY``, the default model's
provider and default only while a model is named, ``pypi_index_url`` from
the fastest ``pypi`` source and ``disable_metrics`` true,
``python_user/lib/python3.12/site-packages`` made beside it, and a volume
that holds a ``cmd_config.json`` left as it is; the source written again
through ``POST /api/v1/provider-sources`` when the base URL changes, and no
file written while AstrBot runs; a new model added as the agent's provider,
the ``default`` profile's provider moved to it only while it names the
agent's provider or none, the agent's earlier provider deleted only when the
agent added it, a provider and a default of the person's left as they are,
nothing changed while no model is named, and a failed call retried at the
next start; a new password in the state stopping the container, writing the
``dashboard`` keys with a new ``jwt_secret`` and every other key kept, and
starting it; the requirements folder named by the image's Python made at a
version change; ``installing`` until ``GET /`` returns 200; the forwarder's
``?tkn=`` setting its own cookie under ``cookie_name`` and redirecting to
``/neutrino_login``, that page signing in with ``POST /api/auth/login`` and
storing ``token`` and ``user``, the cookie passed on, and 401 for each
refused route, for a settings save turning SSL or TOTP on or naming another
dashboard port or host, and for a request with neither.
"""

import hashlib
import hmac
import json
import os
import socket
import stat
import subprocess
import time

import pytest

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.astrbot.constants import (
    ASTRBOT_FORWARDER_FIELDS,
    ASTRBOT_REFUSED_PATHS,
)
from neutrino_agent.modules.astrbot.hooks import AstrbotHooks, normal_path
from neutrino_agent.modules.shared.http_forward import InstanceForwarder, mint_token
from neutrino_agent.modules.shared.source_fetch import SourceProbe
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform
from tests.modules.astrbot.fake_astrbot import FakeAstrbot

SECRET = "token-secret-of-the-module"
NEW_PASSWORD = "Another2password"  # scan: allow
PASSWORD = "Dashboard1password"  # scan: allow
COOKIE_NAME = "neutrino_0123456789ab"
CONFIG = {
    "secret": SECRET,
    "password": PASSWORD,
    "cookie_name": COOKIE_NAME,
    "local_name": "astrbot.m.localhost",
    "model": "",
}
PODMAN = "/usr/bin/podman"
DIGEST = "sha256:" + "a" * 64
RECIPE = {
    "runner": "container",
    "method": "container",
    "params": {
        "version": "4.29.4",
        "artifacts": [
            {
                "name": "astrbot",
                "kind": "image",
                "digest": DIGEST,
                "sources": ["docker.io/soulter/astrbot"],
            }
        ],
        "source_sets": ["pypi"],
    },
}
URL = "http://host.containers.internal:8317"
PYPI = {
    "pypi": {
        "probe": "/numpy/",
        "sources": ["https://pypi.org/simple", "https://mirror.example/pypi/simple"],
        "variables": ["PIP_INDEX_URL"],
    }
}
FAKE_PODMAN = """#!/bin/sh
root={root}
case "$1 $2" in
  "volume exists") [ -d "$root/$3" ] ;;
  "volume create") mkdir -p "$root/$3" && echo "$3" ;;
  "volume inspect") printf '%s\\n' "$root/$5" ;;
  *) exit 2 ;;
esac
"""


class FakeContainers:
    """The Containers runner as the hooks reach it, its volumes folders under one root."""

    def __init__(self, tmp_path, *, upstream: int):
        self.upstream = upstream
        self.root = tmp_path / "volumes"
        self.root.mkdir()
        self.podman = tmp_path / "podman"
        self.podman.write_text(FAKE_PODMAN.format(root=self.root))
        self.podman.chmod(0o755)
        self.driven: list = []
        self.scripts: list = []
        self.url = URL
        self.references = {f"docker.io/soulter/astrbot@{DIGEST}"}

    def podman_command(self):
        return (PODMAN,)

    def page_port(self, module, name):
        assert (module, name) == ("astrbot", "neutrino_astrbot")
        return self.upstream

    def hub_names(self):
        return {"astrbot": ["neutrino_astrbot"]}

    def image_references(self):
        return set(self.references)

    def hub_environment(self, name):
        assert name == "neutrino_astrbot"
        return [
            "PIP_USER=1",
            f"NEUTRINO_GATEWAY_URL={self.url}",
            "NEUTRINO_GATEWAY_KEY=k",
        ]

    def drive_hub_containers(self, names, action):
        self.driven.append((list(names), action))

    def volume_script(self, script):
        self.scripts.append(script)
        done = subprocess.run(
            ["/bin/sh", "-s"],
            input=script.replace(PODMAN, str(self.podman)),
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult([], done.returncode, done.stdout, done.stderr)

    def data(self):
        return self.root / "neutrino_astrbot_data"

    def settings(self) -> dict:
        return json.loads((self.data() / "cmd_config.json").read_text("utf-8"))


class FakePodman:
    """podman's answers: the image's environment and whether the container runs."""

    def __init__(self):
        self.python = "3.12.12"
        self.is_running = False
        self.calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        if command[1:3] == ["image", "inspect"]:
            entry = {
                "Config": {"Env": ["PATH=/usr/bin", f"PYTHON_VERSION={self.python}"]}
            }
            return CommandResult(list(command), 0, json.dumps([entry]), "")
        if command[1] == "inspect":
            entry = {"State": {"Running": self.is_running}}
            return CommandResult(list(command), 0, json.dumps([entry]), "")
        return CommandResult(list(command), 1, "", "unknown")


class StepContext:
    def __init__(self):
        self.is_stopped = False

    def is_stopping(self):
        return self.is_stopped


class FakeForwarder:
    def __init__(self, *, name, record, hooks, log):
        self.record = dict(record)
        self.is_started = False
        self.is_closed = False

    def matches(self, record):
        return all(
            record.get(field) == self.record.get(field)
            for field in ASTRBOT_FORWARDER_FIELDS
        )

    def start(self):
        self.is_started = True

    def close(self):
        self.is_closed = True


def fastest_mirror(url, *, source, is_document=False):
    """The second pypi source answers fastest; every other source not at all."""
    if "mirror.example" in source:
        return SourceProbe(
            source=source, is_answered=True, first_byte_s=0.05, status=200, speed=9.0e6
        )
    return SourceProbe(source=source, reason="timeout")


class Box:
    """The hooks with their fakes and an AstrBot on loopback."""

    def __init__(self, tmp_path, astrbot):
        self.astrbot = astrbot
        self.containers = FakeContainers(tmp_path, upstream=astrbot.port)
        self.podman = FakePodman()
        self.lines: list = []
        self.forwarders: list = []
        self.record_dir = str(tmp_path / "astrbot")
        self.context = StepContext()
        self.hooks = AstrbotHooks(
            platform=AgentPlatform(),
            name="astrbot",
            containers=self.containers,
            log=self.lines.append,
            run_command=self.podman,
            probe_one=fastest_mirror,
            forwarder_factory=self.forwarder,
            record_dir=self.record_dir,
            is_port_free=lambda port: True,
            sleep=lambda seconds: None,
        )
        self.hooks.take_recipe(RECIPE)
        self.hooks.take_source_sets(PYPI)

    def forwarder(self, **kwargs):
        made = FakeForwarder(**kwargs)
        self.forwarders.append(made)
        return made

    def record(self) -> dict:
        path = os.path.join(self.record_dir, "astrbot.json")
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)

    def install(self, config=None, version="4.29.4") -> None:
        """The install's ``settings``, then the start and its first start, as the task runs them."""
        config = dict(CONFIG if config is None else config)
        self.hooks.take_config(config)
        for step in self.hooks.install_steps(version):
            step.run(self.context)
        self.start(config, version)

    def start(self, config=None, version="4.29.4") -> None:
        """A start of the module, its steps before and after it, as the task runs them."""
        config = dict(CONFIG if config is None else config)
        self.hooks.take_config(config)
        before = self.hooks.before_start_steps(config)
        after = self.hooks.start_steps(config, version)
        for step in before:
            step.run(self.context)
        self.hooks.apply(config)
        self.hooks.installed(version)
        self.hooks.start()
        for step in after:
            step.run(self.context)


@pytest.fixture
def astrbot():
    server = FakeAstrbot(password=PASSWORD)
    yield server
    server.stop()


@pytest.fixture
def box(tmp_path, astrbot):
    return Box(tmp_path, astrbot)


def pbkdf2_matches(stored: str, password: str) -> bool:
    algorithm, iterations, salt, digest = stored.split("$")
    computed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
    ).hex()
    return algorithm == "pbkdf2_sha256" and hmac.compare_digest(computed, digest)


# --- the settings file ---


def test_the_settings_file_is_written_whole_into_an_empty_volume(box):
    box.install({**CONFIG, "model": "qwen2.5:0.5b"})

    settings = box.containers.settings()
    dashboard = settings["dashboard"]
    assert set(dashboard) == {
        "username",
        "pbkdf2_password",
        "password",
        "password_storage_upgraded",
        "password_change_required",
        "jwt_secret",
    }
    assert dashboard["username"] == "astrbot"
    assert pbkdf2_matches(dashboard["pbkdf2_password"], PASSWORD)
    assert dashboard["pbkdf2_password"].startswith("pbkdf2_sha256$600000$")
    assert dashboard["password"] == hashlib.md5(PASSWORD.encode()).hexdigest()
    assert dashboard["password_storage_upgraded"] is True
    assert dashboard["password_change_required"] is False
    assert len(bytes.fromhex(dashboard["jwt_secret"])) == 32
    assert settings["provider_sources"] == [
        {
            "id": "neutrino_gateway",
            "provider": "openai",
            "type": "openai_chat_completion",
            "provider_type": "chat_completion",
            "enable": True,
            "key": ["$NEUTRINO_GATEWAY_KEY"],
            "api_base": URL + "/v1",
            "timeout": 120,
            "proxy": "",
            "custom_headers": {},
        }
    ]
    assert settings["provider"] == [
        {
            "id": "neutrino_gateway/qwen2.5:0.5b",
            "model": "qwen2.5:0.5b",
            "enable": True,
            "provider_type": "chat_completion",
            "provider_source_id": "neutrino_gateway",
        }
    ]
    assert settings["agent_runner"] == {
        "runner_type": "local",
        "config": {"model": {"provider_id": "neutrino_gateway/qwen2.5:0.5b"}},
    }
    assert settings["pypi_index_url"] == "https://mirror.example/pypi/simple"
    assert settings["disable_metrics"] is True
    assert "k" not in json.dumps(settings["provider_sources"][0]["key"]).strip('"[]$')
    site = box.containers.data() / "python_user/lib/python3.12/site-packages"
    assert site.is_dir()
    mode = stat.S_IMODE((box.containers.data() / "cmd_config.json").stat().st_mode)
    assert mode == 0o600
    assert not list(box.containers.data().glob("*.neutrino_new"))
    record = box.record()
    assert (record["written_password"], record["python"]) == (PASSWORD, "3.12")
    assert (record["provider"], record["is_provider_own"]) == (
        "neutrino_gateway/qwen2.5:0.5b",
        True,
    )


def test_with_no_model_named_the_file_holds_the_source_alone(box):
    box.install()

    settings = box.containers.settings()
    assert [source["id"] for source in settings["provider_sources"]] == [
        "neutrino_gateway"
    ]
    assert "provider" not in settings
    assert "agent_runner" not in settings
    assert box.record()["provider"] == ""


def test_a_volume_that_holds_a_settings_file_keeps_it(box):
    box.containers.data().mkdir()
    held = '{"dashboard": {"username": "astrbot"}, "persona": "kept"}'
    (box.containers.data() / "cmd_config.json").write_text(held)
    box.hooks.take_config(CONFIG)
    box.hooks._keep({"written_password": PASSWORD})

    (step,) = box.hooks.install_steps("4.29.4")
    step.run(box.context)

    assert (box.containers.data() / "cmd_config.json").read_text() == held
    assert (box.containers.data() / "python_user/lib/python3.12/site-packages").is_dir()
    assert box.containers.driven == []


def test_the_requirements_folder_of_a_new_image_s_python_is_made_at_a_version_change(
    box,
):
    box.astrbot.page_status = 200
    box.install()
    before = (box.containers.data() / "cmd_config.json").read_text()
    box.podman.python = "3.13.1"

    box.hooks.take_config(CONFIG)
    (step,) = box.hooks.install_steps("4.30.0")
    step.run(box.context)

    assert (box.containers.data() / "python_user/lib/python3.13/site-packages").is_dir()
    assert (box.containers.data() / "cmd_config.json").read_text() == before
    assert box.record()["python"] == "3.13"


def test_an_image_whose_environment_names_no_python_fails_the_step(box):
    box.podman.python = ""
    box.hooks.take_config(CONFIG)
    (step,) = box.hooks.install_steps("4.29.4")

    with pytest.raises(ModuleApplyError) as failed:
        step.run(box.context)

    assert failed.value.code == "install_failed"
    assert "PYTHON_VERSION" in failed.value.params["detail"]


def test_a_new_password_stops_the_container_writes_the_dashboard_and_starts_it(box):
    box.install()
    settings = box.containers.settings()
    settings["persona"] = "kept"
    settings["dashboard"]["totp"] = {"enable": False}
    (box.containers.data() / "cmd_config.json").write_text(json.dumps(settings))
    earlier_jwt = settings["dashboard"]["jwt_secret"]
    box.podman.is_running = True
    new = {**CONFIG, "password": NEW_PASSWORD}

    assert [step.name for step in box.hooks.before_start_steps(new)] == ["settings"]
    assert [step.name for step in box.hooks.start_steps(new, "4.29.4")] == [
        "first_start"
    ]
    box.astrbot.password = NEW_PASSWORD
    box.start(new)

    written = box.containers.settings()
    assert box.containers.driven == [
        (["neutrino_astrbot"], "stop"),
        (["neutrino_astrbot"], "start"),
    ]
    assert pbkdf2_matches(written["dashboard"]["pbkdf2_password"], NEW_PASSWORD)
    assert written["dashboard"]["jwt_secret"] != earlier_jwt
    assert written["dashboard"]["totp"] == {"enable": False}
    assert written["persona"] == "kept"
    assert written["provider_sources"] == settings["provider_sources"]
    assert box.record()["written_password"] == NEW_PASSWORD
    assert box.hooks.before_start_steps(new) == []


def test_the_record_keeps_no_password_written_after_the_agent_began_to_stop(box):
    box.context.is_stopped = True
    box.hooks.take_config(CONFIG)
    (step,) = box.hooks.install_steps("4.29.4")

    step.run(box.context)

    assert (box.containers.data() / "cmd_config.json").exists()
    assert "written_password" not in box.hooks._record()


# --- the first start ---


def test_the_module_reads_installing_until_its_page_answers(box):
    box.astrbot.page_status = 503

    with pytest.raises(ModuleInstallPending):
        box.install()

    assert box.hooks.is_installing() is True
    assert box.hooks.is_running() is False
    box.astrbot.page_status = 200
    (step,) = box.hooks.start_steps(CONFIG, "4.29.4")
    step.run(box.context)
    assert box.hooks.is_installing() is False
    assert box.hooks.is_running() is True
    assert box.hooks.start_steps(CONFIG, "4.29.4") == []
    assert [step.name for step in box.hooks.start_steps(CONFIG, "4.30.0")] == [
        "first_start"
    ]


def test_the_steps_are_planned_with_their_locks_and_states(box):
    (settings,) = box.hooks.install_steps("4.29.4")
    (first,) = box.hooks.start_steps(CONFIG, "4.29.4")

    assert (settings.name, settings.locks) == ("settings", (("containers", "shared"),))
    assert (first.name, first.locks) == ("first_start", ())
    assert {settings.failed_state, first.failed_state} == {"install_failed"}
    assert box.hooks.before_start_steps({**CONFIG, "password": ""}) == []


# --- the gateway through AstrBot's API ---


def test_a_new_gateway_address_is_written_through_the_api_and_no_file(box):
    box.install()
    scripts = len(box.containers.scripts)
    box.containers.url = "http://host.containers.internal:8400"

    box.start()

    assert (
        box.astrbot.sources[-1]["api_base"] == "http://host.containers.internal:8400/v1"
    )
    assert box.astrbot.sources[-1]["key"] == ["$NEUTRINO_GATEWAY_KEY"]
    assert box.record()["base_url"] == "http://host.containers.internal:8400/v1"
    assert len(box.containers.scripts) == scripts
    sent = [(method, path) for method, path, _, _ in box.astrbot.requests]
    assert ("POST", "/api/v1/provider-sources") in sent
    assert all(
        "origin" not in headers
        for _, path, headers, _ in box.astrbot.requests
        if path.startswith("/api/")
    )


def test_nothing_changes_while_the_model_and_the_address_hold(box):
    box.install({**CONFIG, "model": "m1"})
    asked = len(box.astrbot.requests)

    box.start({**CONFIG, "model": "m1"})
    box.start({**CONFIG, "model": ""})

    assert box.astrbot.paths()[asked:] == [] or set(box.astrbot.paths()[asked:]) <= {
        "/"
    }
    assert box.record()["model"] == "m1"


def test_a_new_model_becomes_the_agent_s_provider_and_the_default(box):
    box.install({**CONFIG, "model": "m1"})
    box.astrbot.providers = [
        {"id": "neutrino_gateway/m1", "provider_source_id": "neutrino_gateway"}
    ]
    box.astrbot.profile = {
        "agent_runner": {"config": {"model": {"provider_id": "neutrino_gateway/m1"}}},
        "persona": "kept",
    }
    scripts = len(box.containers.scripts)

    box.start({**CONFIG, "model": "m2"})

    assert box.astrbot.provider_ids() == ["neutrino_gateway/m2"]
    assert box.astrbot.default_provider() == "neutrino_gateway/m2"
    assert box.astrbot.profile["persona"] == "kept"
    assert ("DELETE", "/api/v1/providers/neutrino_gateway/m1") in [
        (method, path) for method, path, _, _ in box.astrbot.requests
    ]
    record = box.record()
    assert (record["model"], record["provider"], record["is_provider_own"]) == (
        "m2",
        "neutrino_gateway/m2",
        True,
    )
    assert len(box.containers.scripts) == scripts


def test_an_empty_default_takes_the_agent_s_provider(box):
    box.install()
    box.astrbot.profile = {"agent_runner": {"runner_type": "local"}}

    box.start({**CONFIG, "model": "m1"})

    assert box.astrbot.default_provider() == "neutrino_gateway/m1"
    assert box.astrbot.provider_ids() == ["neutrino_gateway/m1"]
    assert box.record()["provider"] == "neutrino_gateway/m1"


def test_a_default_the_person_picked_stays_and_the_agent_s_provider_follows(box):
    box.install({**CONFIG, "model": "m1"})
    box.astrbot.providers = [
        {"id": "neutrino_gateway/m1"},
        {"id": "deepseek/chat", "provider_source_id": "deepseek"},
    ]
    box.astrbot.profile = {
        "agent_runner": {"config": {"model": {"provider_id": "deepseek/chat"}}}
    }

    box.start({**CONFIG, "model": "m2"})

    assert box.astrbot.default_provider() == "deepseek/chat"
    assert box.astrbot.provider_ids() == ["deepseek/chat", "neutrino_gateway/m2"]
    assert "PUT" not in [method for method, _, _, _ in box.astrbot.requests]


def test_a_provider_of_the_person_s_own_is_used_and_never_deleted(box):
    box.install()
    box.astrbot.providers = [{"id": "neutrino_gateway/m1", "provider_source_id": "x"}]

    box.start({**CONFIG, "model": "m1"})
    box.start({**CONFIG, "model": "m2"})

    assert box.astrbot.provider_ids() == ["neutrino_gateway/m1", "neutrino_gateway/m2"]
    assert (
        box.astrbot.paths("POST").count(
            "/api/v1/provider-sources/neutrino_gateway/providers"
        )
        == 1
    )
    assert "DELETE" not in [method for method, _, _, _ in box.astrbot.requests]
    assert box.record()["is_provider_own"] is True


def test_a_failed_call_keeps_the_earlier_model_and_the_next_start_tries_again(box):
    box.install({**CONFIG, "model": "m1"})
    box.astrbot.providers = [{"id": "neutrino_gateway/m1"}]
    box.astrbot.profile = {
        "agent_runner": {"config": {"model": {"provider_id": "neutrino_gateway/m1"}}}
    }
    box.astrbot.failing.add(("PUT", "/api/v1/config-profiles/default"))

    box.start({**CONFIG, "model": "m2"})

    assert box.record()["model"] == "m1"
    assert any("did not take" in line for line in box.lines)
    box.astrbot.failing.clear()
    box.start({**CONFIG, "model": "m2"})

    assert box.astrbot.provider_ids() == ["neutrino_gateway/m2"]
    assert box.astrbot.default_provider() == "neutrino_gateway/m2"
    assert (
        box.astrbot.paths("POST").count(
            "/api/v1/provider-sources/neutrino_gateway/providers"
        )
        == 1
    )
    assert (box.record()["model"], box.record()["is_provider_own"]) == ("m2", True)


def test_an_astrbot_that_never_answers_leaves_the_record_as_it_was(box, monkeypatch):
    box.install({**CONFIG, "model": "m1"})
    box.astrbot.page_status = 503
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(box.hooks, "_monotonic", lambda: next(clock))

    box.start({**CONFIG, "model": "m2"})

    assert box.record()["model"] == "m1"
    assert any("did not answer" in line for line in box.lines)


# --- the forwarder ---


def open_page(astrbot, record_dir, containers) -> InstanceForwarder:
    """A forwarder in front of one AstrBot, listening on a port of its own."""
    hooks = AstrbotHooks(
        platform=AgentPlatform(),
        name="astrbot",
        containers=containers,
        log=lambda line: None,
        record_dir=str(record_dir),
    )
    forwarder = InstanceForwarder(
        name="astrbot",
        record={
            "account": "",
            "port": 0,
            "secret": SECRET,
            "password": PASSWORD,
            "cookie_name": COOKIE_NAME,
            "upstream_port": astrbot.port,
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
    return forwarder


@pytest.fixture
def page(astrbot, tmp_path):
    forwarder = open_page(
        astrbot, tmp_path / "record", FakeContainers(tmp_path, upstream=astrbot.port)
    )
    yield forwarder.listen_address[1]
    forwarder.close()


def ask(port, request: bytes) -> bytes:
    """One request on a connection it closes, its Host loopback's unless it names one."""
    request = request.replace(b"Host: x\r\n", b"")
    extra = b"" if b"\r\nHost: " in request else b"\r\nHost: 127.0.0.1"
    request = request.replace(b"\r\n\r\n", extra + b"\r\nConnection: close\r\n\r\n", 1)
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


def signed_in(page) -> str:
    """The forwarder's cookie a token trades for, as ``name=value``."""
    answer = ask(
        page, f"GET /?tkn={fresh_token()} HTTP/1.1\r\nHost: x\r\n\r\n".encode()
    )
    return header_of(answer, b"set-cookie").split(";", 1)[0]


def test_a_token_sets_the_forwarder_s_cookie_and_redirects_to_its_login_page(
    page, astrbot
):
    token = fresh_token()

    answer = ask(page, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    again = ask(page, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    forged = ask(
        page, f"GET /?tkn={fresh_token('other')} HTTP/1.1\r\nHost: x\r\n\r\n".encode()
    )

    assert status_of(answer) == 302
    assert header_of(answer, b"location") == "/neutrino_login"
    cookie = header_of(answer, b"set-cookie")
    assert cookie.startswith(COOKIE_NAME + "=")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Max-Age=604800" in cookie
    assert status_of(again) == 401
    assert status_of(forged) == 401
    assert astrbot.requests == []


def test_the_login_page_signs_in_and_stores_the_token_and_the_user(page, astrbot):
    cookie = signed_in(page)

    answer = ask(
        page,
        f"GET /neutrino_login HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n\r\n".encode(),
    )

    assert status_of(answer) == 200
    body = answer.split(b"\r\n\r\n", 1)[1].decode()
    assert "localStorage.setItem('token', \"jwt-1\")" in body
    assert "localStorage.setItem('user', \"astrbot\")" in body
    assert "location.replace('/')" in body
    ((method, path, headers, sent),) = astrbot.requests
    assert (method, path) == ("POST", "/api/auth/login")
    assert json.loads(sent) == {"username": "astrbot", "password": PASSWORD}
    assert "origin" not in headers


def test_the_cookie_is_passed_on_with_host_and_origin_unchanged(page, astrbot):
    cookie = signed_in(page)

    answer = ask(
        page,
        b"POST /api/v1/chat HTTP/1.1\r\nHost: 127.0.0.1:47001\r\n"
        b"Origin: http://127.0.0.1:47001\r\nAuthorization: Bearer jwt-9\r\n"
        + f"Cookie: {cookie}\r\nContent-Length: 2\r\n\r\n{{}}".encode(),
    )

    assert status_of(answer) == 200
    method, path, headers, body = astrbot.requests[-1]
    assert (method, path, body) == ("POST", "/api/v1/chat", b"{}")
    assert headers["host"] == "127.0.0.1:47001"
    assert headers["origin"] == "http://127.0.0.1:47001"


def test_a_request_with_neither_a_token_nor_the_cookie_is_refused(page, astrbot):
    plain = ask(page, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    foreign = ask(
        page,
        f"GET / HTTP/1.1\r\nHost: x\r\nCookie: {COOKIE_NAME}=forged\r\n\r\n".encode(),
    )

    assert (status_of(plain), status_of(foreign)) == (401, 401)
    assert astrbot.requests == []


@pytest.mark.parametrize("path", ASTRBOT_REFUSED_PATHS)
def test_each_refused_route_is_401_whatever_the_request_holds(page, astrbot, path):
    cookie = signed_in(page)

    answer = ask(
        page,
        f"POST {path} HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n"
        "Content-Length: 2\r\n\r\n{}".encode(),
    )
    slashed = ask(
        page,
        f"POST /{path}/ HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n"
        "Content-Length: 2\r\n\r\n{}".encode(),
    )

    assert (status_of(answer), status_of(slashed)) == (401, 401)
    assert astrbot.requests == []


SAVES = [
    ("PUT", "/api/v1/system-config", lambda dashboard: {"dashboard": dashboard}),
    (
        "PUT",
        "/api/v1/config-profiles/default",
        lambda dashboard: {"dashboard": dashboard},
    ),
    (
        "POST",
        "/api/config/astrbot/update",
        lambda dashboard: {"conf_id": "default", "config": {"dashboard": dashboard}},
    ),
]


@pytest.mark.parametrize("method, path, wrap", SAVES)
@pytest.mark.parametrize(
    "dashboard",
    [
        {"ssl": {"enable": True}},
        {"totp": {"enable": True}},
        {"port": 6186},
        {"host": "127.0.0.1"},
    ],
)
def test_a_settings_save_that_moves_the_dashboard_is_refused(
    page, astrbot, method, path, wrap, dashboard
):
    cookie = signed_in(page)
    body = json.dumps(wrap({**dashboard, "username": "astrbot"})).encode()

    answer = ask(
        page,
        f"{method} {path} HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n"
        f"Content-Length: {len(body)}\r\n\r\n".encode() + body,
    )

    assert status_of(answer) == 401
    assert astrbot.requests == []


@pytest.mark.parametrize("method, path, wrap", SAVES)
def test_a_settings_save_that_keeps_the_dashboard_passes_with_its_body(
    page, astrbot, method, path, wrap
):
    cookie = signed_in(page)
    dashboard = {
        "port": 6185,
        "host": "0.0.0.0",
        "ssl": {"enable": False},
        "totp": {"enable": False},
    }
    body = json.dumps({**wrap(dashboard), "timezone": "Asia/Shanghai"}).encode()

    answer = ask(
        page,
        f"{method} {path} HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n"
        "Authorization: Bearer jwt-9\r\n"
        f"Content-Length: {len(body)}\r\n\r\n".encode() + body,
    )

    assert status_of(answer) == 200
    assert astrbot.requests[-1][:2] == (method, path)
    assert astrbot.requests[-1][3] == body


def test_a_settings_save_that_is_no_json_object_is_refused(page, astrbot):
    cookie = signed_in(page)

    answer = ask(
        page,
        f"PUT /api/v1/system-config HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n"
        "Content-Length: 3\r\n\r\n[1]".encode(),
    )

    assert status_of(answer) == 401
    assert astrbot.requests == []


def test_the_path_is_matched_as_astrbot_s_router_matches_it():
    assert normal_path("/api//auth/./login/") == "/api/auth/login"
    assert normal_path("/api/%61uth/login") == "/api/auth/login"
    assert normal_path("") == "/"


def test_the_forwarder_takes_the_first_free_port_from_6185_and_keeps_it(box):
    box.hooks.apply(CONFIG)
    box.hooks.start()

    (forwarder,) = box.forwarders
    assert (forwarder.record["port"], forwarder.record["upstream_port"]) == (
        6185,
        box.astrbot.port,
    )
    assert box.hooks.details() == {"port": 6185}
    box.hooks.stop()
    assert forwarder.is_closed
    assert box.record()["is_stopped"] is True
    box.hooks.remove()
    assert not os.path.exists(box.record_dir)
