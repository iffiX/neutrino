"""The resident over several hubs: one session per binding, the handlers shared.

What is pinned here is a second binding getting a session of its own on its
own socket, the merged service list carrying every hub's id, a hub that is
down subtracting only its own entries, leaving one hub stopping only its
session and releasing only its entries, the one refusal that unbinds
removing the binding through the resident, a disabled hub releasing only
its own, the binding file diffed by id so a rewrite restarts only the
sessions it changed and the welcome's own write restarts none, the exit
hub chosen and followed with the tools moved in one activation, the
disabled check per hub, a start that turns nothing on and clears
what an unclean exit left, and a shutdown that runs its order once, logs a
line a step, and lets no step hold up the rest.
"""

import json
import threading
import time

import pytest

import neutrino_client.core.channel as channel
import neutrino_client.core.resident as resident_module
import neutrino_client.core.session as session_module
from neutrino_client.constants import (
    CLIENT_IDLE_POLL_INTERVAL_S,
    CLIENT_MOUNT_CREDENTIALS_DIR_NAME,
)
from neutrino_client.core import enrollment
from neutrino_client.core.resident import ClientResident
from neutrino_client.exceptions import GatewayRefused
from neutrino_client.services.ai import AiServiceHandler
from neutrino_client.services.base import ServiceTypeHandler
from neutrino_client.services.file import mount_record_id
from tests.conftest import (
    BINDING,
    HUB_SERVICES,
    OFFICE_BINDING,
    OFFICE_SERVICES,
    FakeClientPlatform,
    bind,
    discard,
    with_hub,
)
from tests.core.test_session import ScriptedSocket

HOME_WELCOME = {
    "type": "welcome",
    "protocol": 1,
    "role": "hub",
    "id": "h1",
    "name": "home",
    "software": "neutrino_hub/0.3.0",
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
HOME_URL = "https://hub.lan:8443"
OFFICE_URL = "https://office.lan:8443"


class RecordingHandler(ServiceTypeHandler):
    """A handler that remembers the lifecycle calls it was given.

    Attributes:
        starts: How often the resident started it.
        cleared: How often it was asked to clear leftovers.
        refreshed: The entries of every refresh, in order.
        released_hubs: Every hub it was asked to let go of, in order.
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
        self.acted = []
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

    def let_go(self) -> None:
        """Let a hanging release finish, so the test leaves no thread behind."""
        self._held.set()


class HubScripts:
    """One scripted socket per hub, told apart by the host dialled.

    Attributes:
        made: ``(host, socket)`` for every socket handed out, in order.
    """

    def __init__(self, frames_by_host: dict):
        """
        Args:
            frames_by_host: What each hub's socket hands back in turn.
        """
        self._frames_by_host = frames_by_host
        self.made = []

    def __call__(self, **kwargs) -> ScriptedSocket:
        host = kwargs.get("host", "")
        made = ScriptedSocket(self._frames_by_host.get(host, []))
        self.made.append((host, made))
        return made

    def sockets_of(self, host: str) -> list:
        return [made for made_host, made in self.made if made_host == host]


def sockets_by_hub(monkeypatch, frames_by_host: dict) -> HubScripts:
    """Put one scripted socket under every hub's session."""
    scripts = HubScripts(frames_by_host)
    monkeypatch.setattr(session_module, "WebSocketClient", scripts)
    return scripts


def released_handlers(resident, counts=None) -> list:
    """Swap every releasable handler for one that records, and return the log."""
    log = []
    counts = counts or {}
    for service_type in ("ai", "file", "port", "rdp"):
        resident._services[service_type] = RecordingHandler(
            service_type, log, count=counts.get(service_type)
        )
    return log


def sessions_of(resident) -> dict:
    """The sessions by binding id."""
    return dict(resident._sessions)


def turn(resident, binding_id: str) -> int:
    """One loop turn of one hub's session, by hand."""
    return resident._sessions[binding_id].run_once()


def wait_until(condition, timeout_s: float = 5) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


class QuietSwitcher:
    """A switcher over a machine with nothing pointed at the hub."""

    def __init__(self):
        self.calls = []
        self.base_urls = []

    def is_installed(self) -> bool:
        return True

    def find_cli(self) -> str:
        return "/opt/neutrino_client/bin/cc-switch"

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


def inline_ai(resident) -> tuple:
    """Put an AI handler under the resident whose grants are scripted per hub.

    Returns:
        ``(handler, switcher)``; the credential each hub answers with names
        that hub's own endpoint.
    """
    switcher = QuietSwitcher()

    def grant(hub_id: str, entry_id: str) -> dict:
        return {"base_url": f"http://{hub_id}:8080", "api_key": "k", "model": "m1"}

    handler = AiServiceHandler(
        store=resident._store,
        original_dir=str(resident.platform.config_dir()) + "/original",
        open_service=grant,
        exit_hub_id=resident.exit_hub_id,
        log=discard,
        switcher_module=switcher,
        on_change=resident.notify,
        start_thread=run_inline,
    )
    resident._services["ai"] = handler
    return handler, switcher


@pytest.fixture
def two_hubs(config_path):
    """A resident bound to two hubs, neither connected yet."""
    bind(
        config_path,
        bindings=[dict(BINDING, gateway_url=HOME_URL), dict(OFFICE_BINDING)],
    )
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
    yield resident
    resident.shutdown()


@pytest.fixture
def two_hubs_up(two_hubs, monkeypatch):
    """Both hubs welcomed and their states taken, on their own sockets."""
    scripts = sockets_by_hub(
        monkeypatch,
        {
            "hub.lan": [HOME_WELCOME, HOME_STATE],
            "office.lan": [OFFICE_WELCOME, OFFICE_STATE],
        },
    )
    for binding_id, host in (("c1", "hub.lan"), ("c2", "office.lan")):
        session = two_hubs._sessions[binding_id]
        made = scripts(host=host)
        session._connect(made)
        kind, payload = made.recv()
        session._dispatch(made, kind, payload)
    return two_hubs, scripts


# --- one session per binding ---


def test_a_second_binding_gets_a_session_and_a_socket_of_its_own(two_hubs, monkeypatch):
    scripts = sockets_by_hub(
        monkeypatch,
        {"hub.lan": [HOME_WELCOME, HOME_STATE], "office.lan": [OFFICE_WELCOME]},
    )

    turn(two_hubs, "c1")
    turn(two_hubs, "c2")

    assert list(sessions_of(two_hubs)) == ["c1", "c2"]
    assert [host for host, _made in scripts.made] == ["hub.lan", "office.lan"]
    assert [made.sent[0]["id"] for _host, made in scripts.made] == ["c1", "c2"]
    rows = two_hubs.hubs()
    assert [(row["hub_id"], row["binding_id"]) for row in rows] == [
        ("h1", "c1"),
        ("h2", "c2"),
    ]


def test_the_hub_rows_carry_each_sessions_standing(two_hubs_up):
    resident, _scripts = two_hubs_up

    home, office = resident.hubs()

    assert home == {
        "hub_id": "h1",
        "hub_name": "home",
        "hub_software": "neutrino_hub/0.3.0",
        "binding_id": "c1",
        "name": "box",
        "gateway_url": HOME_URL,
        "connection_state": "connected",
        "is_disabled": False,
        "is_exit": True,
        "last_error": None,
    }
    assert (office["hub_id"], office["gateway_url"], office["is_exit"]) == (
        "h2",
        OFFICE_URL,
        False,
    )
    assert "tok" not in json.dumps(resident.hubs())


def test_the_merged_list_carries_every_entrys_hub(two_hubs_up):
    resident, _scripts = two_hubs_up

    merged = resident.service_entries()

    assert merged == with_hub(HUB_SERVICES, "h1") + with_hub(OFFICE_SERVICES, "h2")
    assert {entry["hub_id"] for entry in merged} == {"h1", "h2"}


def test_a_hub_that_is_down_subtracts_only_its_own_entries(two_hubs_up):
    resident, _scripts = two_hubs_up
    office = resident._sessions["c2"]

    office._drop_socket()

    assert resident.service_entries() == with_hub(HUB_SERVICES, "h1")
    assert [row["connection_state"] for row in resident.hubs()] == [
        "connected",
        "reconnecting",
    ]


def test_a_hubs_state_refreshes_the_ai_handler_with_the_merged_list(
    two_hubs, monkeypatch
):
    released_handlers(two_hubs)
    sockets_by_hub(
        monkeypatch,
        {"hub.lan": [HOME_WELCOME, HOME_STATE], "office.lan": [OFFICE_WELCOME]},
    )

    turn(two_hubs, "c1")

    # The state, then the socket's end after it, each converge once.
    assert two_hubs._services["ai"].refreshed[0] == with_hub(HUB_SERVICES, "h1")


# --- leaving one hub ---


def test_leaving_one_hub_stops_only_its_session_and_releases_only_its_hub(
    two_hubs_up, monkeypatch, config_path
):
    resident, scripts = two_hubs_up
    released = released_handlers(resident)
    posted = []

    def post(self, path, payload):
        posted.append((path, payload))
        return {}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post, raising=True)
    home = resident._sessions["c1"]

    resident.disconnect("h2")

    assert posted == [("/api/channel/leave", {"id": "c2", "token": "tok2"})]
    assert list(sessions_of(resident)) == ["c1"]
    assert resident._sessions["c1"] is home
    assert home.connection_state() == "connected"
    assert scripts.sockets_of("office.lan")[0].is_closed is True
    assert scripts.sockets_of("hub.lan")[0].is_closed is False
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1"]
    assert released == []
    for service_type in ("ai", "file", "port", "rdp"):
        assert resident._services[service_type].released_hubs == ["h2"]
    assert resident.service_entries() == with_hub(HUB_SERVICES, "h1")


def test_leaving_lets_go_when_the_hub_refuses_the_leave(two_hubs_up, monkeypatch):
    resident, _scripts = two_hubs_up

    def refuse(self, path, payload):
        raise GatewayRefused("401")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", refuse, raising=True)

    resident.disconnect("h1")

    assert list(sessions_of(resident)) == ["c2"]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c2"]


def test_a_hub_nobody_joined_cannot_be_left_or_reconnected(two_hubs_up):
    resident, _scripts = two_hubs_up

    with pytest.raises(KeyError):
        resident.disconnect("h9")
    with pytest.raises(KeyError):
        resident.reconnect("h9")
    with pytest.raises(KeyError):
        resident.reconnect("")
    assert list(sessions_of(resident)) == ["c1", "c2"]


def test_an_empty_name_means_the_one_hub_joined(config_path, monkeypatch):
    bind(config_path, url=HOME_URL)
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    try:
        resident.reconnect("")
        resident.disconnect("")
    finally:
        resident.shutdown()

    assert sessions_of(resident) == {}
    assert enrollment.bindings() == []


def test_a_binding_whose_hub_has_not_answered_is_named_by_its_binding_id(
    two_hubs, monkeypatch
):
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    assert [row["hub_id"] for row in two_hubs.hubs()] == ["h1", "h2"]
    two_hubs._sessions["c2"]._binding["hub_id"] = ""

    two_hubs.disconnect("c2")

    assert list(sessions_of(two_hubs)) == ["c1"]


# --- the one refusal that unbinds ---


def test_binding_unknown_removes_the_binding_through_the_resident(
    two_hubs, monkeypatch, config_path
):
    released_handlers(two_hubs)
    scripts = sockets_by_hub(
        monkeypatch,
        {
            "hub.lan": [HOME_WELCOME, HOME_STATE],
            "office.lan": [
                {"type": "refused", "code": "binding_unknown", "params": {"id": "c2"}}
            ],
        },
    )
    turn(two_hubs, "c1")

    delay = turn(two_hubs, "c2")

    assert delay == CLIENT_IDLE_POLL_INTERVAL_S
    assert list(sessions_of(two_hubs)) == ["c1"]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1"]
    for service_type in ("ai", "file", "port", "rdp"):
        assert two_hubs._services[service_type].released_hubs == ["h2"]
    assert [row["hub_id"] for row in two_hubs.hubs()] == ["h1"]
    assert len(scripts.sockets_of("office.lan")) == 1


# --- a hub that switches this client off ---


def test_disabled_releases_only_that_hubs_entries(two_hubs_up):
    resident, _scripts = two_hubs_up
    released = released_handlers(resident)
    office = resident._sessions["c2"]
    made = ScriptedSocket([])

    office._dispatch(made, "text", json.dumps(dict(OFFICE_STATE, is_disabled=True)))
    office._dispatch(made, "text", json.dumps(dict(OFFICE_STATE, is_disabled=True)))

    assert released == []
    for service_type in ("ai", "file", "port", "rdp"):
        assert resident._services[service_type].released_hubs == ["h2"]
    assert [row["is_disabled"] for row in resident.hubs()] == [False, True]
    assert resident.service_action(
        "port", {"hub_id": "h2", "id": "svc_tcp", "is_enabled": True}
    ) == {"code": "client_disabled", "params": {}}
    assert (
        resident.service_action(
            "port", {"hub_id": "h1", "id": "svc_tcp", "is_enabled": True}
        )
        == {}
    )


def test_an_action_naming_no_hub_is_the_exit_hubs(two_hubs_up):
    resident, _scripts = two_hubs_up
    released_handlers(resident)
    home = resident._sessions["c1"]
    made = ScriptedSocket([])
    home._dispatch(made, "text", json.dumps(dict(HOME_STATE, is_disabled=True)))

    assert resident.service_action("ai", {"is_enabled": True}) == {
        "code": "client_disabled",
        "params": {},
    }


def test_an_action_reaches_its_handler_with_the_merged_list(two_hubs_up):
    resident, _scripts = two_hubs_up
    released_handlers(resident)

    assert resident.service_action("port", {"hub_id": "h2", "id": "svc_tcp"}) == {}

    entries, body = resident._services["port"].acted[0]
    assert entries == resident.service_entries()
    assert body == {"hub_id": "h2", "id": "svc_tcp"}
    assert resident.service_action("nothing", {}) == {
        "code": "unknown_request",
        "params": {},
    }


# --- the exit hub ---


def test_the_exit_is_the_chosen_hub_or_else_the_first_joined(two_hubs_up, config_path):
    resident, _scripts = two_hubs_up

    assert resident.exit_hub_id() == "h1"
    assert [row["is_exit"] for row in resident.hubs()] == [True, False]

    enrollment.set_exit_hub_id("h2")
    resident._adopt_external_binding()
    assert resident.exit_hub_id() == "h2"
    assert [row["is_exit"] for row in resident.hubs()] == [False, True]

    enrollment.set_exit_hub_id("h9")
    resident._adopt_external_binding()
    assert resident.exit_hub_id() == "h1"


def test_the_first_joined_binding_is_the_exit_and_the_tools_point_there(
    two_hubs_up,
):
    resident, _scripts = two_hubs_up
    handler, switcher = inline_ai(resident)

    assert resident.service_action("ai", {"is_enabled": True}) == {}

    assert resident.exit_hub_id() == "h1"
    assert switcher.calls == ["activate"]
    assert handler._granted["hub_id"] == "h1"
    assert handler._granted["base_url"] == "http://h1:8080"


def test_set_exit_to_a_joined_hub_moves_the_tools_in_one_activation(
    two_hubs_up, config_path
):
    resident, _scripts = two_hubs_up
    handler, switcher = inline_ai(resident)
    resident.service_action("ai", {"is_enabled": True})

    assert resident.set_exit("h2") == {}

    assert resident.exit_hub_id() == "h2"
    assert enrollment.exit_hub_id() == "h2"
    assert [row["is_exit"] for row in resident.hubs()] == [False, True]
    assert switcher.calls == ["activate", "activate"]
    assert switcher.base_urls == ["http://h1:8080", "http://h2:8080"]
    assert handler._granted["hub_id"] == "h2"

    assert resident.set_exit("c1") == {}
    assert resident.exit_hub_id() == "h1"
    assert switcher.calls == ["activate", "activate", "activate"]


def test_a_hub_that_is_not_connected_cannot_be_the_exit(two_hubs_up, config_path):
    resident, _scripts = two_hubs_up
    _handler, switcher = inline_ai(resident)
    office = resident._sessions["c2"]

    office._drop_socket()
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
    assert resident.exit_hub_id() == "h1"
    assert enrollment.exit_hub_id() == ""
    assert switcher.calls == []


def test_removing_the_exit_binding_moves_the_exit_and_the_tools(
    two_hubs_up, monkeypatch, config_path
):
    resident, _scripts = two_hubs_up
    handler, switcher = inline_ai(resident)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    resident.service_action("ai", {"is_enabled": True})

    resident.disconnect("h1")

    assert resident.exit_hub_id() == "h2"
    assert enrollment.exit_hub_id() == "h2"
    assert [row["is_exit"] for row in resident.hubs()] == [True]
    assert switcher.calls == ["activate", "activate"]
    assert switcher.base_urls == ["http://h1:8080", "http://h2:8080"]
    assert handler._granted["hub_id"] == "h2"


def test_the_exit_is_pinned_where_it_moved_and_a_rejoin_leaves_it(
    two_hubs_up, monkeypatch, config_path
):
    resident, scripts = two_hubs_up
    released_handlers(resident)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    resident.disconnect("h1")
    assert enrollment.exit_hub_id() == "h2"

    enrollment.add_binding(dict(BINDING, gateway_url=HOME_URL))
    resident._adopt_external_binding()

    assert list(sessions_of(resident)) == ["c2", "c1"]
    assert resident.exit_hub_id() == "h2"
    assert [row["is_exit"] for row in resident.hubs()] == [True, False]


def test_a_binding_gone_from_the_file_moves_the_pinned_exit(two_hubs_up, config_path):
    resident, _scripts = two_hubs_up
    released_handlers(resident)
    time.sleep(0.01)
    bind(config_path, bindings=[dict(OFFICE_BINDING)])

    resident._adopt_external_binding()

    assert resident.exit_hub_id() == "h2"
    assert enrollment.exit_hub_id() == "h2"


def test_binding_unknown_on_the_exit_moves_it(two_hubs, monkeypatch, config_path):
    released_handlers(two_hubs)
    sockets_by_hub(
        monkeypatch,
        {
            "hub.lan": [
                {"type": "refused", "code": "binding_unknown", "params": {"id": "c1"}}
            ],
            "office.lan": [OFFICE_WELCOME, OFFICE_STATE],
        },
    )
    turn(two_hubs, "c2")

    turn(two_hubs, "c1")

    assert two_hubs.exit_hub_id() == "h2"
    assert enrollment.exit_hub_id() == "h2"


def test_with_no_joined_hub_the_tools_are_restored(
    two_hubs_up, monkeypatch, config_path
):
    resident, _scripts = two_hubs_up
    handler, switcher = inline_ai(resident)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    resident.service_action("ai", {"is_enabled": True})

    resident.disconnect("h1")
    resident.disconnect("h2")

    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""
    assert switcher.calls == ["activate", "activate", "deactivate"]
    assert handler._granted == {}
    assert handler.state()["ai"]["is_enabled"] is True
    assert handler.state()["ai"]["is_active"] is False


def test_the_service_stream_is_opened_on_the_hub_named(two_hubs_up):
    resident, scripts = two_hubs_up
    outcome = {}

    def wait() -> None:
        outcome["reply"] = resident.open_service("h2", "rdp_lab", timeout_s=5)

    waiter = threading.Thread(target=wait)
    waiter.start()
    office_socket = scripts.sockets_of("office.lan")[0]
    wait_until(lambda: any(frame["type"] == "open" for frame in office_socket.sent))
    (opened,) = [frame for frame in office_socket.sent if frame["type"] == "open"]
    resident._sessions["c2"]._dispatch(
        office_socket,
        "text",
        json.dumps(
            {"type": "close", "stream": opened["stream"], "params": {"host": "x"}}
        ),
    )
    waiter.join(timeout=5)

    assert opened["id"] == "rdp_lab"
    assert outcome["reply"] == {"host": "x"}
    assert all(
        frame["type"] != "open" for frame in scripts.sockets_of("hub.lan")[0].sent
    )
    with pytest.raises(resident_module.GatewayUnreachable):
        resident.open_service("h9", "rdp_lab", timeout_s=0.05)


# --- the binding file, diffed by id ---


def test_a_rewrite_of_the_file_restarts_only_the_sessions_it_changed(
    two_hubs_up, config_path
):
    resident, scripts = two_hubs_up
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
    assert home.connection_state() == "connected"
    assert scripts.sockets_of("office.lan")[0].is_closed is True
    assert resident._services["file"].released_hubs == ["h2"]
    assert resident._sessions["c2"].binding()["token"] == "rotated"


def test_a_binding_gone_from_the_file_stops_its_session(two_hubs_up, config_path):
    resident, scripts = two_hubs_up
    released_handlers(resident)
    time.sleep(0.01)
    bind(config_path, bindings=[dict(OFFICE_BINDING)])

    resident._adopt_external_binding()

    assert list(sessions_of(resident)) == ["c2"]
    assert scripts.sockets_of("hub.lan")[0].is_closed is True
    assert resident._services["port"].released_hubs == ["h1"]
    assert resident.service_entries() == with_hub(OFFICE_SERVICES, "h2")


def test_the_hubs_name_written_by_the_welcome_restarts_nothing(
    config_path, monkeypatch
):
    bind(config_path, bindings=[dict(BINDING, hub_id="", hub_name="")])
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
    scripts = sockets_by_hub(monkeypatch, {"127.0.0.1": [HOME_WELCOME, HOME_STATE]})
    session = resident._sessions["c1"]
    made = scripts(host="127.0.0.1")
    try:
        session._connect(made)
        assert json.loads(config_path.read_text())["bindings"][0]["hub_id"] == "h1"

        resident._adopt_external_binding()

        assert resident._sessions["c1"] is session
        assert made.is_closed is False
        assert resident.hubs()[0]["hub_name"] == "home"
    finally:
        resident.shutdown()


def test_an_external_binding_is_adopted_and_an_unbound_resident_idles(
    config_path, monkeypatch
):
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
    assert resident.is_connected() is False
    assert resident.hubs() == []
    scripts = sockets_by_hub(monkeypatch, {"hub.lan": [HOME_WELCOME]})

    bind(config_path, url=HOME_URL)
    resident._adopt_external_binding()
    turn(resident, "c1")

    assert resident.is_connected() is True
    assert scripts.made[0][1].sent[0]["type"] == "hello"
    resident.shutdown()


def test_connect_starts_the_new_hubs_session(config_path, monkeypatch):
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
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


def test_a_started_resident_adopts_the_file_on_its_own(config_path, monkeypatch):
    monkeypatch.setattr(resident_module, "CLIENT_IDLE_POLL_INTERVAL_S", 0.02)
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
    released_handlers(resident)
    sockets_by_hub(monkeypatch, {})
    resident.start()
    try:
        bind(config_path, url=HOME_URL)
        wait_until(lambda: "c1" in resident._sessions)

        assert list(sessions_of(resident)) == ["c1"]
        assert resident._sessions["c1"]._thread is not None
    finally:
        resident.shutdown()


# --- the start, and the one way out ---


def test_the_start_turns_nothing_on(config_path, tmp_path):
    """Opening the client shows a clean machine: a record is a preference,
    never a mount to bring back."""
    platform = FakeClientPlatform()
    resident = ClientResident(log=discard, platform=platform)
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
    (credentials / f"{record_id}.credentials").write_text("username=media")

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


def test_the_start_clears_what_an_unclean_exit_left(config_path):
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
    released_handlers(resident)

    resident.start()
    resident.shutdown()

    assert resident._services["ai"].cleared == 1
    assert resident._services["file"].cleared == 1
    assert resident._services["ai"].starts == 1


def test_a_handler_that_cannot_clear_is_logged_and_never_fatal(config_path):
    lines = []
    resident = ClientResident(log=lines.append, platform=FakeClientPlatform())
    released_handlers(resident)

    def refuse() -> None:
        raise OSError("busy")

    resident._services["file"].clear_leftovers = refuse

    resident.start()
    resident.shutdown()

    assert any(line.startswith("file: could not clear") for line in lines)
    assert resident._services["file"].starts == 1


def test_the_shutdown_logs_one_line_a_step_in_order(config_path):
    lines = []
    resident = ClientResident(log=lines.append, platform=FakeClientPlatform())
    released_handlers(resident, counts={"file": 2, "port": 1, "rdp": 0})

    resident.shutdown()

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
    monkeypatch.setattr(resident_module, "CLIENT_SHUTDOWN_DEADLINE_S", 0.4)
    lines = []
    resident = ClientResident(log=lines.append, platform=FakeClientPlatform())
    released = released_handlers(resident)
    hanging = RecordingHandler("ai", released, is_hanging=True)
    resident._services["ai"] = hanging

    started = time.monotonic()
    resident.shutdown()
    hanging.let_go()

    assert hanging.is_holding.is_set()
    assert released == ["ai", "file", "port", "rdp"]
    assert lines[0].startswith("ai: gave up after ")
    assert lines[-1] == "shut down"
    assert time.monotonic() - started < 5


def test_shutdown_runs_the_order_once_closes_every_socket_and_is_idempotent(
    two_hubs_up,
):
    resident, scripts = two_hubs_up
    released = released_handlers(resident)

    resident.shutdown()
    resident.shutdown()

    assert released == ["ai", "file", "port", "rdp"]
    assert all(made.is_closed for _host, made in scripts.made)


def test_shutdown_survives_a_handler_that_refuses(two_hubs):
    released = []

    class Refusing(RecordingHandler):
        def release(self):
            raise OSError("busy")

    two_hubs._services["ai"] = Refusing("ai", released)
    for service_type in ("file", "port", "rdp"):
        two_hubs._services[service_type] = RecordingHandler(service_type, released)

    two_hubs.shutdown()

    assert released == ["file", "port", "rdp"]


def test_the_state_carries_every_handlers_keys(two_hubs):
    states = two_hubs.service_states()

    assert set(states) >= {"forwards", "mounts", "ai", "ai_tool_configs", "viewers"}


def test_the_handlers_announce_through_the_resident(two_hubs):
    for service_type in ("port", "ai", "file", "rdp"):
        handler = two_hubs._services[service_type]
        assert handler._on_change == two_hubs.notify


def test_show_reaches_the_registered_window(two_hubs):
    shown = []

    def show() -> None:
        shown.append(1)

    two_hubs.on_show = show
    two_hubs.request_show()
    two_hubs.on_show = None
    two_hubs.request_show()

    assert shown == [1]


# --- the language, the theme and the announcements ---


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


def test_the_resident_forwards_a_sessions_changes_to_the_watchers(
    two_hubs, monkeypatch
):
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.01)
    heard = threading.Event()
    two_hubs.subscribe(heard.set)
    sockets_by_hub(monkeypatch, {"hub.lan": [HOME_WELCOME]})

    turn(two_hubs, "c1")

    assert heard.wait(timeout=5)
