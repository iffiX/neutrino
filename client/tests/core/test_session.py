"""One hub's session: the hello, the welcome, the state, the report, the streams.

One scripted socket stands in for the wire: a test hands the session the
frames the hub would send and reads back what the client sent. What is
pinned here is the hello's six fields, the welcome written onto the binding,
a refused first frame, a state that replaces what was held and reaches the
resident through the callbacks, the disabled switch told once, the report
after every state and on the interval, a service stream correlated to its
close, the one refusal that hands the binding back and the ones the binding
survives, at the door and on a live socket alike, a replaced socket waiting
for a person, the backoff after a broken wire, and a stop that closes the
socket. The connection round over every address the hub answers on is
pinned too: the name first, the one that answered written back, a whole
round failing being what backs off, the state's ``urls`` kept on disk, a
network change starting a round at once and moving a live socket to the
name's address.
"""

import json
import threading
import time

import pytest

import neutrino_client.core.session as session_module
from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_BACKOFF_MAX_S,
    CLIENT_BACKOFF_MIN_S,
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_ROLE,
    CLIENT_SOFTWARE_PREFIX,
    PROTOCOL,
)
from neutrino_client.core import enrollment, protocol
from neutrino_client.core.session import ClientHubSession
from neutrino_client.exceptions import (
    GatewayProtocolRefused,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    SocketClosed,
)
from tests.conftest import BINDING, HUB_SERVICES, bind, discard

WELCOME = {
    "type": "welcome",
    "protocol": 1,
    "role": "hub",
    "id": "h2",
    "name": "office",
    "software": "neutrino_hub/0.3.0",
}
STATE = {"type": "state", "hash": "h1", "is_disabled": False, "services": HUB_SERVICES}
MATERIAL = {"host": "h", "port": 21118, "password": "p"}  # scan: allow
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}


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

    def abort(self) -> None:
        self.is_closed = True
        self.is_open = False


class BlockingSocket(ScriptedSocket):
    """A socket whose connect blocks until it is aborted.

    Attributes:
        is_aborted: Set by ``abort``; the connect then fails.
    """

    def __init__(self):
        super().__init__([])
        self.is_aborted = threading.Event()

    def connect(self) -> None:
        self.is_aborted.wait(timeout=5)
        raise GatewayUnreachable("the connect was aborted")

    def abort(self) -> None:
        self.is_aborted.set()
        self.is_closed = True


class SocketScript:
    """A fresh scripted socket for every connection, all from one script.

    Attributes:
        made: Every socket handed out, in the order they were opened.
        hosts: The host each socket was opened for.
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
        self.hosts = []

    def __call__(self, **kwargs) -> ScriptedSocket:
        made = ScriptedSocket(self._frames, connect_error=self._connect_error)
        self.made.append(made)
        self.hosts.append(kwargs.get("host", ""))
        return made


class Listener:
    """What the resident hears from a session, recorded in order.

    Attributes:
        changes: How often the session announced a change.
        events: ``(name, session)`` for every services, disabled and
            unbound callback, in order.
    """

    def __init__(self):
        self.changes = 0
        self.events = []

    def on_change(self) -> None:
        self.changes += 1

    def on_services(self, session) -> None:
        self.events.append(("services", session))

    def on_disabled(self, session) -> None:
        self.events.append(("disabled", session))

    def on_unbound(self, session) -> None:
        self.events.append(("unbound", session))

    def names(self) -> list:
        return [name for name, _session in self.events]


def socket_of(monkeypatch, frames, *, connect_error=None) -> SocketScript:
    """Put a scripted socket under every connection a session opens."""
    script = SocketScript(frames, connect_error=connect_error)
    monkeypatch.setattr(session_module, "WebSocketClient", script)
    return script


def session_for(binding=None, listener=None, log=discard) -> ClientHubSession:
    """A session over one binding, its callbacks on the listener."""
    listener = listener if listener is not None else Listener()
    return ClientHubSession(
        binding=dict(BINDING, gateway_url="https://hub.lan:8443", **(binding or {})),
        hostname="box",
        platform_tuple=PLATFORM,
        log=log,
        on_change=listener.on_change,
        on_services=listener.on_services,
        on_disabled=listener.on_disabled,
        on_unbound=listener.on_unbound,
    )


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


@pytest.fixture
def bound(config_path):
    bind(config_path, url="https://hub.lan:8443")
    listener = Listener()
    return session_for(listener=listener), listener


# --- the handshake ---


def test_the_hello_is_the_bindings_identity_card(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [WELCOME, STATE])

    session.run_once()

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


def test_the_socket_is_opened_at_the_bindings_hub(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [WELCOME])

    session.run_once()

    assert script.hosts == ["hub.lan"]


def test_the_first_report_follows_the_hello_with_the_machine_and_no_hash(
    bound, monkeypatch
):
    session, _listener = bound
    script = socket_of(monkeypatch, [WELCOME])

    session.run_once()

    report = script.made[0].sent[1]
    assert report == {
        "type": "report",
        "state_hash": "",
        "machine": {"hostname": "box", "platform": PLATFORM},
    }


def test_the_next_connections_first_report_carries_the_hash_held(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [WELCOME, STATE])

    session.run_once()
    session.run_once()

    assert reports(script.made[0])[0]["state_hash"] == ""
    assert reports(script.made[1])[0]["state_hash"] == "h1"


def test_the_welcome_names_the_hub_and_is_written_onto_the_binding(
    bound, monkeypatch, config_path
):
    session, _listener = bound
    socket_of(monkeypatch, [WELCOME, STATE])

    session.run_once()

    assert session.hub_software() == "neutrino_hub/0.3.0"
    assert (session.hub_id(), session.hub_name()) == ("h2", "office")
    (binding,) = json.loads(config_path.read_text())["bindings"]
    assert (binding["hub_id"], binding["hub_name"]) == ("h2", "office")
    assert (binding["id"], binding["token"]) == ("c1", "tok")


def test_a_welcome_naming_what_the_binding_holds_writes_nothing(
    bound, monkeypatch, config_path
):
    session, _listener = bound
    socket_of(monkeypatch, [dict(WELCOME, id="h1", name="home")])
    before = config_path.stat().st_mtime_ns

    session.run_once()

    assert config_path.stat().st_mtime_ns == before
    assert session.hub_id() == "h1"


def test_a_first_frame_that_is_not_a_welcome_is_unreachable(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [STATE])

    delay = session.run_once()

    assert delay == 5
    assert session.last_error()["code"] == "hub_unreachable"
    assert script.made[0].is_closed is True


def test_a_welcome_of_another_role_is_unreachable(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [dict(WELCOME, role="agent")])

    session.run_once()

    assert session.last_error()["code"] == "hub_unreachable"
    assert script.made[0].is_closed is True
    assert session.connection_state() == "reconnecting"


@pytest.mark.parametrize("code", ["protocol_too_old", "protocol_too_new"])
def test_a_refused_first_frame_naming_the_protocol_keeps_the_binding(
    bound, monkeypatch, config_path, code
):
    session, listener = bound
    script = socket_of(
        monkeypatch,
        [{"type": "refused", "code": code, "params": {"peer": 1, "hub": 2, "min": 2}}],
    )

    delays = [session.run_once() for _ in range(5)]

    assert session.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() == {
        "code": code,
        "params": {"peer": 1, "hub": 2, "min": 2},
    }
    assert listener.events == []
    assert delays == [CLIENT_BACKOFF_MAX_S] * 5
    assert all(made.is_closed for made in script.made)


def test_binding_unknown_is_the_one_refusal_that_hands_the_binding_back(
    bound, monkeypatch, config_path
):
    session, listener = bound
    script = socket_of(
        monkeypatch,
        [{"type": "refused", "code": "binding_unknown", "params": {"id": "c1"}}],
    )

    delay = session.run_once()
    session.run_once()

    assert delay == CLIENT_IDLE_POLL_INTERVAL_S
    assert listener.events == [("unbound", session)]
    assert session.last_error() == {
        "code": "binding_unknown",
        "params": {"id": "c1"},
    }
    # The session opens no more; the resident removes the binding.
    assert len(script.made) == 1
    assert len(json.loads(config_path.read_text())["bindings"]) == 1


def test_a_refused_first_frame_of_another_code_keeps_the_binding(
    bound, monkeypatch, config_path
):
    session, listener = bound
    socket_of(
        monkeypatch,
        [{"type": "refused", "code": "ticket_spent", "params": {"id": "c1"}}],
    )

    delays = [session.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert session.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() == {"code": "ticket_spent", "params": {"id": "c1"}}
    assert listener.events == []


def test_a_welcome_after_a_refusal_clears_the_error(bound, monkeypatch):
    session, _listener = bound
    socket_of(monkeypatch, [{"type": "refused", "code": "ticket_spent", "params": {}}])
    session.run_once()
    assert session.last_error()["code"] == "ticket_spent"

    connected(session, socket_of(monkeypatch, [WELCOME]))

    assert session.last_error() is None
    assert session.connection_state() == "connected"


def test_a_refused_frame_carries_its_code_on_the_exception(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(
        monkeypatch,
        [{"type": "refused", "code": "binding_unknown", "params": {"id": "c1"}}],
    )

    with pytest.raises(GatewayRefused) as refused:
        connected(session, script)

    assert refused.value.code == "binding_unknown"
    assert refused.value.params == {"id": "c1"}
    assert not isinstance(refused.value, GatewayProtocolRefused)


# --- the state ---


def test_a_state_replaces_what_was_held_and_reaches_the_resident(bound, monkeypatch):
    session, listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, STATE)
    assert [entry["id"] for entry in session.service_entries()] == [
        entry["id"] for entry in HUB_SERVICES
    ]
    take(session, made, {"type": "state", "hash": "h2", "services": []})

    assert session.service_entries() == []
    assert session._state_hash == "h2"
    assert listener.names() == ["services", "services"]


def test_every_state_is_answered_with_a_report_carrying_its_hash(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, STATE)
    take(session, made, dict(STATE, hash="h2"))

    assert [report["state_hash"] for report in reports(made)] == ["", "h1", "h2"]
    assert reports(made)[-1]["machine"]["hostname"] == "box"


def test_a_state_of_the_wrong_shape_is_typed_and_never_fatal(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(
        monkeypatch,
        [WELCOME, {"type": "state", "hash": "h2", "services": "not a list"}],
    )
    made = script()
    session._connect(made)

    failure = session._serve(made)

    assert isinstance(failure, GatewayUnreachable)
    assert session._last_error["code"] == "hub_reply_unreadable"


def test_the_services_of_a_hub_whose_socket_is_down_are_nothing(bound, monkeypatch):
    """A hub that is unreachable publishes nothing; what it published comes
    back with its socket, without a new state."""
    session, listener = bound
    script = socket_of(monkeypatch, [WELCOME, STATE])
    made = script()
    session._connect(made)
    session._serve(made)
    assert session.service_entries() == []
    assert session._state_hash == "h1"

    connected(session, script)

    assert [entry["id"] for entry in session.service_entries()] == [
        entry["id"] for entry in HUB_SERVICES
    ]
    assert listener.names() == ["services", "services"]


def test_a_welcome_with_nothing_held_announces_no_services(bound, monkeypatch):
    session, listener = bound

    connected(session, socket_of(monkeypatch, [WELCOME]))

    assert listener.names() == []


def test_disabled_is_told_once_and_keeps_the_binding(bound, monkeypatch, config_path):
    session, listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, dict(STATE, is_disabled=True))
    take(session, made, dict(STATE, is_disabled=True))

    assert session.is_disabled() is True
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() == {"code": "client_disabled", "params": {}}
    assert listener.names() == ["disabled"]


def test_a_disabled_client_resumes_with_the_next_state(bound, monkeypatch):
    session, listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, dict(STATE, is_disabled=True))
    take(session, made, dict(STATE, is_disabled=False))

    assert session.is_disabled() is False
    assert session.last_error() is None
    assert listener.names() == ["disabled", "services"]


def test_an_unknown_frame_is_ignored(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, {"type": "something_else"})
    take(session, made, STATE)

    assert [entry["id"] for entry in session.service_entries()] == [
        entry["id"] for entry in HUB_SERVICES
    ]
    assert session.last_error() is None


def test_a_report_goes_up_on_the_interval(bound, monkeypatch):
    session, _listener = bound
    monkeypatch.setattr(session_module, "CLIENT_REPORT_INTERVAL_S", 0.02)
    hold = threading.Event()
    script = socket_of(monkeypatch, [WELCOME, STATE, hold])
    made = script()
    session._connect(made)
    served = threading.Thread(target=session._serve, args=(made,))

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
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    answered = _open_while(
        session, made, {"type": "close", "stream": 1, "params": MATERIAL}
    )

    opened = made.sent[-1]
    assert opened == {"type": "open", "stream": 1, "kind": "service", "id": "rdp_s9"}
    assert answered == MATERIAL


def test_a_second_stream_takes_the_next_odd_id(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    _open_while(session, made, {"type": "close", "stream": 1, "params": {}})

    _open_while(session, made, {"type": "close", "stream": 3, "params": {}})

    assert [frame["stream"] for frame in made.sent if frame["type"] == "open"] == [
        1,
        3,
    ]


def test_a_close_carrying_a_code_is_the_hubs_own_refusal(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    with pytest.raises(GatewayRefusedDetail) as refused:
        _open_while(
            session,
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
    session, _listener = bound

    with pytest.raises(GatewayUnreachable):
        session.open_service("rdp_s9")


def test_a_stream_nobody_closes_gives_up(bound, monkeypatch):
    session, _listener = bound
    connected(session, socket_of(monkeypatch, [WELCOME]))

    with pytest.raises(GatewayUnreachable):
        session.open_service("rdp_s9", timeout_s=0.05)


def test_a_socket_that_ends_wakes_the_stream_unreachable(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    outcome = {}

    def wait() -> None:
        try:
            session.open_service("rdp_s9", timeout_s=5)
        except GatewayUnreachable as error:
            outcome["error"] = error

    waiter = threading.Thread(target=wait)
    waiter.start()
    while len(made.sent) < 3:
        time.sleep(0.01)
    session._end_socket(made)
    waiter.join(timeout=5)

    assert isinstance(outcome.get("error"), GatewayUnreachable)
    assert session._streams is None


def test_a_close_for_nobody_is_dropped(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, {"type": "close", "stream": 9, "params": {}})

    assert session.last_error() is None


def test_credit_and_bytes_from_the_hub_are_dropped(monkeypatch, config_path):
    lines = []
    session = session_for(log=lines.append)
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, {"type": "credit", "stream": 1, "bytes": 4096})
    take(session, made, protocol.encode_binary(1, b"line\n"))

    assert session.last_error() is None
    assert [line for line in lines if line.startswith("dropping")] == [
        "dropping credit on stream 1",
        "dropping 5 bytes the hub sent on stream 1",
    ]
    assert all(frame["type"] != "credit" for frame in made.sent)


def test_a_stream_the_hub_opens_is_closed_kind_unknown(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, {"type": "open", "stream": 2, "kind": "shell", "cols": 80})

    assert made.sent[-1] == {
        "type": "close",
        "stream": 2,
        "code": "kind_unknown",
        "params": {"kind": "shell"},
    }
    assert session.last_error() is None


def test_a_binary_frame_shorter_than_an_id_is_typed_and_never_fatal(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [WELCOME, b"\x00\x01"])
    made = script()
    session._connect(made)

    failure = session._serve(made)

    assert isinstance(failure, GatewayUnreachable)
    assert session._last_error["code"] == "hub_reply_unreadable"


# --- what ends a connection ---


def test_a_broken_wire_backs_off_and_keeps_the_binding(bound, monkeypatch):
    session, _listener = bound
    socket_of(monkeypatch, [], connect_error=GatewayUnreachable("down"))

    delays = [session.run_once() for _ in range(3)]

    assert delays == [5, 10, 20]
    assert session.connection_state() == "reconnecting"
    assert session.last_error()["code"] == "hub_unreachable"


def test_a_replaced_socket_waits_for_a_person(bound, monkeypatch, config_path):
    """Another socket holds this binding; this one opens no more on its own."""
    session, listener = bound
    script = socket_of(monkeypatch, [WELCOME, SocketClosed(4010, "replaced")])

    session.run_once()
    delay = session.run_once()

    assert session.connection_state() == "replaced"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() is None
    assert listener.events == []
    assert delay == CLIENT_IDLE_POLL_INTERVAL_S
    assert len(script.made) == 1


def test_a_person_takes_a_replaced_binding_back(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [WELCOME, SocketClosed(4010, "replaced")])
    session.run_once()
    session._news.clear()

    session.reconnect()

    assert session.connection_state() == "reconnecting"
    assert session._news.is_set()
    session.run_once()
    assert len(script.made) == 2
    assert script.made[1].sent[0]["type"] == "hello"


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
    session, listener = bound
    socket_of(monkeypatch, [], connect_error=error)

    delays = [session.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert session.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error()["code"] == code
    assert listener.events == []


@pytest.mark.parametrize("code", ["protocol_too_old", "protocol_too_new"])
def test_a_hub_that_does_not_speak_this_protocol_never_unbinds(
    bound, monkeypatch, config_path, code
):
    session, listener = bound
    socket_of(
        monkeypatch,
        [],
        connect_error=GatewayProtocolRefused(code=code, peer=1, hub=2, minimum=2),
    )

    delays = [session.run_once() for _ in range(5)]

    assert session.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() == {
        "code": code,
        "params": {"peer": 1, "hub": 2, "min": 2},
    }
    assert listener.events == []
    assert delays == [CLIENT_BACKOFF_MAX_S] * 5


def live_refused(code: str, params=None) -> list:
    """A hub that welcomes, pushes a state, then refuses and closes 4000."""
    return [
        WELCOME,
        STATE,
        {"type": "refused", "code": code, "params": dict(params or {})},
        SocketClosed(4000, code),
    ]


def test_binding_unknown_on_a_live_socket_hands_the_binding_back_at_once(
    bound, monkeypatch, config_path
):
    """The panel forgot this client while its socket was up: the refusal is
    read where it arrives, and what the hub published goes with it."""
    session, listener = bound
    script = socket_of(monkeypatch, live_refused("binding_unknown", {"id": "c1"}))

    delay = session.run_once()
    session.run_once()

    assert delay == CLIENT_IDLE_POLL_INTERVAL_S
    assert listener.names() == ["services", "unbound"]
    assert session.last_error() == {"code": "binding_unknown", "params": {"id": "c1"}}
    assert session.service_entries() == []
    # The session opens no more; the resident removes the binding.
    assert len(script.made) == 1
    assert len(json.loads(config_path.read_text())["bindings"]) == 1


@pytest.mark.parametrize(
    "code, params",
    [
        ("protocol_too_new", {"peer": 1, "hub": 2, "min": 2}),
        ("ticket_spent", {"id": "c1"}),
    ],
)
def test_a_refusal_on_a_live_socket_keeps_the_binding_and_records_its_code(
    bound, monkeypatch, config_path, code, params
):
    """The close 4000 behind the frame is the end of a refusal already
    recorded, so the code stays the hub's own."""
    session, listener = bound
    socket_of(monkeypatch, live_refused(code, params))

    delays = [session.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert session.connection_state() == "reconnecting"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() == {"code": code, "params": params}
    assert "unbound" not in listener.names()


def test_a_close_4000_without_a_frame_is_hub_refused_and_keeps_the_binding(
    bound, monkeypatch, config_path
):
    """The close arrives instead of the welcome, which is when the hub sends
    one."""
    session, listener = bound
    socket_of(monkeypatch, [SocketClosed(4000, "")])

    delays = [session.run_once() for _ in range(3)]

    assert delays == [CLIENT_BACKOFF_MAX_S] * 3
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() == {"code": "hub_refused", "params": {}}
    assert listener.events == []


# --- the addresses the hub answers on ---


LAN_URL = "https://192.0.2.1:8443"
WAN_URL = "https://198.51.100.1:8443"
OVERLAY_URL = "https://100.64.0.1:8443"
NAME_ADDRESS = "192.0.2.1"
STATE_WITH_URLS = dict(STATE, urls=[LAN_URL, OVERLAY_URL])
DOWN = GatewayUnreachable("down")


class AddressScript:
    """One scripted socket per address dialled, told apart by host.

    Attributes:
        hosts: The host of every socket opened, in order.
        made: Every socket handed out, in order.
    """

    def __init__(self, by_host: dict, default=DOWN):
        """
        Args:
            by_host: Host to what its socket does: a list of frames, or an
                exception ``connect`` raises.
            default: What a host the script does not name does.
        """
        self._by_host = by_host
        self._default = default
        self.hosts = []
        self.made = []

    def __call__(self, **kwargs) -> ScriptedSocket:
        host = kwargs.get("host", "")
        script = self._by_host.get(host, self._default)
        if isinstance(script, Exception):
            made = ScriptedSocket([], connect_error=script)
        else:
            made = ScriptedSocket(script)
        self.hosts.append(host)
        self.made.append(made)
        return made


def addresses_of(monkeypatch, by_host: dict, default=DOWN) -> AddressScript:
    script = AddressScript(by_host, default)
    monkeypatch.setattr(session_module, "WebSocketClient", script)
    return script


def stored_binding(config_path) -> dict:
    (binding,) = json.loads(config_path.read_text())["bindings"]
    return binding


@pytest.fixture
def bound_everywhere(config_path):
    """A session whose binding holds three addresses, the LAN one last answered."""
    bind(
        config_path,
        bindings=[
            dict(
                BINDING,
                gateway_url=LAN_URL,
                gateway_urls=[LAN_URL, WAN_URL, OVERLAY_URL],
            )
        ],
    )
    listener = Listener()
    lines = []
    session = ClientHubSession(
        binding=stored_binding(config_path),
        hostname="box",
        platform_tuple=PLATFORM,
        log=lines.append,
        on_change=listener.on_change,
    )
    return session, lines


def test_the_next_address_is_tried_when_one_stops_answering(
    bound_everywhere, monkeypatch, config_path
):
    """Two addresses fail, the third answers: it is written back as the one
    that answered, and the next round opens there first."""
    session, lines = bound_everywhere
    script = addresses_of(monkeypatch, {"100.64.0.1": [WELCOME]})

    delay = session.run_once()

    assert script.hosts == ["192.0.2.1", "198.51.100.1", "100.64.0.1"]
    assert delay == CLIENT_BACKOFF_MIN_S
    assert session.gateway_url() == OVERLAY_URL
    assert stored_binding(config_path)["gateway_url"] == OVERLAY_URL
    assert stored_binding(config_path)["gateway_urls"] == [
        LAN_URL,
        WAN_URL,
        OVERLAY_URL,
    ]
    assert f"the hub answered at {OVERLAY_URL}" in lines

    session.run_once()

    assert script.hosts[3] == "100.64.0.1"


def test_a_whole_round_failing_is_what_backs_off(bound_everywhere, monkeypatch):
    session, _lines = bound_everywhere
    script = addresses_of(monkeypatch, {})

    delays = [session.run_once() for _ in range(3)]

    assert delays == [5, 10, 20]
    assert script.hosts == ["192.0.2.1", "198.51.100.1", "100.64.0.1"] * 3
    assert session.last_error()["code"] == "hub_unreachable"
    assert session.gateway_url() == LAN_URL


def test_the_round_waits_the_rotate_delay_between_addresses(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    addresses_of(monkeypatch, {})
    monkeypatch.setattr(session_module, "CLIENT_ROTATE_DELAY_S", 0.1)
    started = time.monotonic()

    session.run_once()

    assert 0.2 <= time.monotonic() - started < 5


def test_a_stop_ends_the_round(bound_everywhere, monkeypatch):
    session, _lines = bound_everywhere
    script = addresses_of(monkeypatch, {})
    monkeypatch.setattr(session_module, "CLIENT_ROTATE_DELAY_S", 5)
    session._stop.set()
    started = time.monotonic()

    session.run_once()

    assert script.hosts == ["192.0.2.1"]
    assert time.monotonic() - started < 5


def test_the_states_urls_are_written_to_disk(bound, monkeypatch, config_path):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, STATE_WITH_URLS)

    assert stored_binding(config_path)["gateway_urls"] == [LAN_URL, OVERLAY_URL]
    assert stored_binding(config_path)["gateway_url"] == "https://hub.lan:8443"
    assert session.binding()["gateway_urls"] == [LAN_URL, OVERLAY_URL]
    assert [entry["id"] for entry in session.service_entries()] == [
        entry["id"] for entry in HUB_SERVICES
    ]


def test_a_state_naming_the_same_urls_writes_nothing(bound, monkeypatch, config_path):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    take(session, made, STATE_WITH_URLS)
    before = config_path.stat().st_mtime_ns

    take(session, made, STATE_WITH_URLS)

    assert config_path.stat().st_mtime_ns == before


def test_a_state_without_urls_keeps_the_list(
    bound_everywhere, monkeypatch, config_path
):
    session, _lines = bound_everywhere
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, STATE)

    assert stored_binding(config_path)["gateway_urls"] == [
        LAN_URL,
        WAN_URL,
        OVERLAY_URL,
    ]


def test_an_old_binding_without_the_list_still_connects(bound, monkeypatch):
    session, _listener = bound
    script = addresses_of(monkeypatch, {"hub.lan": [WELCOME]})

    session.run_once()

    assert script.hosts == ["hub.lan"]
    assert session.gateway_url() == "https://hub.lan:8443"


def test_the_name_is_tried_first_and_written_back(
    bound_everywhere, monkeypatch, config_path
):
    session, _lines = bound_everywhere
    session._binding["gateway_url"] = OVERLAY_URL
    script = addresses_of(monkeypatch, {NAME_ADDRESS: [WELCOME]})
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: NAME_ADDRESS)

    session.run_once()

    assert script.hosts == [NAME_ADDRESS]
    assert stored_binding(config_path)["gateway_url"] == LAN_URL


def test_the_names_fingerprint_mismatch_is_skipped_without_alarm(
    bound_everywhere, monkeypatch
):
    """A foreign network resolving the name to its own portal is not this
    hub: the round goes on to the stored addresses and records no error."""
    session, lines = bound_everywhere
    script = addresses_of(
        monkeypatch, {"10.9.9.9": GatewayUntrusted("wrong pin"), "192.0.2.1": [WELCOME]}
    )
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "10.9.9.9")

    client = session._connect_round()

    assert script.hosts == ["10.9.9.9", "192.0.2.1"]
    assert client is script.made[1]
    assert session.last_error() is None
    assert session.connection_state() == "connected"
    assert (
        "https://10.9.9.9:8443 answers to the hub's name and is not this hub" in lines
    )


def test_a_stored_address_off_the_pin_is_logged_and_the_round_goes_on(
    bound_everywhere, monkeypatch
):
    session, lines = bound_everywhere
    script = addresses_of(
        monkeypatch,
        {"192.0.2.1": GatewayUntrusted("wrong pin"), "198.51.100.1": [WELCOME]},
    )

    client = session._connect_round()

    assert script.hosts == ["192.0.2.1", "198.51.100.1"]
    assert client is script.made[1]
    assert session.last_error() is None
    assert f"{LAN_URL} presented a certificate that is not the hub's" in lines
    assert session.gateway_url() == WAN_URL


def test_a_stored_address_off_the_pin_alarms_when_no_address_answers(
    bound_everywhere, monkeypatch, config_path
):
    session, _lines = bound_everywhere
    script = addresses_of(monkeypatch, {"192.0.2.1": GatewayUntrusted("wrong pin")})

    delay = session.run_once()

    assert script.hosts == ["192.0.2.1", "198.51.100.1", "100.64.0.1"]
    assert delay == CLIENT_BACKOFF_MAX_S
    assert session.last_error() == {"code": "hub_untrusted", "params": {}}
    assert len(json.loads(config_path.read_text())["bindings"]) == 1


def test_a_refusal_ends_the_round(bound_everywhere, monkeypatch):
    session, _lines = bound_everywhere
    script = addresses_of(
        monkeypatch,
        {"192.0.2.1": [{"type": "refused", "code": "ticket_spent", "params": {}}]},
    )

    delay = session.run_once()

    assert script.hosts == ["192.0.2.1"]
    assert delay == CLIENT_BACKOFF_MAX_S
    assert session.last_error()["code"] == "ticket_spent"


def sources(monkeypatch, *addresses) -> list:
    """The route probe answering each address in turn, the last one after."""
    pending = list(addresses)
    asked: list = []

    def probe(urls):
        asked.append(list(urls))
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(enrollment, "default_source_address", probe)
    return asked


def test_a_changed_source_address_ends_the_wait_and_resets_the_backoff(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    session._backoff_s = CLIENT_BACKOFF_MAX_S
    asked = sources(monkeypatch, "10.0.0.5", "192.0.2.20")
    monkeypatch.setattr(session_module, "CLIENT_IDLE_POLL_INTERVAL_S", 0.01)
    started = time.monotonic()

    session._wait_out(CLIENT_BACKOFF_MAX_S)

    assert time.monotonic() - started < 5
    assert session._backoff_s == CLIENT_BACKOFF_MIN_S
    assert session._source_address == "192.0.2.20"
    # The route is looked at toward the hub's own order of addresses.
    assert asked[0] == [LAN_URL, WAN_URL, OVERLAY_URL]


def test_the_first_look_and_an_unchanged_address_wait_the_delay_out(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    sources(monkeypatch, "10.0.0.5")
    monkeypatch.setattr(session_module, "CLIENT_IDLE_POLL_INTERVAL_S", 0.01)
    started = time.monotonic()

    session._wait_out(0.1)

    assert 0.1 <= time.monotonic() - started < 5
    assert session._source_address == "10.0.0.5"


def test_news_ends_the_wait_before_the_network_is_looked_at(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    asked = sources(monkeypatch, "10.0.0.5")
    session.reconnect_soon()

    session._wait_out(CLIENT_BACKOFF_MAX_S)

    assert asked == []


def test_a_live_socket_follows_the_name_to_a_stored_address(
    bound_everywhere, monkeypatch
):
    """Connected over the overlay, the machine comes home: the name resolves
    to the LAN address the binding holds, and the socket is moved there."""
    session, lines = bound_everywhere
    session._binding["gateway_url"] = OVERLAY_URL
    hold = threading.Event()
    script = addresses_of(monkeypatch, {"100.64.0.1": [WELCOME, hold]})
    monkeypatch.setattr(session_module, "CLIENT_REPORT_INTERVAL_S", 0.02)
    current = ["10.0.0.5"]
    monkeypatch.setattr(enrollment, "default_source_address", lambda urls: current[0])
    session._news.clear()
    client = session._connect_round()
    served = threading.Thread(target=session._serve, args=(client,))

    served.start()
    deadline = time.monotonic() + 5
    while session._source_address is None and time.monotonic() < deadline:
        time.sleep(0.01)
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: NAME_ADDRESS)
    current[0] = "192.0.2.20"
    while f"moving to {LAN_URL}" not in lines and time.monotonic() < deadline:
        time.sleep(0.01)
    hold.set()
    served.join(timeout=5)

    assert not served.is_alive()
    assert script.made[0].is_closed is True
    assert f"moving to {LAN_URL}" in lines
    assert session._news.is_set()
    assert session.last_error() is None
    assert session.connection_state() == "reconnecting"


@pytest.mark.parametrize("resolved", ["", "10.9.9.9", "100.64.0.1"])
def test_a_live_socket_stays_when_the_name_is_elsewhere(
    bound_everywhere, monkeypatch, resolved
):
    """No name, a name off the stored list, or the address in use: nothing
    moves."""
    session, _lines = bound_everywhere
    session._binding["gateway_url"] = OVERLAY_URL
    script = addresses_of(monkeypatch, {"100.64.0.1": [WELCOME]})
    client = session._connect_round()
    sources(monkeypatch, "10.0.0.5", "192.0.2.20")
    session._watch_network()
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: resolved)

    assert session._watch_network() is True
    session._follow_name(client)

    assert script.made[0].is_closed is False
    assert session.connection_state() == "connected"


def test_a_socket_closed_from_here_is_no_failure(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    session._end_socket(made)
    failure = session._serve(made)

    assert failure is None
    assert session.last_error() is None


# --- the loop and the way out ---


def test_stop_closes_the_socket_and_ends_the_loop(bound, monkeypatch):
    session, _listener = bound
    hold = threading.Event()
    script = socket_of(monkeypatch, [WELCOME, hold])

    session.start()
    deadline = time.monotonic() + 5
    while not script.made and time.monotonic() < deadline:
        time.sleep(0.01)
    while script.made and len(script.made[0].sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    hold.set()
    session.stop()
    session.stop()

    assert script.made[0].is_closed is True
    assert session.connection_state() == "reconnecting"
    assert not session._thread.is_alive()


def test_stop_aborts_a_connect_in_progress_and_returns_within_a_second(
    bound, monkeypatch
):
    session, _listener = bound
    made = BlockingSocket()
    monkeypatch.setattr(session_module, "WebSocketClient", lambda **kwargs: made)

    session.start()
    deadline = time.monotonic() + 5
    while session._connecting is not made and time.monotonic() < deadline:
        time.sleep(0.01)
    started = time.monotonic()
    session.stop()
    elapsed = time.monotonic() - started
    session._thread.join(timeout=5)

    assert elapsed < 1
    assert made.is_aborted.is_set()
    assert not session._thread.is_alive()
    assert session._connecting is None


def test_refresh_reports_on_a_live_socket(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    session.refresh()

    assert [frame["type"] for frame in made.sent] == ["hello", "report", "report"]


def test_refresh_wakes_a_session_that_is_down_with_its_backoff_reset(bound):
    session, _listener = bound
    session._backoff_s = CLIENT_BACKOFF_MAX_S
    session._news.clear()

    session.refresh()

    assert session._backoff_s == CLIENT_BACKOFF_MIN_S
    assert session._news.is_set()


def test_a_stop_before_the_thread_is_published_joins_nothing_and_still_ends_it(
    bound,
):
    """A stop from another thread can land between the thread being made
    and it running; it has nothing to join, and the loop it did not see
    ends on its first turn."""
    session, _listener = bound
    turns = []
    session.run_once = lambda: turns.append(1) or 60

    session.stop()
    session.start()
    session._thread.join(timeout=5)

    assert not session._thread.is_alive()
    assert turns == []


def test_a_stop_during_a_turn_ends_the_loop_without_waiting_out_the_delay(bound):
    """The stop lands while a turn runs; the wait after it must not sleep."""
    session, _listener = bound
    turns = []

    def one_turn():
        turns.append(1)
        session.stop()
        return 60

    session.run_once = one_turn
    started = time.monotonic()
    session.run_forever()

    assert turns == [1]
    assert time.monotonic() - started < 5


def test_a_socket_that_ends_while_stopping_is_no_failure(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    session._stop.set()

    failure = session._serve(made)

    assert failure is None
    assert session.last_error() is None


def test_every_change_the_page_draws_is_announced(bound, monkeypatch):
    session, listener = bound
    script = socket_of(monkeypatch, [WELCOME, STATE])

    session.run_once()

    # The welcome, the state, the socket's end and the backoff after it each
    # announce once.
    assert listener.changes == 4
    assert script.made[0].is_closed is True


def _open_while(session, made, close_frame):
    """Open a service stream on one thread while the test closes it.

    Args:
        session: The session under test.
        made: The scripted socket the open lands on.
        close_frame: The close the hub answers with, handed to the session
            once the open has gone up.

    Returns:
        What :meth:`ClientHubSession.open_service` returned.

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
