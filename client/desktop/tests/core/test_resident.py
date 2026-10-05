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
line a step, and lets no step hold up the rest. The state document's jobs:
a refresh set per hub and cleared by its answer, a leave and a service
press shown before the work, a duplicate press dropped and never answered
as ``busy``, a failure kept on the entry until the next press or a refresh,
the notice a forgotten binding leaves, closed or dropped by a refresh, a
leave that forgets the binding whatever the hub answers, and the clipboard
written.
"""

import functools
import json
import socket
import threading
import time
import uuid

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
from neutrino_client.exceptions import (
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
)
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
    link_for,
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

    def drop_withdrawn(self, *, hub_id, entries):
        self.withdrawn.append((hub_id, list(entries)))
        return 0

    def machines(self) -> set:
        return set()

    def let_go(self) -> None:
        """Let a hanging release finish, so the test leaves no thread behind."""
        self._held.set()


class RecordingForwards(RecordingHandler):
    """The forward registry, remembering its lifecycle calls; nothing listens."""

    def forwards(self) -> dict:
        return {}

    def port_of(self, hub_id: str, entry_id: str) -> int:
        return 0


class AiForwards:
    """The forward registry as the AI handler sees it: one port per hub."""

    PORTS = {"h1": 21001, "h2": 21002}

    def __init__(self):
        self.running = {}

    def ensure(self, *, hub_id, entry_id, own_port, kind, local_port=0):
        self.running[(hub_id, entry_id)] = self.PORTS[hub_id]
        return self.PORTS[hub_id]

    def stop(self, hub_id, entry_id):
        return self.running.pop((hub_id, entry_id), None) is not None


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


def inline_ai(resident) -> tuple:
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
    resident = ClientResident(
        log=discard, platform=FakeClientPlatform(), start_thread=run_inline
    )
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
        "binding_id": "c1",
        "gateway_url": HOME_URL,
        "software": "neutrino_hub/0.3.0",
        "connection": "connected",
        "reached_through": "",
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
            "stage_since": 0,
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
    resident, _scripts = two_hubs_up

    merged = resident.service_entries()

    assert merged == with_hub(HUB_SERVICES, "h1") + with_hub(OFFICE_SERVICES, "h2")
    assert {entry["hub_id"] for entry in merged} == {"h1", "h2"}


def test_a_hub_that_is_down_subtracts_only_its_own_entries(two_hubs_up):
    resident, _scripts = two_hubs_up
    office = resident._sessions["c2"]

    office._drop_socket()

    assert resident.service_entries() == with_hub(HUB_SERVICES, "h1")
    assert [row["connection"] for row in resident.hubs()] == [
        "connected",
        "connecting",
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


def test_a_hubs_state_and_a_leave_tell_the_shares_what_that_hub_lists(
    two_hubs_up, monkeypatch, config_path
):
    resident, _scripts = two_hubs_up
    released_handlers(resident)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    home = resident._sessions["c1"]

    home._dispatch(ScriptedSocket([]), "text", json.dumps(HOME_STATE))
    listed = home.service_entries()
    resident.disconnect("h1")

    assert listed
    assert resident._services["file"].withdrawn == [("h1", listed), ("h1", [])]


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

    wait_until(lambda: posted)
    assert posted == [("/api/channel/leave", {"id": "c2", "token": "tok2"})]
    assert list(sessions_of(resident)) == ["c1"]
    assert resident._sessions["c1"] is home
    assert home.connection() == "connected"
    assert scripts.sockets_of("office.lan")[0].is_closed is True
    assert scripts.sockets_of("hub.lan")[0].is_closed is False
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1"]
    assert released == []
    for handler in hub_releasers(resident):
        assert handler.released_hubs == ["h2"]
    assert resident.service_entries() == with_hub(HUB_SERVICES, "h1")


def test_leaving_lets_go_when_the_hub_refuses_the_leave(two_hubs_up, monkeypatch):
    resident, _scripts = two_hubs_up

    def refuse(self, path, payload):
        raise GatewayRefused("401")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", refuse, raising=True)

    resident.disconnect("h1")

    assert list(sessions_of(resident)) == ["c2"]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c2"]


def test_leaving_drops_the_binding_first_and_tells_the_hub_from_its_own_thread(
    two_hubs_up, monkeypatch
):
    """The row is gone before the hub hears; a hub that takes its time
    holds nobody up."""
    resident, _scripts = two_hubs_up
    released_handlers(resident)
    posted = []
    hold = threading.Event()

    def post(self, path, payload):
        posted.append([binding["id"] for binding in enrollment.bindings()])
        hold.wait(timeout=5)
        return {}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post, raising=True)
    started = time.monotonic()

    resident.disconnect("h2")
    elapsed = time.monotonic() - started
    wait_until(lambda: posted)
    hold.set()

    assert elapsed < 1
    assert posted == [["c1"]]
    assert list(sessions_of(resident)) == ["c1"]


def test_a_refresh_reports_on_a_live_socket_and_wakes_a_session_that_is_down(
    two_hubs_up,
):
    resident, scripts = two_hubs_up
    home = scripts.sockets_of("hub.lan")[0]
    office = resident._sessions["c2"]
    office._end_socket(scripts.sockets_of("office.lan")[0])
    office._backoff_s = 60
    office._news.clear()
    reports_before = len([frame for frame in home.sent if frame["type"] == "report"])

    resident.refresh()

    reports_after = len([frame for frame in home.sent if frame["type"] == "report"])
    assert reports_after == reports_before + 1
    assert office._backoff_s == 5
    assert office._news.is_set()


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
    for handler in hub_releasers(two_hubs):
        assert handler.released_hubs == ["h2"]
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
    for handler in hub_releasers(resident):
        assert handler.released_hubs == ["h2"]
    assert [row["connection"] for row in resident.hubs()] == [
        "connected",
        "disabled",
    ]
    assert resident.service_action(
        "port", {"hub_id": "h2", "id": "svc_tcp", "is_enabled": True}
    ) == {"code": "client_disabled", "params": {}}
    assert (
        resident.service_action(
            "port", {"hub_id": "h1", "id": "svc_tcp", "is_enabled": True}
        )
        == {}
    )


def test_an_action_naming_no_hub_is_the_exit_hubs(two_hubs_up, config_path):
    resident, _scripts = two_hubs_up
    released_handlers(resident)
    resident.set_exit("h1")
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


def test_the_exit_is_the_chosen_hub_and_no_hub_otherwise(two_hubs_up, config_path):
    resident, _scripts = two_hubs_up

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
    resident, _scripts = two_hubs_up
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
    resident, _scripts = two_hubs_up
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
    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""
    assert switcher.calls == []


def test_leaving_the_exit_leaves_no_exit_and_puts_the_tools_back(
    two_hubs_up, monkeypatch, config_path
):
    resident, _scripts = two_hubs_up
    handler, switcher = inline_ai(resident)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    resident.set_exit("h1")
    resident.service_action("ai", {"is_enabled": True})

    resident.disconnect("h1")

    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""
    assert [row["is_exit"] for row in resident.hubs()] == [False]
    assert switcher.calls == ["activate", "deactivate"]
    assert handler._granted == {}


def test_a_rejoin_after_leaving_the_exit_makes_no_hub_the_exit(
    two_hubs_up, monkeypatch, config_path
):
    resident, scripts = two_hubs_up
    released_handlers(resident)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    resident.set_exit("h1")
    resident.disconnect("h1")
    assert enrollment.exit_hub_id() == ""

    enrollment.add_binding(dict(BINDING, gateway_url=HOME_URL))
    resident._adopt_external_binding()

    assert list(sessions_of(resident)) == ["c2", "c1"]
    assert resident.exit_hub_id() == ""
    assert [row["is_exit"] for row in resident.hubs()] == [False, False]


def test_a_binding_gone_from_the_file_clears_the_exit(two_hubs_up, config_path):
    resident, _scripts = two_hubs_up
    released_handlers(resident)
    resident.set_exit("h1")
    time.sleep(0.01)
    bind(config_path, bindings=[dict(OFFICE_BINDING)])
    enrollment.set_exit_hub_id("h1")

    resident._adopt_external_binding()

    assert resident.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""


def test_binding_unknown_on_the_exit_clears_it(two_hubs, monkeypatch, config_path):
    released_handlers(two_hubs)
    two_hubs._pin_exit("h1")
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

    assert two_hubs.exit_hub_id() == ""
    assert enrollment.exit_hub_id() == ""


def test_with_no_joined_hub_the_tools_are_restored(
    two_hubs_up, monkeypatch, config_path
):
    resident, _scripts = two_hubs_up
    handler, switcher = inline_ai(resident)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
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
    assert home.connection() == "connected"
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
    assert resident._forwards.released_hubs == ["h1"]
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
        # The session is held before its thread is published: wait for both.
        wait_until(
            lambda: "c1" in resident._sessions
            and resident._sessions["c1"]._thread is not None
        )

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


def test_the_start_returns_before_the_leftovers_are_cleared(config_path):
    """The window opens first: the clearing, which can run a console tool,
    happens on the resident's own thread, the handlers after it."""
    resident = ClientResident(log=discard, platform=FakeClientPlatform())
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
    assert released == ["ai", "file", "rdp", "forwards"]
    assert lines[0] == "networks: 0 kept"
    assert lines[1].startswith("ai: gave up after ")
    assert lines[-1] == "shut down"
    assert time.monotonic() - started < 5


def test_shutdown_runs_the_order_once_closes_every_socket_and_is_idempotent(
    two_hubs_up,
):
    resident, scripts = two_hubs_up
    released = released_handlers(resident)

    resident.shutdown()
    resident.shutdown()

    assert released == ["ai", "file", "rdp", "forwards"]
    assert all(made.is_closed for _host, made in scripts.made)


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
    two_hubs, monkeypatch
):
    monkeypatch.setattr(resident_module, "ANNOUNCE_SETTLE_S", 0.01)
    heard = threading.Event()
    two_hubs.subscribe(heard.set)
    sockets_by_hub(monkeypatch, {"hub.lan": [HOME_WELCOME]})

    turn(two_hubs, "c1")

    assert heard.wait(timeout=5)


# --- the virtual networks and the terminals ---

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

    def status(self, material):
        return {
            "is_on": self.is_on,
            "is_other_network": False,
            "address": "10.144.144.5" if self.is_on else "",
            "is_hub_seen": self.is_on,
        }

    def join(self, material, hostname):
        self.steps.append(("join", material["network_name"]))
        self.is_on = True

    def leave(self, material):
        self.steps.append(("leave", material["network_name"]))
        self.is_on = False


@pytest.fixture
def overlay_resident(config_path):
    bind(
        config_path,
        bindings=[dict(BINDING, gateway_url=HOME_URL, overlays=[EASYTIER_OVERLAY])],
    )
    driver = FakeOverlayDriver()
    resident = ClientResident(
        log=discard,
        platform=FakeClientPlatform(),
        overlay_drivers={"easytier": driver, "netbird": FakeOverlayDriver()},
    )
    yield resident, driver
    resident.shutdown()


@pytest.fixture
def joining_resident(config_path):
    driver = FakeOverlayDriver()
    resident = ClientResident(
        log=discard,
        platform=FakeClientPlatform(),
        overlay_drivers={"easytier": driver, "netbird": FakeOverlayDriver()},
    )
    resident.connect(
        link_for(
            {
                "urls": [HOME_URL, "https://10.144.144.1:8443"],
                "token": "ticket-1",
                "overlays": [EASYTIER_OVERLAY],
            }
        )
    )
    yield resident, driver
    resident.shutdown()


def test_a_join_shows_its_row_at_once_pending_with_its_network(joining_resident):
    resident, _driver = joining_resident

    (row,) = resident.hubs()

    assert (row["connection"], row["is_pending"]) == ("pending", True)
    assert row["gateway_url"] == HOME_URL
    assert row["binding_id"].startswith("pending_")
    assert "ticket-1" not in json.dumps(resident.hubs())
    assert row["overlay"]["networks"] == [{"provider": "easytier", "network": "home"}]
    assert row["overlay"]["state"] == "off"
    assert resident.connect_overlay(row["binding_id"]) == {}


def test_a_completed_join_keeps_the_session_and_its_network(joining_resident):
    resident, _driver = joining_resident
    (session,) = sessions_of(resident).values()
    pending_id = session.binding_id
    assert resident.connect_overlay(pending_id) == {}
    wait_until(lambda: resident.hubs()[0]["overlay"]["state"] == "on")
    completed = dict(
        session.binding(), id="c7", token="tok7", ticket="", is_pending=False
    )

    resident._hub_joined(session, completed)
    resident._reconcile_bindings(enrollment.config_stamp())

    assert list(sessions_of(resident).values()) == [session]
    (row,) = resident.hubs()
    assert (row["binding_id"], row["is_pending"]) == ("c7", False)
    assert row["overlay"]["state"] == "on"
    assert [binding["id"] for binding in enrollment.bindings()] == ["c7"]


def test_leaving_a_pending_join_tells_no_hub(joining_resident, monkeypatch):
    resident, _driver = joining_resident
    told = []
    monkeypatch.setattr(enrollment, "leave", told.append)
    (row,) = resident.hubs()

    resident.disconnect(row["binding_id"])

    assert resident.hubs() == [] and enrollment.bindings() == []
    assert told == []


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


def test_a_network_that_is_on_has_its_hub_connect_through_it_first(
    overlay_resident,
):
    resident, _driver = overlay_resident
    session = resident._sessions["c1"]
    hosts = []
    session.reconnect_through = functools.partial(_note_route, hosts)

    resident._overlay_route("h1", ["10.144.144.1"], True)
    resident._overlay_route("c1", [])

    assert hosts == [(["10.144.144.1"], True), ([], False)]


def _note_route(seen, hosts, is_only) -> None:
    seen.append((hosts, is_only))


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


def test_the_terminals_of_every_hub_are_stamped_with_it(two_hubs_up):
    resident, _scripts = two_hubs_up
    lepton = {
        "device_id": "d1",
        "name": "lepton",
        "is_online": True,
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
    resident._sessions["c1"]._take_state(dict(HOME_STATE, terminals=[lepton]))

    assert resident.terminal_entries() == [
        {"device_id": "d1", "name": "lepton", "is_online": True, "hub_id": "h1"}
    ]
    (row,) = resident.terminal_sessions()
    assert (row["hub_id"], row["device_id"], row["owner"], row["is_shared"]) == (
        "h1",
        "d1",
        "hub",
        True,
    )


def offered(resident) -> None:
    """The home hub offers a terminal on lepton."""
    lepton = {"device_id": "d1", "name": "lepton", "is_online": True}
    resident._sessions["c1"]._take_state(dict(HOME_STATE, terminals=[lepton]))


def test_a_terminal_opens_a_shell_stream_with_its_size(two_hubs_up):
    resident, scripts = two_hubs_up
    offered(resident)

    outcome = resident.open_terminal("h1", "d1", 120, 40)

    (made,) = scripts.sockets_of("hub.lan")
    opened = [frame for frame in made.sent if frame.get("type") == "open"]
    assert opened == [
        {
            "type": "open",
            "stream": 1,
            "kind": "shell",
            "device_id": "d1",
            "cols": 120,
            "rows": 40,
            "session_id": outcome["session_id"],
        }
    ]
    assert str(uuid.UUID(outcome["session_id"])) == outcome["session_id"]
    assert resident.has_terminal(outcome["terminal_id"])


def test_every_new_terminal_is_a_new_session(two_hubs_up):
    resident, _scripts = two_hubs_up
    offered(resident)

    first = resident.open_terminal("h1", "d1", 80, 24)
    second = resident.open_terminal("h1", "d1", 80, 24)

    assert first["session_id"] != second["session_id"]


def test_a_kept_session_is_attached_to_again_by_its_id(two_hubs_up):
    resident, scripts = two_hubs_up
    offered(resident)

    outcome = resident.open_window_terminal("h1", "d1", 80, 24, "kept-1")

    (made,) = scripts.sockets_of("hub.lan")
    (opened,) = [frame for frame in made.sent if frame.get("kind") == "shell"]
    assert (opened["session_id"], opened["is_resumed"]) == ("kept-1", True)
    assert outcome["session_id"] == "kept-1"


def test_persist_names_the_terminals_session_and_stop_names_the_hub(two_hubs_up):
    resident, _scripts = two_hubs_up
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


def test_a_machine_the_hub_does_not_offer_opens_nothing(two_hubs_up):
    resident, _scripts = two_hubs_up

    assert resident.open_terminal("h1", "d9", 80, 24) == {
        "code": "unknown_terminal",
        "params": {"device_id": "d9"},
    }
    assert resident.open_terminal("h9", "d1", 80, 24)["code"] == "unknown_hub"


def test_the_result_is_asked_once_after_the_shell_ended(two_hubs_up):
    resident, _scripts = two_hubs_up
    offered(resident)
    terminal_id = resident.open_terminal("h1", "d1", 80, 24)["terminal_id"]
    session = resident._sessions["c1"]
    session._streams.take_close(
        {"type": "close", "stream": 1, "params": {"exit_code": 0}}
    )

    assert resident.terminal_result(terminal_id) == {"exit_code": 0}
    assert resident.terminal_result(terminal_id)["code"] == "unknown_terminal"


def test_the_windows_terminal_pushes_its_output_then_its_end(two_hubs_up):
    resident, _scripts = two_hubs_up
    offered(resident)
    pieces = []
    resident.on_terminal_output = pieces.append

    terminal_id = resident.open_window_terminal("h1", "d1", 80, 24)["terminal_id"]
    session = resident._sessions["c1"]
    session._streams.take_bytes(1, b"$ ")
    session._streams.take_close(
        {"type": "close", "stream": 1, "params": {"exit_code": 0}}
    )

    wait_until(lambda: len(pieces) == 2)
    assert pieces == [
        {"id": terminal_id, "data": b"$ "},
        {"id": terminal_id, "end": {"exit_code": 0}},
    ]
    assert not resident.has_terminal(terminal_id)


def test_the_windows_keys_and_close_reach_the_shell(two_hubs_up):
    resident, scripts = two_hubs_up
    offered(resident)
    terminal_id = resident.open_window_terminal("h1", "d1", 80, 24)["terminal_id"]
    session = resident._sessions["c1"]
    session._streams.take_credit({"type": "credit", "stream": 1, "bytes": 64})

    assert resident.terminal_input(terminal_id, b"ls\r") == {}
    assert resident.close_terminal(terminal_id) == {}

    (made,) = scripts.sockets_of("hub.lan")
    assert [frame for frame in made.sent if isinstance(frame, tuple)] == [(1, b"ls\r")]
    assert {"type": "close", "stream": 1, "code": "", "params": {}} in made.sent
    assert resident.terminal_input(terminal_id, b"x")["code"] == "unknown_terminal"
    assert resident.close_terminal(terminal_id)["code"] == "unknown_terminal"


def test_a_machine_the_hub_does_not_offer_opens_no_window_terminal(two_hubs_up):
    resident, _scripts = two_hubs_up

    assert resident.open_window_terminal("h1", "d9", 80, 24)["code"] == (
        "unknown_terminal"
    )


# --- the jobs in the state document ---


class SlowHandler(ServiceTypeHandler):
    """A handler whose action waits until the test lets it finish.

    Attributes:
        acted: Every body it was handed.
        answer: What the action ends with.
    """

    service_type = "port"

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
    resident, _scripts = two_hubs_up
    handler = SlowHandler()
    resident._services["port"] = handler
    held = []
    resident._start_thread = held.append

    assert (
        resident.service_action(
            "port", {"hub_id": "h1", "id": "svc_tcp", "is_enabled": True}
        )
        == {}
    )
    assert entry(resident, "h1", "svc_tcp")["job"] == "forwarding"
    assert handler.acted == []

    handler.release_it.set()
    held[0]()
    assert entry(resident, "h1", "svc_tcp")["job"] == ""
    assert entry(resident, "h1", "svc_tcp")["last_error"] is None


def test_a_forwardable_entry_carries_its_local_port_and_its_forward(two_hubs_up):
    resident, _scripts = two_hubs_up
    probe = socket.create_server(("127.0.0.1", 0))
    wanted = probe.getsockname()[1]
    probe.close()

    row = entry(resident, "h1", "svc_tcp")
    assert (row["local_port"], row["forward"]) == ("auto", None)
    for entry_id in ("svc_wiki", "ai", "rdp_s9", "share_media"):
        assert entry(resident, "h1", entry_id)["local_port"] == "auto"
    assert resident.configure_forward("h1", "svc_tcp", wanted) == {}
    assert resident.configure_forward("h2", "svc_tcp", wanted)["code"] == "port_taken"
    assert resident.configure_forward("h1", "svc_wiki", 15000) == {}
    for entry_id in ("ai", "rdp_s9", "share_media"):
        assert resident.configure_forward("h1", entry_id, 15001) == {
            "code": "unknown_request",
            "params": {},
        }
    resident._services["port"].forward(hub_id="h1", entry_id="svc_tcp", port=1)

    row = entry(resident, "h1", "svc_tcp")
    assert (row["local_port"], row["forward"]) == (wanted, wanted)
    resident._forwards.release()


def test_a_second_press_while_the_job_runs_is_dropped(two_hubs_up):
    resident, _scripts = two_hubs_up
    handler = SlowHandler()
    resident._services["port"] = handler
    held = []
    resident._start_thread = held.append
    body = {"hub_id": "h1", "id": "svc_tcp", "is_enabled": True}

    resident.service_action("port", body)
    assert resident.service_action("port", body) == {}

    assert len(held) == 1


def test_a_failed_job_is_the_entrys_error_until_a_refresh(two_hubs_up):
    resident, _scripts = two_hubs_up
    handler = SlowHandler()
    handler.answer = {"code": "forward_failed", "params": {"detail": "in use"}}
    handler.release_it.set()
    resident._services["port"] = handler

    resident.service_action(
        "port", {"hub_id": "h1", "id": "svc_tcp", "is_enabled": True}
    )

    assert entry(resident, "h1", "svc_tcp")["last_error"] == {
        "code": "forward_failed",
        "params": {"detail": "in use"},
    }
    resident.refresh()
    assert entry(resident, "h1", "svc_tcp")["last_error"] is None


def test_a_lane_that_answers_busy_never_reaches_the_page(two_hubs_up):
    resident, _scripts = two_hubs_up
    handler = SlowHandler()
    handler.answer = {"code": "busy", "params": {"step": "switching"}}
    handler.release_it.set()
    resident._services["port"] = handler

    assert (
        resident.service_action(
            "port", {"hub_id": "h1", "id": "svc_tcp", "is_enabled": False}
        )
        == {}
    )
    assert entry(resident, "h1", "svc_tcp")["last_error"] is None


def test_a_mount_on_its_way_is_the_entrys_job(two_hubs_up):
    resident, _scripts = two_hubs_up

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

    resident._services["file"] = Mounting()

    assert entry(resident, "h1", "share_media")["job"] == "mounting"


def test_a_refresh_sets_each_hub_refreshing_and_clears_its_errors(two_hubs_up):
    resident, scripts = two_hubs_up
    home = resident._sessions["c1"]
    home._last_error = {"code": "hub_reply_unreadable", "params": {}}

    resident.refresh()

    assert [row["jobs"]["is_refreshing"] for row in resident.hubs()] == [True, True]
    assert resident.hubs()[0]["last_error"] is None
    (made,) = scripts.sockets_of("hub.lan")
    assert made.sent[-1]["is_refresh"] is True

    home._dispatch(made, "text", json.dumps(dict(HOME_STATE, hash="s9")))
    assert [row["jobs"]["is_refreshing"] for row in resident.hubs()] == [False, True]


def test_a_refresh_while_a_hub_refreshes_is_dropped(two_hubs_up):
    resident, scripts = two_hubs_up
    resident.refresh()
    (made,) = scripts.sockets_of("hub.lan")
    sent = len(made.sent)

    resident.refresh()

    assert len(made.sent) == sent


def test_a_disabled_hub_does_not_refresh(two_hubs_up):
    resident, _scripts = two_hubs_up
    office = resident._sessions["c2"]
    office._dispatch(
        ScriptedSocket([]), "text", json.dumps(dict(OFFICE_STATE, is_disabled=True))
    )

    resident.refresh()

    assert [row["jobs"]["is_refreshing"] for row in resident.hubs()] == [True, False]


def test_a_leave_is_shown_before_the_hub_is_left(two_hubs_up, monkeypatch):
    resident, _scripts = two_hubs_up
    monkeypatch.setattr(
        channel.GatewayHttpChannel, "post", lambda self, path, payload: {}
    )
    held = []
    resident._start_thread = held.append

    resident.leave("h2")
    resident.leave("h2")

    assert len(held) == 1
    assert [row["jobs"]["is_leaving"] for row in resident.hubs()] == [False, True]
    held[0]()
    assert [row["hub_id"] for row in resident.hubs()] == ["h1"]


def test_leaving_a_hub_nobody_joined_is_a_key_error(two_hubs_up):
    resident, _scripts = two_hubs_up

    with pytest.raises(KeyError):
        resident.leave("h9")


def test_a_forgotten_binding_leaves_a_notice(two_hubs_up, monkeypatch):
    resident, _scripts = two_hubs_up
    monkeypatch.setattr(resident_module, "CLIENT_NOTICE_S", 0.05)
    office = resident._sessions["c2"]

    office._unbind({"code": "binding_unknown", "params": {}})

    (notice,) = resident.notices()
    assert (notice["code"], notice["params"]) == ("binding_unknown", {"hub": "office"})
    assert notice["id"]
    assert [row["hub_id"] for row in resident.hubs()] == ["h1"]
    wait_until(lambda: resident.notices() == [])
    assert resident.notices() == []


def test_a_closed_notice_is_gone_and_a_refresh_drops_every_notice(two_hubs_up):
    resident, _scripts = two_hubs_up
    resident._add_notice("binding_unknown", {"hub": "office"})
    resident._add_notice("binding_unknown", {"hub": "lab"})
    first, second = resident.notices()

    resident.close_notice(first["id"])

    assert resident.notices() == [second]
    resident.close_notice("nobody")
    assert resident.notices() == [second]

    resident.refresh()

    assert resident.notices() == []


def leave_with_hub_answering(resident, monkeypatch, answer):
    """Press Leave on the office hub while the hub answers its leave with
    ``answer``; returns the binding ids on disk at each post."""
    seen = []

    def post(self, path, payload):
        seen.append([binding["id"] for binding in enrollment.bindings()])
        raise answer

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post, raising=True)
    resident.leave("h2")
    wait_until(lambda: seen)
    return seen


@pytest.mark.parametrize(
    "answer",
    [GatewayUnreachable("cannot reach hub"), GatewayRefused("401")],
    ids=["unreachable", "token_rejected"],
)
def test_a_leave_forgets_the_binding_and_the_row_whatever_the_hub_answers(
    two_hubs_up, monkeypatch, answer
):
    resident, _scripts = two_hubs_up
    released_handlers(resident)

    seen = leave_with_hub_answering(resident, monkeypatch, answer)

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


def test_a_token_entry_opens_as_a_job(two_hubs_up, monkeypatch):
    resident, _scripts = two_hubs_up
    token_entry = {
        "hub_id": "h1",
        "id": "cloudcli_d1_alice",
        "type": "web",
        "payload": {"url": "http://h:3001/", "is_token_required": True},
    }
    monkeypatch.setattr(resident, "service_entries", lambda: [token_entry])

    assert resident._entry_job("web", {"hub_id": "h1", "id": "cloudcli_d1_alice"}) == (
        "h1/cloudcli_d1_alice",
        "opening",
    )


def test_every_web_entry_opens_as_a_job_and_its_disconnect_is_one(two_hubs_up):
    resident, _scripts = two_hubs_up

    assert resident._entry_job("web", {"hub_id": "h1", "id": "svc_wiki"}) == (
        "h1/svc_wiki",
        "opening",
    )
    assert resident._entry_job(
        "web", {"hub_id": "h1", "id": "svc_wiki", "is_enabled": False}
    ) == ("h1/svc_wiki", "disconnecting")


# --- the way in, the panel and the connect stream ---


def test_the_hub_row_says_the_way_in_and_whether_the_panel_is_allowed(two_hubs_up):
    resident, _scripts = two_hubs_up
    home = resident._sessions["c1"]

    home._take_state(dict(HOME_STATE, reached_through="relay", is_panel_allowed=True))

    row, office = resident.hubs()
    assert (row["reached_through"], row["is_panel_allowed"]) == ("relay", True)
    assert (office["reached_through"], office["is_panel_allowed"]) == ("", False)


def test_open_connect_opens_a_connect_stream_on_the_hub_named(two_hubs_up):
    resident, scripts = two_hubs_up

    stream = resident.open_connect("h2", "svc_tcp")

    (made,) = scripts.sockets_of("office.lan")
    opened = [frame for frame in made.sent if frame.get("type") == "open"]
    assert opened == [
        {"type": "open", "stream": stream.stream_id, "kind": "connect", "id": "svc_tcp"}
    ]
    assert {"type": "credit", "stream": stream.stream_id, "bytes": 1048576} in made.sent
    with pytest.raises(GatewayUnreachable):
        resident.open_connect("h9", "svc_tcp")


def panel_allowed(resident) -> None:
    resident._sessions["c1"]._take_state(dict(HOME_STATE, is_panel_allowed=True))


def test_panel_makes_the_forward_and_opens_the_hubs_own_address(two_hubs_up):
    resident, scripts = two_hubs_up
    panel_allowed(resident)
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
    assert port >= 20000
    assert resident.platform.opened_urls == [f"http://panel-h1.localhost:{port}/"]
    socket.create_connection(("127.0.0.1", port), timeout=5).close()
    (made,) = scripts.sockets_of("hub.lan")
    wait_until(lambda: any(frame.get("is_panel") is True for frame in list(made.sent)))
    assert any(
        frame.get("kind") == "connect" and frame.get("is_panel") is True
        for frame in made.sent
    )
    resident._forwards.release()


def test_panel_on_a_mac_opens_the_loopback(two_hubs_up):
    resident, _scripts = two_hubs_up
    panel_allowed(resident)
    resident.platform.os_name = "darwin"
    resident._start_thread = run_inline

    assert resident.open_panel("h1") == {}

    port = resident.hubs()[0]["panel_forward"]
    assert resident.platform.opened_urls == [f"http://127.0.0.1:{port}/"]
    resident._forwards.release()


def test_panel_is_refused_without_the_permission_or_the_hub(two_hubs_up):
    resident, _scripts = two_hubs_up

    assert resident.open_panel("h1") == {
        "code": "permission_denied",
        "params": {"kind": "panel"},
    }
    assert resident.open_panel("h9")["code"] == "unknown_hub"
    panel_allowed(resident)
    resident._sessions["c1"]._drop_socket()
    assert resident.open_panel("h1")["code"] == "hub_unreachable"


def test_a_panel_that_cannot_listen_is_the_hub_rows_error_until_a_refresh(
    two_hubs_up,
):
    resident, _scripts = two_hubs_up
    panel_allowed(resident)
    resident._start_thread = run_inline
    held = socket.create_server(("127.0.0.1", 0))
    resident._ports.configure("h1/:panel", held.getsockname()[1])

    assert resident.open_panel("h1") == {}

    assert resident.hubs()[0]["last_error"]["code"] == "forward_failed"
    resident.refresh()
    assert resident.hubs()[0]["last_error"] is None
    held.close()


def test_leaving_a_hub_ends_its_panel_forward(two_hubs_up, monkeypatch):
    resident, _scripts = two_hubs_up
    panel_allowed(resident)
    resident._start_thread = run_inline
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    resident.open_panel("h1")
    port = resident.hubs()[0]["panel_forward"]

    resident.disconnect("h1")

    assert resident._forwards.forwards() == {}
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_an_entry_gone_from_the_hubs_list_ends_its_forward(two_hubs_up):
    resident, _scripts = two_hubs_up
    resident._services["port"].forward(hub_id="h1", entry_id="svc_tcp", port=0)
    resident._services["port"].forward(hub_id="h2", entry_id="svc_tcp", port=0)
    home = resident._sessions["c1"]

    home._take_state(dict(HOME_STATE, hash="s9", services=HUB_SERVICES[:2]))

    assert list(resident._forwards.forwards()) == ["h2/svc_tcp"]
    resident._forwards.release()


# --- Clear on the window's terminal ---


def test_clear_sends_ctrl_c_and_drops_the_output_until_the_stream_is_quiet(
    two_hubs_up, monkeypatch
):
    import neutrino_client.core.terminal as terminal_module

    monkeypatch.setattr(terminal_module, "CLIENT_TERMINAL_CLEAR_QUIET_S", 0.2)
    resident, scripts = two_hubs_up
    offered(resident)
    pieces = []
    resident.on_terminal_output = pieces.append
    terminal_id = resident.open_window_terminal("h1", "d1", 80, 24)["terminal_id"]
    session = resident._sessions["c1"]
    session._streams.take_credit({"type": "credit", "stream": 1, "bytes": 64})

    assert resident.clear_terminal(terminal_id) == {}
    session._streams.take_bytes(1, b"flood")
    wait_until(lambda: {"id": terminal_id, "clearing": False} in pieces)
    session._streams.take_bytes(1, b"$ ")
    wait_until(lambda: {"id": terminal_id, "data": b"$ "} in pieces)

    assert pieces[0] == {"id": terminal_id, "clearing": True}
    assert {"id": terminal_id, "data": b"flood"} not in pieces
    assert pieces[-1] == {"id": terminal_id, "data": b"$ "}
    (made,) = scripts.sockets_of("hub.lan")
    assert (1, b"\x03") in made.sent
    assert resident.clear_terminal("nobody")["code"] == "unknown_terminal"
    resident.close_terminal(terminal_id)


# --- a share on Windows, through the files adapter ---

FILES_PIPE = "\\\\.\\pipe\\neutrino_client_files"
FIRST_FILES_ADDRESS = "198.19.255.2"  # scan: allow
STRANGER_FILES_ADDRESS = "198.19.255.9"  # scan: allow


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
def windows_hub(config_path, monkeypatch):
    """A Windows resident whose home hub is connected and publishes a share."""
    bind(config_path, bindings=[dict(BINDING, gateway_url=HOME_URL)])
    platform = DrivePlatform()
    resident = ClientResident(log=discard, platform=platform, start_thread=run_inline)
    daemon = FilesDaemon()
    resident._files_adapter._ask = daemon
    scripts = sockets_by_hub(monkeypatch, {"hub.lan": [HOME_WELCOME, HOME_STATE]})
    session = resident._sessions["c1"]
    made = scripts(host="hub.lan")
    session._connect(made)
    kind, payload = made.recv()
    session._dispatch(made, kind, payload)
    yield resident, platform, daemon, made
    resident.shutdown()


def mount_z(resident) -> None:
    """Mount the home hub's share at Z:, the worker's pass run by hand."""
    assert (
        resident.service_action(
            "file",
            {
                "action": "mount",
                "hub_id": "h1",
                "id": "share_media",
                "username": "media",
                "password": "pw",
                "path": "Z:",
            },
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


def test_a_windows_mount_maps_the_machines_address_and_rides_a_connect_stream(
    windows_hub,
):
    resident, platform, daemon, made = windows_hub

    mount_z(resident)

    (call,) = platform.attach_calls
    assert call["share_url"] == f"//{FIRST_FILES_ADDRESS}/media"
    assert (call["location"], call["port"]) == ("Z:", 0)
    assert daemon.verbs == ["up"]
    endpoint = resident._files_adapter._endpoint
    client = socks_to(
        endpoint.port, endpoint.user, endpoint.password, FIRST_FILES_ADDRESS
    )
    assert client.recv(10)[:2] == b"\x05\x00"
    wait_until(lambda: any(frame.get("kind") == "connect" for frame in list(made.sent)))
    (opened,) = [frame for frame in made.sent if frame.get("kind") == "connect"]
    assert opened["id"] == "share_media"
    session = resident._sessions["c1"]
    session._streams.take_credit(
        {"type": "credit", "stream": opened["stream"], "bytes": 64}
    )
    client.sendall(b"smb")
    wait_until(lambda: (opened["stream"], b"smb") in list(made.sent))
    assert (opened["stream"], b"smb") in made.sent
    client.close()


def test_the_endpoint_refuses_another_port_or_address(windows_hub):
    resident, _platform, _daemon, made = windows_hub
    mount_z(resident)
    endpoint = resident._files_adapter._endpoint

    stranger = socks_to(
        endpoint.port, endpoint.user, endpoint.password, STRANGER_FILES_ADDRESS
    )

    assert stranger.recv(10)[:2] == b"\x05\x02"
    assert not any(frame.get("kind") == "connect" for frame in made.sent)
    stranger.close()


def test_unmounting_the_last_drive_takes_the_adapter_down(windows_hub):
    resident, _platform, daemon, _made = windows_hub
    mount_z(resident)
    (row,) = resident._services["file"].rows()

    assert (
        resident.service_action(
            "file", {"action": "unmount", "record_id": row["record_id"]}
        )
        == {}
    )

    assert daemon.verbs == ["up", "status", "down"]


def test_a_daemon_that_refuses_fails_the_row_with_the_adapters_code(windows_hub):
    resident, platform, daemon, _made = windows_hub
    daemon.refusal = {"code": "adapter_failed", "params": {"detail": "no wintun"}}

    mount_z(resident)

    (row,) = resident._services["file"].rows()
    assert (row["state"], row["code"]) == ("failed", "files_adapter_unavailable")
    assert row["params"] == {"detail": "no wintun"}
    assert platform.attach_calls == []


def test_leaving_a_hub_forgets_the_files_addresses_no_record_names(
    windows_hub, monkeypatch
):
    resident, _platform, daemon, _made = windows_hub
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda *a: {})
    daemon.refusal = {"code": "adapter_failed", "params": {"detail": "no wintun"}}
    mount_z(resident)
    assert list(resident._store.files_addresses()) == [FIRST_FILES_ADDRESS]

    resident.disconnect("h1")

    assert resident._store.mounts() == {}
    assert resident._store.files_addresses() == {}


def test_a_kept_record_holds_its_machines_address(windows_hub):
    resident, _platform, _daemon, _made = windows_hub
    mount_z(resident)

    assert resident._held_files_addresses() == {FIRST_FILES_ADDRESS}


def test_a_quit_takes_the_adapter_down_and_stops_the_endpoint(windows_hub):
    resident, _platform, daemon, _made = windows_hub
    mount_z(resident)

    resident.shutdown()

    assert daemon.verbs[-1] == "down"
    assert resident._files_adapter._endpoint.is_running is False
