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

import functools
import json
import os
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
    CLIENT_STREAM_CREDIT_BYTES,
    PROTOCOL,
)
from neutrino_client.core import enrollment, protocol
from neutrino_client.core.session import ClientHubSession
from neutrino_client.exceptions import (
    EnrollmentError,
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
SESSION_ID = "5d1c0e2a-7b6f-4c1d-9a8e-3f2b1c0d9e8f"


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

    def send_bytes(self, data: bytes) -> None:
        if self.is_closed:
            raise GatewayUnreachable("the socket is closed")
        self.sent.append(protocol.decode_binary(data))

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


def session_for(
    binding=None, listener=None, log=discard, **options
) -> ClientHubSession:
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
        **options,
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
    assert PROTOCOL == 3 and CLIENT_ROLE == "client"
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


def test_a_new_round_removes_the_error_line_of_the_last(bound, monkeypatch):
    session, _listener = bound
    socket_of(monkeypatch, [STATE])
    session.run_once()
    assert session.last_error()["code"] == "hub_unreachable"
    seen = []

    def round_seen():
        seen.append((session.connection(), session.last_error()))
        raise GatewayUnreachable("still away")

    monkeypatch.setattr(session, "_connect_round", round_seen)
    session.run_once()

    assert seen == [("connecting", None)]
    assert session.connection() == "down"
    assert session.last_error()["code"] == "hub_unreachable"


def test_a_welcome_of_another_role_is_unreachable(bound, monkeypatch):
    session, _listener = bound
    script = socket_of(monkeypatch, [dict(WELCOME, role="agent")])

    session.run_once()

    assert session.last_error()["code"] == "hub_unreachable"
    assert script.made[0].is_closed is True
    assert session.connection() == "down"


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

    assert session.connection() == "down"
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
    assert session.connection() == "down"
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
    assert session.connection() == "connected"


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
    assert session.connection() == "disabled"
    assert len(json.loads(config_path.read_text())["bindings"]) == 1
    assert session.last_error() is None
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


def test_the_state_names_the_way_in_and_the_panel(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    assert (session.reached_through(), session.is_panel_allowed()) == ("", False)

    for way in ("lan", "netbird", "easytier", "relay"):
        take(session, made, dict(STATE, reached_through=way, is_panel_allowed=True))
        assert (session.reached_through(), session.is_panel_allowed()) == (way, True)

    take(session, made, dict(STATE, is_panel_allowed="yes"))
    assert (session.reached_through(), session.is_panel_allowed()) == ("", False)


def test_a_connect_stream_carries_bytes_both_ways_under_credit(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    stream = session.open_connect({"id": "svc_tcp"})
    take(session, made, {"type": "credit", "stream": stream.stream_id, "bytes": 4})
    stream.send(b"ping")
    take(session, made, stream.stream_id.to_bytes(4, "big") + b"pong")

    assert made.sent[-3:] == [
        {"type": "open", "stream": 1, "kind": "connect", "id": "svc_tcp"},
        {"type": "credit", "stream": 1, "bytes": 1048576},
        (1, b"ping"),
    ]
    assert stream.read(1) == b"pong"
    take(session, made, {"type": "close", "stream": 1, "code": "", "params": {}})
    assert stream.read(1) == b""


def test_a_connect_stream_for_the_panel_names_it(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    session.open_connect({"is_panel": True})

    assert {"type": "open", "stream": 1, "kind": "connect", "is_panel": True} in (
        made.sent
    )


def test_a_connect_stream_needs_the_socket(bound):
    session, _listener = bound

    with pytest.raises(GatewayUnreachable):
        session.open_connect({"id": "svc_tcp"})


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


def test_credit_and_bytes_for_no_open_stream_are_dropped(monkeypatch, config_path):
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


def test_a_shell_opens_odd_with_its_size_and_grants_the_window(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    stream = session.open_shell("dev_lepton", 120, 40, SESSION_ID)

    assert stream.stream_id == 1
    assert made.sent[-2] == {
        "type": "open",
        "stream": 1,
        "kind": "shell",
        "device_id": "dev_lepton",
        "cols": 120,
        "rows": 40,
        "session_id": SESSION_ID,
    }
    assert made.sent[-1] == {
        "type": "credit",
        "stream": 1,
        "bytes": CLIENT_STREAM_CREDIT_BYTES,
    }


def test_a_kept_session_is_opened_again_as_resumed(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    session.open_shell("dev_lepton", 80, 24, SESSION_ID, is_resumed=True)

    opened = made.sent[-2]
    assert (opened["session_id"], opened["is_resumed"]) == (SESSION_ID, True)


def answered(session, made, ask, stream_id: int):
    """Run one ask on a thread, answer its command's open, and hand back what it got."""
    outcome = {}

    def run() -> None:
        try:
            outcome["params"] = ask()
        except Exception as error:  # noqa: BLE001 - handed back to the test
            outcome["error"] = error

    asking = threading.Thread(target=run)
    asking.start()
    deadline = time.monotonic() + 5
    while made.sent[-1].get("stream") != stream_id and time.monotonic() < deadline:
        time.sleep(0.01)
    take(session, made, {"type": "close", "stream": stream_id, "params": {}})
    asking.join(timeout=5)
    return outcome


def test_persist_and_stop_name_the_session_on_the_agent_module(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    def persist():
        return session.persist_shell(SESSION_ID, True, False)

    def stop():
        return session.stop_shell_session(SESSION_ID)

    assert answered(session, made, persist, 1) == {"params": {}}
    assert answered(session, made, stop, 3) == {"params": {}}

    commands = [frame for frame in made.sent if frame.get("kind") == "command"]
    assert commands == [
        {
            "type": "open",
            "stream": 1,
            "kind": "command",
            "verb": "persist",
            "session_id": SESSION_ID,
            "is_persistent": True,
            "is_shared": False,
            "module": "agent",
        },
        {
            "type": "open",
            "stream": 3,
            "kind": "command",
            "verb": "stop_session",
            "session_id": SESSION_ID,
            "module": "agent",
        },
    ]


def test_a_session_the_machine_does_not_keep_is_the_hubs_refusal(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    outcome = {}

    def stop() -> None:
        try:
            session.stop_shell_session(SESSION_ID, timeout_s=5)
        except GatewayRefusedDetail as refused:
            outcome["code"] = refused.code

    asking = threading.Thread(target=stop)
    asking.start()
    while made.sent[-1].get("kind") != "command":
        time.sleep(0.01)
    take(
        session,
        made,
        {
            "type": "close",
            "stream": 1,
            "code": "session_unknown",
            "params": {"session_id": SESSION_ID},
        },
    )
    asking.join(timeout=5)

    assert outcome == {"code": "session_unknown"}


def test_the_hubs_bytes_on_a_shell_reach_its_reader(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    stream = session.open_shell("dev_lepton", 80, 24, SESSION_ID)

    take(session, made, protocol.encode_binary(1, b"$ "))

    assert stream.read(timeout_s=1) == b"$ "


def test_a_shell_sends_only_after_the_hubs_credit(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    stream = session.open_shell("dev_lepton", 80, 24, SESSION_ID)
    sent = threading.Thread(target=stream.send, args=(b"ls\n",))

    sent.start()
    time.sleep(0.05)
    assert all(not isinstance(frame, tuple) for frame in made.sent)
    take(session, made, {"type": "credit", "stream": 1, "bytes": 1024})
    sent.join(timeout=5)

    assert made.sent[-1] == (1, b"ls\n")


def test_a_resize_opens_a_command_naming_the_shell(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    stream = session.open_shell("dev_lepton", 80, 24, SESSION_ID)
    outcome = {}

    def resize() -> None:
        outcome["params"] = session.resize_shell(stream.stream_id, 100, 30)

    asking = threading.Thread(target=resize)
    asking.start()
    while made.sent[-1].get("kind") != "command":
        time.sleep(0.01)
    take(session, made, {"type": "close", "stream": 3, "params": {}})
    asking.join(timeout=5)

    assert made.sent[-1] == {
        "type": "open",
        "stream": 3,
        "kind": "command",
        "module": "agent",
        "verb": "resize",
        "shell": 1,
        "cols": 100,
        "rows": 30,
    }
    assert outcome == {"params": {}}


def test_a_socket_that_ends_wakes_a_shell_reader_empty(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    stream = session.open_shell("dev_lepton", 80, 24, SESSION_ID)
    outcome = {}

    def read() -> None:
        outcome["data"] = stream.read(timeout_s=5)

    reader = threading.Thread(target=read)
    reader.start()
    session._end_socket(made)
    reader.join(timeout=5)

    assert outcome == {"data": b""}


def test_a_shell_with_no_socket_is_unreachable(bound):
    session, _listener = bound

    with pytest.raises(GatewayUnreachable):
        session.open_shell("dev_lepton", 80, 24, SESSION_ID)


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
    assert session.connection() == "down"
    assert session.last_error()["code"] == "hub_unreachable"


def test_a_replaced_socket_waits_for_a_person(bound, monkeypatch, config_path):
    """Another socket holds this binding; this one opens no more on its own."""
    session, listener = bound
    script = socket_of(monkeypatch, [WELCOME, SocketClosed(4010, "replaced")])

    session.run_once()
    delay = session.run_once()

    assert session.connection() == "replaced"
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

    assert session.connection() == "connecting"
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
    assert session.connection() == "down"
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

    assert session.connection() == "down"
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
    assert session.connection() == "down"
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
    assert session.connection() == "connected"
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
    session._news.set()

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
    assert session.connection() == "connecting"


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
    assert session.connection() == "connected"


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
    assert session.connection() == "connecting"
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

    # The welcome, the state and the socket's end each announce once; a
    # lost socket goes back to connecting with nothing more to draw.
    assert listener.changes == 3
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


# --- the overlay object and the terminals ---

NETBIRD_OVERLAY = {
    "provider": "netbird",
    "setup_key": "KEY-1",  # scan: allow
    "management_url": "https://nb.example",
    "fqdn": "hub.netbird.cloud",
    "hub_address": "100.88.92.30",
}
EASYTIER_OVERLAY = {
    "provider": "easytier",
    "mode": "manual",
    "network_name": "home",
    "network_secret": "s3cret",  # scan: allow
    "peer": "tcp://203.0.113.7:11010",
    "hub_address": "10.144.144.1",
}
KEPT = {
    "session_id": SESSION_ID,
    "account": "alice",
    "started_at": 1759300000,
    "title": "vim notes.md",
    "owner": "client:c1",
    "owner_name": "box",
    "is_owned": True,
    "is_attached": True,
    "attached_count": 2,
    "is_persistent": True,
    "is_shared": True,
}
# A kept session as the session holds it.
KEPT_ROW = {
    "session_id": SESSION_ID,
    "device_id": "d1",
    "owner": "client:c1",
    "owner_name": "box",
    "is_owned": True,
    "is_persistent": True,
    "is_shared": True,
    "attached_count": 2,
    "title": "vim notes.md",
    "started_at": 1759300000,
}
TERMINALS = [
    {
        "device_id": "d1",
        "name": "lepton",
        "is_online": True,
        "sessions": [KEPT, {"account": "no id"}, dict(KEPT, session_id="s2", x=1)],
    },
    {"device_id": "d2", "name": "", "is_online": False},
    {"name": "no id"},
    "junk",
]


@pytest.mark.feature("netbird")
def test_a_states_overlays_are_kept_on_the_binding(bound, monkeypatch, config_path):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, dict(STATE, overlays=[NETBIRD_OVERLAY, EASYTIER_OVERLAY]))

    assert session.overlays() == [NETBIRD_OVERLAY, EASYTIER_OVERLAY]
    assert stored_binding(config_path)["overlays"] == [
        NETBIRD_OVERLAY,
        EASYTIER_OVERLAY,
    ]


def test_the_same_overlays_a_second_time_write_nothing(bound, monkeypatch, config_path):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    take(session, made, dict(STATE, overlays=[EASYTIER_OVERLAY]))
    written = config_path.read_bytes()
    os.utime(config_path, ns=(0, 0))

    take(session, made, dict(STATE, hash="h2", overlays=[EASYTIER_OVERLAY]))

    assert config_path.stat().st_mtime_ns == 0
    assert config_path.read_bytes() == written


def test_an_empty_list_clears_the_overlays_and_a_state_without_one_keeps_them(
    bound, monkeypatch, config_path
):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    take(session, made, dict(STATE, overlays=[EASYTIER_OVERLAY]))

    take(session, made, dict(STATE))
    assert session.overlays() == [EASYTIER_OVERLAY]
    take(session, made, dict(STATE, overlays=[]))

    assert session.overlays() == []
    assert stored_binding(config_path)["overlays"] == []


def test_the_overlay_secret_never_reaches_the_log(monkeypatch, config_path):
    bind(config_path, url="https://hub.lan:8443")
    lines = []
    session = session_for(log=lines.append)
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, dict(STATE, overlays=[NETBIRD_OVERLAY, EASYTIER_OVERLAY]))

    assert lines and not any("KEY-1" in line for line in lines)
    assert not any("s3cret" in line for line in lines)


def test_the_networks_state_and_engine_are_written_onto_the_binding(bound, config_path):
    session, _listener = bound

    session.set_overlay_choice(True, "easytier")

    assert session.overlay_choice() == (True, "easytier")
    stored = stored_binding(config_path)
    assert (stored["is_overlay_on"], stored["overlay_pick"]) == (True, "easytier")


def test_a_switch_reconnects_through_that_networks_address_first(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    script = addresses_of(monkeypatch, {"100.64.0.1": [WELCOME]})

    session.reconnect_through(["100.64.0.1", ""])
    session.run_once()

    assert script.hosts == ["100.64.0.1"]


def test_a_round_held_to_the_networks_address_tries_no_other(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    script = addresses_of(monkeypatch, {"192.0.2.1": [WELCOME]})

    session.reconnect_through(["100.88.92.30"], is_only=True)
    session.run_once()
    session.run_once()

    assert script.hosts == ["100.88.92.30", "100.88.92.30"]
    assert session.connection() == "down"


class RedirectScript:
    """Every address but the network's blocks its connect until aborted.

    Attributes:
        hosts: The host of every socket opened, in order.
    """

    def __init__(self, answering: str):
        self._answering = answering
        self.hosts = []

    def __call__(self, **kwargs):
        host = kwargs.get("host", "")
        self.hosts.append(host)
        if host == self._answering:
            return ScriptedSocket([WELCOME])
        return BlockingSocket()


def round_in_thread(session) -> list:
    """Run one connection round on a thread; the list gets what it returned."""
    ended = []
    threading.Thread(
        target=functools.partial(_take_round, session, ended), daemon=True
    ).start()
    deadline = time.monotonic() + 5
    while session._connecting is None and time.monotonic() < deadline:
        time.sleep(0.01)
    return ended


@pytest.mark.parametrize("how", ["preference", "probe"])
def test_a_round_through_other_addresses_ends_within_a_second_of_the_network(
    bound_everywhere, monkeypatch, how
):
    session, _lines = bound_everywhere
    script = RedirectScript("100.64.0.1")
    monkeypatch.setattr(session_module, "WebSocketClient", script)
    ended = round_in_thread(session)
    assert script.hosts == ["192.0.2.1"]

    started = time.monotonic()
    if how == "preference":
        session.reconnect_through(["100.64.0.1"], is_only=True)
    else:
        assert session.reaches_through(["100.64.0.1"]) is False
    while not ended and time.monotonic() - started < 5:
        time.sleep(0.01)

    assert ended == [None]
    assert time.monotonic() - started < 1
    session.reconnect_through(["100.64.0.1"], is_only=True)
    script.hosts.clear()
    assert session._connect_round() is not None
    assert script.hosts == ["100.64.0.1"]
    assert session.reaches_through(["100.64.0.1"]) is True


def test_a_redirected_round_starts_the_next_one_at_once(bound_everywhere, monkeypatch):
    session, lines = bound_everywhere
    monkeypatch.setattr(session, "_connect_round", _redirected_round)

    assert session.run_once() == 0
    assert "the round was redirected; connecting again now" in lines
    assert session.last_error() is None


def _redirected_round():
    return None


def _take_round(session, ended) -> None:
    ended.append(session._connect_round())


def test_the_channel_moves_to_the_networks_address_once_its_port_answers(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    script = addresses_of(
        monkeypatch, {"192.0.2.1": [WELCOME], "100.64.0.1": [WELCOME]}
    )
    lan = session._connect_round()
    session.reconnect_through(["100.64.0.1"], is_only=True)

    assert session.reaches_through(["100.64.0.1"]) is False
    assert lan.is_closed and session.connection() != "connected"
    session._connect_round()
    assert session.reaches_through(["100.64.0.1"]) is True
    assert script.hosts == ["192.0.2.1", "100.64.0.1", "100.64.0.1"]


def test_a_live_socket_stays_while_the_networks_address_does_not_answer(
    bound_everywhere, monkeypatch
):
    session, _lines = bound_everywhere
    addresses_of(monkeypatch, {"192.0.2.1": [WELCOME]})
    lan = session._connect_round()
    session.reconnect_through(["100.64.0.1"], is_only=True)

    assert session.reaches_through(["100.64.0.1"]) is False
    assert not lan.is_closed and session.connection() == "connected"


def test_the_states_terminals_are_held_while_the_socket_is_up(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, dict(STATE, terminals=TERMINALS))

    assert session.terminal_entries() == [
        {"device_id": "d1", "name": "lepton", "is_online": True},
        {"device_id": "d2", "name": "d2", "is_online": False},
    ]
    assert session.terminal_sessions() == [
        KEPT_ROW,
        dict(KEPT_ROW, session_id="s2"),
    ]
    session._end_socket(made)
    assert session.terminal_entries() == []
    assert session.terminal_sessions() == []


def test_the_terminals_as_two_lists_read_the_same(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    terminals = {
        "machines": [{"device_id": "d1", "name": "lepton", "is_online": True}],
        "sessions": [dict(KEPT, device_id="d1"), {"session_id": "no machine"}],
    }

    take(session, made, dict(STATE, terminals=terminals))

    assert session.terminal_entries() == [
        {"device_id": "d1", "name": "lepton", "is_online": True}
    ]
    assert session.terminal_sessions() == [KEPT_ROW]


def test_a_session_from_an_older_hub_counts_its_attachment(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    older = {
        "session_id": "s9",
        "account": "alice",
        "started_at": 1,
        "title": "",
        "is_attached": True,
        "is_persistent": False,
    }
    terminals = [
        {"device_id": "d1", "name": "lepton", "is_online": True, "sessions": [older]}
    ]

    take(session, made, dict(STATE, terminals=terminals))

    row = session.terminal_sessions()[0]
    assert (row["attached_count"], row["owner"], row["is_owned"]) == (1, "", False)
    assert row["owner_name"] == ""
    assert row["is_shared"] is False


def test_the_flags_set_show_at_once_until_the_next_state(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    take(session, made, dict(STATE, terminals=TERMINALS))

    session.note_session_flags(SESSION_ID, False, False)
    assert (
        session.terminal_sessions()[0]["is_persistent"],
        session.terminal_sessions()[0]["is_shared"],
    ) == (False, False)

    take(session, made, dict(STATE, hash="h2", terminals=TERMINALS))
    assert session.terminal_sessions()[0]["is_shared"] is True


def test_a_state_without_terminals_holds_none(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    take(session, made, dict(STATE, terminals=TERMINALS))

    take(session, made, dict(STATE))

    assert session.terminal_entries() == []


# --- the five connection states ---


def test_a_session_starts_connecting():
    session = session_for()

    assert session.connection() == "connecting"


def test_a_round_that_ends_in_a_code_is_down_and_the_next_round_connecting(
    bound, monkeypatch
):
    session, _listener = bound
    socket_of(monkeypatch, [], connect_error=GatewayUnreachable("down"))
    session.run_once()
    assert session.connection() == "down"

    seen = []

    def round_seen():
        seen.append(session.connection())
        raise GatewayUnreachable("still")

    monkeypatch.setattr(session, "_connect_round", round_seen)
    session.run_once()

    assert seen == ["connecting"]
    assert session.connection() == "down"


def test_a_lost_socket_is_connecting_with_no_error_line(bound, monkeypatch):
    session, _listener = bound
    socket_of(monkeypatch, [WELCOME, GatewayUnreachable("wire cut")])

    delay = session.run_once()

    assert delay == CLIENT_BACKOFF_MIN_S
    assert session.connection() == "connecting"
    assert session.last_error() is None


def test_a_disabled_hub_is_disabled_and_enabled_again_is_connected(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    take(session, made, dict(STATE, is_disabled=True))
    assert session.connection() == "disabled"
    take(session, made, dict(STATE, hash="h2", is_disabled=False))
    assert session.connection() == "connected"


def test_every_connection_state_is_named():
    assert session_module.CONNECTION_STATES == (
        "connected",
        "connecting",
        "down",
        "replaced",
        "disabled",
        "pending",
    )


# --- the refresh ---


def test_a_refresh_of_a_connected_hub_asks_for_the_whole_state(bound, monkeypatch):
    session, listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    session._last_error = {"code": "hub_reply_unreadable", "params": {}}
    changes = listener.changes

    assert session.refresh() is True

    assert session.is_refreshing() is True
    assert session.last_error() is None
    assert made.sent[-1]["type"] == "report"
    assert made.sent[-1]["is_refresh"] is True
    assert listener.changes == changes + 1


def test_a_plain_report_carries_no_refresh(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))

    assert "is_refresh" not in made.sent[-1]


def test_a_state_ends_the_refresh(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    session.refresh()

    take(session, made, dict(STATE))

    assert session.is_refreshing() is False


def test_a_second_refresh_while_one_runs_is_not_taken(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    session.refresh()
    sent = len(made.sent)

    assert session.refresh() is False
    assert len(made.sent) == sent


def test_a_refresh_of_a_down_hub_starts_a_round_now_at_the_floor(bound, monkeypatch):
    session, _listener = bound
    socket_of(monkeypatch, [], connect_error=GatewayUnreachable("down"))
    session.run_once()
    session.run_once()
    session._news.clear()
    assert session._backoff_s > CLIENT_BACKOFF_MIN_S

    assert session.refresh() is True

    assert session._backoff_s == CLIENT_BACKOFF_MIN_S
    assert session._news.is_set()
    assert session.last_error() is None
    assert session.is_refreshing() is True


def test_a_round_that_ends_in_a_code_ends_the_refresh(bound, monkeypatch):
    session, _listener = bound
    socket_of(monkeypatch, [], connect_error=GatewayUnreachable("down"))
    session.refresh()

    session.run_once()

    assert session.is_refreshing() is False
    assert session.connection() == "down"
    assert session.last_error()["code"] == "hub_unreachable"


def test_a_refresh_that_reaches_a_hub_asks_its_first_report_for_the_whole_state(
    bound, monkeypatch
):
    session, _listener = bound
    script = socket_of(monkeypatch, [WELCOME])
    session.refresh()

    made = connected(session, script)

    reports = [frame for frame in made.sent if frame.get("type") == "report"]
    assert reports[0]["is_refresh"] is True


def test_a_refresh_nothing_answers_ends_by_itself(monkeypatch, config_path):
    bind(config_path)
    listener = Listener()
    session = session_for(listener=listener, refresh_timeout_s=0.05)

    assert session.refresh() is True
    deadline = time.monotonic() + 5
    while session.is_refreshing() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert session.is_refreshing() is False


@pytest.mark.parametrize("state", ["replaced", "disabled"])
def test_a_replaced_or_disabled_hub_does_not_refresh(bound, monkeypatch, state):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    if state == "replaced":
        session._is_replaced = True
    else:
        take(session, made, dict(STATE, is_disabled=True))
    sent = len(made.sent)

    assert session.refresh() is False
    assert session.is_refreshing() is False
    assert len(made.sent) == sent


def test_a_session_without_an_owner_name_is_named_by_its_stamp(bound, monkeypatch):
    session, _listener = bound
    made = connected(session, socket_of(monkeypatch, [WELCOME]))
    nameless = dict(KEPT)
    del nameless["owner_name"]
    terminals = [
        {"device_id": "d1", "name": "lepton", "is_online": True, "sessions": [nameless]}
    ]

    take(session, made, dict(STATE, terminals=terminals))

    assert session.terminal_sessions()[0]["owner_name"] == "client:c1"


# --- a join that has not reached its hub yet ---


PENDING_BINDING = dict(
    BINDING,
    id="pending_1",
    hub_id="",
    hub_name="",
    gateway_url=LAN_URL,
    gateway_urls=[LAN_URL, OVERLAY_URL],
    token="",
    ticket="ticket-1",
    is_pending=True,
)


@pytest.fixture
def pending_session(config_path):
    bind(config_path, bindings=[PENDING_BINDING])
    lines = []
    session = ClientHubSession(
        binding=stored_binding(config_path),
        hostname="box",
        platform_tuple=PLATFORM,
        log=lines.append,
    )
    return session, lines


class JoinDesk:
    """The hub's join, as the round reaches it: completed or refused.

    Attributes:
        asked: Every address the ticket was spent at, in order.
        refusal: The refusal the join ends in; None completes it.
        unreachable_at: An address that stops answering mid-join.
        sockets: The sockets of the round, for the order of join and hello.
    """

    def __init__(self, sockets):
        self.asked = []
        self.refusal = None
        self.unreachable_at = ""
        self.sockets = sockets

    def __call__(self, binding, url):
        self.asked.append((url, [list(made.sent) for made in self.sockets.made]))
        if url == self.unreachable_at:
            raise GatewayUnreachable("gone")
        if self.refusal is not None:
            raise self.refusal
        return enrollment._binding(
            dict(
                binding,
                id="c7",
                token="tok7",
                gateway_url=url,
                ticket="",
                is_pending=False,
            )
        )


def test_a_pending_join_reads_pending_until_its_ticket_is_spent(pending_session):
    session, _lines = pending_session

    assert session.connection() == "pending"
    assert session.is_pending() is True
    assert session.local_key == "pending_1"


def test_the_first_address_that_answers_spends_the_ticket_before_the_hello(
    pending_session, monkeypatch, config_path
):
    session, _lines = pending_session
    script = addresses_of(monkeypatch, {"100.64.0.1": [WELCOME]})
    desk = JoinDesk(script)
    monkeypatch.setattr(enrollment, "complete_join", desk)

    session.run_once()

    assert script.hosts == ["192.0.2.1", "100.64.0.1"]
    (asked,) = desk.asked
    assert asked == (OVERLAY_URL, [[], []])
    hello = script.made[-1].sent[0]
    assert (hello["type"], hello["id"], hello["token"]) == ("hello", "c7", "tok7")
    (stored,) = json.loads(config_path.read_text())["bindings"]
    assert (stored["id"], stored["token"], stored["gateway_url"]) == (
        "c7",
        "tok7",
        OVERLAY_URL,
    )
    assert "ticket" not in stored and "is_pending" not in stored
    assert session.binding_id == "c7" and session.local_key == "pending_1"
    assert session.is_pending() is False


@pytest.mark.parametrize(
    "refusal",
    [
        EnrollmentError("ticket_spent"),
        EnrollmentError("protocol_too_old", {"peer": 1, "hub": 3, "min": 2}),
    ],
)
def test_a_refused_join_is_down_with_its_code_and_runs_no_more_rounds(
    pending_session, monkeypatch, config_path, refusal
):
    session, _lines = pending_session
    script = addresses_of(monkeypatch, {"192.0.2.1": [WELCOME]})
    desk = JoinDesk(script)
    desk.refusal = refusal
    monkeypatch.setattr(enrollment, "complete_join", desk)

    session.run_once()
    session.run_once()

    assert session.connection() == "down"
    assert session.last_error() == {"code": refusal.code, "params": refusal.params}
    assert script.hosts == ["192.0.2.1"]
    assert script.made[0].sent == []
    assert stored_binding(config_path)["is_pending"] is True


def test_a_paused_admission_keeps_the_join_pending_and_tries_again_after_its_wait(
    pending_session, monkeypatch, config_path
):
    session, _lines = pending_session
    script = addresses_of(monkeypatch, {"192.0.2.1": [WELCOME]})
    desk = JoinDesk(script)
    desk.refusal = EnrollmentError("admission_paused", {"retry_after_s": 42})
    monkeypatch.setattr(enrollment, "complete_join", desk)

    delay = session.run_once()

    assert delay == 42
    assert session.connection() == "pending"
    assert session.last_error() == {
        "code": "admission_paused",
        "params": {"retry_after_s": 42},
    }
    assert stored_binding(config_path)["is_pending"] is True
    assert stored_binding(config_path)["ticket"]

    desk.refusal = None
    session.run_once()

    assert script.hosts == ["192.0.2.1", "192.0.2.1"]


def test_an_address_that_stops_answering_mid_join_lets_the_round_go_on(
    pending_session, monkeypatch
):
    session, _lines = pending_session
    script = addresses_of(
        monkeypatch, {"192.0.2.1": [WELCOME], "100.64.0.1": [WELCOME]}
    )
    desk = JoinDesk(script)
    desk.unreachable_at = LAN_URL
    monkeypatch.setattr(enrollment, "complete_join", desk)

    session.run_once()

    assert [url for url, _sent in desk.asked] == [LAN_URL, OVERLAY_URL]
    assert session.binding_id == "c7"
