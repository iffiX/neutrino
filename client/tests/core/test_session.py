"""The resident's socket: the hello, the welcome, the state, the report, the streams.

One scripted socket stands in for the wire: a test hands the session the
frames the hub would send and reads back what the client sent. What is
pinned here is the hello's six fields, the welcome written onto the binding,
a refused first frame, a state that replaces what was held and feeds the
handlers, the disabled switch letting go once and resuming, the report
after every state and on the interval, a service stream correlated to its
close, the one refusal that unbinds and the ones the binding survives, a
replaced socket waiting for a person, the backoff after a broken wire, a
start that turns nothing on and clears what an unclean exit left, and a
shutdown that runs its order once, logs a line a step, and lets no step
hold up the rest.
"""

import json
import threading
import time

import pytest

import neutrino_client.core.channel as channel
import neutrino_client.core.session as session_module
from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_BACKOFF_MAX_S,
    CLIENT_DEFAULT_THEME,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
    CLIENT_ROLE,
    CLIENT_SOFTWARE_PREFIX,
    PROTOCOL,
)
from neutrino_client.core import protocol
from neutrino_client.core.session import ClientSession
from neutrino_client.exceptions import (
    GatewayProtocolRefused,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    SocketClosed,
)
from neutrino_client.services.base import ServiceTypeHandler
from neutrino_client.services.file import mount_record_id
from tests.conftest import SERVICES, FakeClientPlatform, bind, discard

WELCOME = {
    "type": "welcome",
    "protocol": 1,
    "role": "hub",
    "id": "h2",
    "name": "office",
    "software": "neutrino_hub/0.3.0",
}
STATE = {"type": "state", "hash": "h1", "is_disabled": False, "services": SERVICES}
MATERIAL = {"host": "h", "port": 21118, "password": "p"}  # scan: allow


class ScriptedSocket:
    """A socket whose frames are written by the test that needs them.

    Attributes:
        sent: Every message the client sent, decoded.
        is_closed: Whether the client closed it.
    """

    def __init__(self, frames, *, connect_error=None):
        """
        Args:
            frames: What ``recv`` hands back in turn. A dict is sent as a
                text frame, bytes as a binary frame, an exception is raised,
                an event holds the read until it is set, and the list
                running out behaves like the hub hanging up.
            connect_error: Raised by ``connect`` instead of connecting.
        """
        self._frames = list(frames)
        self._connect_error = connect_error
        self.sent = []
        self.is_closed = False
        self.is_open = False
        # Set once the client has read every frame the script holds.
        self.is_drained = threading.Event()

    def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self.is_open = True

    def send_text(self, text: str) -> None:
        if self.is_closed:
            raise GatewayUnreachable("the socket is closed")
        self.sent.append(json.loads(text))

    def recv(self):
        while self._frames and isinstance(self._frames[0], threading.Event):
            self._frames.pop(0).wait(timeout=5)
        if not self._frames:
            self.is_drained.set()
            raise GatewayUnreachable("hub hung up")
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        if isinstance(frame, bytes):
            return "binary", frame
        return "text", json.dumps(frame)

    def close(self, code: int = 1000, reason: str = "") -> None:
        self.is_closed = True
        self.is_open = False


class RecordingHandler(ServiceTypeHandler):
    """A handler that remembers the lifecycle calls it was given.

    Attributes:
        starts: How often the resident started it.
        cleared: How often it was asked to clear leftovers.
        refreshed: The entries of every refresh, in order.
        is_holding: Set while a release that hangs is held.
    """

    def __init__(self, service_type: str, log: list, *, count=None, is_hanging=False):
        """
        Args:
            service_type: The type this stands in for.
            log: Appended to on every release, in order.
            count: What its release reports letting go of.
            is_hanging: Whether its release blocks until it is let go.
        """
        self.service_type = service_type
        self.starts = 0
        self.cleared = 0
        self.refreshed = []
        self._log = log
        self._count = count
        self._is_hanging = is_hanging
        self._held = threading.Event()
        self.is_holding = threading.Event()

    def act(self, *, entries, body):
        return {}

    def refresh(self, *, entries) -> None:
        self.refreshed.append(list(entries))

    def start(self) -> None:
        self.starts += 1

    def clear_leftovers(self) -> None:
        self.cleared += 1

    def release(self):
        self._log.append(self.service_type)
        if self._is_hanging:
            self.is_holding.set()
            self._held.wait(timeout=5)
        return self._count

    def let_go(self) -> None:
        """Let a hanging release finish, so the test leaves no thread behind."""
        self._held.set()


class SocketScript:
    """A fresh scripted socket for every connection, all from one script.

    Attributes:
        made: Every socket handed out, in the order they were opened.
    """

    def __init__(self, frames, connect_error=None):
        """
        Args:
            frames: What each socket's ``recv`` hands back in turn.
            connect_error: Raised by every ``connect``.
        """
        self._frames = list(frames)
        self._connect_error = connect_error
        self.made = []

    def __call__(self, **kwargs) -> ScriptedSocket:
        made = ScriptedSocket(self._frames, connect_error=self._connect_error)
        self.made.append(made)
        return made


def socket_of(monkeypatch, frames, *, connect_error=None) -> SocketScript:
    """Put a scripted socket under every connection the session opens."""
    script = SocketScript(frames, connect_error=connect_error)
    monkeypatch.setattr(session_module, "WebSocketClient", script)
    return script


def connected(session, script) -> ScriptedSocket:
    """Open one socket and take its welcome, without serving frames after it."""
    made = script()
    session._connect(made)
    return made


def take(session, made, frame) -> None:
    """Hand the session one frame the way its reader would.

    Args:
        session: The session under test.
        made: The socket the frame arrives on.
        frame: A dict for a text frame, bytes for a binary one.
    """
    if isinstance(frame, bytes):
        session._dispatch(made, "binary", frame)
    else:
        session._dispatch(made, "text", json.dumps(frame))


def reports(made) -> list:
    """Every report the client sent on one socket."""
    return [frame for frame in made.sent if frame["type"] == "report"]


def released_handlers(session, counts=None) -> list:
    """Swap every releasable handler for one that records, and return the log."""
    log = []
    counts = counts or {}
    for service_type in ("ai", "file", "port", "rdp"):
        session._services[service_type] = RecordingHandler(
            service_type, log, count=counts.get(service_type)
        )
    return log


class QuietSwitcher:
    """A switcher over a machine with nothing pointed at the hub."""

    def __init__(self):
        self.calls = []

    def is_installed(self) -> bool:
        return True

    def find_cli(self) -> str:
        return "/opt/neutrino_client/bin/cc-switch"

    def is_active_for(self, app: str) -> bool:
        return False

    def activate(self, *, base_url, api_key, tool_configs=None) -> str:
        self.calls.append("activate")
        return "claude"

    def deactivate(self, *, base_url="") -> str:
        self.calls.append("deactivate")
        return ""


@pytest.fixture
def bound(config_path):
    bind(config_path, url="https://hub.lan:8443")
    return ClientSession(log=discard, platform=FakeClientPlatform())


def test_the_first_start_takes_the_machines_language_and_keeps_it(bound):
    """The machine is asked once; what it answered is the client's own from then."""
    bound.platform.language = "zh-CN"

    assert bound.language() == "zh-CN"

    bound.platform.language = "en"
    assert bound.language() == "zh-CN"


def test_a_picked_language_is_kept_and_the_watchers_are_told(bound):
    told = []
    bound.subscribe(lambda: told.append(1))

    bound.set_language("zh-CN")

    assert bound.language() == "zh-CN"
    deadline = time.time() + 2
    while not told and time.time() < deadline:
        time.sleep(0.01)
    assert told == [1]


def test_a_picked_theme_is_kept_and_the_watchers_are_told(bound):
    told = []
    bound.subscribe(lambda: told.append(1))

    bound.set_theme("light")

    assert bound.theme() == "light"
    deadline = time.time() + 2
    while not told and time.time() < deadline:
        time.sleep(0.01)
    assert told == [1]


def test_the_theme_is_the_default_until_one_is_picked(bound):
    assert bound.theme() == CLIENT_DEFAULT_THEME


# --- the handshake ---


def test_the_hello_is_the_bindings_identity_card(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME, STATE])

    bound.run_once()

    hello = script.made[0].sent[0]
    assert hello == {
        "type": "hello",
        "protocol": PROTOCOL,
        "role": CLIENT_ROLE,
        "id": "c1",
        "name": "box",
        "software": f"{CLIENT_SOFTWARE_PREFIX}{CLIENT_VERSION}",
        "token": "tok",
    }
    assert PROTOCOL == 1 and CLIENT_ROLE == "client"
    for absent in ("hostname", "platform", "catalog_hash", "state_hash", "kind"):
        assert absent not in hello


def test_the_first_report_follows_the_hello_with_the_machine_and_no_hash(
    bound, monkeypatch
):
    script = socket_of(monkeypatch, [WELCOME])

    bound.run_once()

    report = script.made[0].sent[1]
    assert report == {
        "type": "report",
        "state_hash": "",
        "machine": {"hostname": bound.hostname(), "platform": bound.platform_tuple()},
    }


def test_the_next_connections_first_report_carries_the_hash_held(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME, STATE])

    bound.run_once()
    bound.run_once()

    assert reports(script.made[0])[0]["state_hash"] == ""
    assert reports(script.made[1])[0]["state_hash"] == "h1"


def test_the_welcome_names_the_hub_and_is_written_onto_the_binding(
    bound, monkeypatch, config_path
):
    socket_of(monkeypatch, [WELCOME, STATE])

    bound.run_once()

    assert bound.hub_version() == "0.3.0"
    assert bound.is_connected() is True
    (binding,) = json.loads(config_path.read_text())["bindings"]
    assert (binding["hub_id"], binding["hub_name"]) == ("h2", "office")
    assert (binding["id"], binding["token"]) == ("c1", "tok")


def test_a_welcome_naming_what_the_binding_holds_writes_nothing(
    bound, monkeypatch, config_path
):
    socket_of(monkeypatch, [dict(WELCOME, id="h1", name="home")])
    before = config_path.stat().st_mtime_ns

    bound.run_once()

    assert config_path.stat().st_mtime_ns == before
    assert bound.is_connected() is True


def test_a_first_frame_that_is_not_a_welcome_is_unreachable(bound, monkeypatch):
    script = socket_of(monkeypatch, [STATE])

    delay = bound.run_once()

    assert delay == 5
    assert bound.last_error()["code"] == "hub_unreachable"
    assert script.made[0].is_closed is True


def test_a_welcome_of_another_role_is_unreachable(bound, monkeypatch):
    script = socket_of(monkeypatch, [dict(WELCOME, role="agent")])

    bound.run_once()

    assert bound.last_error()["code"] == "hub_unreachable"
    assert script.made[0].is_closed is True
    assert bound.connection_state() == "reconnecting"


@pytest.mark.parametrize("code", ["protocol_too_old", "protocol_too_new"])
def test_a_refused_first_frame_naming_the_protocol_keeps_the_binding(
    bound, monkeypatch, config_path, code
):
    script = socket_of(
        monkeypatch,
        [{"type": "refused", "code": code, "params": {"peer": 1, "hub": 2, "min": 2}}],
    )
    released = released_handlers(bound)

    delays = [bound.run_once() for _ in range(5)]

    assert bound.is_connected() is True
    assert bound.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert bound.last_error() == {
        "code": code,
        "params": {"peer": 1, "hub": 2, "min": 2},
    }
    assert released == []
    assert delays == [CLIENT_BACKOFF_MAX_S] * 5
    assert all(made.is_closed for made in script.made)


def test_binding_unknown_is_the_one_refusal_that_unbinds(
    bound, monkeypatch, config_path
):
    script = socket_of(
        monkeypatch,
        [{"type": "refused", "code": "binding_unknown", "params": {"id": "c1"}}],
    )
    released = released_handlers(bound)

    delay = bound.run_once()
    bound.run_once()

    assert delay == CLIENT_IDLE_POLL_INTERVAL_S
    assert bound.is_connected() is False
    assert bound.connection_state() == "unbound"
    assert json.loads(config_path.read_text())["bindings"] == []
    assert released == ["ai", "file", "port", "rdp"]
    assert bound.last_error() == {
        "code": "binding_unknown",
        "params": {"id": "c1"},
    }
    assert len(script.made) == 1


def test_a_refused_first_frame_of_another_code_keeps_the_binding(
    bound, monkeypatch, config_path
):
    socket_of(
        monkeypatch,
        [{"type": "refused", "code": "ticket_spent", "params": {"id": "c1"}}],
    )
    released = released_handlers(bound)

    delays = [bound.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert bound.is_connected() is True
    assert bound.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert bound.last_error() == {"code": "ticket_spent", "params": {"id": "c1"}}
    assert released == []


def test_a_welcome_after_a_refusal_clears_the_error(bound, monkeypatch):
    socket_of(monkeypatch, [{"type": "refused", "code": "ticket_spent", "params": {}}])
    bound.run_once()
    assert bound.last_error()["code"] == "ticket_spent"

    connected(bound, socket_of(monkeypatch, [WELCOME]))

    assert bound.last_error() is None
    assert bound.connection_state() == "connected"


def test_a_refused_frame_carries_its_code_on_the_exception(bound, monkeypatch):
    script = socket_of(
        monkeypatch,
        [{"type": "refused", "code": "binding_unknown", "params": {"id": "c1"}}],
    )

    with pytest.raises(GatewayRefused) as refused:
        connected(bound, script)

    assert refused.value.code == "binding_unknown"
    assert refused.value.params == {"id": "c1"}
    assert not isinstance(refused.value, GatewayProtocolRefused)


# --- the state ---


def test_a_state_replaces_what_was_held(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    take(bound, made, STATE)
    assert [entry["id"] for entry in bound.service_entries()] == [
        entry["id"] for entry in SERVICES
    ]
    take(bound, made, {"type": "state", "hash": "h2", "services": []})

    assert bound.service_entries() == []
    assert bound._state_hash == "h2"


def test_every_state_is_answered_with_a_report_carrying_its_hash(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    take(bound, made, STATE)
    take(bound, made, dict(STATE, hash="h2"))

    assert [report["state_hash"] for report in reports(made)] == ["", "h1", "h2"]
    assert reports(made)[-1]["machine"]["hostname"] == bound.hostname()


def test_a_state_of_the_wrong_shape_is_typed_and_never_fatal(bound, monkeypatch):
    script = socket_of(
        monkeypatch,
        [WELCOME, {"type": "state", "hash": "h2", "services": "not a list"}],
    )
    made = script()
    bound._connect(made)

    failure = bound._serve(made)

    assert isinstance(failure, GatewayUnreachable)
    assert bound._last_error["code"] == "hub_reply_unreadable"


def test_a_state_hands_its_services_to_the_ai_handler(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))
    released_handlers(bound)

    take(bound, made, STATE)

    assert bound._services["ai"].refreshed == [SERVICES]


def test_disabled_lets_go_of_everything_but_the_binding(
    bound, monkeypatch, config_path
):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))
    released = released_handlers(bound)

    take(bound, made, dict(STATE, is_disabled=True))

    assert bound.is_disabled() is True
    assert bound.is_connected() is True
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert bound.last_error() == {"code": "client_disabled", "params": {}}
    assert released == ["ai", "file", "port", "rdp"]
    assert bound._services["ai"].refreshed == []
    assert bound.service_action("port", {"id": "svc_tcp", "is_enabled": True}) == {
        "code": "client_disabled",
        "params": {},
    }


def test_a_disabled_client_is_released_once_then_resumes(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))
    released = released_handlers(bound)

    take(bound, made, dict(STATE, is_disabled=True))
    take(bound, made, dict(STATE, is_disabled=True))
    take(bound, made, dict(STATE, is_disabled=False))

    assert released == ["ai", "file", "port", "rdp"]
    assert bound.is_disabled() is False
    assert bound.last_error() is None
    assert bound._services["ai"].refreshed == [SERVICES]


def test_an_unknown_frame_is_ignored(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    take(bound, made, {"type": "something_else"})
    take(bound, made, STATE)

    assert [entry["id"] for entry in bound.service_entries()] == [
        entry["id"] for entry in SERVICES
    ]
    assert bound.last_error() is None


def test_a_report_goes_up_on_the_interval(bound, monkeypatch):
    monkeypatch.setattr(session_module, "CLIENT_REPORT_INTERVAL_S", 0.02)
    hold = threading.Event()
    script = socket_of(monkeypatch, [WELCOME, STATE, hold])
    made = script()
    bound._connect(made)
    served = threading.Thread(target=bound._serve, args=(made,))

    served.start()
    deadline = time.monotonic() + 5
    while len(reports(made)) < 4 and time.monotonic() < deadline:
        time.sleep(0.01)
    hold.set()
    served.join(timeout=5)

    assert len(reports(made)) >= 4
    assert {report["state_hash"] for report in reports(made)[2:]} == {"h1"}


# --- the streams ---


def test_a_service_stream_goes_up_odd_and_its_close_comes_back(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    answered = _open_while(
        bound, made, {"type": "close", "stream": 1, "params": MATERIAL}
    )

    opened = made.sent[-1]
    assert opened == {"type": "open", "stream": 1, "kind": "service", "id": "rdp_s9"}
    assert answered == MATERIAL


def test_a_second_stream_takes_the_next_odd_id(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))
    _open_while(bound, made, {"type": "close", "stream": 1, "params": {}})

    _open_while(bound, made, {"type": "close", "stream": 3, "params": {}})

    assert [frame["stream"] for frame in made.sent if frame["type"] == "open"] == [
        1,
        3,
    ]


def test_a_close_carrying_a_code_is_the_hubs_own_refusal(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    with pytest.raises(GatewayRefusedDetail) as refused:
        _open_while(
            bound,
            made,
            {
                "type": "close",
                "stream": 1,
                "code": "rdp_not_shared",
                "params": {"id": "rdp_s9"},
            },
        )

    assert refused.value.code == "rdp_not_shared"
    assert refused.value.params == {"id": "rdp_s9"}


def test_a_stream_with_no_socket_is_unreachable(bound):
    with pytest.raises(GatewayUnreachable):
        bound.open_service("rdp_s9")


def test_a_stream_nobody_closes_gives_up(bound, monkeypatch):
    connected(bound, socket_of(monkeypatch, [WELCOME]))

    with pytest.raises(GatewayUnreachable):
        bound.open_service("rdp_s9", timeout_s=0.05)


def test_a_socket_that_ends_wakes_the_stream_unreachable(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))
    outcome = {}

    def wait() -> None:
        try:
            bound.open_service("rdp_s9", timeout_s=5)
        except GatewayUnreachable as error:
            outcome["error"] = error

    waiter = threading.Thread(target=wait)
    waiter.start()
    while len(made.sent) < 3:
        time.sleep(0.01)
    bound._end_socket(made)
    waiter.join(timeout=5)

    assert isinstance(outcome.get("error"), GatewayUnreachable)
    assert bound._streams is None


def test_a_close_for_nobody_is_dropped(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    take(bound, made, {"type": "close", "stream": 9, "params": {}})

    assert bound.last_error() is None


def test_credit_and_bytes_from_the_hub_are_dropped(bound, monkeypatch):
    lines = []
    bound._log = lines.append
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    take(bound, made, {"type": "credit", "stream": 1, "bytes": 4096})
    take(bound, made, protocol.encode_binary(1, b"line\n"))

    assert bound.last_error() is None
    assert [line for line in lines if line.startswith("dropping")] == [
        "dropping credit on stream 1",
        "dropping 5 bytes the hub sent on stream 1",
    ]
    assert all(frame["type"] != "credit" for frame in made.sent)


def test_a_stream_the_hub_opens_is_closed_kind_unknown(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    take(bound, made, {"type": "open", "stream": 2, "kind": "shell", "cols": 80})

    assert made.sent[-1] == {
        "type": "close",
        "stream": 2,
        "code": "kind_unknown",
        "params": {"kind": "shell"},
    }
    assert bound.last_error() is None


def test_a_binary_frame_shorter_than_an_id_is_typed_and_never_fatal(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME, b"\x00\x01"])
    made = script()
    bound._connect(made)

    failure = bound._serve(made)

    assert isinstance(failure, GatewayUnreachable)
    assert bound._last_error["code"] == "hub_reply_unreadable"


# --- what ends a connection ---


def test_a_broken_wire_backs_off_and_keeps_the_binding(bound, monkeypatch):
    socket_of(monkeypatch, [], connect_error=GatewayUnreachable("down"))

    delays = [bound.run_once() for _ in range(3)]

    assert delays == [5, 10, 20]
    assert bound.is_connected() is True
    assert bound.connection_state() == "reconnecting"
    assert bound.last_error()["code"] == "hub_unreachable"


def test_a_replaced_socket_waits_for_a_person(bound, monkeypatch, config_path):
    """Another socket holds this binding; this one opens no more on its own."""
    script = socket_of(monkeypatch, [WELCOME, SocketClosed(4010, "replaced")])
    released = released_handlers(bound)

    bound.run_once()
    delay = bound.run_once()

    assert bound.connection_state() == "replaced"
    assert bound.is_connected() is True
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert bound.last_error() is None
    assert released == []
    assert delay == CLIENT_IDLE_POLL_INTERVAL_S
    assert len(script.made) == 1


def test_a_person_takes_a_replaced_binding_back(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME, SocketClosed(4010, "replaced")])
    bound.run_once()
    bound._news.clear()

    bound.reconnect()

    assert bound.connection_state() == "reconnecting"
    assert bound._news.is_set()
    bound.run_once()
    assert len(script.made) == 2
    assert script.made[1].sent[0]["type"] == "hello"


def test_reconnect_names_the_hub_held_or_none(bound, monkeypatch):
    socket_of(monkeypatch, [WELCOME, SocketClosed(4010, "replaced")])
    bound.run_once()

    with pytest.raises(KeyError):
        bound.reconnect("h9")
    assert bound.connection_state() == "replaced"

    bound.reconnect("h2")
    assert bound.connection_state() == "reconnecting"


def test_a_binding_written_on_disk_ends_the_replaced_state(
    bound, monkeypatch, config_path
):
    socket_of(monkeypatch, [WELCOME, SocketClosed(4010, "replaced")])
    bound.run_once()
    assert bound.connection_state() == "replaced"

    config_path.write_text("{}")
    bound.run_once()

    assert bound.connection_state() == "unbound"


@pytest.mark.parametrize(
    "error, code",
    [
        (GatewayRefused("401"), "hub_refused"),
        (GatewayUntrusted("pin"), "hub_untrusted"),
        (GatewayRefused("refused", code="role_mismatch"), "role_mismatch"),
    ],
)
def test_a_refusal_the_binding_survives_asks_again_a_minute_later(
    bound, monkeypatch, config_path, error, code
):
    socket_of(monkeypatch, [], connect_error=error)
    released = released_handlers(bound)

    delays = [bound.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert bound.is_connected() is True
    assert bound.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert bound.last_error()["code"] == code
    assert released == []


@pytest.mark.parametrize("code", ["protocol_too_old", "protocol_too_new"])
def test_a_hub_that_does_not_speak_this_protocol_never_unbinds(
    bound, monkeypatch, config_path, code
):
    socket_of(
        monkeypatch,
        [],
        connect_error=GatewayProtocolRefused(code=code, peer=1, hub=2, minimum=2),
    )
    released = released_handlers(bound)

    delays = [bound.run_once() for _ in range(5)]

    assert bound.is_connected() is True
    assert bound.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert bound.last_error() == {
        "code": code,
        "params": {"peer": 1, "hub": 2, "min": 2},
    }
    assert released == []
    assert delays == [CLIENT_BACKOFF_MAX_S] * 5


def test_a_close_4000_without_a_frame_is_hub_refused_and_keeps_the_binding(
    bound, monkeypatch, config_path
):
    """The close arrives instead of the welcome, which is when the hub sends
    one."""
    socket_of(monkeypatch, [SocketClosed(4000, "")])
    released = released_handlers(bound)

    delays = [bound.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert bound.is_connected() is True
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert bound.last_error() == {"code": "hub_refused", "params": {}}
    assert released == []


# --- the binding, and the way out ---


def test_an_unbound_resident_idles_and_opens_no_socket(monkeypatch, config_path):
    session = ClientSession(log=discard, platform=FakeClientPlatform())
    script = socket_of(monkeypatch, [WELCOME])

    delay = session.run_once()

    assert delay == 2
    assert session.connection_state() == "unbound"
    assert script.made == []


def test_an_external_binding_is_adopted_by_its_stamp(monkeypatch, config_path):
    session = ClientSession(log=discard, platform=FakeClientPlatform())
    assert session.is_connected() is False
    script = socket_of(monkeypatch, [WELCOME])

    bind(config_path, url="https://hub.lan:8443")
    session.run_once()

    assert session.is_connected() is True
    assert script.made[0].sent[0]["type"] == "hello"


def test_the_hubs_name_written_by_the_welcome_is_not_adopted_as_news(
    bound, monkeypatch
):
    """The welcome's write is the session's own; the next turn must not
    drop the socket over it."""
    script = socket_of(monkeypatch, [WELCOME, STATE])
    lines = []
    bound._log = lines.append

    bound.run_once()
    bound.run_once()

    assert len(script.made) == 2
    assert "adopted the binding written on disk" not in lines


def test_an_external_disconnect_releases_everything(bound, monkeypatch, config_path):
    socket_of(monkeypatch, [WELCOME, STATE])
    released = released_handlers(bound)
    bound.run_once()

    config_path.write_text("{}")
    delay = bound.run_once()

    assert bound.is_connected() is False
    assert bound.service_entries() == []
    assert released == ["ai", "file", "port", "rdp"]
    assert delay == 2


def test_disconnect_tells_the_hub_over_http_first_and_lets_go(
    bound, monkeypatch, config_path
):
    posted = []

    def post(self, path, payload):
        posted.append((path, payload))
        return {}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post, raising=True)
    released = released_handlers(bound)

    bound.disconnect()

    assert posted == [("/api/channel/leave", {"id": "c1", "token": "tok"})]
    assert bound.is_connected() is False
    assert json.loads(config_path.read_text())["bindings"] == []
    assert released == ["ai", "file", "port", "rdp"]


def test_disconnect_lets_go_when_the_hub_refuses_the_leave(
    bound, monkeypatch, config_path
):
    def refuse(self, path, payload):
        raise GatewayRefused("401")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", refuse, raising=True)

    bound.disconnect()

    assert bound.is_connected() is False
    assert json.loads(config_path.read_text())["bindings"] == []


# --- the start, and the one way out ---


def test_the_start_turns_nothing_on(config_path, tmp_path):
    """Opening the client shows a clean machine: a record is a preference,
    never a mount to bring back."""
    platform = FakeClientPlatform()
    session = ClientSession(log=discard, platform=platform)
    session._services["ai"]._switcher = QuietSwitcher()
    location = str(tmp_path / "nas")
    record_id = mount_record_id("share_media", location)
    session._store.set_mount(
        record_id,
        {
            "entry_id": "share_media",
            "host": "hub",
            "share": "media",
            "username": "media",
            "path": location,
        },
    )
    credentials = tmp_path / "config" / CLIENT_MOUNT_CREDENTIALS_DIR_NAME
    credentials.mkdir(parents=True)
    (credentials / f"{record_id}.credentials").write_text("username=media")

    session.start()
    try:
        session._services["file"].reconcile()
    finally:
        session.shutdown()

    assert platform.attach_calls == []
    states = session.service_states()
    assert states["ai"]["is_enabled"] is False
    assert states["ai"]["is_active"] is False
    assert [row["state"] for row in states["mounts"]] == ["detached"]


def test_the_start_clears_what_an_unclean_exit_left(config_path):
    session = ClientSession(log=discard, platform=FakeClientPlatform())
    released_handlers(session)

    session.start()
    session.shutdown()

    assert session._services["ai"].cleared == 1
    assert session._services["file"].cleared == 1
    assert session._services["ai"].starts == 1


def test_a_handler_that_cannot_clear_is_logged_and_never_fatal(config_path):
    lines = []
    session = ClientSession(log=lines.append, platform=FakeClientPlatform())
    released_handlers(session)

    def refuse() -> None:
        raise OSError("busy")

    session._services["file"].clear_leftovers = refuse

    session.start()
    session.shutdown()

    assert any(line.startswith("file: could not clear") for line in lines)
    assert session._services["file"].starts == 1


def test_the_shutdown_logs_one_line_a_step_in_order(config_path):
    lines = []
    session = ClientSession(log=lines.append, platform=FakeClientPlatform())
    released_handlers(session, counts={"file": 2, "port": 1, "rdp": 0})

    session.shutdown()

    assert lines == [
        "ai: restored",
        "mounts: 2 detached",
        "forwards: 1 closed",
        "viewers: 0 closed",
        "shut down",
    ]


def test_a_step_that_hangs_is_given_up_and_the_others_still_run(
    config_path, monkeypatch
):
    monkeypatch.setattr(session_module, "CLIENT_SHUTDOWN_DEADLINE_S", 0.4)
    lines = []
    session = ClientSession(log=lines.append, platform=FakeClientPlatform())
    released = released_handlers(session)
    hanging = RecordingHandler("ai", released, is_hanging=True)
    session._services["ai"] = hanging

    started = time.monotonic()
    session.shutdown()
    hanging.let_go()

    assert hanging.is_holding.is_set()
    assert released == ["ai", "file", "port", "rdp"]
    assert lines[0].startswith("ai: gave up after ")
    assert lines[-1] == "shut down"
    assert time.monotonic() - started < 5


def test_shutdown_runs_the_order_once_and_is_idempotent(bound):
    released = released_handlers(bound)

    bound.shutdown()
    bound.shutdown()

    assert released == ["ai", "file", "port", "rdp"]


def test_shutdown_survives_a_handler_that_refuses(bound):
    released = []

    class Refusing(RecordingHandler):
        def release(self):
            raise OSError("busy")

    bound._services["ai"] = Refusing("ai", released)
    for service_type in ("file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)

    bound.shutdown()

    assert released == ["file", "port", "rdp"]


def test_shutdown_closes_the_socket(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    bound.shutdown()

    assert made.is_closed is True


def test_the_state_carries_every_handlers_keys(bound):
    states = bound.service_states()

    assert set(states) >= {"forwards", "mounts", "ai", "ai_tool_configs", "viewers"}


def test_an_unknown_service_type_is_refused(bound):
    assert bound.service_action("nothing", {}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_show_reaches_the_registered_window(bound):
    shown = []

    def show() -> None:
        shown.append(1)

    bound.on_show = show
    bound.request_show()
    bound.on_show = None
    bound.request_show()

    assert shown == [1]


def _open_while(session, made, close_frame):
    """Open a service stream on one thread while the test closes it.

    Args:
        session: The session under test.
        made: The scripted socket the open lands on.
        close_frame: The close the hub answers with, handed to the session
            once the open has gone up.

    Returns:
        What :meth:`ClientSession.open_service` returned.

    Raises:
        Exception: Whatever the open raised.
    """
    outcome = {}
    opens_before = len([frame for frame in made.sent if frame["type"] == "open"])

    def run() -> None:
        try:
            outcome["result"] = session.open_service("rdp_s9", timeout_s=5)
        except Exception as error:  # noqa: BLE001 - handed back to the test
            outcome["error"] = error

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 5
    while (
        len([frame for frame in made.sent if frame["type"] == "open"]) <= opens_before
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    take(session, made, close_frame)
    thread.join(timeout=5)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def test_a_burst_of_changes_reaches_the_watchers_once(bound, monkeypatch):
    monkeypatch.setattr(session_module, "ANNOUNCE_SETTLE_S", 0.05)
    heard = []
    done = threading.Event()

    def watcher():
        heard.append(1)
        done.set()

    bound.subscribe(watcher)

    for _ in range(5):
        bound.notify()

    assert done.wait(timeout=5)
    time.sleep(0.2)
    assert heard == [1]


def test_a_change_during_the_announcement_brings_one_more_round(bound, monkeypatch):
    monkeypatch.setattr(session_module, "ANNOUNCE_SETTLE_S", 0.05)
    heard = []
    second = threading.Event()

    def watcher():
        heard.append(1)
        if len(heard) == 1:
            bound.notify()
        else:
            second.set()

    bound.subscribe(watcher)
    bound.notify()

    assert second.wait(timeout=5)
    time.sleep(0.2)
    assert heard == [1, 1]


def test_a_watcher_that_fails_does_not_stop_the_others(bound, monkeypatch):
    monkeypatch.setattr(session_module, "ANNOUNCE_SETTLE_S", 0.01)
    heard = threading.Event()

    def broken():
        raise RuntimeError("no window")

    bound.subscribe(broken)
    bound.subscribe(heard.set)
    bound.notify()

    assert heard.wait(timeout=5)


def test_a_stop_during_a_turn_ends_the_loop_without_waiting_out_the_delay(bound):
    """The stop lands while a turn runs; the wait after it must not sleep."""
    turns = []

    def one_turn():
        turns.append(1)
        bound.shutdown()
        return 60

    bound.run_once = one_turn
    started = time.monotonic()
    bound.run_forever()

    assert turns == [1]
    assert time.monotonic() - started < 5


def test_a_socket_that_ends_while_stopping_is_no_failure(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))
    bound._stop.set()

    failure = bound._serve(made)

    assert failure is None
    assert bound.last_error() is None


def test_the_handlers_announce_through_the_session(bound):
    for service_type in ("port", "ai", "file", "rdp"):
        handler = bound._services[service_type]
        assert handler._on_change == bound.notify
