"""Ayakaleaf's hooks: the first start, the forwarder's login, the guests, a version change.

What these pin, against a faked ``podman`` and a fake app on loopback: the
replica set initiated once, the administrator made through ``/launchpad``
with its session's CSRF token, the Chinese TeX set installed with the
fastest ``ctan`` source on ``tlmgr``'s command line after ``tlmgr`` updates
itself from it, each step kept in the record and skipped after, a new password in
the state changed on the administrator signed in with the old one,
``ayakaleaf_setup_failed {step, detail}`` from
each step and from a ``/launchpad`` that already sends to ``/login``; the
forwarder's two requests giving the app's cookie under ``cookie_name``, 401
for a ``POST /login``, a path under ``/launchpad`` and a request with
neither; a version change making the TeX volume again; each guest the state
names made in the four steps and kept with its ``user_id``, a guest the
state drops deleted, ``ayakaleaf_guest_failed {step, detail}`` from each
step and the step run again at the next apply; and the forwarder signing a
token under a guest's secret in as that guest with its invitations
accepted, never as the administrator.
"""

import json
import os
import socket
import time

import pytest

from neutrino_agent.exceptions import (
    ModuleApplyError,
    ModuleInstallPending,
    ModuleSetupError,
)
from neutrino_agent.modules.ayakaleaf import hooks as hooks_module
from neutrino_agent.modules.ayakaleaf.constants import AYAKALEAF_FORWARDER_FIELDS
from neutrino_agent.modules.ayakaleaf.hooks import (
    AppBrowser,
    AyakaleafHooks,
    activation,
    invitations,
    is_login_route,
    route_path,
)
from neutrino_agent.modules.shared.http_forward import InstanceForwarder, mint_token
from neutrino_agent.modules.shared.source_fetch import SourceProbe
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform
from tests.modules.ayakaleaf.fake_app import ADMIN_EMAIL, FakeApp

SECRET = "token-secret-of-the-module"
PASSWORD = "administrator-password"
COOKIE_NAME = "ayakaleaf_sid_a9cae9416662"
GUEST = {
    "account": "guest-k3f9",
    "email": "guest-k3f9@share.neutrino",
    "password": "guest-password",
    "secret": "guest-token-secret",
}
CONFIG = {
    "secret": SECRET,
    "password": PASSWORD,
    "cookie_name": COOKIE_NAME,
    "local_name": "ayakaleaf.m.localhost",
    "guests": [],
}
PODMAN = "/usr/bin/podman"
CTAN = {
    "probe": "/systems/texlive/tlnet/tlpkg/texlive.tlpdb.sha512",
    "sources": ["https://slow.example/CTAN", "https://fast.example/CTAN"],
    "variables": [],
}
COLLECTIONS = [
    "collection-langchinese",
    "collection-xetex",
    "collection-latexrecommended",
    "collection-pictures",
]


class FakeContainers:
    """The Containers runner as the hooks reach it."""

    def __init__(self, *, upstream=41234):
        self.upstream = upstream
        self.driven: list = []
        self.names = {
            "ayakaleaf": [
                "neutrino_ayakaleaf_mongo",
                "neutrino_ayakaleaf_redis",
                "neutrino_ayakaleaf",
            ]
        }

    def podman_command(self):
        return (PODMAN,)

    def page_port(self, module, name):
        assert (module, name) == ("ayakaleaf", "neutrino_ayakaleaf")
        return self.upstream

    def hub_names(self):
        return dict(self.names)

    def drive_hub_containers(self, names, action):
        self.driven.append((list(names), action))


class FakePodman:
    """podman's answers: mongosh, tlmgr by repository, and the volume commands."""

    def __init__(self):
        self.calls: list = []
        self.mongo_exit = 0
        self.mongo_said = "MongoServerError: connection refused"
        # Each tlmgr repository's exit code, 0 for one not named, and the
        # repositories whose install alone fails.
        self.tlmgr_exits: dict = {}
        self.install_refusals: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        if "mongosh" in command:
            said = "" if self.mongo_exit == 0 else self.mongo_said
            return CommandResult(list(command), self.mongo_exit, "", said)
        if "tlmgr" in command:
            repository = command[command.index("--repository") + 1]
            code = self.tlmgr_exits.get(repository, 0)
            if "install" in command and repository in self.install_refusals:
                code = 3
            said = "" if code == 0 else f"tlmgr: {repository} is not a repository"
            return CommandResult(list(command), code, "running mktexlsr\n", said)
        return CommandResult(list(command), 0, "", "")

    def named(self, word: str) -> list:
        return [call for call in self.calls if word in call]


class FakeForwarder:
    def __init__(self, *, name, record, hooks, log):
        self.record = dict(record)
        self.is_started = False
        self.is_closed = False

    def matches(self, record):
        return all(
            record.get(field) == self.record.get(field)
            for field in AYAKALEAF_FORWARDER_FIELDS
        )

    def start(self):
        self.is_started = True

    def close(self):
        self.is_closed = True


def fast_ctan(url, *, source, headers=None):
    """The probe of a ctan source: the fast one answers quicker."""
    speed = 2_000_000.0 if "fast" in source else 100_000.0
    return SourceProbe(source=source, is_answered=True, speed=speed, status=200)


class Box:
    """The hooks against a fake app and a faked podman, the clock set by the test."""

    def __init__(self, tmp_path, app):
        self.app = app
        self.podman = FakePodman()
        self.containers = FakeContainers(upstream=app.port)
        self.forwarders: list = []
        self.lines: list = []
        self.now = 1000.0
        self.record_dir = str(tmp_path / "ayakaleaf")
        self.hooks = self.make()
        self.hooks.take_source_sets({"ctan": CTAN})

    def make(self) -> AyakaleafHooks:
        return AyakaleafHooks(
            platform=AgentPlatform(),
            name="ayakaleaf",
            containers=self.containers,
            log=self.lines.append,
            run_command=self.podman,
            forwarder_factory=self.forwarder,
            record_dir=self.record_dir,
            is_port_free=lambda port: True,
            probe_one=fast_ctan,
            clock=lambda: self.now,
        )

    def forwarder(self, **kwargs):
        made = FakeForwarder(**kwargs)
        self.forwarders.append(made)
        return made

    def record(self) -> dict:
        path = os.path.join(self.record_dir, "ayakaleaf.json")
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)

    def start(self, config=None) -> None:
        self.hooks.apply(config or CONFIG)
        self.hooks.start()


@pytest.fixture
def app():
    server = FakeApp(cookie_name=COOKIE_NAME)
    yield server
    server.stop()


@pytest.fixture
def box(tmp_path, app):
    return Box(tmp_path, app)


def ready(box) -> None:
    """A box whose first start has ended."""
    box.hooks.installed("6.3.2")
    box.start()


# --- the first start ---


def test_the_first_start_runs_the_three_steps_in_order_and_keeps_each(box, app):
    box.hooks.installed("6.3.2")
    box.start()

    (initiate,) = box.podman.named("mongosh")
    assert initiate == [
        PODMAN,
        "exec",
        "neutrino_ayakaleaf_mongo",
        "mongosh",
        "--quiet",
        "--eval",
        'db.isMaster().primary || rs.initiate({_id: "overleaf", members: '
        '[{_id: 0, host: "neutrino_ayakaleaf_mongo:27017"}]})',
    ]
    assert app.accounts[ADMIN_EMAIL]["password"] == PASSWORD
    assert app.accounts[ADMIN_EMAIL]["is_admin"] is True
    head = [
        PODMAN,
        "exec",
        "neutrino_ayakaleaf",
        "tlmgr",
        "--repository",
        "https://fast.example/CTAN/systems/texlive/tlnet",
    ]
    assert box.podman.named("tlmgr") == [
        [*head, "update", "--self"],
        [*head, "install", *COLLECTIONS],
    ]
    assert box.record()["steps"] == ["replica_set", "admin", "tex"]
    assert box.record()["is_ready"] is True
    assert box.hooks.is_installing() is False


def test_the_administrator_is_made_with_the_launchpad_s_session_and_token(box, app):
    ready(box)

    get, post = [
        entry
        for entry in app.requests
        if entry[1] in ("/launchpad", "/launchpad/register_admin")
    ]
    assert (get[0], post[0]) == ("GET", "POST")
    body = json.loads(post[3])
    assert set(body) == {"_csrf", "email", "password"}
    assert body["email"] == ADMIN_EMAIL
    assert "Origin" not in post[2]
    assert COOKIE_NAME + "=" in post[2]["Cookie"]


def test_the_start_waits_while_the_app_does_not_answer_and_reads_installing(box, app):
    app.status_code = 503
    box.hooks.installed("6.3.2")

    with pytest.raises(ModuleInstallPending):
        box.start()

    assert box.record()["steps"] == ["replica_set"]
    assert box.hooks.is_installing() is True
    assert "/launchpad" not in app.paths()

    app.status_code = 200
    box.start()

    assert len(box.podman.named("mongosh")) == 1
    assert box.hooks.is_installing() is False


def test_the_replica_set_is_tried_again_while_mongo_starts_then_fails(box):
    box.podman.mongo_exit = 1
    box.hooks.installed("6.3.2")

    with pytest.raises(ModuleInstallPending):
        box.start()
    box.now += 119
    with pytest.raises(ModuleInstallPending):
        box.start()
    box.now += 2
    with pytest.raises(ModuleSetupError) as failed:
        box.start()

    assert failed.value.code == "ayakaleaf_setup_failed"
    assert failed.value.params == {
        "step": "replica_set",
        "detail": "MongoServerError: connection refused",
    }
    assert box.hooks.is_installing() is False
    assert box.record().get("steps") == []


def test_a_launchpad_that_sends_to_login_fails_the_administrator_step(box, app):
    app.add_account("someone@example.com", "theirs", is_admin=True)
    box.hooks.installed("6.3.2")

    with pytest.raises(ModuleSetupError) as failed:
        box.start()

    assert failed.value.params["step"] == "admin"
    assert "an administrator exists" in failed.value.params["detail"]
    assert box.record()["steps"] == ["replica_set"]
    assert box.podman.named("tlmgr") == []


def test_the_tex_step_moves_to_the_next_source_when_one_fails(box):
    box.podman.tlmgr_exits = {
        "https://fast.example/CTAN/systems/texlive/tlnet": 1,
    }
    ready(box)

    assert [call[5:7] for call in box.podman.named("tlmgr")] == [
        ["https://fast.example/CTAN/systems/texlive/tlnet", "update"],
        ["https://slow.example/CTAN/systems/texlive/tlnet", "update"],
        ["https://slow.example/CTAN/systems/texlive/tlnet", "install"],
    ]
    assert box.record()["is_ready"] is True


def test_an_install_refused_after_the_self_update_moves_to_the_next_source(box):
    box.podman.install_refusals = {"https://fast.example/CTAN/systems/texlive/tlnet"}
    ready(box)

    assert [call[5:7] for call in box.podman.named("tlmgr")] == [
        ["https://fast.example/CTAN/systems/texlive/tlnet", "update"],
        ["https://fast.example/CTAN/systems/texlive/tlnet", "install"],
        ["https://slow.example/CTAN/systems/texlive/tlnet", "update"],
        ["https://slow.example/CTAN/systems/texlive/tlnet", "install"],
    ]


def test_the_tex_step_fails_with_the_last_source_s_last_line(box):
    box.podman.tlmgr_exits = {
        "https://fast.example/CTAN/systems/texlive/tlnet": 1,
        "https://slow.example/CTAN/systems/texlive/tlnet": 2,
    }
    box.hooks.installed("6.3.2")

    with pytest.raises(ModuleSetupError) as failed:
        box.start()

    assert failed.value.params == {
        "step": "tex",
        "detail": "tlmgr: https://slow.example/CTAN/systems/texlive/tlnet "
        "is not a repository",
    }
    assert box.record()["steps"] == ["replica_set", "admin"]


def test_a_state_with_no_ctan_source_fails_the_tex_step(box):
    box.hooks.take_source_sets({})
    box.hooks.installed("6.3.2")

    with pytest.raises(ModuleSetupError) as failed:
        box.start()

    assert failed.value.params == {
        "step": "tex",
        "detail": "the state names no ctan source",
    }


def test_install_again_runs_only_the_steps_the_record_does_not_hold(box, app):
    box.podman.tlmgr_exits = {
        "https://fast.example/CTAN/systems/texlive/tlnet": 1,
        "https://slow.example/CTAN/systems/texlive/tlnet": 1,
    }
    box.hooks.installed("6.3.2")
    with pytest.raises(ModuleSetupError):
        box.start()

    box.podman.tlmgr_exits = {}
    box.hooks.installed("6.3.2")
    box.start()

    assert len(box.podman.named("mongosh")) == 1
    assert app.paths("POST").count("/launchpad/register_admin") == 1
    assert box.record()["steps"] == ["replica_set", "admin", "tex"]


def test_a_new_password_in_the_state_changes_the_administrator_s(box, app):
    """A machine that joins another hub keeps the app's data, whose
    administrator has the old hub's password."""
    ready(box)
    before = len(app.requests)

    box.start({**CONFIG, "password": "new-hub-password"})

    assert app.accounts[ADMIN_EMAIL]["password"] == "new-hub-password"
    (change,) = [
        entry
        for entry in app.requests[before:]
        if entry[:2] == ("POST", "/user/password/update")
    ]
    body = json.loads(change[3])
    assert body["currentPassword"] == PASSWORD
    assert body["newPassword1"] == body["newPassword2"] == "new-hub-password"
    assert app.paths("POST").count("/launchpad/register_admin") == 1
    assert len(box.podman.named("mongosh")) == 1
    assert len(box.podman.named("tlmgr")) == 2
    assert sorted(box.record()["steps"]) == ["admin", "replica_set", "tex"]
    assert box.record()["admin_password"] == "new-hub-password"
    assert box.record()["is_ready"] is True


def test_the_same_password_changes_nothing(box, app):
    ready(box)

    box.start()

    assert "/user/password/update" not in app.paths()


def test_a_refused_change_fails_the_administrator_step_and_keeps_the_old_password(
    box, app
):
    ready(box)
    app.accounts[ADMIN_EMAIL]["password"] = "a-person-s-own"

    with pytest.raises(ModuleSetupError) as failed:
        box.start({**CONFIG, "password": "new-hub-password"})

    assert failed.value.params["step"] == "admin"
    assert box.record()["admin_password"] == PASSWORD
    assert "admin" not in box.record()["steps"]


def test_the_guests_of_the_new_password_are_made_after_the_change(box, app):
    ready(box)

    box.start({**CONFIG, "password": "new-hub-password", "guests": [GUEST]})

    assert GUEST["email"] in app.accounts
    assert box.hooks.details()["guests"] == [
        {"account": "guest-k3f9", "code": "", "params": {}}
    ]


def test_a_version_change_makes_the_tex_volume_again_and_runs_the_tex_step(box):
    ready(box)

    box.hooks.installed("6.3.3")

    assert box.containers.driven == [(["neutrino_ayakaleaf"], "stop")]
    assert box.podman.named("volume") == [
        [PODMAN, "volume", "rm", "-f", "neutrino_ayakaleaf_texlive"],
        [PODMAN, "volume", "create", "neutrino_ayakaleaf_texlive"],
    ]
    assert box.record()["steps"] == ["replica_set", "admin"]
    assert box.record()["is_ready"] is False

    box.start()

    assert len(box.podman.named("mongosh")) == 1
    assert len(box.podman.named("tlmgr")) == 4
    assert box.record()["version"] == "6.3.3"


def test_the_first_install_and_the_same_version_again_reset_nothing(box):
    box.hooks.installed("6.3.2")
    box.hooks.installed("6.3.2")

    assert box.containers.driven == []
    assert box.podman.calls == []


def test_running_is_status_answering_200_at_the_published_port(box, app):
    ready(box)

    assert box.hooks.is_running() is True
    app.status_code = 500
    assert box.hooks.is_running() is False


def test_the_forwarder_takes_the_first_free_port_from_8900_and_keeps_it(box):
    ready(box)

    (forwarder,) = box.forwarders
    assert (forwarder.record["port"], forwarder.record["upstream_port"]) == (
        8900,
        box.app.port,
    )
    assert box.hooks.details() == {"port": 8900, "guests": []}


def test_stop_closes_the_forwarder_and_remove_forgets_the_record(box):
    ready(box)

    box.hooks.stop()
    assert box.forwarders[0].is_closed
    assert box.record()["is_stopped"] is True

    box.hooks.remove()
    assert not os.path.exists(box.record_dir)


def test_after_a_restart_the_record_brings_the_forwarder_and_the_guests_back(box):
    ready(box)
    box.start({**CONFIG, "guests": [GUEST]})

    again = box.make()
    details = again.details()

    assert details["guests"] == [{"account": "guest-k3f9", "code": "", "params": {}}]
    assert box.forwarders[-1].is_started
    assert [made["email"] for made in again._guests._made] == [GUEST["email"]]


# --- the guests ---


def test_a_guest_is_made_in_four_steps_and_kept_with_its_user_id(box, app):
    ready(box)
    before = len(app.requests)

    box.start({**CONFIG, "guests": [GUEST]})

    steps = [(method, path) for method, path, _, _ in app.requests[before:]]
    assert steps == [
        ("GET", "/status"),
        ("GET", "/login"),
        ("POST", "/login"),
        ("GET", "/project"),
        ("POST", "/admin/register"),
        ("GET", "/user/activate"),
        ("POST", "/user/password/set"),
        ("GET", "/login"),
        ("POST", "/login"),
        ("GET", "/project"),
        ("POST", "/user/settings"),
    ]
    account = app.accounts[GUEST["email"]]
    assert account["password"] == GUEST["password"]
    assert account["first_name"] == "guest-k3f9"
    (made,) = box.record()["guests"]
    assert made == {**GUEST, "user_id": account["user_id"]}
    assert box.hooks.details()["guests"] == [
        {"account": "guest-k3f9", "code": "", "params": {}}
    ]


def test_an_apply_that_changes_nothing_writes_no_record(box, app):
    ready(box)
    path = os.path.join(box.record_dir, "ayakaleaf.json")
    before = os.stat(path).st_mtime_ns
    os.utime(path, ns=(before - 10**9, before - 10**9))

    box.start()

    assert os.stat(path).st_mtime_ns == before - 10**9


def test_a_guest_the_record_holds_is_not_made_again(box, app):
    ready(box)
    box.start({**CONFIG, "guests": [GUEST]})
    before = len(app.requests)

    box.start({**CONFIG, "guests": [GUEST]})

    assert app.requests[before:] == []


def test_a_guest_the_state_drops_is_deleted_by_its_user_id(box, app):
    ready(box)
    box.start({**CONFIG, "guests": [GUEST]})
    user_id = app.accounts[GUEST["email"]]["user_id"]

    box.start(CONFIG)

    assert ("POST", f"/admin/user/{user_id}/delete") in [
        (method, path) for method, path, _, _ in app.requests
    ]
    assert GUEST["email"] not in app.accounts
    assert box.record()["guests"] == []
    assert box.hooks.details()["guests"] == []


@pytest.mark.parametrize(
    ("refused", "step"),
    [
        ("/admin/register", "register"),
        ("/user/password/set", "password"),
        ("/user/settings", "name"),
    ],
)
def test_a_failed_step_names_the_guest_and_runs_again_at_the_next_apply(
    box, app, refused, step
):
    ready(box)
    app.refused_paths.add(refused)

    box.start({**CONFIG, "guests": [GUEST]})

    (reported,) = box.hooks.details()["guests"]
    assert reported["account"] == "guest-k3f9"
    assert reported["code"] == "ayakaleaf_guest_failed"
    assert reported["params"]["step"] == step
    assert reported["params"]["detail"].startswith(f"{refused} answered 500")
    assert box.record()["guests"] == []

    app.refused_paths.clear()
    box.start({**CONFIG, "guests": [GUEST]})

    assert box.hooks.details()["guests"] == [
        {"account": "guest-k3f9", "code": "", "params": {}}
    ]


def test_a_refused_administrator_login_fails_every_owed_guest(box, app):
    ready(box)
    app.accounts[ADMIN_EMAIL]["password"] = "changed"

    box.start({**CONFIG, "guests": [GUEST]})

    (reported,) = box.hooks.details()["guests"]
    assert reported["params"]["step"] == "admin_login"


def test_an_owed_guest_waits_while_the_app_does_not_answer(box, app):
    ready(box)
    app.status_code = 503

    with pytest.raises(ModuleInstallPending):
        box.start({**CONFIG, "guests": [GUEST]})

    assert box.hooks.is_installing() is False
    assert box.hooks.details()["guests"] == []


# --- the forwarder ---


def open_page(box) -> InstanceForwarder:
    """A forwarder in front of the fake app, listening on a port of its own."""
    forwarder = InstanceForwarder(
        name="ayakaleaf",
        record={**box.record(), "account": "", "port": 0},
        hooks=box.hooks,
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
def page(box):
    ready(box)
    forwarder = open_page(box)
    yield forwarder.listen_address[1]
    forwarder.close()


def ask(port, request: bytes) -> bytes:
    """One request on a connection it closes, its Host loopback's unless it names one."""
    extra = b"" if b"\r\nHost: " in request else b"\r\nHost: 127.0.0.1"
    request = request.replace(b"\r\n\r\n", extra + b"\r\nConnection: close\r\n\r\n", 1)
    with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
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


def signed_in_as(app, answer: bytes) -> str:
    """The e-mail the session the forwarder handed the browser signs in as."""
    cookie = header_of(answer, b"set-cookie")
    name, _, value = cookie.split(";", 1)[0].partition("=")
    assert name == COOKIE_NAME
    return app.sessions[value]["email"]


def test_a_token_under_the_module_s_secret_signs_in_as_the_administrator(page, app):
    token = fresh_token()

    answer = ask(page, f"GET /?tkn={token} HTTP/1.1\r\n\r\n".encode())
    again = ask(page, f"GET /?tkn={token} HTTP/1.1\r\n\r\n".encode())

    assert status_of(answer) == 302
    assert header_of(answer, b"location") == "/project"
    assert signed_in_as(app, answer) == ADMIN_EMAIL
    assert status_of(again) == 401
    login = [entry for entry in app.requests if entry[:2] == ("POST", "/login")][-1]
    assert "Origin" not in login[2]
    assert login[2]["Accept"] == "application/json"


def test_a_token_under_a_guest_s_secret_signs_in_as_the_guest_and_accepts_its_invitations(
    box, page, app
):
    box.start({**CONFIG, "guests": [GUEST]})
    app.invitations[GUEST["email"]] = [("a" * 24, "invitetoken1")]

    answer = ask(
        page, f"GET /?tkn={fresh_token(GUEST['secret'])} HTTP/1.1\r\n\r\n".encode()
    )

    assert status_of(answer) == 302
    assert signed_in_as(app, answer) == GUEST["email"]
    assert app.accepted == [(GUEST["email"], "a" * 24)]
    assert app.invitations[GUEST["email"]] == []


def test_a_guest_token_is_401_while_the_record_does_not_hold_the_guest(box, page, app):
    app.refused_paths.add("/admin/register")
    box.start({**CONFIG, "guests": [GUEST]})

    answer = ask(
        page, f"GET /?tkn={fresh_token(GUEST['secret'])} HTTP/1.1\r\n\r\n".encode()
    )

    assert status_of(answer) == 401


def test_the_session_cookie_is_passed_on_with_host_and_origin_unchanged(page, app):
    answer = ask(
        page,
        b"GET /project HTTP/1.1\r\nHost: 127.0.0.1:47001\r\n"
        b"Origin: http://127.0.0.1:47001\r\n"
        + f"Cookie: {COOKIE_NAME}=abc\r\n\r\n".encode(),
    )

    assert status_of(answer) == 302
    method, path, headers, _ = app.requests[-1]
    assert (method, path) == ("GET", "/project")
    assert headers["Host"] == "127.0.0.1:47001"
    assert headers["Origin"] == "http://127.0.0.1:47001"


@pytest.mark.parametrize(
    "request_bytes",
    [
        b"POST /login HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}",
        b"POST //LOGIN/ HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}",
        b"GET /launchpad HTTP/1.1\r\n\r\n",
        b"POST /launchpad/register_admin HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}",
        b"GET /project HTTP/1.1\r\n\r\n",
    ],
)
def test_the_browser_s_login_the_launchpad_and_a_request_with_neither_are_401(
    page, app, request_bytes
):
    before = len(app.requests)
    request = request_bytes.replace(
        b"\r\n\r\n", f"\r\nCookie: {COOKIE_NAME}=abc\r\n\r\n".encode(), 1
    )
    if b"/project" in request_bytes:
        request = request_bytes

    assert status_of(ask(page, request)) == 401
    assert app.requests[before:] == []


def test_a_token_of_another_secret_is_401(page):
    answer = ask(page, f"GET /?tkn={fresh_token('other')} HTTP/1.1\r\n\r\n".encode())

    assert status_of(answer) == 401


def test_an_app_that_refuses_the_password_is_502(box, page, app):
    app.accounts[ADMIN_EMAIL]["password"] = "changed"

    answer = ask(page, f"GET /?tkn={fresh_token()} HTTP/1.1\r\n\r\n".encode())

    assert status_of(answer) == 502


# --- the pure parts ---


@pytest.mark.parametrize(
    ("method", "path", "is_refused"),
    [
        ("POST", "/login", True),
        ("POST", "/Login/", True),
        ("POST", "//login", True),
        ("POST", "/x/../login", True),
        ("POST", "/%6Cogin", True),
        ("GET", "/login", False),
        ("GET", "/launchpad", True),
        ("GET", "/LaunchPad/x", True),
        ("POST", "/launchpad/register_admin", True),
        ("GET", "/launchpadx", False),
        ("POST", "/project/new", False),
    ],
)
def test_the_login_routes_are_matched_however_they_are_spelled(
    method, path, is_refused
):
    assert is_login_route(method, path) is is_refused


def test_a_route_is_lower_case_with_dots_and_slashes_resolved():
    assert route_path("//A/./b/../C/") == "/a/c"
    assert route_path("") == "/"


def test_the_invitations_are_read_from_the_project_list_s_notifications():
    held = json.dumps(
        [
            {
                "templateKey": "notification_project_invite",
                "messageOpts": {"projectId": "a" * 24, "token": "tok_1"},
            },
            {"templateKey": "notification_other", "messageOpts": {}},
            {
                "templateKey": "notification_project_invite",
                "messageOpts": {"projectId": "../x", "token": "tok"},
            },
        ]
    ).replace('"', "&quot;")
    page = f'<meta name="ol-notifications" data-type="json" content="{held}">'

    assert invitations(page) == [("a" * 24, "tok_1")]
    assert invitations("<html></html>") == []


def test_the_activation_address_names_the_user_id_and_the_token():
    url = "http://localhost/user/activate?token=abc&user_id=" + "f" * 24

    assert activation(url) == ("f" * 24, "abc")
    assert activation("http://localhost/user/activate?token=abc") == ("", "")


def test_a_browser_keeps_the_app_s_cookies_and_the_last_csrf_token(app):
    browser = AppBrowser(port=app.port, cookie_name=COOKIE_NAME)

    browser.get("/login")

    assert browser.csrf != ""
    assert browser.session_header.startswith(COOKIE_NAME + "=")


def test_the_forwarder_tries_a_held_port_again_every_report_interval():
    made = hooks_module._forwarder(
        name="ayakaleaf",
        record={"account": "ayakaleaf", "port": 8900},
        hooks=None,
        log=lambda line: None,
    )

    assert made._retry_s == 5
    assert made.account == ""
