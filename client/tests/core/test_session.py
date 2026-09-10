"""The resident's socket: the hello, what the hub pushes, and the asks.

One scripted socket stands in for the wire: a test hands the session the
frames the hub would send and reads back what the client sent. What is
pinned here is the hello's own fields, the welcome, a catalog that replaces
what was held, the credential handed to the AI handler, the disabled switch
letting go once and resuming, an ask correlated to its answer, three
refusals unbinding, the backoff after a broken wire, and a shutdown that
runs its order once.
"""

import json
import threading

import pytest

import neutrino_client.core.session as session_module
from neutrino_client import CLIENT_VERSION
from neutrino_client.core.channel import (
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
)
from neutrino_client.core.session import ClientSession
from neutrino_client.core.ws_client import SocketClosed
from neutrino_client.services.base import ServiceTypeHandler
from tests.conftest import SERVICES, FakeClientPlatform, bind, discard

CREDENTIAL = {
    "base_url": "http://hub:8080",
    "api_key": "key-1",  # scan: allow
    "model": "m1",
}
WELCOME = {"type": "welcome", "hub_version": "0.2.0", "client_id": "c1"}
CATALOG = {"type": "catalog", "hash": "h1", "services": SERVICES}


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
                text frame, an exception is raised, and the list running out
                behaves like the hub hanging up.
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
        self.sent.append(json.loads(text))

    def recv(self):
        if not self._frames:
            self.is_drained.set()
            raise GatewayUnreachable("hub hung up")
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return "text", json.dumps(frame)

    def close(self, code: int = 1000, reason: str = "") -> None:
        self.is_closed = True
        self.is_open = False


class RecordingHandler(ServiceTypeHandler):
    """A handler that remembers when it was released."""

    def __init__(self, service_type: str, log: list):
        self.service_type = service_type
        self._log = log

    def act(self, *, entries, body):
        return {}

    def update_credential(self, credential) -> None:
        return None

    def release(self) -> None:
        self._log.append(self.service_type)


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


def take(session, frame: dict) -> None:
    """Hand the session one frame the way its reader would."""
    session._dispatch("text", json.dumps(frame))


def released_handlers(session) -> list:
    """Swap every releasable handler for one that records, and return the log."""
    log = []
    for service_type in ("ai", "file", "port", "rdp"):
        session._services[service_type] = RecordingHandler(service_type, log)
    return log


@pytest.fixture
def bound(config_path):
    bind(config_path, url="https://hub.lan:8443")
    return ClientSession(log=discard, platform=FakeClientPlatform())


def test_the_hello_carries_the_persons_facts_and_the_held_hash(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME, CATALOG])

    bound.run_once()

    hello = script.made[0].sent[0]
    assert set(hello) == {
        "type",
        "kind",
        "token",
        "client_version",
        "hostname",
        "platform",
        "catalog_hash",
    }
    assert hello["type"] == "hello"
    assert hello["kind"] == "client"
    assert hello["token"] == "tok"
    assert hello["client_version"] == CLIENT_VERSION
    assert hello["catalog_hash"] == ""
    assert "accounts" not in hello and "metrics" not in hello


def test_the_next_hello_carries_the_hash_the_catalog_named(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME, CATALOG])

    bound.run_once()
    bound.run_once()

    assert script.made[0].sent[0]["catalog_hash"] == ""
    assert script.made[1].sent[0]["catalog_hash"] == "h1"


def test_the_welcome_names_the_hub_and_opens_the_socket(bound, monkeypatch):
    socket_of(monkeypatch, [WELCOME, CATALOG])

    bound.run_once()

    assert bound.hub_version() == "0.2.0"
    assert bound.is_connected() is True


def test_a_first_frame_that_is_not_a_welcome_is_unreachable(bound, monkeypatch):
    script = socket_of(monkeypatch, [CATALOG])

    delay = bound.run_once()

    assert delay == 5
    assert bound.last_error()["code"] == "hub_unreachable"
    assert script.made[0].is_closed is True


def test_a_catalog_replaces_what_was_held(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME])
    connected(bound, script)

    take(bound, CATALOG)
    assert [entry["id"] for entry in bound.service_entries()] == [
        entry["id"] for entry in SERVICES
    ]
    take(bound, {"type": "catalog", "hash": "h2", "services": []})

    assert bound.service_entries() == []
    assert bound._catalog_hash == "h2"


def test_a_catalog_of_the_wrong_shape_is_typed_and_never_fatal(bound, monkeypatch):
    script = socket_of(
        monkeypatch,
        [WELCOME, {"type": "catalog", "hash": "h2", "services": "not a list"}],
    )
    made = script()
    bound._connect(made)

    failure = bound._serve(made)

    assert isinstance(failure, GatewayUnreachable)
    assert bound._last_error["code"] == "hub_reply_unreadable"


def test_the_credential_is_adopted_and_handed_to_the_ai_handler(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME])
    connected(bound, script)
    seen = []
    bound._services["ai"].update_credential = seen.append

    take(bound, {"type": "ai", "credential": CREDENTIAL})

    assert bound.ai_credential() == CREDENTIAL
    assert seen == [CREDENTIAL]


def test_a_withdrawn_credential_restores_the_tools(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME])
    connected(bound, script)
    granted = []
    restores = []
    handler = bound._services["ai"]
    handler.update_credential = granted.append

    def restore() -> None:
        restores.append(1)

    handler.restore = restore

    take(bound, {"type": "ai", "credential": CREDENTIAL})
    take(bound, {"type": "ai", "credential": None})

    assert bound.ai_credential() == {}
    assert granted == [CREDENTIAL]
    assert restores == [1]


def test_disabled_lets_go_of_everything_but_the_binding(
    bound, monkeypatch, config_path
):
    script = socket_of(monkeypatch, [WELCOME])
    connected(bound, script)
    released = released_handlers(bound)

    take(bound, {"type": "disabled", "is_disabled": True})

    assert bound.is_disabled() is True
    assert bound.is_connected() is True
    assert "gateway_url" in json.loads(config_path.read_text())
    assert bound.last_error() == {"code": "client_disabled", "params": {}}
    assert released == ["ai", "file", "port", "rdp"]
    assert bound.service_action("port", {"id": "svc_tcp", "is_enabled": True}) == {
        "code": "client_disabled",
        "params": {},
    }


def test_a_disabled_client_is_released_once_then_resumes(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME])
    connected(bound, script)
    released = released_handlers(bound)

    take(bound, {"type": "disabled", "is_disabled": True})
    take(bound, {"type": "disabled", "is_disabled": True})
    take(bound, {"type": "disabled", "is_disabled": False})

    assert released == ["ai", "file", "port", "rdp"]
    assert bound.is_disabled() is False
    assert bound.last_error() is None


def test_a_welcome_that_says_disabled_is_taken_at_once(bound, monkeypatch):
    script = socket_of(monkeypatch, [{**WELCOME, "is_disabled": True}])
    released = released_handlers(bound)

    connected(bound, script)

    assert bound.is_disabled() is True
    assert released == ["ai", "file", "port", "rdp"]


def test_an_unknown_frame_is_ignored(bound, monkeypatch):
    script = socket_of(monkeypatch, [WELCOME])
    connected(bound, script)

    take(bound, {"type": "something_else"})
    take(bound, CATALOG)

    assert [entry["id"] for entry in bound.service_entries()] == [
        entry["id"] for entry in SERVICES
    ]
    assert bound.last_error() is None


# --- the asks ---


def test_an_ask_goes_up_correlated_and_its_answer_comes_back(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    answered = _ask_while(
        bound,
        made,
        lambda ask_id: {
            "type": "answer",
            "id": ask_id,
            "result": {"host": "h", "port": 21118, "password": "p"},  # scan: allow
        },
    )

    ask = made.sent[1]
    assert ask["type"] == "ask"
    assert ask["kind"] == "rdp_connect"
    assert ask["args"] == {"service_id": "rdp_s9"}
    assert ask["id"]
    assert answered == {"host": "h", "port": 21118, "password": "p"}  # scan: allow


def test_an_answer_carrying_a_code_is_the_hubs_own_refusal(bound, monkeypatch):
    made = connected(bound, socket_of(monkeypatch, [WELCOME]))

    with pytest.raises(GatewayRefusedDetail) as refused:
        _ask_while(
            bound,
            made,
            lambda ask_id: {
                "type": "answer",
                "id": ask_id,
                "code": "rdp_not_shared",
                "params": {"id": "rdp_s9"},
            },
        )

    assert refused.value.code == "rdp_not_shared"
    assert refused.value.params == {"id": "rdp_s9"}


def test_an_ask_with_no_socket_is_unreachable(bound):
    with pytest.raises(GatewayUnreachable):
        bound.ask("rdp_connect", {"service_id": "rdp_s9"})


def test_an_ask_nobody_answers_gives_up(bound, monkeypatch):
    connected(bound, socket_of(monkeypatch, [WELCOME]))

    with pytest.raises(GatewayUnreachable):
        bound.ask("rdp_connect", {"service_id": "rdp_s9"}, timeout_s=0.05)

    assert bound._pending == {}


def test_an_answer_for_nobody_is_dropped(bound, monkeypatch):
    connected(bound, socket_of(monkeypatch, [WELCOME]))

    take(bound, {"type": "answer", "id": "gone", "result": {}})

    assert bound._pending == {}


# --- what ends a connection ---


def test_a_broken_wire_backs_off_and_keeps_the_binding(bound, monkeypatch):
    socket_of(monkeypatch, [], connect_error=GatewayUnreachable("down"))

    delays = [bound.run_once() for _ in range(3)]

    assert delays == [5, 10, 20]
    assert bound.is_connected() is True
    assert bound.connection_state() == "reconnecting"
    assert bound.last_error()["code"] == "hub_unreachable"


def test_a_replaced_socket_reconnects_quietly(bound, monkeypatch):
    """The hub took this socket over; nothing about that is a problem."""
    socket_of(monkeypatch, [WELCOME, SocketClosed(4410, "replaced")])

    delay = bound.run_once()

    assert delay == 5
    assert bound.is_connected() is True
    assert bound.last_error() is None


@pytest.mark.parametrize(
    "error, cause",
    [
        (GatewayRefused("401"), "hub_refused"),
        (GatewayUntrusted("pin"), "hub_untrusted"),
        (
            GatewayVersionRefused(hub_version="0.1.0", client_version="0.2.0"),
            "client_newer_than_hub",
        ),
    ],
)
def test_three_refusals_of_any_kind_unbind(
    bound, monkeypatch, config_path, error, cause
):
    socket_of(monkeypatch, [], connect_error=error)
    released = released_handlers(bound)

    bound.run_once()
    bound.run_once()
    assert bound.is_connected() is True
    assert bound.last_error()["code"] == cause
    bound.run_once()

    assert bound.is_connected() is False
    assert bound.connection_state() == "unbound"
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert bound.last_error() == {"code": "self_unbound", "params": {"cause": cause}}
    assert released == ["ai", "file", "port", "rdp"]


def test_a_close_the_hub_sends_refuses_the_same_way(bound, monkeypatch, config_path):
    """The close arrives instead of the welcome, which is when the hub sends
    one."""
    socket_of(monkeypatch, [SocketClosed(4401, "unknown_token")])

    for _ in range(3):
        bound.run_once()

    assert bound.is_connected() is False
    assert bound.last_error() == {
        "code": "self_unbound",
        "params": {"cause": "hub_refused"},
    }


def test_an_unreachable_hub_between_refusals_neither_counts_nor_resets(
    bound, monkeypatch
):
    socket_of(monkeypatch, [], connect_error=GatewayRefused("401"))
    bound.run_once()
    socket_of(monkeypatch, [], connect_error=GatewayUnreachable("down"))
    bound.run_once()
    socket_of(monkeypatch, [], connect_error=GatewayRefused("401"))
    bound.run_once()

    assert bound.is_connected() is True
    assert bound._refusals == 2


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


def test_an_external_disconnect_releases_everything(bound, monkeypatch, config_path):
    socket_of(monkeypatch, [WELCOME, CATALOG])
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
        posted.append(path)
        return {}

    monkeypatch.setattr(session_module.GatewayHttpChannel, "post", post, raising=True)
    released = released_handlers(bound)

    bound.disconnect()

    assert posted == ["/api/client/leave"]
    assert bound.is_connected() is False
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert released == ["ai", "file", "port", "rdp"]


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


def _ask_while(session, made, answer_for):
    """Ask on one thread while the test answers what the ask carried.

    Args:
        session: The session under test.
        made: The scripted socket the ask lands on.
        answer_for: Called with the ask's id; returns the answer frame.

    Returns:
        What :meth:`ClientSession.ask` returned.

    Raises:
        Exception: Whatever the ask raised.
    """
    outcome = {}

    def run() -> None:
        try:
            outcome["result"] = session.ask(
                "rdp_connect", {"service_id": "rdp_s9"}, timeout_s=5
            )
        except Exception as error:  # noqa: BLE001 - handed back to the test
            outcome["error"] = error

    thread = threading.Thread(target=run)
    thread.start()
    deadline = threading.Event()
    while len(made.sent) < 2 and not deadline.wait(timeout=0.01):
        pass
    session._take_answer(answer_for(made.sent[1]["id"]))
    thread.join(timeout=5)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]
