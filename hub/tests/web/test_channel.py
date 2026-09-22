"""The channel's three routes, driven end to end through the test client.

What these pin is the door both peers must match: a join admitted by
protocol before its ticket is spent, a ticket spent once, a ticket for the
other role refused, a blank ticket landing on the row whose machine id
matches, a client landing on the row that machine already had, a leave
removing the binding; and the hello gate on the socket,
where a refusal is one ``refused`` frame then close 4000, a second socket
for one binding closes the first with 4010, and a refusal leaves the
binding standing.
"""

import time
from functools import partial

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.channel.constants import (
    CHANNEL_CLOSE_REFUSED,
    CHANNEL_CLOSE_REPLACED,
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
    PROTOCOL,
)
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.web import identity
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers import channel as channel_router
from tests.conftest import StubDesiredStates, StubPublishedServices

MACHINE = "machine-of-testbox"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}


class FakeRuntime:
    """Only the parts of the runtime the three routes touch."""

    def __init__(self):
        self.events = PanelEventBus()
        self.enrollments: dict = {}
        self.device_metrics = {}
        self.device_modules = {}
        self.device_platform = {}
        self.device_hostname = {}
        self.device_accounts = {}
        self.device_interfaces = {}
        self.device_address = {}
        self.device_scope = {}
        self.device_last_error = {}
        self.client_scope = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.desired_states = StubDesiredStates()
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.forgotten: list = []
        self.desired = ("", {"modules": {}, "desktop": {"seat_password": ""}})

    def host_scopes(self):
        return []

    def desired_state_for(self, device):
        return self.desired

    def push_desired_state(self, key):
        return None

    def forget_device(self, device_id):
        self.forgotten.append(("agent", device_id))

    def forget_client(self, client_id):
        self.forgotten.append(("client", client_id))


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    identity.ensure_hub_identity()
    identity.set_hub_name("hub-one")
    monkeypatch.setattr(channel_router, "HUB_VERSION", "1.2.3")
    monkeypatch.setattr(channel_router, "CHANNEL_HELLO_TIMEOUT_S", 0.3)
    app = FastAPI()
    app.include_router(channel_router.router)
    runtime = FakeRuntime()
    app.state.runtime = runtime
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def ticket(runtime, token: str, **fields) -> None:
    runtime.enrollments[token] = {
        "name": "",
        "device_id": None,
        "expires_at": time.time() + 600,
        **fields,
    }


def join_body(**fields) -> dict:
    body = {
        "ticket": "t1",
        "role": "agent",
        "protocol": PROTOCOL,
        "machine_id": MACHINE,
        "name": "box",
        "software": "neutrino_agent/1.2.3",
        "platform": PLATFORM,
    }
    body.update(fields)
    return body


def joined_device(client, runtime, **fields) -> dict:
    """A device joined on a blank ticket; the binding it was handed."""
    ticket(runtime, "t1")
    answer = client.post("/api/channel/join", json=join_body(**fields))
    assert answer.status_code == 200, answer.json()
    return answer.json()


def joined_client(client, runtime, name: str = "alice") -> tuple:
    """A client joined on its link; the row's id and the binding."""
    client_id = ClientRegistry().create(name)
    ticket(runtime, "c1", kind="client", client_id=client_id)
    answer = client.post(
        "/api/channel/join",
        json=join_body(
            ticket="c1", role="client", software="neutrino_client/1.2.3", name="lap"
        ),
    )
    assert answer.status_code == 200, answer.json()
    return client_id, answer.json()


def hello(binding: dict, **fields) -> dict:
    body = {
        "type": "hello",
        "protocol": PROTOCOL,
        "role": "agent",
        "id": binding["id"],
        "name": "box",
        "software": "neutrino_agent/1.2.3",
        "token": binding["token"],
    }
    body.update(fields)
    return body


def closed_with(socket) -> tuple:
    """The close code and reason the hub ended the socket with."""
    message = socket.receive()
    assert message["type"] == "websocket.close"
    return message["code"], message.get("reason", "")


def refused_with(socket) -> dict:
    """The refused frame, followed by the refused close."""
    frame = socket.receive_json()
    assert frame["type"] == "refused"
    assert closed_with(socket)[0] == CHANNEL_CLOSE_REFUSED
    return frame


def welcomed(client, binding: dict, **fields):
    """A socket past its hello, with the welcome read."""
    socket = client.websocket_connect("/api/channel/socket")
    socket.__enter__()
    socket.send_json(hello(binding, **fields))
    return socket, socket.receive_json()


def wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- join ---


def test_a_blank_ticket_lands_on_a_new_row_with_a_token(api):
    client, runtime = api

    binding = joined_device(client, runtime)

    device = DeviceRegistry().get(binding["id"])
    assert device is not None
    assert device.machine_id == MACHINE
    assert device.name == "box"
    assert DeviceRegistry().find_by_token(binding["token"]).id == binding["id"]
    assert runtime.enrollments == {}
    assert runtime.device_platform[binding["id"]] == PLATFORM
    assert runtime.device_hostname[binding["id"]] == "box"
    assert runtime.device_address[binding["id"]] == "testclient"


def test_a_blank_ticket_lands_on_the_row_whose_machine_id_matches(api):
    client, runtime = api
    stored = DeviceRegistry().create("xenode", machine_id=MACHINE)

    binding = joined_device(client, runtime)

    assert binding["id"] == stored.id
    assert DeviceRegistry().get(stored.id).name == "xenode"


def test_a_ticket_made_for_a_row_lands_on_it_and_names_it(api):
    client, runtime = api
    stored = DeviceRegistry().create(None)
    ticket(runtime, "t1", device_id=stored.id, name="laptop")

    answer = client.post("/api/channel/join", json=join_body())

    assert answer.json()["id"] == stored.id
    row = DeviceRegistry().get(stored.id)
    assert (row.name, row.machine_id) == ("laptop", MACHINE)


def test_a_ticket_is_spent_once(api):
    client, runtime = api
    joined_device(client, runtime)

    again = client.post("/api/channel/join", json=join_body())

    assert again.status_code == 401
    assert again.json()["detail"] == {"code": "ticket_spent", "params": {}}


def test_an_unknown_or_expired_ticket_is_ticket_spent(api):
    client, runtime = api
    ticket(runtime, "old", expires_at=time.time() - 1)

    unknown = client.post("/api/channel/join", json=join_body(ticket="nonsense"))
    expired = client.post("/api/channel/join", json=join_body(ticket="old"))

    assert unknown.status_code == expired.status_code == 401
    assert expired.json()["detail"]["code"] == "ticket_spent"
    assert runtime.enrollments == {}


def test_a_rejected_protocol_spends_no_ticket(api):
    client, runtime = api
    ticket(runtime, "t1")

    old = client.post("/api/channel/join", json=join_body(protocol=0))
    new = client.post("/api/channel/join", json=join_body(protocol=PROTOCOL + 1))

    assert old.status_code == new.status_code == 409
    assert old.json()["detail"]["code"] == "protocol_too_old"
    assert new.json()["detail"] == {
        "code": "protocol_too_new",
        "params": {"peer": PROTOCOL + 1, "hub": PROTOCOL, "min": PROTOCOL},
    }
    assert "t1" in runtime.enrollments
    assert DeviceRegistry().all_stored() == []


def test_a_device_ticket_refuses_a_client_and_the_other_way_round(api):
    client, runtime = api
    ticket(runtime, "t1")
    client_id = ClientRegistry().create("alice")
    ticket(runtime, "c1", kind="client", client_id=client_id)

    as_client = client.post("/api/channel/join", json=join_body(role="client"))
    as_agent = client.post(
        "/api/channel/join", json=join_body(ticket="c1", role="agent")
    )
    as_nothing = client.post("/api/channel/join", json=join_body(role="hub"))

    assert as_client.status_code == as_agent.status_code == 409
    assert as_client.json()["detail"] == {
        "code": "role_mismatch",
        "params": {"role": "client"},
    }
    assert as_agent.json()["detail"]["params"] == {"role": "agent"}
    assert as_nothing.json()["detail"]["code"] == "role_mismatch"
    assert runtime.enrollments == {}


def test_a_client_joins_on_its_link_and_the_row_records_what_it_said(api):
    client, runtime = api

    client_id, binding = joined_client(client, runtime)

    assert binding["id"] == client_id
    stored = ClientRegistry().get(client_id)
    assert stored.is_enrolled
    assert (stored.hostname, stored.version) == ("lap", "1.2.3")
    assert stored.platform == PLATFORM
    assert stored.machine_id == MACHINE
    assert ClientRegistry().find_by_token(binding["token"]).id == client_id


def test_a_client_that_joins_again_lands_on_the_row_it_had(api):
    client, runtime = api
    first_id, first = joined_client(client, runtime)
    ClientRegistry().set_disabled(first_id, True)
    ClientRegistry().set_ai_key_id(first_id, "k1")
    minted_id = ClientRegistry().create("alice-again")
    ticket(runtime, "c2", kind="client", client_id=minted_id, name="alice-again")

    answer = client.post(
        "/api/channel/join",
        json=join_body(
            ticket="c2", role="client", software="neutrino_client/1.2.4", name="lap"
        ),
    )

    assert answer.status_code == 200, answer.json()
    binding = answer.json()
    assert binding["id"] == first_id
    assert ClientRegistry().get(minted_id) is None
    assert runtime.forgotten == [("client", minted_id)]
    row = ClientRegistry().get(first_id)
    assert row.name == "alice-again"
    assert (row.is_disabled, row.ai_key_id, row.version) == (True, "k1", "1.2.4")
    assert ClientRegistry().find_by_token(binding["token"]).id == first_id
    assert ClientRegistry().find_by_token(first["token"]) is None


def test_a_client_on_another_machine_keeps_the_row_its_link_made(api):
    client, runtime = api
    first_id, _ = joined_client(client, runtime)
    minted_id = ClientRegistry().create("bob-laptop")
    ticket(runtime, "c2", kind="client", client_id=minted_id, name="bob-laptop")

    answer = client.post(
        "/api/channel/join",
        json=join_body(ticket="c2", role="client", machine_id="machine-of-another"),
    )

    assert answer.json()["id"] == minted_id
    assert ClientRegistry().get(first_id) is not None
    assert runtime.forgotten == []


def test_a_client_ticket_for_a_row_that_is_gone_is_ticket_spent(api):
    client, runtime = api
    ticket(runtime, "c1", kind="client", client_id="gone")

    answer = client.post(
        "/api/channel/join", json=join_body(ticket="c1", role="client")
    )

    assert answer.status_code == 401
    assert answer.json()["detail"]["code"] == "ticket_spent"


# --- leave ---


def test_an_agent_leaving_loses_its_token_and_keeps_its_row(api):
    client, runtime = api
    binding = joined_device(client, runtime)

    answer = client.post("/api/channel/leave", json=binding)

    assert answer.status_code == 200 and answer.json() == {}
    row = DeviceRegistry().get(binding["id"])
    assert row is not None and not row.is_managed
    assert runtime.forgotten == [("agent", binding["id"])]


def test_an_agent_leaving_keeps_its_module_configuration(api, tmp_path, monkeypatch):
    """The panel's remove is what deletes ``config/devices/<id>/``; a leave
    drops the socket and the memory and leaves the files."""
    client, runtime = api
    binding = joined_device(client, runtime)
    monkeypatch.setattr(
        runtime, "forget_device", partial(PanelRuntime.forget_device, runtime)
    )
    DesiredStateStore().set_want(binding["id"], "samba", "running")

    answer = client.post("/api/channel/leave", json=binding)

    assert answer.status_code == 200
    assert not DeviceRegistry().get(binding["id"]).is_managed
    assert (tmp_path / "devices" / binding["id"] / "modules.json").is_file()
    assert DesiredStateStore().want_of(binding["id"], "samba") == "running"


def test_a_client_leaving_takes_its_row(api):
    client, runtime = api
    client_id, binding = joined_client(client, runtime)

    answer = client.post("/api/channel/leave", json=binding)

    assert answer.status_code == 200
    assert ClientRegistry().get(client_id) is None
    assert runtime.forgotten == [("client", client_id)]


def test_a_leave_with_the_wrong_token_or_id_is_binding_unknown(api):
    client, runtime = api
    binding = joined_device(client, runtime)

    wrong_token = client.post(
        "/api/channel/leave", json={"id": binding["id"], "token": "x"}
    )
    wrong_id = client.post(
        "/api/channel/leave", json={"id": "other", "token": binding["token"]}
    )

    assert wrong_token.status_code == wrong_id.status_code == 401
    assert wrong_id.json()["detail"] == {"code": "binding_unknown", "params": {}}
    assert DeviceRegistry().get(binding["id"]).is_managed


# --- the hello gate ---


def test_a_late_hello_is_refused_then_closed_4000(api):
    """A rejected hello is a refused frame and then the close, like every
    other refusal; a peer written from the protocol page reads it so."""
    client, _ = api

    with client.websocket_connect("/api/channel/socket") as socket:
        assert refused_with(socket) == {
            "type": "refused",
            "code": "hello_invalid",
            "params": {},
        }


def test_a_first_frame_that_is_no_hello_is_refused_then_closed_4000(api):
    client, _ = api

    with client.websocket_connect("/api/channel/socket") as socket:
        socket.send_json({"type": "report"})
        refused = socket.receive_json()
        assert refused["code"] == "hello_invalid"
        assert closed_with(socket) == (CHANNEL_CLOSE_REFUSED, "hello_invalid")


def test_a_hello_the_hub_cannot_read_is_refused_then_closed_4000(api):
    client, _ = api

    with client.websocket_connect("/api/channel/socket") as socket:
        socket.send_json({"type": "hello", "protocol": "one"})
        assert refused_with(socket)["code"] == "hello_invalid"


@pytest.mark.parametrize(
    ("protocol", "code"), [(0, "protocol_too_old"), (PROTOCOL + 1, "protocol_too_new")]
)
def test_a_protocol_outside_the_range_is_refused_then_closed_4000(api, protocol, code):
    client, runtime = api
    binding = joined_device(client, runtime)

    with client.websocket_connect("/api/channel/socket") as socket:
        socket.send_json(hello(binding, protocol=protocol))
        refused = refused_with(socket)

    assert refused == {
        "type": "refused",
        "code": code,
        "params": {"peer": protocol, "hub": PROTOCOL, "min": PROTOCOL},
    }
    # A refusal keeps the binding: the token still resolves.
    assert DeviceRegistry().find_by_token(binding["token"]).id == binding["id"]
    assert not runtime.agent_sessions.is_online(binding["id"])
    assert runtime.agent_sessions.last_seen_at(binding["id"]) is None


def test_a_token_no_binding_holds_is_binding_unknown(api):
    client, runtime = api
    binding = joined_device(client, runtime)

    with client.websocket_connect("/api/channel/socket") as socket:
        socket.send_json(hello(binding, token="nonsense"))  # scan: allow
        assert refused_with(socket)["code"] == "binding_unknown"
    with client.websocket_connect("/api/channel/socket") as socket:
        socket.send_json(hello(binding, id="other"))
        assert refused_with(socket)["code"] == "binding_unknown"
    assert not runtime.agent_sessions.is_online(binding["id"])


def test_a_hello_claiming_the_other_role_is_role_mismatch(api):
    client, runtime = api
    binding = joined_device(client, runtime)

    with client.websocket_connect("/api/channel/socket") as socket:
        socket.send_json(hello(binding, role="client"))
        refused = refused_with(socket)

    assert refused == {
        "type": "refused",
        "code": "role_mismatch",
        "params": {"role": "client"},
    }


# --- the welcome ---


def test_a_good_hello_is_welcomed_with_the_hubs_identity_card(api):
    client, runtime = api
    binding = joined_device(client, runtime)

    socket, welcome = welcomed(client, binding)
    try:
        assert welcome == {
            "type": "welcome",
            "protocol": PROTOCOL,
            "role": "hub",
            "id": identity.hub_id(),
            "name": "hub-one",
            "software": "neutrino_hub/1.2.3",
        }
        assert runtime.agent_sessions.is_online(binding["id"])
        session = runtime.agent_sessions.get(binding["id"])
        assert (session.name, session.software) == ("box", "neutrino_agent/1.2.3")
        assert session.version == "1.2.3"
        assert runtime.device_address[binding["id"]] == "testclient"
    finally:
        socket.__exit__(None, None, None)
    assert wait_until(lambda: not runtime.agent_sessions.is_online(binding["id"]))
    assert runtime.agent_sessions.last_seen_at(binding["id"])


def test_a_client_hello_lands_in_the_client_registry(api):
    client, runtime = api
    client_id, binding = joined_client(client, runtime)

    socket, welcome = welcomed(
        client, binding, role="client", software="neutrino_client/1.2.3"
    )
    try:
        assert welcome["role"] == "hub"
        assert runtime.client_sessions.is_online(client_id)
        assert not runtime.agent_sessions.is_online(client_id)
        assert runtime.client_scope[client_id].hub_address == "testserver"
    finally:
        socket.__exit__(None, None, None)


def test_a_second_socket_for_one_binding_replaces_the_first_with_4010(api):
    client, runtime = api
    binding = joined_device(client, runtime)
    first, _ = welcomed(client, binding)
    try:
        second, _ = welcomed(client, binding)
        try:
            assert closed_with(first) == (CHANNEL_CLOSE_REPLACED, "replaced")
            assert runtime.agent_sessions.is_online(binding["id"])
        finally:
            second.__exit__(None, None, None)
    finally:
        first.__exit__(None, None, None)
    assert wait_until(lambda: not runtime.agent_sessions.is_online(binding["id"]))
