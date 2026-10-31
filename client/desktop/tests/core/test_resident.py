"""The resident over several hubs: one session per binding, the handlers shared.

Every hub is reached through the client's transport, played here in process
by the conftest's scripted channel: a test hands a session the events and
frames the transport would pass, and reads back the commands, the frames and
the streams the resident sent. What is pinned here is a second binding
dialled under its own id, the merged service list carrying every hub's id,
a hub that is down subtracting only its own entries, leaving one hub
stopping only its session, releasing only its entries and telling the hub
with the transport's ``leave`` from a thread of its own whatever it
answers, the one refusal that unbinds keeping the row for a Leave, a
disabled hub releasing only its own, the binding file diffed by id so a
rewrite restarts only the sessions it changed and the welcome's own write
restarts none, the exit hub chosen and followed with the tools moved in one
activation, the disabled check per hub, a start that turns nothing on and
clears what an unclean exit left, and a shutdown that runs its order once,
logs a line a step, lets no step hold up the rest and ends the transport,
with a virtual network's connect ending after it writing no binding, and a
rewrite of the SSH configuration ending before it and none running after it.
The state document's jobs: a refresh set per hub and cleared by its answer,
a leave and a service press shown before the work, a duplicate press
dropped and never answered as ``busy``, a failure kept on its row until the
next press or a refresh, the notice closed or dropped by a refresh, and the
clipboard written. One binding per hub id: a join landing on the binding
held here ending it with the hub not told, a welcome naming a hub another
binding holds ending that one with the hub told whatever it answers, and a
start keeping the binding joined last of each hub. The apps: one row per
app with entries the client forwards, Use forwarding every entry at its
fixed number through ``forward_start`` and opening the browser at the
app's local name, a token page opened with the token a ``service`` reply
gives, a number another program holds refused ``port_taken`` with the
other forwards kept, Stop ending them, and Configure's numbers judged
before any is kept. The panel's sign-in asked with a ``service`` frame
before its forward, the terminals' streams opened through the transport
with their account, the window terminal's Clear, the shares on Windows
through the files adapter, and the Settings page's values.
"""

import functools
import hashlib
import io
import json
import queue
import socket
import threading
import time
import uuid

import pytest

import neutrino_client.core.resident as resident_module
from neutrino_client.constants import CLIENT_MOUNT_CREDENTIALS_DIR_NAME
from neutrino_client.core import enrollment
from neutrino_client.core.resident import ClientResident
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.base import ServiceTypeHandler
from neutrino_client.services.file import mount_record_id
from tests.conftest import (
    BINDING,
    HUB_KEY,
    HUB_SERVICES,
    OFFICE_BINDING,
    OFFICE_SERVICES,
    Clock,
    FakeClientPlatform,
    FakeTransportChannel,
    bind,
    discard,
    link_for,
    with_hub,
)

HOME_WELCOME = {
    "type": "welcome",
    "protocol": 4,
    "role": "hub",
    "id": "h1",
    "name": "home",
    "software": "neutrino_hub/0.6.0",
    "time": 1.0,
}
OFFICE_WELCOME = dict(HOME_WELCOME, id="h2", name="office")
HOME_STATE = {
    "type": "state",
    "hash": "s1",
    "is_disabled": False,
    "services": HUB_SERVICES,
}
OFFICE_STATE = {
    "type": "state",
    "hash": "s2",
    "is_disabled": False,
    "services": OFFICE_SERVICES,
}
HOME_URL = "tcp://hub.lan:8443"
OFFICE_URL = "tcp://office.lan:8443"


class RecordingHandler(ServiceTypeHandler):
    """A handler that remembers the lifecycle calls it was given.

    Attributes:
        starts: How often the resident started it.
        cleared: How often it was asked to clear leftovers.
        refreshed: The entries of every refresh, in order.
        gates: Every look at the agent's program directory, in order with
            the refreshes as ``"gate"`` in ``order``.
        released_hubs: Every hub it was asked to let go of, in order.
        withdrawn: ``(hub_id, entries)`` of every list it was told of.
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
        self.released_hubs = []
        self.withdrawn = []
        self.acted = []
        self.gates = 0
        self.order = []
        self._log = log
        self._count = count
        self._is_hanging = is_hanging
        self._held = threading.Event()
        self.is_holding = threading.Event()

    def act(self, *, entries, body):
        self.acted.append((list(entries), dict(body)))
        return {}

    def refresh(self, *, entries) -> None:
        self.refreshed.append(list(entries))
        self.order.append("refresh")

    def check_gate(self) -> bool:
        self.gates += 1
        self.order.append("gate")
        return False

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

    def release_hub(self, hub_id: str):
        self.released_hubs.append(hub_id)
        return 0

    def drop_withdrawn(self, *, hub_id, entries):
        self.withdrawn.append((hub_id, list(entries)))
        return 0

    def adapter_pairs(self) -> set:
        return set()

    def entry_fields(self, entry: dict) -> dict:
        return {}

    def let_go(self) -> None:
        """Let a hanging release finish, so the test leaves no thread behind."""
        self._held.set()


class RecordingForwards(RecordingHandler):
    """The forward registry, remembering its lifecycle calls; nothing listens."""

    def forwards(self) -> dict:
        return {}

    def port_of(self, hub_id: str, entry_id: str) -> int:
        return 0

    def take_end(self, line: dict) -> None:
        """A listener's end, which no forward of this one has."""

    def restart(self) -> None:
        """Nothing to start again."""


class AiForwards:
    """The forward registry as the AI handler sees it: one port per hub."""

    PORTS = {"h1": 21001, "h2": 21002}

    def __init__(self):
        self.running = {}

    def ensure(self, *, hub_id, entry_id, own_port=0, kind="", protocol="tcp"):
        self.running[(hub_id, entry_id)] = self.PORTS[hub_id]
        return self.PORTS[hub_id]

    def stop(self, hub_id, entry_id):
        return self.running.pop((hub_id, entry_id), None) is not None


class ScriptedStream:
    """One stream the transport opened, the far side accepting it; a test
    scripts the bytes it sends back and how it ends.

    Attributes:
        binding: The binding it was opened on.
        open: Its open record.
        records: What this side sent, in order: ``("data", bytes)``,
            ``("eof",)``, ``("resize", cols, rows)`` and ``("close",)``.
    """

    kind = "stream"

    def __init__(self, binding: str, open_record: dict):
        self.binding = binding
        self.open = dict(open_record)
        self.records = []
        self._pieces = queue.Queue()
        self._lock = threading.Lock()
        self._is_drained = False
        self._code = ""
        self._params: dict = {}
        self.is_far_ended = False
        self.is_closed_here = False

    @property
    def is_done(self) -> bool:
        return self.is_far_ended or self.is_closed_here

    @property
    def is_accepted(self) -> bool:
        return not self._code

    def wait_accept(self, timeout_s: float) -> bool:
        return not self._code

    def push(self, data: bytes) -> None:
        """The far side sends bytes."""
        self._pieces.put(bytes(data))

    def end(self, params=None, code: str = "") -> None:
        """The far side closes the stream: its result, or a refusal's code."""
        self._params = dict(params or {})
        self._code = code
        self.is_far_ended = True
        self._pieces.put(b"")

    def read(self, timeout_s: float):
        if self._is_drained:
            return b""
        try:
            piece = self._pieces.get(timeout=max(timeout_s, 0.001))
        except queue.Empty:
            return None
        if piece == b"":
            self._is_drained = True
        return piece

    def send(self, data: bytes) -> None:
        if self.is_done:
            raise GatewayUnreachable("the stream has ended")
        with self._lock:
            self.records.append(("data", bytes(data)))

    def send_eof(self) -> None:
        if self.is_done:
            raise GatewayUnreachable("the stream has ended")
        with self._lock:
            self.records.append(("eof",))

    def resize(self, cols: int, rows: int) -> None:
        if self.is_done:
            raise GatewayUnreachable("the stream has ended")
        with self._lock:
            self.records.append(("resize", cols, rows))

    def close(self) -> None:
        if self.is_closed_here:
            return
        if not self.is_far_ended:
            with self._lock:
                self.records.append(("close",))
        self.is_closed_here = True
        self._pieces.put(b"")

    def refusal(self):
        if not self._code:
            return None
        return {"code": self._code, "params": dict(self._params)}

    def wait_close(self, timeout_s: float) -> dict:
        if self._code:
            raise GatewayRefusedDetail(code=self._code, params=dict(self._params))
        if not self.is_far_ended:
            raise GatewayUnreachable("the stream did not end in time")
        return dict(self._params)

    def data(self) -> list:
        """The bytes this side sent, record by record."""
        with self._lock:
            return [record[1] for record in self.records if record[0] == "data"]


class Streams:
    """The transport's stream factory: every stream it opened, in order."""

    def __init__(self):
        self.made = []

    def __call__(self, binding, open_record, **kwargs) -> ScriptedStream:
        made = ScriptedStream(binding, open_record)
        self.made.append(made)
        return made


def answering(transport, respond) -> None:
    """Answer every question frame the resident sends with ``respond``'s reply.

    Args:
        transport: The scripted channel.
        respond: ``respond(frame)`` gives the reply's ``{params}`` or
            ``{code, params}``.
    """
    sent = transport.send_frame

    def send_frame(binding, frame, is_last=False):
        sent(binding, frame, is_last)
        if "request" in frame:
            reply = dict(respond(dict(frame)))
            transport.deliver(
                binding,
                {"frame": dict(reply, type="reply", request=frame["request"])},
            )

    transport.send_frame = send_frame


def listen(resident, transport) -> None:
    """Hand each session the lines of its binding, as a started one takes them."""
    for session in list(resident._sessions.values()):
        transport.listen_binding(session.label, session.take_line)


def up(transport, label: str, url: str, welcome: dict, state=None) -> None:
    """Open one hub's session, welcome it, and hand it a state."""
    transport.deliver(
        label,
        {"event": "session_open", "address": url, "path": "lan", "handshake_ms": 1},
    )
    transport.deliver(label, {"frame": welcome})
    if state is not None:
        transport.deliver(label, {"frame": state})


def released_handlers(resident, counts=None) -> list:
    """Swap every releasable handler for one that records, and return the log."""
    log = []
    counts = counts or {}
    for service_type in ("ai", "file", "rdp"):
        resident._services[service_type] = RecordingHandler(
            service_type, log, count=counts.get(service_type)
        )
    resident._forwards = RecordingForwards(
        "forwards", log, count=counts.get("forwards")
    )
    return log


def hub_releasers(resident) -> list:
    """What a hub's leaving lets go of, in the shutdown's order."""
    return [
        resident._releaser(service_type)
        for service_type in ("ai", "file", "rdp", "forwards")
    ]


def sessions_of(resident) -> dict:
    """The sessions by binding id."""
    return dict(resident._sessions)


def wait_until(condition, timeout_s: float = 5) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


def free_port() -> int:
    """A loopback port nothing listens on now."""
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class QuietSwitcher:
    """A switcher over a machine with nothing pointed at the hub."""

    def __init__(self):
        self.calls = []
        self.base_urls = []

    def is_installed(self) -> bool:
        return True

    def find_cli(self) -> str:
        return "/opt/neutrino/client/bin/cc-switch"

    def is_active_for(self, app: str) -> bool:
        return False

    def activate(self, *, base_url, api_key, tool_configs=None) -> str:
        self.calls.append("activate")
        self.base_urls.append(base_url)
        return "claude"

    def deactivate(self, *, base_url="") -> str:
        self.calls.append("deactivate")
        return ""


def run_inline(target) -> None:
    """The lane's thread starter, running the job right here."""
    target()


def inline_ai(resident, *, is_managed=None) -> tuple:
    """Put an AI handler under the resident whose grants are scripted per hub.

    Returns:
        ``(handler, switcher)``; the credential each hub answers with names
        the port of that hub's own forward.
    """
    switcher = QuietSwitcher()

    def grant(hub_id: str, entry_id: str) -> dict:
        return {"api_key": "k", "model": "m1"}

    handler = AiServiceHandler(
        store=resident._store,
        original_dir=str(resident.platform.config_dir()) + "/original",
        open_service=grant,
        exit_hub_id=resident.exit_hub_id,
        forwards=AiForwards(),
        log=discard,
        switcher_module=switcher,
        on_change=resident.notify,
        start_thread=run_inline,
        is_managed=is_managed,
    )
    resident._services["ai"] = handler
    return handler, switcher


@pytest.fixture
def transport():
    """The transport, in process, every stream it opens a scripted one."""
    made = FakeTransportChannel()
    made.stream_factory = Streams()
    return made


@pytest.fixture
def two_hubs(config_path, transport):
    """A resident bound to two hubs, neither connected yet, each session listening."""
    bind(
        config_path,
        bindings=[dict(BINDING, gateway_url=HOME_URL), dict(OFFICE_BINDING)],
    )
    resident = ClientResident(
        log=discard,
        platform=FakeClientPlatform(),
        start_thread=run_inline,
        transport=transport,
    )
    listen(resident, transport)
    yield resident
    resident.shutdown()


@pytest.fixture
def two_hubs_up(two_hubs, transport):
    """Both hubs welcomed and their states taken."""
    up(transport, "c1", HOME_URL, HOME_WELCOME, HOME_STATE)
    up(transport, "c2", OFFICE_URL, OFFICE_WELCOME, OFFICE_STATE)
    return two_hubs, transport


# --- one session per binding ---


def test_a_second_binding_is_dialled_under_its_own_id(two_hubs, transport):
    for session in sessions_of(two_hubs).values():
        session.run_once()

    dials = transport.commands_of("dial")
    assert [dial["binding"] for dial in dials] == ["c1", "c2"]
    assert [dial["psk"] for dial in dials] == [
        hashlib.sha256(b"tok").hexdigest(),
        hashlib.sha256(b"tok2").hexdigest(),
    ]
    assert list(sessions_of(two_hubs)) == ["c1", "c2"]
    rows = two_hubs.hubs()
    assert [(row["hub_id"], row["binding_id"]) for row in rows] == [
        ("h1", "c1"),
        ("h2", "c2"),
    ]


def test_each_hello_names_its_own_binding(two_hubs_up):
    _resident, transport = two_hubs_up

    hellos = [
        (binding, frame["id"])
        for binding, frame in transport.frames
        if frame["type"] == "hello"
    ]

    assert hellos == [("c1", "c1"), ("c2", "c2")]
    assert all("token" not in frame for _binding, frame in transport.frames)


def test_a_hub_row_carries_the_round_trip_its_last_pong_measured(two_hubs_up):
    resident, transport = two_hubs_up
    session = resident._sessions["c1"]
    clock = Clock()
    session._clock = clock

    session._ping()
    clock.now += 0.0236
    transport.deliver(
        "c1",
        {"frame": {"type": "pong", "nonce": transport.frames_of("ping")[-1]["nonce"]}},
    )

    home, office = resident.hubs()
    assert (home["rtt_ms"], office["rtt_ms"]) == (24, None)


def test_the_hub_rows_carry_each_sessions_standing(two_hubs_up):
    resident, _transport = two_hubs_up

    home, office = resident.hubs()

    assert home == {
        "hub_id": "h1",
        "hub_name": "home",
        "binding_id": "c1",
        "gateway_url": HOME_URL,
        "software": "neutrino_hub/0.6.0",
        "connection": "connected",
        "wait_reason": "",
        "wait_code": None,
        "next_round_at": None,
        "reached_through": "",
        "rtt_ms": None,
        "is_panel_allowed": False,
        "panel_forward": None,
        "is_pending": False,
        "last_error": None,
        "is_exit": False,
        "overlay": {
            "network": "",
            "networks": [],
            "state": "off",
            "stage": "",
            "is_waiting": False,
            "address": "",
            "error": None,
        },
        "jobs": {
            "is_refreshing": False,
            "overlay_job": "",
            "is_leaving": False,
            "is_opening_panel": False,
        },
    }
    assert (office["hub_id"], office["gateway_url"], office["is_exit"]) == (
        "h2",
        OFFICE_URL,
        False,
    )
    assert "tok" not in json.dumps(resident.hubs())


def test_the_merged_list_carries_every_entrys_hub(two_hubs_up):
    resident, _transport = two_hubs_up

    merged = resident.service_entries()

    assert merged == with_hub(HUB_SERVICES, "h1") + with_hub(OFFICE_SERVICES, "h2")
    assert {entry["hub_id"] for entry in merged} == {"h1", "h2"}


def test_a_hub_that_is_down_subtracts_only_its_own_entries(two_hubs_up):
    resident, transport = two_hubs_up

    transport.deliver("c2", {"event": "session_end"})

    assert resident.service_entries() == with_hub(HUB_SERVICES, "h1")
    assert [row["connection"] for row in resident.hubs()] == [
        "connected",
        "connecting",
    ]


def test_a_hubs_state_refreshes_the_ai_handler_with_the_merged_list(
    two_hubs, transport
):
    released_handlers(two_hubs)

    up(transport, "c1", HOME_URL, HOME_WELCOME, HOME_STATE)

    assert two_hubs._services["ai"].refreshed[-1] == with_hub(HUB_SERVICES, "h1")


def test_a_hubs_state_and_a_leave_tell_the_shares_what_that_hub_lists(
    two_hubs_up, config_path
):
    resident, transport = two_hubs_up
    released_handlers(resident)
    home = resident._sessions["c1"]

    transport.deliver("c1", {"frame": HOME_STATE})
    listed = home.service_entries()
    resident.disconnect("h1")

    assert listed
    assert resident._services["file"].withdrawn == [("h1", listed), ("h1", [])]


# --- leaving one hub ---


def test_leaving_one_hub_stops_only_its_session_and_releases_only_its_hub(
    two_hubs_up, config_path
):
    resident, transport = two_hubs_up
    released = released_handlers(resident)
    home = resident._sessions["c1"]

    resident.disconnect("h2")

    wait_until(lambda: transport.commands_of("leave"))
    (leave,) = transport.commands_of("leave")
    assert leave["binding"] == "c2"
    assert leave["psk"] == hashlib.sha256(b"tok2").hexdigest()
    assert OFFICE_URL in leave["addresses"]
    assert list(sessions_of(resident)) == ["c1"]
    assert resident._sessions["c1"] is home
    assert home.connection() == "connected"
    assert set(transport.listeners) == {"c1"}
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1"]
    assert released == []
    for handler in hub_releasers(resident):
        assert handler.released_hubs == ["h2"]
    assert resident.service_entries() == with_hub(HUB_SERVICES, "h1")


def test_leaving_lets_go_when_the_hub_refuses_the_leave(two_hubs_up):
    resident, transport = two_hubs_up
    transport.answers["leave"] = functools.partial(
        dict, code="binding_unknown", params={}
    )

    resident.disconnect("h1")

    assert list(sessions_of(resident)) == ["c2"]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c2"]


def test_leaving_drops_the_binding_first_and_tells_the_hub_from_its_own_thread(
    two_hubs_up,
):
    """The row is gone before the hub hears; a hub that takes its time
    holds nobody up."""
    resident, transport = two_hubs_up
    released_handlers(resident)
    told = []
    hold = threading.Event()

    def leave(fields):
        told.append([binding["id"] for binding in enrollment.bindings()])
        hold.wait(timeout=5)
        return {}

    transport.answers["leave"] = leave
    started = time.monotonic()

    resident.disconnect("h2")
    elapsed = time.monotonic() - started
    wait_until(lambda: told)
    hold.set()

    assert elapsed < 1
    assert told == [["c1"]]
    assert list(sessions_of(resident)) == ["c1"]


def test_a_refresh_reports_on_a_live_session_and_starts_a_round_for_one_that_is_down(
    two_hubs_up,
):
    resident, transport = two_hubs_up
    office = resident._sessions["c2"]
    office.run_once()
    transport.deliver("c2", {"event": "session_end"})
    reports_before = len(transport.frames_of("report"))

    resident.refresh()
    office.run_once()

    refreshed = [
        (binding, frame)
        for binding, frame in transport.frames
        if frame["type"] == "report" and frame.get("is_refresh")
    ]
    assert [binding for binding, _frame in refreshed] == ["c1"]
    assert len(transport.frames_of("report")) == reports_before + 1
    assert transport.commands_of("round") == [{"binding": "c2"}]
    assert [row["jobs"]["is_refreshing"] for row in resident.hubs()] == [True, True]


def test_a_hub_nobody_joined_cannot_be_left_or_reconnected(two_hubs_up):
    resident, _transport = two_hubs_up

    with pytest.raises(KeyError):
        resident.disconnect("h9")
    with pytest.raises(KeyError):
        resident.reconnect("h9")
    with pytest.raises(KeyError):
        resident.reconnect("")
    assert list(sessions_of(resident)) == ["c1", "c2"]


def test_an_empty_name_means_the_one_hub_joined(config_path, transport):
    bind(config_path, url=HOME_URL)
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    try:
        resident.reconnect("")
        resident.disconnect("")
    finally:
        resident.shutdown()

    assert sessions_of(resident) == {}
    assert enrollment.bindings() == []


def test_a_binding_whose_hub_has_not_answered_is_named_by_its_binding_id(two_hubs):
    assert [row["hub_id"] for row in two_hubs.hubs()] == ["h1", "h2"]
    two_hubs._sessions["c2"]._binding["hub_id"] = ""

    two_hubs.disconnect("c2")

    assert list(sessions_of(two_hubs)) == ["c1"]


# --- a hub that no longer knows this device ---


def test_binding_unknown_keeps_the_row_waiting_for_leave(two_hubs, transport):
    released_handlers(two_hubs)
    up(transport, "c1", HOME_URL, HOME_WELCOME, HOME_STATE)

    transport.deliver(
        "c2",
        {
            "frame": {
                "type": "refused",
                "code": "binding_unknown",
                "params": {"id": "c2"},
            }
        },
    )
    transport.deliver(
        "c2",
        {"event": "session_end", "code": "binding_unknown", "params": {"id": "c2"}},
    )

    assert list(sessions_of(two_hubs)) == ["c1", "c2"]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1", "c2"]
    for handler in hub_releasers(two_hubs):
        assert handler.released_hubs == ["h2"]
    _home, office = two_hubs.hubs()
    assert (office["connection"], office["wait_reason"]) == (
        "waiting",
        "unknown_device",
    )
    assert office["wait_code"] == {"code": "binding_unknown", "params": {"id": "c2"}}
    assert two_hubs.notices() == []


# --- a hub that switches this client off ---


def test_disabled_releases_only_that_hubs_entries(two_hubs_up):
    resident, transport = two_hubs_up
    released = released_handlers(resident)

    transport.deliver("c2", {"frame": dict(OFFICE_STATE, is_disabled=True)})
    transport.deliver("c2", {"frame": dict(OFFICE_STATE, is_disabled=True)})

    assert released == []
    for handler in hub_releasers(resident):
        assert handler.released_hubs == ["h2"]
    assert [row["connection"] for row in resident.hubs()] == [
        "connected",
        "disabled",
    ]
    assert resident.service_action("rdp", {"hub_id": "h2", "id": "rdp_lab"}) == {
        "code": "client_disabled",
        "params": {},
    }
    assert resident.service_action("rdp", {"hub_id": "h1", "id": "rdp_s9"}) == {}


def test_an_action_naming_no_hub_is_the_exit_hubs(two_hubs_up, config_path):
    resident, transport = two_hubs_up
    released_handlers(resident)
    resident.set_exit("h1")

    transport.deliver("c1", {"frame": dict(HOME_STATE, is_disabled=True)})

    assert resident.service_action("ai", {"is_enabled": True}) == {
        "code": "client_disabled",
        "params": {},
    }


def test_an_action_reaches_its_handler_with_the_merged_list(two_hubs_up):
    resident, _transport = two_hubs_up
    released_handlers(resident)

    assert resident.service_action("file", {"hub_id": "h2", "id": "share_media"}) == {}

    entries, body = resident._services["file"].acted[0]
    assert entries == resident.service_entries()
    assert body == {"hub_id": "h2", "id": "share_media"}
    for gone in ("nothing", "web", "port"):
        assert resident.service_action(gone, {}) == {
            "code": "unknown_request",
            "params": {},
        }


# --- the exit hub ---


def test_the_exit_is_the_chosen_hub_and_no_hub_otherwise(two_hubs_up, config_path):
    resident, _transport = two_hubs_up

    assert resident.exit_hub_id() == ""
    assert [row["is_exit"] for row in resident.hubs()] == [False, False]

    enrollment.set_exit_hub_id("h2")
    resident._adopt_external_binding()
    assert resident.exit_hub_id() == "h2"
    assert [row["is_exit"] for row in resident.hubs()] == [False, True]

    enrollment.set_exit_hub_id("h9")
    resident._adopt_external_binding()
    assert resident.exit_hub_id() == ""


def test_the_chosen_exit_is_where_the_tools_point(two_hubs_up, config_path):
    resident, _transport = two_hubs_up
    handler, switcher = inline_ai(resident)

    assert resident.set_exit("h1") == {}
    assert resident.service_action("ai", {"is_enabled": True}) == {}

    assert resident.exit_hub_id() == "h1"
    assert switcher.calls == ["activate"]
    assert handler._granted["hub_id"] == "h1"
    assert handler._granted["base_url"] == "http://127.0.0.1:21001"


def test_set_exit_to_a_joined_hub_moves_the_tools_in_one_activation(
    two_hubs_up, config_path
):
    resident, _transport = two_hubs_up
    handler, switcher = inline_ai(resident)
    resident.set_exit("h1")
    resident.service_action("ai", {"is_enabled": True})

    assert resident.set_exit("h2") == {}

    assert resident.exit_hub_id() == "h2"
    assert enrollment.exit_hub_id() == "h2"
    assert [row["is_exit"] for row in resident.hubs()] == [False, True]
    assert switcher.calls == ["activate", "activate"]
    assert switcher.base_urls == ["http://127.0.0.1:21001", "http://127.0.0.1:21002"]
    assert handler._granted["hub_id"] == "h2"

    assert resident.set_exit("c1") == {}
    assert resident.exit_hub_id() == "h1"
    assert switcher.calls == ["activate", "activate", "activate"]


def test_a_hub_that_is_not_connected_cannot_be_the_exit(two_hubs_up, config_path):
    resident, transport = two_hubs_up
    _handler, switcher = inline_ai(resident)
    office = resident._sessions["c2"]

    transport.deliver("c2", {"event": "session_end"})
    assert resident.set_exit("h2") == {
        "code": "no_exit_hub",
        "params": {"hub_id": "h2"},
    }

    office._stand_aside()
    assert resident.set_exit("h2")["code"] == "no_exit_hub"

    assert resident.set_exit("h9") == {
        "code": "unknown_hub",
        "params": {"hub_id": "h9"},
    }
    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""
    assert switcher.calls == []


def test_leaving_the_exit_leaves_no_exit_and_puts_the_tools_back(
    two_hubs_up, config_path
):
    resident, _transport = two_hubs_up
    handler, switcher = inline_ai(resident)
    resident.set_exit("h1")
    resident.service_action("ai", {"is_enabled": True})

    resident.disconnect("h1")

    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""
    assert [row["is_exit"] for row in resident.hubs()] == [False]
    assert switcher.calls == ["activate", "deactivate"]
    assert handler._granted == {}


def test_a_rejoin_after_leaving_the_exit_makes_no_hub_the_exit(
    two_hubs_up, config_path
):
    resident, _transport = two_hubs_up
    released_handlers(resident)
    resident.set_exit("h1")
    resident.disconnect("h1")
    assert enrollment.exit_hub_id() == ""

    enrollment.add_binding(dict(BINDING, gateway_url=HOME_URL))
    resident._adopt_external_binding()

    assert list(sessions_of(resident)) == ["c2", "c1"]
    assert resident.exit_hub_id() == ""
    assert [row["is_exit"] for row in resident.hubs()] == [False, False]


def test_a_binding_gone_from_the_file_clears_the_exit(two_hubs_up, config_path):
    resident, _transport = two_hubs_up
    released_handlers(resident)
    resident.set_exit("h1")
    time.sleep(0.01)
    bind(config_path, bindings=[dict(OFFICE_BINDING)])
    enrollment.set_exit_hub_id("h1")

    resident._adopt_external_binding()

    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""


def test_binding_unknown_on_the_exit_keeps_it_until_leave(
    two_hubs, transport, config_path
):
    released_handlers(two_hubs)
    two_hubs._pin_exit("h1")
    up(transport, "c2", OFFICE_URL, OFFICE_WELCOME, OFFICE_STATE)

    transport.deliver(
        "c1",
        {
            "frame": {
                "type": "refused",
                "code": "binding_unknown",
                "params": {"id": "c1"},
            }
        },
    )

    assert two_hubs.exit_hub_id() == "h1"
    two_hubs.disconnect("h1")

    assert two_hubs.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""


def test_with_no_joined_hub_the_tools_are_restored(two_hubs_up, config_path):
    resident, _transport = two_hubs_up
    handler, switcher = inline_ai(resident)
    resident.set_exit("h1")
    resident.service_action("ai", {"is_enabled": True})

    resident.disconnect("h1")
    resident.disconnect("h2")

    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""
    assert switcher.calls == ["activate", "deactivate"]
    assert handler._granted == {}
    assert handler.state()["ai"]["is_enabled"] is True
    assert handler.state()["ai"]["is_active"] is False


def test_the_service_frame_is_asked_of_the_hub_named(two_hubs_up):
    resident, transport = two_hubs_up
    asked = []

    def respond(frame):
        asked.append(frame)
        return {"params": {"host": "x"}}

    answering(transport, respond)

    assert resident.open_service("h2", "rdp_lab", timeout_s=5) == {"host": "x"}

    services = [
        (binding, frame)
        for binding, frame in transport.frames
        if frame["type"] == "service"
    ]
    assert [(binding, frame["id"]) for binding, frame in services] == [
        ("c2", "rdp_lab")
    ]
    with pytest.raises(GatewayUnreachable):
        resident.open_service("h9", "rdp_lab", timeout_s=0.05)


def test_a_reply_with_a_code_is_the_hubs_refusal(two_hubs_up):
    resident, transport = two_hubs_up
    answering(
        transport,
        functools.partial(dict, code="service_unknown", params={"service_id": "x"}),
    )

    with pytest.raises(GatewayRefusedDetail) as refused:
        resident.open_service("h1", "x", timeout_s=5)

    assert refused.value.code == "service_unknown"


# --- the binding file, diffed by id ---


def test_a_rewrite_of_the_file_restarts_only_the_sessions_it_changed(
    two_hubs_up, config_path
):
    resident, transport = two_hubs_up
    released_handlers(resident)
    home = resident._sessions["c1"]
    office = resident._sessions["c2"]
    third = dict(OFFICE_BINDING, id="c3", hub_id="", hub_name="", token="tok3")
    time.sleep(0.01)
    bind(
        config_path,
        bindings=[
            dict(BINDING, gateway_url=HOME_URL),
            dict(OFFICE_BINDING, token="rotated"),
            third,
        ],
    )

    resident._adopt_external_binding()

    assert list(sessions_of(resident)) == ["c1", "c2", "c3"]
    assert resident._sessions["c1"] is home
    assert resident._sessions["c2"] is not office
    assert home.connection() == "connected"
    assert "c2" not in transport.listeners and "c1" in transport.listeners
    assert resident._services["file"].released_hubs == ["h2"]
    assert resident._sessions["c2"].binding()["token"] == "rotated"


def test_a_binding_gone_from_the_file_stops_its_session(two_hubs_up, config_path):
    resident, transport = two_hubs_up
    released_handlers(resident)
    time.sleep(0.01)
    bind(config_path, bindings=[dict(OFFICE_BINDING)])

    resident._adopt_external_binding()

    assert list(sessions_of(resident)) == ["c2"]
    assert "c1" not in transport.listeners
    assert resident._forwards.released_hubs == ["h1"]
    assert resident.service_entries() == with_hub(OFFICE_SERVICES, "h2")


def test_the_hubs_name_written_by_the_welcome_restarts_nothing(config_path, transport):
    bind(config_path, bindings=[dict(BINDING, hub_id="", hub_name="")])
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    listen(resident, transport)
    session = resident._sessions["c1"]
    try:
        up(transport, "c1", "tcp://127.0.0.1:9", HOME_WELCOME, HOME_STATE)
        assert json.loads(config_path.read_text())["bindings"][0]["hub_id"] == "h1"

        resident._adopt_external_binding()

        assert resident._sessions["c1"] is session
        assert "c1" in transport.listeners
        assert resident.hubs()[0]["hub_name"] == "home"
    finally:
        resident.shutdown()


def test_an_external_binding_is_adopted_and_an_unbound_resident_idles(
    config_path, transport
):
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    assert resident.is_connected() is False
    assert resident.hubs() == []

    bind(config_path, url=HOME_URL)
    resident._adopt_external_binding()
    resident._sessions["c1"].run_once()

    assert resident.is_connected() is True
    assert [dial["binding"] for dial in transport.commands_of("dial")] == ["c1"]
    resident.shutdown()


def test_connect_starts_the_new_hubs_session(config_path, monkeypatch, transport):
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    monkeypatch.setattr(
        enrollment,
        "enroll",
        lambda link: enrollment.add_binding(dict(BINDING, gateway_url=HOME_URL)),
    )
    try:
        resident.connect("neutrino://enroll/x")

        assert list(sessions_of(resident)) == ["c1"]
        assert resident.hubs()[0]["gateway_url"] == HOME_URL
    finally:
        resident.shutdown()


def test_a_started_resident_starts_its_transport_and_adopts_the_file_on_its_own(
    config_path, monkeypatch, transport
):
    monkeypatch.setattr(resident_module, "CLIENT_IDLE_POLL_INTERVAL_S", 0.02)
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    released_handlers(resident)
    resident.start()
    try:
        bind(config_path, url=HOME_URL)
        # The session is held before its thread is published: wait for both.
        wait_until(
            lambda: "c1" in resident._sessions
            and resident._sessions["c1"]._thread is not None
        )
        wait_until(lambda: transport.commands_of("dial"))

        assert transport.started == 1
        assert list(sessions_of(resident)) == ["c1"]
        assert resident._sessions["c1"]._thread is not None
        assert transport.commands_of("dial")[0]["binding"] == "c1"
    finally:
        resident.shutdown()
    assert transport.stopped == 1


def test_a_start_with_no_transport_program_leaves_a_notice(config_path, transport):
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    released_handlers(resident)
    resident._transport_program = ""

    resident.start()
    wait_until(lambda: transport.started == 1)
    resident.shutdown()

    assert [notice["code"] for notice in resident.notices()] == ["transport_missing"]


def test_the_transport_ending_and_coming_back_dials_every_hub_again(two_hubs_up):
    resident, transport = two_hubs_up
    for session in sessions_of(resident).values():
        session.run_once()
    transport.commands.clear()

    resident._transport_lost()
    assert [row["connection"] for row in resident.hubs()] == [
        "connecting",
        "connecting",
    ]
    resident._transport_ready()
    for session in sessions_of(resident).values():
        session.run_once()

    assert [dial["binding"] for dial in transport.commands_of("dial")] == ["c1", "c2"]


# --- the start, and the one way out ---


def test_the_start_turns_nothing_on(config_path, tmp_path, transport):
    """Opening the client shows a clean machine: a record is a preference,
    never a mount to bring back."""
    platform = FakeClientPlatform()
    resident = ClientResident(log=discard, platform=platform, transport=transport)
    resident._services["ai"]._switcher = QuietSwitcher()
    location = str(tmp_path / "nas")
    record_id = mount_record_id("h1", "share_media", location)
    resident._store.set_mount(
        record_id,
        {
            "hub_id": "h1",
            "entry_id": "share_media",
            "host": "hub",
            "share": "media",
            "username": "media",
            "path": location,
        },
    )
    credentials = tmp_path / "config" / CLIENT_MOUNT_CREDENTIALS_DIR_NAME
    credentials.mkdir(parents=True)

    resident.start()
    try:
        resident._services["file"].reconcile()
    finally:
        resident.shutdown()

    assert platform.attach_calls == []
    states = resident.service_states()
    assert states["ai"]["is_enabled"] is False
    assert states["ai"]["is_active"] is False
    assert [row["state"] for row in states["mounts"]] == ["detached"]


def test_the_start_returns_before_the_leftovers_are_cleared(config_path, transport):
    """The window opens first: the clearing, which can run a console tool,
    happens on the resident's own thread, the handlers after it."""
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    released_handlers(resident)
    entered = threading.Event()
    hold = threading.Event()

    def clear() -> None:
        entered.set()
        hold.wait(timeout=5)

    resident._services["ai"].clear_leftovers = clear
    started = time.monotonic()

    resident.start()
    elapsed = time.monotonic() - started
    assert entered.wait(timeout=5)
    is_file_untouched = resident._services["file"].cleared == 0
    is_ai_unstarted = resident._services["ai"].starts == 0
    hold.set()
    wait_until(
        lambda: resident._services["file"].cleared == 1
        and resident._services["ai"].starts == 1
    )
    resident.shutdown()

    assert elapsed < 1
    assert is_file_untouched and is_ai_unstarted


def test_the_start_clears_what_an_unclean_exit_left(config_path, transport):
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    released_handlers(resident)

    resident.start()
    wait_until(lambda: resident._services["ai"].starts == 1)
    resident.shutdown()

    assert resident._services["ai"].cleared == 1
    assert resident._services["file"].cleared == 1
    assert resident._services["ai"].starts == 1


def test_a_handler_that_cannot_clear_is_logged_and_never_fatal(config_path, transport):
    lines = []
    resident = ClientResident(
        log=lines.append, platform=FakeClientPlatform(), transport=transport
    )
    released_handlers(resident)

    def refuse() -> None:
        raise OSError("busy")

    resident._services["file"].clear_leftovers = refuse

    resident.start()
    wait_until(lambda: resident._services["file"].starts == 1)
    resident.shutdown()

    assert any(line.startswith("file: could not clear") for line in lines)
    assert resident._services["file"].starts == 1


def test_the_shutdown_logs_one_line_a_step_in_order(config_path, transport):
    lines = []
    resident = ClientResident(
        log=lines.append, platform=FakeClientPlatform(), transport=transport
    )
    released_handlers(resident, counts={"file": 2, "forwards": 1, "rdp": 0})

    resident.shutdown()

    assert lines == [
        "networks: 0 kept",
        "ai: restored",
        "mounts: 2 detached",
        "viewers: 0 closed",
        "forwards: 1 closed",
        "shut down",
    ]
    assert transport.stopped == 1


def test_a_step_that_hangs_is_given_up_and_the_others_still_run(
    config_path, monkeypatch, transport
):
    monkeypatch.setattr(resident_module, "CLIENT_SHUTDOWN_DEADLINE_S", 0.4)
    lines = []
    resident = ClientResident(
        log=lines.append, platform=FakeClientPlatform(), transport=transport
    )
    released = released_handlers(resident)
    hanging = RecordingHandler("ai", released, is_hanging=True)
    resident._services["ai"] = hanging

    started = time.monotonic()
    resident.shutdown()
    hanging.let_go()

    assert hanging.is_holding.is_set()
    assert released == ["ai", "file", "rdp", "forwards"]
    assert lines[0] == "networks: 0 kept"
    assert lines[1].startswith("ai: gave up after ")
    assert lines[-1] == "shut down"
    assert time.monotonic() - started < 5


def test_shutdown_runs_the_order_once_undials_every_hub_and_ends_the_transport(
    two_hubs_up,
):
    resident, transport = two_hubs_up
    for session in sessions_of(resident).values():
        session.run_once()
    released = released_handlers(resident)

    resident.shutdown()
    resident.shutdown()

    assert released == ["ai", "file", "rdp", "forwards"]
    assert transport.commands_of("undial") == [{"binding": "c1"}, {"binding": "c2"}]
    assert transport.stopped == 1
    assert transport.listeners == {}


def test_shutdown_survives_a_handler_that_refuses(two_hubs):
    released = []

    class Refusing(RecordingHandler):
        def release(self):
            raise OSError("busy")

    two_hubs._services["ai"] = Refusing("ai", released)
    for service_type in ("file", "rdp"):
        two_hubs._services[service_type] = RecordingHandler(service_type, released)
    two_hubs._forwards = RecordingForwards("forwards", released)

    two_hubs.shutdown()

    assert released == ["file", "rdp", "forwards"]


def test_the_state_carries_every_handlers_keys(two_hubs):
    states = two_hubs.service_states()

    assert set(states) >= {"mounts", "ai", "ai_tool_configs", "viewers"}


def test_the_handlers_announce_through_the_resident(two_hubs):
    for service_type in ("ai", "file", "rdp"):
        handler = two_hubs._services[service_type]
        assert handler._on_change == two_hubs.notify
    assert two_hubs._forwards._on_change == two_hubs.notify


def test_show_reaches_the_registered_window(two_hubs):
    shown = []

    def show() -> None:
        shown.append(1)

    two_hubs.on_show = show
    two_hubs.request_show()
    two_hubs.on_show = None
    two_hubs.request_show()

    assert shown == [1]


# --- the settings, the language, the theme and the announcements ---


def test_the_first_start_takes_the_machines_language_and_keeps_it(two_hubs):
    """The machine is asked once; what it answered is the client's own from then."""
    two_hubs.platform.language = "zh-CN"

    assert two_hubs.language() == "zh-CN"

    two_hubs.platform.language = "en"
    assert two_hubs.language() == "zh-CN"


def test_a_picked_language_and_theme_are_kept_and_the_watchers_are_told(two_hubs):
    told = []
    two_hubs.subscribe(lambda: told.append(1))

    two_hubs.set_language("zh-CN")
    wait_until(lambda: len(told) >= 1)
    two_hubs.set_theme("light")
    wait_until(lambda: len(told) >= 2)

    assert two_hubs.language() == "zh-CN"
    assert two_hubs.theme() == "light"
    assert told == [1, 1]


def test_the_settings_save_keeps_each_value_given(two_hubs, tmp_path):
    ssh_config = tmp_path / "home" / ".ssh" / "config"
    ssh_config.parent.mkdir()
    ssh_config.write_text("Host lab\n    User me\n")

    assert (
        two_hubs.apply_settings(
            {"language": "zh-CN", "theme": "light", "is_ssh_include_enabled": True}
        )
        == {}
    )

    assert (two_hubs.language(), two_hubs.theme()) == ("zh-CN", "light")
    assert two_hubs.is_ssh_include_enabled() is True
    assert ssh_config.read_text().splitlines()[0] == "Include ~/.ssh/neutrino_config"
    assert two_hubs.apply_settings({"is_ssh_include_enabled": False}) == {}
    assert ssh_config.read_text() == "Host lab\n    User me\n"
    assert two_hubs.apply_settings({"theme": "dark"}) == {}
    assert two_hubs.language() == "zh-CN"


@pytest.mark.parametrize(
    "body, name, value",
    [
        ({"language": "fr"}, "language", "fr"),
        ({"theme": "pink"}, "theme", "pink"),
        ({"is_ssh_include_enabled": "yes"}, "is_ssh_include_enabled", "yes"),
    ],
)
def test_a_setting_value_it_does_not_take_keeps_nothing(two_hubs, body, name, value):
    two_hubs.set_theme("light")

    outcome = two_hubs.apply_settings(dict(body, theme=body.get("theme", "dark")))

    assert outcome == {
        "code": "setting_value_unknown",
        "params": {"name": name, "value": value},
    }
    assert two_hubs.theme() == "light"


def test_the_ssh_configuration_is_read_back(two_hubs):
    reply = two_hubs.ssh_config()

    assert reply["path"].endswith("/.ssh/neutrino_config")
    assert set(reply) == {"path", "text"}


def test_a_burst_of_changes_reaches_the_watchers_once(two_hubs, monkeypatch):
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.05)
    heard = []
    done = threading.Event()

    def watcher():
        heard.append(1)
        done.set()

    two_hubs.subscribe(watcher)

    for _ in range(5):
        two_hubs.notify()

    assert done.wait(timeout=5)
    time.sleep(0.2)
    assert heard == [1]


def test_a_change_during_the_announcement_brings_one_more_round(two_hubs, monkeypatch):
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.05)
    heard = []
    second = threading.Event()

    def watcher():
        heard.append(1)
        if len(heard) == 1:
            two_hubs.notify()
        else:
            second.set()

    two_hubs.subscribe(watcher)
    two_hubs.notify()

    assert second.wait(timeout=5)
    time.sleep(0.2)
    assert heard == [1, 1]


def test_a_watcher_that_fails_does_not_stop_the_others(two_hubs, monkeypatch):
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.01)
    heard = threading.Event()

    def broken():
        raise RuntimeError("no window")

    two_hubs.subscribe(broken)
    two_hubs.subscribe(heard.set)
    two_hubs.notify()

    assert heard.wait(timeout=5)


def test_a_watcher_that_never_returns_holds_no_later_announcement(
    two_hubs, monkeypatch
):
    """A window whose script call never answers, as WebView2's can after the
    machine slept: the next change still reaches it, and every other
    watcher, on threads of their own."""
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.01)
    monkeypatch.setattr(resident_module, "ANNOUNCE_WATCHER_WAIT_S", 0.05)
    held = threading.Event()
    calls = []
    other = []

    def stuck():
        calls.append(1)
        if len(calls) == 1:
            held.wait(timeout=10)

    two_hubs.subscribe(stuck)
    two_hubs.subscribe(lambda: other.append(1))
    two_hubs.notify()
    wait_until(lambda: other == [1])
    two_hubs.notify()
    wait_until(lambda: other == [1, 1])

    assert other == [1, 1]
    assert calls == [1, 1]
    held.set()


def test_a_watcher_held_too_often_is_skipped_until_it_returns(two_hubs, monkeypatch):
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.01)
    monkeypatch.setattr(resident_module, "ANNOUNCE_WATCHER_WAIT_S", 0.01)
    monkeypatch.setattr(resident_module, "ANNOUNCE_WATCHER_HELD_MAX", 2)
    held = threading.Event()
    calls = []

    def stuck():
        calls.append(1)
        held.wait(timeout=10)

    two_hubs.subscribe(stuck)
    for _ in range(4):
        two_hubs.notify()
        time.sleep(0.1)

    assert calls == [1, 1]
    held.set()
    wait_until(lambda: two_hubs._held_watchers[id(stuck)] == 0)
    two_hubs.notify()
    wait_until(lambda: len(calls) == 3)
    assert len(calls) == 3


def test_the_resident_forwards_a_sessions_changes_to_the_watchers(
    two_hubs, transport, monkeypatch
):
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.01)
    heard = threading.Event()
    two_hubs.subscribe(heard.set)

    up(transport, "c1", HOME_URL, HOME_WELCOME)

    assert heard.wait(timeout=5)


# --- the virtual networks and the joins ---

EASYTIER_OVERLAY = {
    "provider": "easytier",
    "network_name": "home",
    "network_secret": "s3cret",  # scan: allow
    "peer": "tcp://203.0.113.7:11010",
}


class FakeOverlayDriver:
    """An overlay driver that remembers every step and answers a set status."""

    provider = "easytier"

    def __init__(self):
        self.steps = []
        self.is_on = False
        self.peers = []

    def status(self, material):
        return {
            "is_on": self.is_on,
            "is_other_network": False,
            "address": "10.144.144.5" if self.is_on else "",
            "is_hub_seen": self.is_on,
            "peers": list(self.peers) if self.is_on else [],
        }

    def join(self, material, hostname):
        self.steps.append(("join", material["network_name"]))
        self.is_on = True

    def leave(self, material):
        self.steps.append(("leave", material["network_name"]))
        self.is_on = False


@pytest.fixture
def overlay_resident(config_path, transport):
    bind(
        config_path,
        bindings=[dict(BINDING, gateway_url=HOME_URL, overlays=[EASYTIER_OVERLAY])],
    )
    driver = FakeOverlayDriver()
    resident = ClientResident(
        log=discard,
        platform=FakeClientPlatform(),
        overlay_drivers={"easytier": driver, "netbird": FakeOverlayDriver()},
        transport=transport,
    )
    yield resident, driver
    resident.shutdown()


@pytest.fixture
def joining_resident(config_path, transport):
    driver = FakeOverlayDriver()
    resident = ClientResident(
        log=discard,
        platform=FakeClientPlatform(),
        overlay_drivers={"easytier": driver, "netbird": FakeOverlayDriver()},
        transport=transport,
    )
    resident.connect(
        link_for(
            {
                "urls": [HOME_URL, "tcp://10.144.144.1:8443"],
                "token": "ticket-1",
                "key": HUB_KEY,
                "overlays": [EASYTIER_OVERLAY],
            }
        )
    )
    yield resident, driver
    resident.shutdown()


def test_a_join_shows_its_row_at_once_connecting_with_its_network(joining_resident):
    resident, _driver = joining_resident

    (row,) = resident.hubs()

    assert (row["connection"], row["is_pending"]) == ("connecting", True)
    assert (row["wait_reason"], row["next_round_at"]) == ("", None)
    assert row["gateway_url"] == HOME_URL
    assert row["binding_id"].startswith("pending_")
    assert "ticket-1" not in json.dumps(resident.hubs())
    assert row["overlay"]["networks"] == [{"provider": "easytier", "network": "home"}]
    assert row["overlay"]["state"] == "off"
    assert resident.connect_overlay(row["binding_id"]) == {}


def test_a_join_is_spent_through_the_transport_under_the_pending_id(
    joining_resident, transport
):
    resident, _driver = joining_resident
    (session,) = sessions_of(resident).values()
    pending_id = session.binding_id
    transport.answers["join"] = functools.partial(dict, binding_id="c7", token="tok7")
    transport.listen_binding(session.label, session.take_line)

    session.run_once()
    session.run_once()

    (join,) = transport.commands_of("join")
    assert join["binding"] == pending_id
    assert join["ticket"] == "ticket-1"
    assert join["hub_key"] == HUB_KEY
    (dial,) = transport.commands_of("dial")
    assert dial["binding"] == "c7"
    assert dial["psk"] == hashlib.sha256(b"tok7").hexdigest()
    assert [binding["id"] for binding in enrollment.bindings()] == ["c7"]
    assert resident.hubs()[0]["binding_id"] == "c7"
    assert "c7" in transport.listeners and pending_id not in transport.listeners


def test_a_completed_join_keeps_the_session_and_its_network(joining_resident):
    resident, _driver = joining_resident
    (session,) = sessions_of(resident).values()
    pending_id = session.binding_id
    assert resident.connect_overlay(pending_id) == {}
    wait_until(lambda: resident.hubs()[0]["overlay"]["state"] == "on")
    completed = enrollment.joined_binding(session.binding(), "c7", "tok7")

    resident._hub_joined(session, completed)
    resident._reconcile_bindings(enrollment.config_stamp())

    assert list(sessions_of(resident).values()) == [session]
    (row,) = resident.hubs()
    assert (row["binding_id"], row["is_pending"]) == ("c7", False)
    assert row["overlay"]["state"] == "on"
    assert [binding["id"] for binding in enrollment.bindings()] == ["c7"]


def told_left(transport) -> list:
    """The binding of every leave the hub was told of, in order."""
    return [fields["binding"] for fields in transport.commands_of("leave")]


@pytest.fixture
def rejoining(config_path, transport):
    """The home hub's binding c1, the exit, and a join of the home hub beside it."""
    bind(config_path, url=HOME_URL)
    enrollment.set_exit_hub_id("h1")
    lines = []
    resident = ClientResident(
        log=lines.append,
        platform=FakeClientPlatform(),
        overlay_drivers={
            "easytier": FakeOverlayDriver(),
            "netbird": FakeOverlayDriver(),
        },
        start_thread=run_inline,
        transport=transport,
    )
    resident.connect(
        link_for({"urls": [HOME_URL], "token": "ticket-2", "key": HUB_KEY})
    )
    listen(resident, transport)
    yield resident, lines
    resident.shutdown()


def test_a_join_landing_on_the_binding_held_here_ends_it_and_tells_no_hub(
    rejoining, transport
):
    """The hub lands a machine joining again on its row: the old binding gives way."""
    resident, _lines = rejoining
    _held, joining = sessions_of(resident).values()
    completed = dict(
        joining.binding(), id="c1", token="fresh", ticket="", is_pending=False
    )

    resident._hub_joined(joining, completed)

    assert list(sessions_of(resident).values()) == [joining]
    (row,) = resident.hubs()
    assert (row["binding_id"], row["hub_id"], row["hub_name"]) == ("c1", "h1", "home")
    assert row["connection"] == "connecting"
    assert resident.exit_hub_id() == "h1"
    stored = [(binding["id"], binding["token"]) for binding in enrollment.bindings()]
    assert stored == [("c1", "fresh")]
    assert told_left(transport) == []


def test_a_join_given_a_new_id_ends_the_binding_its_welcome_names_and_tells_the_hub(
    rejoining, transport
):
    resident, _lines = rejoining
    held, joining = sessions_of(resident).values()
    transport.answers["join"] = functools.partial(dict, binding_id="c9", token="fresh")

    joining.run_once()
    up(transport, "c9", HOME_URL, HOME_WELCOME, HOME_STATE)

    assert list(sessions_of(resident).values()) == [joining]
    (row,) = resident.hubs()
    assert (row["binding_id"], row["hub_id"], row["hub_name"]) == ("c9", "h1", "home")
    assert row["connection"] == "connected"
    assert resident.exit_hub_id() == "h1"
    assert [binding["id"] for binding in enrollment.bindings()] == ["c9"]
    assert told_left(transport) == ["c1"]
    assert held.connection() != "connected"


def test_a_binding_the_hub_forgot_ends_at_the_welcome_whatever_the_leave_answers(
    rejoining, transport
):
    resident, lines = rejoining
    transport.answers["leave"] = functools.partial(
        dict, code="binding_unknown", params={}
    )
    transport.answers["join"] = functools.partial(dict, binding_id="c9", token="fresh")
    held, joining = sessions_of(resident).values()
    held._unbind({"code": "binding_unknown", "params": {}})
    assert resident.hubs()[0]["wait_reason"] == "unknown_device"

    joining.run_once()
    up(transport, "c9", HOME_URL, HOME_WELCOME, HOME_STATE)

    assert [row["binding_id"] for row in resident.hubs()] == ["c9"]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c9"]
    assert told_left(transport) == ["c1"]
    assert any("could not tell the hub we are leaving" in line for line in lines)


def test_a_start_with_two_bindings_for_one_hub_keeps_the_one_joined_last(
    config_path, transport
):
    bind(
        config_path,
        bindings=[
            dict(BINDING, gateway_url=HOME_URL),
            dict(OFFICE_BINDING),
            dict(BINDING, id="c3", token="tok3", gateway_url=HOME_URL),
        ],
    )
    transport.answers["leave"] = functools.partial(
        dict, code="binding_unknown", params={}
    )

    resident = ClientResident(
        log=discard,
        platform=FakeClientPlatform(),
        start_thread=run_inline,
        transport=transport,
    )

    assert [row["binding_id"] for row in resident.hubs()] == ["c2", "c3"]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c2", "c3"]
    assert told_left(transport) == ["c1"]
    resident.shutdown()


def test_leaving_a_pending_join_tells_no_hub(joining_resident, transport):
    resident, _driver = joining_resident
    (row,) = resident.hubs()

    resident.disconnect(row["binding_id"])

    assert resident.hubs() == [] and enrollment.bindings() == []
    time.sleep(0.05)
    assert told_left(transport) == []


def test_a_hub_row_carries_its_networks_row_and_no_secret(overlay_resident):
    resident, _driver = overlay_resident
    resident._overlay.refresh_bindings()

    (row,) = resident.hubs()

    assert row["overlay"]["network"] == "easytier"
    assert row["overlay"]["networks"] == [{"provider": "easytier", "network": "home"}]
    assert row["overlay"]["state"] == "off"
    assert row["jobs"]["overlay_job"] == ""
    assert "s3cret" not in json.dumps(row)  # scan: allow


def test_connect_and_disconnect_reach_the_hubs_network(overlay_resident):
    resident, driver = overlay_resident

    assert resident.connect_overlay("h1") == {}
    wait_until(lambda: resident.hubs()[0]["overlay"]["state"] == "on")
    assert driver.steps == [("join", "home")]
    assert resident.hubs()[0]["overlay"]["address"] == "10.144.144.5"
    wait_until(lambda: enrollment.bindings()[0]["is_overlay_on"] is True)
    assert enrollment.bindings()[0]["is_overlay_on"] is True

    assert resident.disconnect_overlay("c1") == {}
    wait_until(lambda: resident.hubs()[0]["overlay"]["state"] == "off")
    assert driver.steps[-1] == ("leave", "home")
    wait_until(lambda: enrollment.bindings()[0]["is_overlay_on"] is False)
    assert enrollment.bindings()[0]["is_overlay_on"] is False


def test_a_second_connect_while_one_runs_is_dropped_and_never_busy(
    overlay_resident,
):
    resident, driver = overlay_resident
    held = []
    resident._overlay._start_thread = held.append

    assert resident.connect_overlay("h1") == {}
    assert resident.hubs()[0]["jobs"]["overlay_job"] == "connecting"
    assert resident.connect_overlay("h1") == {}

    assert len(held) == 1
    held[0]()
    assert driver.steps == [("join", "home")]


def test_a_cancel_reaches_a_connect_in_progress(overlay_resident):
    resident, driver = overlay_resident
    held = []
    resident._overlay._start_thread = held.append
    resident.connect_overlay("h1")

    assert resident.cancel_overlay("h1") == {}
    assert resident.hubs()[0]["jobs"]["overlay_job"] == "disconnecting"
    held[1]()

    assert resident.hubs()[0]["overlay"]["state"] == "off"
    assert ("leave", "home") in driver.steps


def test_a_pick_keeps_the_provider_on_the_binding(overlay_resident):
    resident, _driver = overlay_resident

    assert resident.pick_overlay("h1", "easytier") == {}
    assert resident.pick_overlay("h1", "netbird") == {}
    assert resident.pick_overlay("h9", "easytier")["code"] == "unknown_hub"

    assert enrollment.bindings()[0]["overlay_pick"] == "easytier"


def test_a_network_that_turns_on_or_off_names_its_hub_address_to_the_session(
    overlay_resident,
):
    resident, _driver = overlay_resident
    session = resident._sessions["c1"]
    routes = []
    session.set_overlay_route = functools.partial(_note_route, routes)

    resident._overlay_route("h1", "10.144.144.1", "easytier")
    resident._overlay_route("c1", "", "")

    assert routes == [("10.144.144.1", "easytier"), ("", "")]


def _note_route(seen, host, provider) -> None:
    seen.append((host, provider))


def test_a_peer_list_change_on_a_network_that_is_on_starts_a_round(
    overlay_resident,
):
    resident, driver = overlay_resident
    session = resident._sessions["c1"]
    before = set(threading.enumerate())
    assert resident.connect_overlay("h1") == {}
    # The step names the route after the state reads on.
    for step in set(threading.enumerate()) - before:
        step.join(timeout=5)
    changes = []
    session.change_network = functools.partial(changes.append, "change")

    resident._overlay.watch()
    assert changes == []

    driver.peers = ["10.144.144.1"]
    resident._overlay.watch()

    assert changes == ["change"]


def test_a_press_on_the_network_of_a_hub_nobody_joined_is_unknown_hub(
    overlay_resident,
):
    resident, _driver = overlay_resident

    for press in (
        resident.connect_overlay,
        resident.cancel_overlay,
        resident.disconnect_overlay,
    ):
        assert press("h9") == {"code": "unknown_hub", "params": {"hub_id": "h9"}}


def test_leaving_a_hub_leaves_its_network_when_no_other_hub_names_it(
    overlay_resident,
):
    resident, driver = overlay_resident
    resident.connect_overlay("h1")
    wait_until(lambda: resident.hubs()[0]["overlay"]["state"] == "on")

    resident.disconnect("h1")

    wait_until(lambda: len(driver.steps) == 2)
    assert driver.steps == [("join", "home"), ("leave", "home")]


def test_a_connect_ending_after_the_shutdown_writes_no_binding(
    overlay_resident, config_path
):
    resident, driver = overlay_resident
    is_asked = threading.Event()
    may_answer = threading.Event()
    answer_status = driver.status

    def held_status(material):
        is_asked.set()
        may_answer.wait(timeout=5)
        return answer_status(material)

    driver.status = held_status
    before = set(threading.enumerate())
    resident.connect_overlay("h1")
    assert is_asked.wait(timeout=5)
    steps = set(threading.enumerate()) - before

    resident.shutdown()
    written = config_path.read_bytes()
    may_answer.set()
    for step in steps:
        step.join(timeout=5)

    assert resident.hubs()[0]["overlay"]["state"] == "on"
    assert config_path.read_bytes() == written


def test_a_shutdown_ends_a_rewrite_of_the_ssh_configuration(tmp_path, overlay_resident):
    resident, _driver = overlay_resident
    started = []
    resident._ssh._start_thread = started.append
    machine = {
        "entries": [
            {
                "id": "ssh_server_d1_lab",
                "hub_id": "h1",
                "app_id": "ssh_server_d1",
                "device_id": "d1",
                "device_name": "lab",
                "type": "ssh",
                "payload": {"account": "lab"},
            }
        ],
        "apps": [],
        "hub_names": {},
    }

    resident._ssh.refresh(**machine)
    resident.shutdown()
    for rewrite in started:
        rewrite()

    assert started
    assert not (tmp_path / "home" / ".ssh").exists()


# --- the terminals ---


def test_the_terminals_of_every_hub_are_stamped_with_it(two_hubs_up):
    resident, transport = two_hubs_up
    lepton = {
        "device_id": "d1",
        "name": "lepton",
        "is_online": True,
        "accounts": ["alice", "lab"],
        "sessions": [
            {
                "session_id": "s1",
                "owner": "hub",
                "is_owned": False,
                "is_shared": True,
                "attached_count": 1,
            }
        ],
    }
    transport.deliver("c1", {"frame": dict(HOME_STATE, terminals=[lepton])})

    assert resident.terminal_entries() == [
        {
            "device_id": "d1",
            "name": "lepton",
            "is_online": True,
            "accounts": ["alice", "lab"],
            "hub_id": "h1",
        }
    ]
    (row,) = resident.terminal_sessions()
    assert (row["hub_id"], row["device_id"], row["owner"], row["is_shared"]) == (
        "h1",
        "d1",
        "hub",
        True,
    )


def offered(resident) -> None:
    """The home hub offers a terminal on lepton and on muon."""
    lepton = {"device_id": "d1", "name": "lepton", "is_online": True}
    muon = {"device_id": "d2", "name": "muon", "is_online": True}
    resident._sessions["c1"]._take_state(dict(HOME_STATE, terminals=[lepton, muon]))


def opened(transport, kind: str) -> list:
    """The open record of every stream of one kind, with its binding."""
    return [
        (binding, record)
        for binding, record in transport.opens
        if record.get("kind") == kind
    ]


def test_a_terminal_opens_a_shell_stream_with_its_size_and_account(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)

    outcome = resident.open_terminal("h1", "d1", 120, 40, account="lab")

    assert opened(transport, "shell") == [
        (
            "c1",
            {
                "kind": "shell",
                "device_id": "d1",
                "cols": 120,
                "rows": 40,
                "account": "lab",
                "session_id": outcome["session_id"],
            },
        )
    ]
    assert str(uuid.UUID(outcome["session_id"])) == outcome["session_id"]
    assert resident.has_terminal(outcome["terminal_id"])


def test_every_new_terminal_is_a_new_session(two_hubs_up):
    resident, _transport = two_hubs_up
    offered(resident)

    first = resident.open_terminal("h1", "d1", 80, 24)
    second = resident.open_terminal("h1", "d1", 80, 24)

    assert first["session_id"] != second["session_id"]


def test_a_kept_session_is_attached_to_again_by_its_id(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)

    outcome = resident.open_window_terminal("h1", "d1", 80, 24, "kept-1")

    ((_binding, record),) = opened(transport, "shell")
    assert (record["session_id"], record["is_resumed"]) == ("kept-1", True)
    assert outcome["session_id"] == "kept-1"


def test_a_window_terminal_runs_as_the_account_picked(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)

    resident.open_window_terminal("h1", "d1", 80, 24, account="lab")

    ((_binding, record),) = opened(transport, "shell")
    assert record["account"] == "lab"


def test_a_resize_goes_to_the_shell_as_a_record(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)
    terminal_id = resident.open_terminal("h1", "d1", 80, 24)["terminal_id"]
    (stream,) = transport.stream_factory.made

    assert resident.resize_terminal(terminal_id, 132, 50) == {}
    stream.end({"exit_code": 0})

    assert stream.records == [("resize", 132, 50)]
    assert resident.resize_terminal(terminal_id, 80, 24) == {
        "code": "shell_unknown",
        "params": {"shell": terminal_id},
    }
    assert resident.resize_terminal("nobody", 80, 24)["code"] == "unknown_terminal"


def test_persist_names_the_terminals_session_and_stop_names_the_hub(two_hubs_up):
    resident, _transport = two_hubs_up
    offered(resident)
    outcome = resident.open_terminal("h1", "d1", 80, 24)
    session = resident._sessions["c1"]
    asked = []

    def persist(session_id, is_persistent, is_shared):
        asked.append(("persist", session_id, is_persistent, is_shared))

    def stop(session_id):
        asked.append(("stop", session_id))
        raise GatewayRefusedDetail(
            code="session_unknown", params={"session_id": session_id}
        )

    session.persist_shell = persist
    session.stop_shell_session = stop

    assert resident.persist_terminal(outcome["terminal_id"], True, True) == {}
    assert (
        resident.persist_terminal("nobody", True, False)["code"] == "unknown_terminal"
    )
    assert resident.stop_terminal_session("h1", "kept-9") == {
        "code": "session_unknown",
        "params": {"session_id": "kept-9"},
    }
    assert resident.stop_terminal_session("h9", "kept-9")["code"] == "unknown_hub"
    assert asked == [
        ("persist", outcome["session_id"], True, True),
        ("stop", "kept-9"),
    ]


def test_persist_and_stop_go_to_the_hub_as_frames_answered_by_replies(two_hubs_up):
    resident, transport = two_hubs_up
    answering(transport, functools.partial(dict, params={}))

    assert resident.persist_terminal_session("h1", "kept-1", is_shared=True) == {}
    assert resident.stop_terminal_session("h1", "kept-1") == {}

    persist = transport.frames_of("persist")[0]
    assert (persist["session_id"], persist["is_shared"]) == ("kept-1", True)
    assert "is_persistent" not in persist
    assert transport.frames_of("stop_session")[0]["session_id"] == "kept-1"


def test_a_new_shared_terminal_says_so_and_a_resumed_one_does_not(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)

    resident.open_terminal("h1", "d1", 80, 24, is_shared=True)
    resident.open_terminal("h1", "d1", 80, 24, "kept-1", is_shared=True)

    shells = [record for _binding, record in opened(transport, "shell")]
    assert [record.get("is_shared") for record in shells] == [True, None]


def test_a_machine_the_hub_does_not_offer_opens_no_shell(two_hubs_up):
    resident, _transport = two_hubs_up
    offered(resident)

    assert resident.open_terminal("h1", "d9", 80, 24) == {
        "code": "unknown_terminal",
        "params": {"device_id": "d9"},
    }


def test_an_exec_opens_on_a_machine_the_hub_offers(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)

    outcome = resident.open_exec("h1", "d2", ["uptime"], False, 80, 24, "lab")

    assert opened(transport, "exec") == [
        (
            "c1",
            {
                "kind": "exec",
                "device_id": "d2",
                "argv": ["uptime"],
                "is_tty": False,
                "cols": 80,
                "rows": 24,
                "account": "lab",
            },
        )
    ]
    assert resident.has_terminal(outcome["terminal_id"])


def test_an_exec_on_a_machine_the_hub_does_not_offer_opens_nothing(two_hubs_up):
    resident, _transport = two_hubs_up
    offered(resident)
    resident._sessions["c1"]._take_state(
        dict(
            HOME_STATE,
            terminals=[{"device_id": "d1", "name": "lepton", "is_online": True}],
        )
    )

    assert resident.open_exec("h1", "d2", ["ls"], False, 80, 24) == {
        "code": "unknown_terminal",
        "params": {"device_id": "d2"},
    }
    assert resident.open_exec("h9", "d1", ["ls"], False, 80, 24)["code"] == (
        "unknown_hub"
    )


def test_an_execs_pieces_carry_its_input_its_eof_and_its_two_outputs(two_hubs_up):
    from neutrino_client.core.terminal import encode_piece, read_piece

    resident, transport = two_hubs_up
    offered(resident)
    terminal_id = resident.open_exec("h1", "d2", ["cat"], False, 80, 24)["terminal_id"]
    (stream,) = transport.stream_factory.made
    typed = io.BytesIO(encode_piece(b"hi\n") + encode_piece(b""))
    is_ended = threading.Event()

    def read(size):
        data = typed.read(size)
        if not data:
            is_ended.wait(timeout=5)
        return data

    typing = threading.Thread(target=resident.attach_terminal, args=(terminal_id, read))
    typing.start()
    wait_until(lambda: ("eof",) in stream.records)
    stream.push(b"\x01hi\n")
    stream.push(b"\x02warn")
    stream.end({"exit_code": 4})
    is_ended.set()
    typing.join(timeout=5)
    shown = io.BytesIO()
    resident.terminal_output(terminal_id, shown.write)

    assert stream.records.index(("data", b"hi\n")) < stream.records.index(("eof",))
    assert ("close",) not in stream.records
    shown.seek(0)
    assert [read_piece(shown.read), read_piece(shown.read)] == [
        b"\x01hi\n",
        b"\x02warn",
    ]
    assert resident.terminal_result(terminal_id) == {"exit_code": 4}


def test_persist_by_session_id_names_only_the_flag_given(two_hubs_up):
    resident, _transport = two_hubs_up
    offered(resident)
    session = resident._sessions["c1"]
    asked = []

    def persist(session_id, is_persistent, is_shared):
        asked.append((session_id, is_persistent, is_shared))

    session.persist_shell = persist

    assert resident.persist_terminal_session("h1", "kept-1", is_shared=True) == {}
    assert resident.persist_terminal_session("h9", "kept-1", True)["code"] == (
        "unknown_hub"
    )
    assert asked == [("kept-1", None, True)]


def test_a_machine_the_hub_does_not_offer_opens_nothing(two_hubs_up):
    resident, _transport = two_hubs_up

    assert resident.open_terminal("h1", "d9", 80, 24) == {
        "code": "unknown_terminal",
        "params": {"device_id": "d9"},
    }
    assert resident.open_terminal("h9", "d1", 80, 24)["code"] == "unknown_hub"


def test_the_result_is_asked_once_after_the_shell_ended(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)
    terminal_id = resident.open_terminal("h1", "d1", 80, 24)["terminal_id"]
    (stream,) = transport.stream_factory.made
    stream.end({"exit_code": 0})

    assert resident.terminal_result(terminal_id) == {"exit_code": 0}
    assert resident.terminal_result(terminal_id)["code"] == "unknown_terminal"


def test_a_refused_shell_says_why(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)
    terminal_id = resident.open_terminal("h1", "d1", 80, 24)["terminal_id"]
    (stream,) = transport.stream_factory.made
    stream.end({"account": "root"}, code="account_not_enabled")

    assert resident.terminal_result(terminal_id) == {
        "code": "account_not_enabled",
        "params": {"account": "root"},
    }


def test_the_windows_terminal_pushes_its_output_then_its_end(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)
    pieces = []
    resident.on_terminal_output = pieces.append

    terminal_id = resident.open_window_terminal("h1", "d1", 80, 24)["terminal_id"]
    (stream,) = transport.stream_factory.made
    stream.push(b"$ ")
    stream.end({"exit_code": 0})

    wait_until(lambda: len(pieces) == 2)
    assert pieces == [
        {"id": terminal_id, "data": b"$ "},
        {"id": terminal_id, "end": {"exit_code": 0}},
    ]
    assert not resident.has_terminal(terminal_id)


def test_the_windows_keys_and_close_reach_the_shell(two_hubs_up):
    resident, transport = two_hubs_up
    offered(resident)
    terminal_id = resident.open_window_terminal("h1", "d1", 80, 24)["terminal_id"]
    (stream,) = transport.stream_factory.made

    assert resident.terminal_input(terminal_id, b"ls\r") == {}
    assert resident.close_terminal(terminal_id) == {}

    assert stream.records == [("data", b"ls\r"), ("close",)]
    assert resident.terminal_input(terminal_id, b"x")["code"] == "unknown_terminal"
    assert resident.close_terminal(terminal_id)["code"] == "unknown_terminal"


def test_a_machine_the_hub_does_not_offer_opens_no_window_terminal(two_hubs_up):
    resident, _transport = two_hubs_up

    assert resident.open_window_terminal("h1", "d9", 80, 24)["code"] == (
        "unknown_terminal"
    )


# --- ssh for other programs ---

SSH_ENTRY = {
    "id": "ssh_server_d1_lab",
    "type": "ssh",
    "title": "SSH (lab)",
    "payload": {
        "host": "192.168.1.5",
        "port": 22001,
        "account": "lab",
        "host_key_fingerprint": "SHA256:x",
    },
    "is_healthy": True,
    "source": "module",
    "device_id": "d1",
    "device_name": "lab-gpu",
    "app_id": "ssh_server_d1",
    "name": "lab",
    "local_port": 24001,
}


def test_an_ssh_proxy_carries_its_bytes_on_a_connect_stream_raw(two_hubs_up):
    resident, transport = two_hubs_up
    transport.deliver("c1", {"frame": dict(HOME_STATE, services=[SSH_ENTRY])})

    outcome = resident.open_ssh_proxy("h1", "ssh_server_d1_lab")
    (stream,) = transport.stream_factory.made
    stream.push(b"SSH-2.0-server\r\n")
    stream.end()
    shown = io.BytesIO()
    resident.terminal_output(outcome["terminal_id"], shown.write)

    assert opened(transport, "connect") == [
        ("c1", {"kind": "connect", "id": "ssh_server_d1_lab"})
    ]
    assert shown.getvalue() == b"SSH-2.0-server\r\n"
    assert resident.terminal_result(outcome["terminal_id"]) == {"exit_code": None}


def test_an_ssh_entry_is_forwarded_at_its_local_port_while_its_hub_lists_it(
    two_hubs_up,
):
    resident, transport = two_hubs_up
    port = free_port()
    shell = dict(SSH_ENTRY, local_port=port)

    transport.deliver("c1", {"frame": dict(HOME_STATE, hash="sh", services=[shell])})
    transport.deliver("c1", {"frame": dict(HOME_STATE, hash="si", services=[shell])})

    assert transport.commands_of("forward_start") == [
        {
            "binding": "c1",
            "listen": f"127.0.0.1:{port}",
            "protocol": "tcp",
            "open": {"kind": "connect", "id": "ssh_server_d1_lab"},
        }
    ]
    row = entry(resident, "h1", "ssh_server_d1_lab")
    assert (row["local_port"], row["forward"], row["last_error"]) == (port, port, None)

    transport.deliver("c1", {"frame": dict(HOME_STATE, hash="sj", services=[])})

    assert transport.commands_of("forward_stop") == [
        {"listen": f"127.0.0.1:{port}", "protocol": "tcp"}
    ]
    assert resident._forwards.forwards() == {}


def test_an_ssh_entry_whose_port_is_taken_says_so_on_its_row(two_hubs_up):
    resident, transport = two_hubs_up
    holder = socket.create_server(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        shell = dict(SSH_ENTRY, local_port=port)
        transport.deliver(
            "c1", {"frame": dict(HOME_STATE, hash="sh", services=[shell])}
        )
    finally:
        holder.close()

    assert transport.commands_of("forward_start") == []
    assert entry(resident, "h1", "ssh_server_d1_lab")["last_error"] == {
        "code": "port_taken",
        "params": {"port": port},
    }


def test_the_ssh_servers_row_is_in_the_document_and_use_forwards_none_of_it(
    two_hubs_up,
):
    resident, transport = two_hubs_up
    port = free_port()
    ssh_server = {
        "id": "ssh_server_d1",
        "title": "SSH",
        "source": "module",
        "device_id": "d1",
        "device_name": "lab-gpu",
        "local_name": "ssh.lab-gpu.localhost",
    }
    transport.deliver(
        "c1",
        {
            "frame": dict(
                HOME_STATE,
                hash="sh",
                services=[dict(SSH_ENTRY, local_port=port)],
                apps=[ssh_server],
            )
        },
    )

    assert resident.open_app("h1", "ssh_server_d1") == {}
    assert len(transport.commands_of("forward_start")) == 1
    assert resident.app_rows()[0]["is_in_use"] is False


def test_an_ssh_proxy_names_an_ssh_entry_of_a_hub_joined(two_hubs_up):
    resident, transport = two_hubs_up

    assert resident.open_ssh_proxy("h1", "svc_tcp") == {
        "code": "service_unknown",
        "params": {"service_id": "svc_tcp"},
    }
    assert resident.open_ssh_proxy("h9", "x")["code"] == "unknown_hub"
    assert transport.opens == []


# --- the jobs in the state document ---


class SlowHandler(ServiceTypeHandler):
    """A desktop handler whose action waits until the test lets it finish.

    Attributes:
        acted: Every body it was handed.
        answer: What the action ends with.
    """

    service_type = "rdp"

    def __init__(self):
        self.acted = []
        self.answer = {}
        self.release_it = threading.Event()

    def act(self, *, entries, body):
        self.acted.append(dict(body))
        self.release_it.wait(timeout=5)
        return dict(self.answer)

    def release_hub(self, hub_id: str):
        return 0


def entry(resident, hub_id: str, entry_id: str) -> dict:
    return next(
        row
        for row in resident.entry_rows()
        if row["hub_id"] == hub_id and row["id"] == entry_id
    )


def test_a_press_writes_its_job_before_the_work_and_clears_it_after(two_hubs_up):
    resident, _transport = two_hubs_up
    handler = SlowHandler()
    resident._services["rdp"] = handler
    held = []
    resident._start_thread = held.append

    assert resident.service_action("rdp", {"hub_id": "h1", "id": "rdp_s9"}) == {}
    assert entry(resident, "h1", "rdp_s9")["job"] == "connecting"
    assert handler.acted == []

    handler.release_it.set()
    held[0]()
    assert entry(resident, "h1", "rdp_s9")["job"] == ""
    assert entry(resident, "h1", "rdp_s9")["last_error"] is None


def test_a_second_press_while_the_job_runs_is_dropped(two_hubs_up):
    resident, _transport = two_hubs_up
    handler = SlowHandler()
    resident._services["rdp"] = handler
    held = []
    resident._start_thread = held.append
    body = {"hub_id": "h1", "id": "rdp_s9"}

    resident.service_action("rdp", body)
    assert resident.service_action("rdp", body) == {}

    assert len(held) == 1


def test_a_failed_job_is_the_entrys_error_until_a_refresh(two_hubs_up):
    resident, _transport = two_hubs_up
    handler = SlowHandler()
    handler.answer = {"code": "forward_failed", "params": {"detail": "in use"}}
    handler.release_it.set()
    resident._services["rdp"] = handler

    resident.service_action("rdp", {"hub_id": "h1", "id": "rdp_s9"})

    assert entry(resident, "h1", "rdp_s9")["last_error"] == {
        "code": "forward_failed",
        "params": {"detail": "in use"},
    }
    resident.refresh()
    assert entry(resident, "h1", "rdp_s9")["last_error"] is None


def test_a_lane_that_answers_busy_never_reaches_the_page(two_hubs_up):
    resident, _transport = two_hubs_up
    handler = SlowHandler()
    handler.answer = {"code": "busy", "params": {"step": "switching"}}
    handler.release_it.set()
    resident._services["rdp"] = handler

    assert resident.service_action("rdp", {"hub_id": "h1", "id": "rdp_s9"}) == {}
    assert entry(resident, "h1", "rdp_s9")["last_error"] is None


def test_a_mount_on_its_way_is_the_entrys_job(two_hubs_up):
    resident, _transport = two_hubs_up

    class Mounting(ServiceTypeHandler):
        service_type = "file"

        def state(self):
            return {
                "mounts": [
                    {
                        "record_id": "r1",
                        "hub_id": "h1",
                        "entry_id": "share_media",
                        "state": "queued",
                    }
                ]
            }

        def entry_fields(self, entry):
            return {}

    resident._services["file"] = Mounting()

    assert entry(resident, "h1", "share_media")["job"] == "mounting"


def test_a_file_entry_carries_its_default_place_and_whose_login_mounts_it(
    two_hubs_up, tmp_path
):
    resident, _transport = two_hubs_up

    row = entry(resident, "h1", "share_media")

    assert row["mount_default"] == str(tmp_path / "home" / "remote" / "hub-media")
    assert row["is_declared"] is False
    assert (row["local_port"], row["forward"]) == ("auto", None)


def test_a_refresh_sets_each_hub_refreshing_and_clears_its_errors(two_hubs_up):
    resident, transport = two_hubs_up
    resident._panel_errors["c1"] = {"code": "web_token_missing", "params": {}}

    resident.refresh()

    assert [row["jobs"]["is_refreshing"] for row in resident.hubs()] == [True, True]
    assert resident.hubs()[0]["last_error"] is None
    refreshed = [
        binding
        for binding, frame in transport.frames
        if frame["type"] == "report" and frame.get("is_refresh")
    ]
    assert refreshed == ["c1", "c2"]

    transport.deliver("c1", {"frame": dict(HOME_STATE, hash="s9")})
    assert [row["jobs"]["is_refreshing"] for row in resident.hubs()] == [False, True]


def test_a_refresh_while_a_hub_refreshes_is_dropped(two_hubs_up):
    resident, transport = two_hubs_up
    resident.refresh()
    sent = len(transport.frames)

    resident.refresh()

    assert len(transport.frames) == sent


def test_a_disabled_hub_does_not_refresh(two_hubs_up):
    resident, transport = two_hubs_up
    transport.deliver("c2", {"frame": dict(OFFICE_STATE, is_disabled=True)})

    resident.refresh()

    assert [row["jobs"]["is_refreshing"] for row in resident.hubs()] == [True, False]


def test_a_leave_is_shown_before_the_hub_is_left(two_hubs_up):
    resident, _transport = two_hubs_up
    held = []
    resident._start_thread = held.append

    resident.leave("h2")
    resident.leave("h2")

    assert len(held) == 1
    assert [row["jobs"]["is_leaving"] for row in resident.hubs()] == [False, True]
    held[0]()
    assert [row["hub_id"] for row in resident.hubs()] == ["h1"]


def test_leaving_a_hub_nobody_joined_is_a_key_error(two_hubs_up):
    resident, _transport = two_hubs_up

    with pytest.raises(KeyError):
        resident.leave("h9")


def test_a_forgotten_binding_keeps_its_row_and_leaves_no_notice(two_hubs_up):
    resident, transport = two_hubs_up
    office = resident._sessions["c2"]
    transport.deliver("c2", {"event": "session_end"})

    office._unbind({"code": "binding_unknown", "params": {}})

    assert resident.notices() == []
    assert [row["hub_id"] for row in resident.hubs()] == ["h1", "h2"]
    assert resident.hubs()[1]["wait_reason"] == "unknown_device"


def test_a_closed_notice_is_gone_and_a_refresh_drops_every_notice(two_hubs_up):
    resident, _transport = two_hubs_up
    resident._add_notice("binding_unknown", {"hub": "office"})
    resident._add_notice("binding_unknown", {"hub": "lab"})
    first, second = resident.notices()

    resident.close_notice(first["id"])

    assert resident.notices() == [second]
    resident.close_notice("nobody")
    assert resident.notices() == [second]

    resident.refresh()

    assert resident.notices() == []


def _unreachable(fields):
    raise GatewayUnreachable("cannot reach hub")


@pytest.mark.parametrize(
    "answer",
    [_unreachable, functools.partial(dict, code="binding_unknown", params={})],
    ids=["unreachable", "token_rejected"],
)
def test_a_leave_forgets_the_binding_and_the_row_whatever_the_hub_answers(
    two_hubs_up, answer
):
    resident, transport = two_hubs_up
    released_handlers(resident)
    seen = []

    def leave(fields):
        seen.append([binding["id"] for binding in enrollment.bindings()])
        return answer(fields)

    transport.answers["leave"] = leave

    resident.leave("h2")
    wait_until(lambda: seen)

    assert seen == [["c1"]]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1"]
    assert [row["hub_id"] for row in resident.hubs()] == ["h1"]
    assert all(row["jobs"]["is_leaving"] is False for row in resident.hubs())


def test_a_pending_binding_is_forgotten_and_no_hub_is_told(
    joining_resident, monkeypatch
):
    resident, _driver = joining_resident
    told = []
    monkeypatch.setattr(resident, "_tell_hub_left", told.append)
    (row,) = resident.hubs()

    resident.disconnect(row["binding_id"])

    assert resident.hubs() == []
    assert enrollment.bindings() == []
    assert told == []


def test_the_clipboard_is_written_through_the_platform(two_hubs):
    written = []
    two_hubs.platform.write_clipboard = written.append

    assert two_hubs.write_clipboard("ls -la") == {}
    assert written == ["ls -la"]


def test_a_clipboard_the_platform_cannot_write_is_a_code(two_hubs):
    def refuse(text):
        raise OSError("no display")

    two_hubs.platform.write_clipboard = refuse

    assert two_hubs.write_clipboard("x") == {
        "code": "clipboard_unwritable",
        "params": {"detail": "no display"},
    }


# --- the apps ---


def app_state(web_port: int, port_port: int, *, is_token_required=False) -> dict:
    """The home hub's state with one app of two entries and a declared share."""
    services = [
        {
            "id": "gitea_d1_web",
            "type": "web",
            "title": "Gitea",
            "payload": {
                "url": "http://192.168.1.5:3000/explore?tab=repos",
                "is_token_required": is_token_required,
            },
            "is_healthy": True,
            "source": "module",
            "device_id": "d1",
            "device_name": "lab",
            "app_id": "gitea_d1",
            "name": "web",
            "local_port": web_port,
        },
        {
            "id": "gitea_d1_ssh",
            "type": "port",
            "title": "Gitea",
            "payload": {"host": "192.168.1.5", "port": 2222, "protocol": "tcp"},
            "is_healthy": True,
            "source": "module",
            "device_id": "d1",
            "device_name": "lab",
            "app_id": "gitea_d1",
            "name": "ssh",
            "local_port": port_port,
        },
        {
            "id": "nas_file_media",
            "type": "file",
            "title": "media",
            "payload": {"protocol": "smb", "host": "192.168.1.9", "share": "media"},
            "is_healthy": True,
            "source": "declared",
            "device_id": "",
            "device_name": "",
            "app_id": "nas",
            "name": "file_media",
        },
    ]
    apps = [
        {
            "id": "gitea_d1",
            "title": "Gitea",
            "source": "module",
            "device_id": "d1",
            "device_name": "lab",
            "local_name": "gitea.lab.localhost",
        },
        {
            "id": "nas",
            "title": "NAS",
            "source": "declared",
            "device_id": "",
            "device_name": "",
            "local_name": "nas.nas.localhost",
        },
    ]
    return dict(HOME_STATE, hash="sa", services=services, apps=apps)


@pytest.fixture
def app_hub(two_hubs_up):
    """The home hub publishing Gitea's two entries at free fixed numbers."""
    resident, transport = two_hubs_up
    ports = (free_port(), free_port())
    transport.deliver("c1", {"frame": app_state(*ports)})
    return resident, transport, ports


def forward_starts(transport) -> list:
    return transport.commands_of("forward_start")


def test_an_app_row_is_listed_with_its_job_and_whether_it_is_in_use(app_hub):
    resident, _transport, _ports = app_hub

    rows = resident.app_rows()

    assert [row["id"] for row in rows] == ["gitea_d1", "nas"]
    assert rows[0] == {
        "id": "gitea_d1",
        "title": "Gitea",
        "source": "module",
        "device_id": "d1",
        "device_name": "lab",
        "local_name": "gitea.lab.localhost",
        "hub_id": "h1",
        "job": "",
        "last_error": None,
        "is_in_use": False,
    }


def test_an_app_entry_forwards_at_the_hubs_number_until_the_person_sets_one(app_hub):
    resident, _transport, (web_port, _port_port) = app_hub

    row = entry(resident, "h1", "gitea_d1_web")

    assert (row["local_port"], row["is_local_port_own"], row["forward"]) == (
        web_port,
        False,
        None,
    )


def test_use_forwards_every_entry_at_its_number_and_opens_nothing(app_hub):
    resident, transport, (web_port, port_port) = app_hub
    held = []
    resident._start_thread = held.append

    assert resident.open_app("h1", "gitea_d1") == {}
    assert resident.app_rows()[0]["job"] == "opening"
    held[0]()

    assert forward_starts(transport) == [
        {
            "binding": "c1",
            "listen": f"127.0.0.1:{web_port}",
            "protocol": "tcp",
            "open": {"kind": "connect", "id": "gitea_d1_web"},
        },
        {
            "binding": "c1",
            "listen": f"127.0.0.1:{port_port}",
            "protocol": "tcp",
            "open": {"kind": "connect", "id": "gitea_d1_ssh"},
        },
    ]
    assert resident.platform.opened_urls == []
    row = resident.app_rows()[0]
    assert (row["job"], row["last_error"], row["is_in_use"]) == ("", None, True)
    assert entry(resident, "h1", "gitea_d1_ssh")["forward"] == port_port


def test_an_app_is_not_in_use_while_its_use_runs(app_hub):
    resident, _transport, (web_port, _port_port) = app_hub
    held = []
    resident._start_thread = held.append
    resident.open_app("h1", "gitea_d1")
    resident._forwards.ensure(
        hub_id="h1", entry_id="gitea_d1_web", kind="web", own_port=web_port
    )

    assert resident.app_rows()[0]["is_in_use"] is False
    held[0]()
    assert resident.app_rows()[0]["is_in_use"] is True


def test_open_opens_the_first_page_of_an_app_in_use(app_hub):
    resident, _transport, (web_port, _port_port) = app_hub
    resident.open_app("h1", "gitea_d1")
    held = []
    resident._start_thread = held.append

    assert resident.open_app_page("h1", "gitea_d1") == {}
    assert resident.app_rows()[0]["job"] == "opening"
    assert resident.app_rows()[0]["is_in_use"] is True
    held[0]()

    assert resident.platform.opened_urls == [
        f"http://gitea.lab.localhost:{web_port}/explore?tab=repos"
    ]
    assert resident.app_rows()[0]["job"] == ""


def test_open_on_an_app_not_in_use_or_with_no_page_is_refused(two_hubs_up):
    resident, transport = two_hubs_up
    state = app_state(free_port(), free_port())
    transport.deliver("c1", {"frame": state})

    assert resident.open_app_page("h1", "gitea_d1") == {
        "code": "app_not_in_use",
        "params": {},
    }
    state["services"][0]["payload"]["url"] = "ssh://192.168.1.5"
    transport.deliver("c1", {"frame": dict(state, hash="state-2")})
    assert resident.open_app_page("h1", "gitea_d1") == {
        "code": "app_no_page",
        "params": {},
    }
    assert resident.platform.opened_urls == []


def test_an_app_entry_the_hub_gave_no_number_has_none_and_use_passes_it_by(
    two_hubs_up,
):
    resident, transport = two_hubs_up
    state = app_state(free_port(), free_port())
    del state["services"][1]["local_port"]
    transport.deliver("c1", {"frame": state})
    held = []
    resident._start_thread = held.append

    assert entry(resident, "h1", "gitea_d1_ssh")["local_port"] is None
    assert resident.open_app("h1", "gitea_d1") == {}
    held[0]()

    assert [line["open"]["id"] for line in forward_starts(transport)] == [
        "gitea_d1_web"
    ]
    assert resident.app_rows()[0]["last_error"] is None


def test_open_on_a_mac_opens_the_loopback(app_hub):
    resident, _transport, (web_port, _port_port) = app_hub
    resident.platform.os_name = "darwin"

    resident.open_app("h1", "gitea_d1")
    resident.open_app_page("h1", "gitea_d1")

    assert resident.platform.opened_urls == [
        f"http://127.0.0.1:{web_port}/explore?tab=repos"
    ]


def test_a_token_page_opens_with_the_token_its_service_reply_gives(two_hubs_up):
    resident, transport = two_hubs_up
    ports = (free_port(), free_port())
    transport.deliver("c1", {"frame": app_state(*ports, is_token_required=True)})
    asked = []

    def respond(frame):
        asked.append(frame.get("id"))
        return {"params": {"token": "t0k"}}

    answering(transport, respond)

    resident.open_app("h1", "gitea_d1")
    assert asked == []
    resident.open_app_page("h1", "gitea_d1")

    assert asked == ["gitea_d1_web"]
    assert resident.platform.opened_urls == [
        f"http://gitea.lab.localhost:{ports[0]}/explore?tab=repos&tkn=t0k"
    ]
    assert "t0k" not in json.dumps(resident.app_rows())


def test_a_number_another_program_holds_is_refused_and_the_other_forwards_stay(
    app_hub,
):
    resident, transport, (web_port, port_port) = app_hub
    held = socket.create_server(("127.0.0.1", port_port))
    try:
        resident.open_app("h1", "gitea_d1")
    finally:
        held.close()

    row = resident.app_rows()[0]
    assert row["last_error"] == {"code": "port_taken", "params": {"port": port_port}}
    assert row["is_in_use"] is True
    assert [command["listen"] for command in forward_starts(transport)] == [
        f"127.0.0.1:{web_port}"
    ]


def test_a_number_the_transport_cannot_bind_is_port_taken(app_hub):
    resident, transport, (web_port, _port_port) = app_hub
    transport.answers["forward_start"] = functools.partial(
        dict, code="port_taken", params={"port": web_port}
    )

    resident.open_app("h1", "gitea_d1")

    assert resident.app_rows()[0]["last_error"] == {
        "code": "port_taken",
        "params": {"port": web_port},
    }
    assert resident.platform.opened_urls == []


def test_stop_ends_every_forward_of_the_app(app_hub):
    resident, transport, (web_port, port_port) = app_hub
    resident.open_app("h1", "gitea_d1")

    assert resident.stop_app("h1", "gitea_d1") == {}

    assert transport.commands_of("forward_stop") == [
        {"listen": f"127.0.0.1:{web_port}", "protocol": "tcp"},
        {"listen": f"127.0.0.1:{port_port}", "protocol": "tcp"},
    ]
    assert resident.app_rows()[0]["is_in_use"] is False


def test_an_app_the_hub_does_not_list_is_unknown(app_hub):
    resident, _transport, _ports = app_hub

    assert resident.open_app("h1", "nobody") == {
        "code": "unknown_app",
        "params": {"app_id": "nobody"},
    }
    assert resident.stop_app("h9", "gitea_d1")["code"] == "unknown_app"
    assert resident.configure_app("h1", "nobody", {})["code"] == "unknown_app"


def test_a_failed_use_is_the_apps_error_until_a_refresh(app_hub):
    resident, transport, _ports = app_hub
    transport.answers["forward_start"] = functools.partial(
        dict, code="forward_failed", params={}
    )
    resident.open_app("h1", "gitea_d1")
    assert resident.app_rows()[0]["last_error"] is not None

    resident.refresh()

    assert resident.app_rows()[0]["last_error"] is None


def test_configure_keeps_the_persons_numbers_and_an_empty_one_goes_back(app_hub):
    resident, _transport, (web_port, port_port) = app_hub
    own = free_port()

    assert resident.configure_app("h1", "gitea_d1", {"web": own}) == {}

    row = entry(resident, "h1", "gitea_d1_web")
    assert (row["local_port"], row["is_local_port_own"]) == (own, True)
    assert resident.configure_app("h1", "gitea_d1", {"web": None}) == {}
    row = entry(resident, "h1", "gitea_d1_web")
    assert (row["local_port"], row["is_local_port_own"]) == (web_port, False)
    assert resident.configure_app("h1", "gitea_d1", {"web": ""}) == {}


@pytest.mark.parametrize("number", [80, 70000, "abc", True])
def test_configure_refuses_a_number_out_of_range(app_hub, number):
    resident, _transport, _ports = app_hub

    assert resident.configure_app("h1", "gitea_d1", {"web": number}) == {
        "code": "local_port_invalid",
        "params": {"port": number},
    }
    assert entry(resident, "h1", "gitea_d1_web")["is_local_port_own"] is False


def test_configure_refuses_another_entrys_number_and_keeps_nothing(app_hub):
    resident, _transport, (web_port, port_port) = app_hub
    own = free_port()

    assert resident.configure_app("h1", "gitea_d1", {"web": port_port}) == {
        "code": "port_taken",
        "params": {"port": port_port},
    }
    assert resident.configure_app("h1", "gitea_d1", {"web": own, "ssh": own}) == {
        "code": "port_taken",
        "params": {"port": own},
    }
    assert entry(resident, "h1", "gitea_d1_web")["local_port"] == web_port
    assert entry(resident, "h1", "gitea_d1_ssh")["local_port"] == port_port


def test_configure_lets_two_entries_of_one_save_trade_numbers(app_hub):
    resident, _transport, (web_port, port_port) = app_hub

    assert (
        resident.configure_app("h1", "gitea_d1", {"web": port_port, "ssh": web_port})
        == {}
    )

    assert entry(resident, "h1", "gitea_d1_web")["local_port"] == port_port
    assert entry(resident, "h1", "gitea_d1_ssh")["local_port"] == web_port


def test_configure_is_refused_while_the_app_is_in_use(app_hub):
    resident, _transport, _ports = app_hub
    resident.open_app("h1", "gitea_d1")

    assert resident.configure_app("h1", "gitea_d1", {"web": free_port()}) == {
        "code": "app_in_use",
        "params": {},
    }


def test_configure_refuses_an_entry_the_app_has_not(app_hub):
    resident, _transport, _ports = app_hub

    assert resident.configure_app("h1", "gitea_d1", {"file_media": 30000}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_a_tcp_and_a_udp_entry_may_hold_one_number(two_hubs_up):
    resident, transport = two_hubs_up
    state = app_state(free_port(), free_port())
    udp = dict(
        state["services"][1],
        id="gitea_d1_dns_udp",
        name="dns_udp",
        payload={"host": "192.168.1.5", "port": 53, "protocol": "udp"},
        local_port=free_port(),
    )
    state["services"].insert(2, udp)
    transport.deliver("c1", {"frame": state})
    shared = free_port()

    assert resident.configure_app("h1", "gitea_d1", {"ssh": shared}) == {}
    assert resident.configure_app("h1", "gitea_d1", {"dns_udp": shared}) == {}
    assert resident._store.local_ports()["h1/gitea_d1_dns_udp"]["protocol"] == "udp"


def test_an_entry_gone_from_the_hubs_list_ends_its_forward(app_hub):
    resident, transport, (web_port, port_port) = app_hub
    resident.open_app("h1", "gitea_d1")
    state = app_state(web_port, port_port)
    state["services"] = state["services"][:1] + state["services"][2:]

    transport.deliver("c1", {"frame": dict(state, hash="sb")})

    assert list(resident._forwards.forwards()) == ["h1/gitea_d1_web"]
    assert transport.commands_of("forward_stop") == [
        {"listen": f"127.0.0.1:{port_port}", "protocol": "tcp"}
    ]


def test_a_forward_that_ends_with_a_code_is_its_entrys_and_its_apps_error(app_hub):
    resident, transport, (_web_port, port_port) = app_hub
    resident.open_app("h1", "gitea_d1")
    refusal = {"code": "agent_offline", "params": {"device": "d1"}}

    resident._forwards.take_end(
        dict(
            refusal,
            event="forward_end",
            listen=f"127.0.0.1:{port_port}",
            protocol="tcp",
        )
    )

    assert entry(resident, "h1", "gitea_d1_ssh")["last_error"] == refusal
    assert resident.app_rows()[0]["last_error"] == refusal
    assert entry(resident, "h1", "gitea_d1_ssh")["forward"] is None
    resident.refresh()
    assert entry(resident, "h1", "gitea_d1_ssh")["last_error"] is None


# --- the way in, the panel and the connect stream ---


def test_the_hub_row_says_the_way_in_and_whether_the_panel_is_allowed(two_hubs_up):
    resident, transport = two_hubs_up

    transport.deliver(
        "c1",
        {"frame": dict(HOME_STATE, reached_through="ssh_relay", is_panel_allowed=True)},
    )

    row, office = resident.hubs()
    assert (row["reached_through"], row["is_panel_allowed"]) == ("ssh_relay", True)
    assert (office["reached_through"], office["is_panel_allowed"]) == ("", False)


def test_open_connect_opens_a_connect_stream_on_the_hub_named(two_hubs_up):
    resident, transport = two_hubs_up

    resident.open_connect("h2", "svc_tcp")

    assert opened(transport, "connect") == [
        ("c2", {"kind": "connect", "id": "svc_tcp"})
    ]
    with pytest.raises(GatewayUnreachable):
        resident.open_connect("h9", "svc_tcp")


PANEL_TOKEN = "panel-token-once"  # scan: allow


def panel_allowed(resident, transport, *, code="", params=None) -> list:
    """The home hub allows the panel and answers its ``service`` frame.

    Returns:
        Every step, in order: ``("service", frame)`` for each question and
        ``("forward_start", fields)`` for each forward.
    """
    transport.deliver("c1", {"frame": dict(HOME_STATE, is_panel_allowed=True)})
    steps = []
    answer = {"token": PANEL_TOKEN} if params is None and not code else params

    def respond(frame):
        steps.append(("service", frame))
        reply = {"params": dict(answer or {})}
        if code:
            reply["code"] = code
        return reply

    def forward_start(fields):
        steps.append(("forward_start", fields))
        return {}

    answering(transport, respond)
    transport.answers.setdefault("forward_start", forward_start)
    return steps


def test_panel_asks_its_sign_in_then_makes_the_forward_and_opens_its_address(
    two_hubs_up,
):
    resident, transport = two_hubs_up
    steps = panel_allowed(resident, transport)
    held = []
    resident._start_thread = held.append

    assert resident.open_panel("h1") == {}

    assert resident.hubs()[0]["jobs"]["is_opening_panel"] is True
    assert resident.open_panel("h1") == {}
    assert len(held) == 1
    held[0]()
    row = resident.hubs()[0]
    port = row["panel_forward"]
    assert row["jobs"]["is_opening_panel"] is False
    assert 20000 <= port <= 23999
    assert resident.platform.opened_urls == [
        f"http://panel-h1.localhost:{port}/?tkn={PANEL_TOKEN}"
    ]
    assert [step for step, _detail in steps] == ["service", "forward_start"]
    assert steps[0][1]["is_panel"] is True
    assert steps[1][1] == {
        "binding": "c1",
        "listen": f"127.0.0.1:{port}",
        "protocol": "tcp",
        "open": {"kind": "connect", "is_panel": True},
    }


def test_panel_on_a_mac_opens_the_loopback(two_hubs_up):
    resident, transport = two_hubs_up
    panel_allowed(resident, transport)
    resident.platform.os_name = "darwin"

    assert resident.open_panel("h1") == {}

    port = resident.hubs()[0]["panel_forward"]
    assert resident.platform.opened_urls == [
        f"http://127.0.0.1:{port}/?tkn={PANEL_TOKEN}"
    ]


def test_panel_is_refused_without_the_permission_or_the_hub(two_hubs_up):
    resident, transport = two_hubs_up

    assert resident.open_panel("h1") == {
        "code": "permission_denied",
        "params": {"kind": "panel"},
    }
    assert resident.open_panel("h9")["code"] == "unknown_hub"
    panel_allowed(resident, transport)
    transport.deliver("c1", {"event": "session_end"})
    assert resident.open_panel("h1")["code"] == "hub_unreachable"


def test_a_panel_the_transport_cannot_listen_for_is_the_hub_rows_error_until_a_refresh(
    two_hubs_up,
):
    resident, transport = two_hubs_up
    transport.answers["forward_start"] = functools.partial(
        dict, code="port_taken", params={"port": 20000}
    )
    panel_allowed(resident, transport)

    assert resident.open_panel("h1") == {}

    assert resident.hubs()[0]["last_error"]["code"] == "port_taken"
    assert resident.platform.opened_urls == []
    resident.refresh()
    assert resident.hubs()[0]["last_error"] is None


@pytest.mark.parametrize(
    "code, params",
    [
        ("permission_denied", {"kind": "panel"}),
        ("client_disabled", {}),
    ],
)
def test_a_refused_sign_in_opens_nothing_and_is_the_rows_error(
    two_hubs_up, code, params
):
    resident, transport = two_hubs_up
    steps = panel_allowed(resident, transport, code=code, params=params)

    assert resident.open_panel("h1") == {}

    row = resident.hubs()[0]
    assert row["last_error"] == {"code": code, "params": params}
    assert row["panel_forward"] is None
    assert resident.platform.opened_urls == []
    assert [step for step, _detail in steps] == ["service"]


def test_an_answer_without_a_token_opens_nothing(two_hubs_up):
    resident, transport = two_hubs_up
    panel_allowed(resident, transport, params={})

    resident.open_panel("h1")

    assert resident.hubs()[0]["last_error"]["code"] == "web_token_missing"
    assert resident.platform.opened_urls == []


def test_the_panel_token_is_in_no_log_line_and_not_in_the_state(two_hubs_up):
    resident, transport = two_hubs_up
    lines = []
    resident._log = lines.append
    resident._forwards._log = lines.append
    panel_allowed(resident, transport)

    resident.open_panel("h1")

    assert resident.platform.opened_urls[0].endswith(f"?tkn={PANEL_TOKEN}")
    assert lines
    assert all(PANEL_TOKEN not in line for line in lines)
    state = json.dumps(
        {
            "hubs": resident.hubs(),
            "services": resident.entry_rows(),
            "states": resident.service_states(),
        }
    )
    assert PANEL_TOKEN not in state
    assert all(
        PANEL_TOKEN not in json.dumps(fields) for _command, fields in transport.commands
    )


def test_leaving_a_hub_ends_its_panel_forward(two_hubs_up):
    resident, transport = two_hubs_up
    panel_allowed(resident, transport)
    resident.open_panel("h1")
    port = resident.hubs()[0]["panel_forward"]

    resident.disconnect("h1")

    assert resident._forwards.forwards() == {}
    assert {"listen": f"127.0.0.1:{port}", "protocol": "tcp"} in (
        transport.commands_of("forward_stop")
    )


# --- Clear on the window's terminal ---


def test_clear_sends_ctrl_c_and_drops_the_output_until_the_stream_is_quiet(
    two_hubs_up, monkeypatch
):
    import neutrino_client.core.terminal as terminal_module

    monkeypatch.setattr(terminal_module, "CLIENT_TERMINAL_CLEAR_QUIET_S", 0.2)
    resident, transport = two_hubs_up
    offered(resident)
    pieces = []
    resident.on_terminal_output = pieces.append
    terminal_id = resident.open_window_terminal("h1", "d1", 80, 24)["terminal_id"]
    (stream,) = transport.stream_factory.made

    assert resident.clear_terminal(terminal_id) == {}
    stream.push(b"flood")
    wait_until(lambda: {"id": terminal_id, "clearing": False} in pieces)
    stream.push(b"$ ")
    wait_until(lambda: {"id": terminal_id, "data": b"$ "} in pieces)

    assert pieces[0] == {"id": terminal_id, "clearing": True}
    assert {"id": terminal_id, "data": b"flood"} not in pieces
    assert pieces[-1] == {"id": terminal_id, "data": b"$ "}
    assert ("data", b"\x03") in stream.records
    assert resident.clear_terminal("nobody")["code"] == "unknown_terminal"
    resident.close_terminal(terminal_id)


# --- a share on Windows, through the files adapter ---

FILES_PIPE = "\\\\.\\pipe\\neutrino_client_files"
FIRST_FILES_ADDRESS = "198.19.255.2"  # scan: allow
STRANGER_FILES_ADDRESS = "198.19.255.9"  # scan: allow
SHARE_LOGIN = {"user": "media", "password": "pw"}  # scan: allow


class DrivePlatform(FakeClientPlatform):
    """A platform that maps a share to a drive letter through the files daemon."""

    os_name = "windows"
    mount_location_shape = "drive_letter"

    def validate_mount_location(self, *, location: str) -> "dict | None":
        return None

    def prepare_mount_location(self, *, location: str) -> "dict | None":
        return None

    def files_daemon_address(self) -> str:
        return FILES_PIPE


class FilesDaemon:
    """The files daemon behind its pipe, scripted."""

    def __init__(self):
        self.verbs = []
        self.refusal = None
        self.serving = 0

    def __call__(self, address, request):
        assert address == FILES_PIPE
        self.verbs.append(request["verb"])
        if self.refusal is not None and request["verb"] == "up":
            return dict(self.refusal)
        if request["verb"] == "up":
            self.serving = request["port"]
        if request["verb"] == "down":
            self.serving = 0
        return {"is_up": bool(self.serving), "port": self.serving}


@pytest.fixture
def windows_hub(config_path, transport):
    """A Windows resident whose home hub is connected and publishes a share,
    the share's login answered by the hub."""
    bind(config_path, bindings=[dict(BINDING, gateway_url=HOME_URL)])
    platform = DrivePlatform()
    resident = ClientResident(
        log=discard, platform=platform, start_thread=run_inline, transport=transport
    )
    daemon = FilesDaemon()
    resident._files_adapter._ask = daemon
    listen(resident, transport)
    up(transport, "c1", HOME_URL, HOME_WELCOME, HOME_STATE)
    answering(transport, functools.partial(dict, params=dict(SHARE_LOGIN)))
    yield resident, platform, daemon, transport
    resident.shutdown()


def mount_z(resident) -> None:
    """Mount the home hub's share at Z:, the worker's pass run by hand."""
    assert (
        resident.service_action(
            "file",
            {"action": "mount", "hub_id": "h1", "id": "share_media", "path": "Z:"},
        )
        == {}
    )
    resident._services["file"].reconcile()


def socks_to(port: int, user: str, password: str, address: str) -> socket.socket:
    """A SOCKS5 client past the login, asking for ``address:445``."""
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.sendall(b"\x05\x01\x02")
    assert client.recv(2) == b"\x05\x02"
    client.sendall(
        bytes((1, len(user)))
        + user.encode()
        + bytes((len(password),))
        + password.encode()
    )
    assert client.recv(2) == b"\x01\x00"
    client.sendall(b"\x05\x01\x00\x01" + socket.inet_aton(address) + b"\x01\xbd")
    return client


def test_a_windows_mount_asks_the_hub_for_the_login_and_maps_the_machines_address(
    windows_hub,
):
    resident, platform, daemon, transport = windows_hub

    mount_z(resident)

    (call,) = platform.attach_calls
    assert call["share_url"] == f"//{FIRST_FILES_ADDRESS}/media"
    assert (call["location"], call["port"]) == ("Z:", 0)
    assert daemon.verbs == ["up"]
    assert [frame["id"] for frame in transport.frames_of("service")] == ["share_media"]
    assert not __import__("os").path.exists(call["credentials_path"])
    (row,) = resident._services["file"].rows()
    assert (row["state"], row["username"]) == ("mounted", "media")


def test_a_windows_share_rides_a_connect_stream_through_the_endpoint(windows_hub):
    resident, _platform, _daemon, transport = windows_hub
    mount_z(resident)
    endpoint = resident._files_adapter._endpoint

    client = socks_to(
        endpoint.port, endpoint.user, endpoint.password, FIRST_FILES_ADDRESS
    )
    assert client.recv(10)[:2] == b"\x05\x00"
    client.sendall(b"smb")
    wait_until(lambda: transport.stream_factory.made)
    (stream,) = transport.stream_factory.made
    wait_until(lambda: stream.data() == [b"smb"])

    assert opened(transport, "connect") == [
        ("c1", {"kind": "connect", "id": "share_media"})
    ]
    assert stream.data() == [b"smb"]
    client.close()


def test_the_endpoint_refuses_another_port_or_address(windows_hub):
    resident, _platform, _daemon, transport = windows_hub
    mount_z(resident)
    endpoint = resident._files_adapter._endpoint

    stranger = socks_to(
        endpoint.port, endpoint.user, endpoint.password, STRANGER_FILES_ADDRESS
    )

    assert stranger.recv(10)[:2] == b"\x05\x02"
    assert opened(transport, "connect") == []
    stranger.close()


def test_the_adapter_stays_up_after_the_last_unmount_and_goes_with_a_quit(
    windows_hub,
):
    """Windows keeps its SMB connection to an address after the unmount, and
    an adapter taken away and brought back under it fails the next mount."""
    resident, _platform, daemon, _transport = windows_hub
    mount_z(resident)
    (row,) = resident._services["file"].rows()

    assert (
        resident.service_action(
            "file", {"action": "unmount", "record_id": row["record_id"]}
        )
        == {}
    )
    assert daemon.verbs == ["up"]

    resident.shutdown()

    assert daemon.verbs == ["up", "status", "down"]


def test_a_daemon_that_refuses_fails_the_row_with_the_adapters_code(windows_hub):
    resident, platform, daemon, _transport = windows_hub
    daemon.refusal = {"code": "adapter_failed", "params": {"detail": "no wintun"}}

    mount_z(resident)

    (row,) = resident._services["file"].rows()
    assert (row["state"], row["code"]) == ("failed", "files_adapter_unavailable")
    assert row["params"] == {"detail": "no wintun"}
    assert platform.attach_calls == []


def test_leaving_a_hub_forgets_the_files_addresses_no_record_names(windows_hub):
    resident, _platform, daemon, _transport = windows_hub
    daemon.refusal = {"code": "adapter_failed", "params": {"detail": "no wintun"}}
    mount_z(resident)
    assert list(resident._store.files_addresses()) == [FIRST_FILES_ADDRESS]

    resident.disconnect("h1")

    assert resident._store.mounts() == {}
    assert resident._store.files_addresses() == {}


def test_leaving_a_hub_frees_its_drive_letters_in_the_state_file(
    windows_hub, config_path
):
    """The lab's LETTER row: a leave ends the hub's mounts and drops their
    records, so the letter the picker offers is one Mount takes."""
    resident, platform, _daemon, _transport = windows_hub
    mount_z(resident)
    assert platform.attached == {"Z:"}

    resident.disconnect("h1")

    state = json.loads((config_path.parent / "state.json").read_text())
    assert state.get("mounts", {}) == {}
    assert state.get("files_addresses", {}) == {}
    assert platform.attached == set()
    assert "Z:" in platform.detach_calls
    credentials = config_path.parent / "mount_credentials"
    assert not credentials.exists() or list(credentials.iterdir()) == []


def test_a_kept_record_holds_its_machines_address(windows_hub):
    resident, _platform, _daemon, _transport = windows_hub
    mount_z(resident)

    assert resident._held_files_addresses() == {FIRST_FILES_ADDRESS}


def test_a_quit_takes_the_adapter_down_and_stops_the_endpoint(windows_hub):
    resident, _platform, daemon, _transport = windows_hub
    mount_z(resident)

    resident.shutdown()

    assert daemon.verbs[-1] == "down"
    assert resident._files_adapter._endpoint.is_running is False


def test_a_mount_job_that_crashes_says_so_in_the_log(windows_hub, monkeypatch):
    """A first mount once ended with a bare failure and no line anywhere."""
    resident, platform, _daemon, _transport = windows_hub
    lines = []
    monkeypatch.setattr(resident, "_log", lines.append)

    def held(*_args, **_kwargs):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(resident._store, "set_mount", held)

    assert (
        resident.service_action(
            "file",
            {"action": "mount", "hub_id": "h1", "id": "share_media", "path": "T:"},
        )
        == {}
    )

    assert resident._entry_errors["h1/share_media"]["code"] == "crashed"
    assert any(
        "h1/share_media: the job crashed: PermissionError" in line for line in lines
    )
    assert platform.attach_calls == []


# --- the agent's gate on the AI page ---


def test_the_start_looks_for_the_agent(config_path, transport):
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), transport=transport
    )
    released_handlers(resident)

    resident.start()
    wait_until(lambda: resident._services["ai"].gates == 1)
    resident.shutdown()

    assert resident._services["ai"].gates == 1


def test_each_hubs_state_looks_for_the_agent_before_the_refresh(two_hubs, transport):
    released_handlers(two_hubs)

    up(transport, "c1", HOME_URL, HOME_WELCOME, HOME_STATE)

    order = two_hubs._services["ai"].order
    assert order[:2] == ["gate", "refresh"]


def test_the_agent_turns_the_chip_off_once_and_its_removal_frees_the_page(
    two_hubs_up, monkeypatch, tmp_path
):
    resident, transport = two_hubs_up
    program_dir = tmp_path / "agent"
    monkeypatch.setattr(
        resident.platform, "agent_program_dir", lambda: str(program_dir)
    )
    handler, switcher = inline_ai(
        resident, is_managed=resident.platform.is_agent_installed
    )
    resident.set_exit("h1")
    resident.service_action("ai", {"is_enabled": True})

    program_dir.mkdir()
    transport.deliver("c1", {"frame": HOME_STATE})
    transport.deliver("c1", {"frame": HOME_STATE})
    refused = resident.service_action("ai", {"is_enabled": True})

    assert switcher.calls == ["activate", "deactivate"]
    assert refused == {}
    assert list(resident._entry_errors.values()) == [
        {"code": "ai_tools_managed", "params": {}}
    ]
    row = handler.state()["ai"]
    assert row["is_managed"] is True and row["is_enabled"] is False

    program_dir.rmdir()
    transport.deliver("c1", {"frame": HOME_STATE})

    assert handler.state()["ai"]["is_managed"] is False
    assert resident.service_action("ai", {"is_enabled": True}) == {}
    assert switcher.calls == ["activate", "deactivate", "activate"]


class RelaunchPlatform(FakeClientPlatform):
    def __init__(self, outcome):
        super().__init__()
        self.outcome = outcome

    def register_relaunch(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize(
    "outcome, line",
    [
        (True, "the client starts again once the upgrade is installed"),
        (
            OSError("Access is denied."),
            "the restart after the upgrade could not be arranged: Access is denied.",
        ),
    ],
)
def test_an_upgrade_quit_arranges_the_return_and_says_how_it_went(
    outcome, line, transport
):
    lines = []
    resident = ClientResident(
        log=lines.append, platform=RelaunchPlatform(outcome), transport=transport
    )

    resident.arrange_relaunch()

    assert line in lines
