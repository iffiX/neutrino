"""The hub's side of the local channel, against a fake transport on a socket.

What these pin, line by line of protocol.md's "The hub's local channel": the
control connection opens with the secret and a wrong one is refused; the
``peer`` question is answered from the bindings' static keys with the
binding, the role and the psk, or ``binding_unknown`` and ``role_mismatch``;
the ``ticket`` question spends the ticket, records the key on the row and
answers ``{binding_id, token}``; a ``session_open`` followed by ``hello``
puts the device online and writes ``welcome``; a hello naming another
binding is a ``session_close`` with ``hello_invalid``; a ``report`` is
recorded and the state pushed once; ``leave`` drops the token and writes
``left`` as the last frame; ``session_end`` takes the device offline; a
``stream`` event for ``log`` is attached and accepted; the ``entry`` and
``token`` questions carry the judgments' answers; a client's ``persist`` is
relayed to the agent and the agent's ``reply`` answered back; and a control
connection that drops ends every session and is dialled again.
"""

import asyncio
import hashlib
import json

import pytest

from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
)
from neutrino_hub.modules.channel.local_channel import LocalChannelClient
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.channel.tickets import ChannelTicketRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.services import ConnectTarget
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.host_scope import link_scope
from neutrino_hub.web import channel_entry, channel_serve, channel_shell, channel_state
from neutrino_hub.web.channel_serve import ChannelControlHandler
from neutrino_hub.web.channel_shell import SessionReplyBook
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.shell_bridge import ShellSessionLedger
from neutrino_hub.web.task_stream import TaskStreamRegistry
from tests.conftest import StubPublishedServices
from tests.web.fake_transport import SECRET, FakeTransport

AGENT_KEY = "a1" * 32
CLIENT_KEY = "c1" * 32
STATE = {"hash": "h1", "modules": {}, "desktop": {}}


class FakeRuntime:
    """What the control handler reaches for, the judgments stubbed."""

    def __init__(self, tmp_path):
        self.agent_sessions = ChannelSessionRegistry(CHANNEL_ROLE_AGENT)
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.channel_port = ChannelPortGuard()
        self.enrollments = ChannelTicketRegistry(path=tmp_path / "tickets.json")
        self.events = PanelEventBus()
        self.tasks = TaskStreamRegistry()
        self.channel_replies = SessionReplyBook()
        self.shell_ledger = ShellSessionLedger()
        self.published_services = StubPublishedServices()
        self.device_platform: dict = {}
        self.device_hostname: dict = {}
        self.device_address: dict = {}
        self.device_metrics: dict = {}
        self.client_scope: dict = {}
        self.client_reached: dict = {}
        self.settings = {"listen_port": 8080}
        self.forgotten: list = []
        self.legacy_settled = 0
        self.channel = None

    def settle_legacy_channel(self):
        self.legacy_settled += 1
        return False

    def forget_device(self, key):
        self.forgotten.append(("device", key))

    def forget_client(self, key):
        self.forgotten.append(("client", key))


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def recorded(monkeypatch):
    """The report path, the states and the judgments, each stubbed and recorded."""
    seen = {"hello": [], "reports": [], "offline": [], "scopes": [], "entries": []}
    monkeypatch.setattr(
        channel_serve,
        "record_hello",
        lambda runtime, device, **fields: seen["hello"].append((device.id, fields)),
    )
    monkeypatch.setattr(
        channel_serve,
        "record_report",
        lambda runtime, device, report, **fields: seen["reports"].append(
            (device.id, report)
        ),
    )
    monkeypatch.setattr(
        channel_serve,
        "record_offline",
        lambda runtime, device: seen["offline"].append(device.id),
    )
    monkeypatch.setattr(channel_state, "agent_state", lambda runtime, key: dict(STATE))
    monkeypatch.setattr(
        channel_state,
        "client_state",
        lambda runtime, key: {"hash": "c1", "services": [], "apps": []},
    )
    monkeypatch.setattr(
        channel_state,
        "note_client_scope",
        lambda runtime, key, **fields: seen["scopes"].append((key, fields))
        or link_scope(""),
    )
    monkeypatch.setattr(channel_state, "push_states", lambda runtime, role: None)
    monkeypatch.setattr(
        channel_serve,
        "welcome_frame",
        lambda: {"type": "welcome", "protocol": 4, "role": "hub", "id": "hub-1"},
    )
    monkeypatch.setattr(
        channel_serve, "panel_material", lambda runtime, client_id: ("", {"token": "t"})
    )
    monkeypatch.setattr(
        channel_serve,
        "service_material",
        lambda runtime, client_id, entry_id: (
            ("", {"password": "p"})
            if entry_id == "rdp_1"
            else ("service_unknown", {"service_id": entry_id})
        ),
    )
    return seen


def bound_device(config) -> str:
    registry = DeviceRegistry()
    device = registry.create("box", machine_id="m-1")
    registry.issue_token(device.id)
    registry.set_public_key(device.id, AGENT_KEY)
    return device.id


def bound_client(config) -> str:
    registry = ClientRegistry()
    client_id = registry.create("laptop")
    registry.issue_token(client_id)
    registry.set_public_key(client_id, CLIENT_KEY)
    return client_id


async def started(tmp_path, runtime):
    """A fake transport listening, and the hub's client connected to it."""
    fake = FakeTransport(str(tmp_path / "transport.sock"))
    await fake.start()
    channel = LocalChannelClient(
        address=fake.path,
        secret_of=lambda: SECRET,
        handler=ChannelControlHandler(runtime),
    )
    runtime.channel = channel
    task = asyncio.create_task(channel.run())
    await fake.wait_control()
    return fake, channel, task


async def stopped(fake, channel, task):
    channel.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await fake.stop()


async def admitted_agent(fake, device_id, session="s1"):
    """An agent's session open and its hello answered with welcome."""
    await fake.event(
        "session_open",
        session=session,
        binding_id=device_id,
        role="agent",
        address="192.168.100.7",
        listener="main",
    )
    await fake.frame(
        session,
        {
            "type": "hello",
            "protocol": 4,
            "role": "agent",
            "id": device_id,
            "name": "box",
            "software": "neutrino_agent/0.6.0",
        },
    )
    return await fake.next_frame()


def test_the_control_connection_opens_with_the_secret(config, recorded, tmp_path):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            is_connected = channel.is_connected
        finally:
            await stopped(fake, channel, task)
        return is_connected, fake.control_count, fake.refused_secrets

    assert asyncio.run(scenario()) == (True, 1, 0)


def test_a_wrong_secret_is_refused_and_dialled_again(config, recorded, tmp_path):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        fake = FakeTransport(str(tmp_path / "transport.sock"))
        await fake.start()
        channel = LocalChannelClient(
            address=fake.path,
            secret_of=lambda: "bad",
            handler=ChannelControlHandler(runtime),
        )
        task = asyncio.create_task(channel.run())
        await asyncio.sleep(0.3)
        try:
            return fake.refused_secrets >= 1, channel.is_connected
        finally:
            await stopped(fake, channel, task)

    assert asyncio.run(scenario()) == (True, False)


def test_the_peer_question_names_the_binding_its_role_and_its_psk(
    config, recorded, tmp_path
):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        client_id = bound_client(config)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            agent = await fake.ask(
                "peer",
                public_key=AGENT_KEY,
                role="agent",
                protocol=4,
                address="a",
                listener="main",
            )
            client = await fake.ask(
                "peer",
                public_key=CLIENT_KEY,
                role="client",
                protocol=4,
                address="a",
                listener="main",
            )
            mismatch = await fake.ask(
                "peer",
                public_key=AGENT_KEY,
                role="client",
                protocol=4,
                address="a",
                listener="main",
            )
            unknown = await fake.ask(
                "peer",
                public_key="ff" * 32,
                role="agent",
                protocol=4,
                address="a",
                listener="main",
            )
            old = await fake.ask(
                "peer",
                public_key=AGENT_KEY,
                role="agent",
                protocol=3,
                address="a",
                listener="main",
            )
        finally:
            await stopped(fake, channel, task)
        device = DeviceRegistry().get(device_id)
        return (
            agent,
            client,
            mismatch,
            unknown,
            old,
            device.client.token_sha256,
            client_id,
        )

    agent, client, mismatch, unknown, old, token_sha256, client_id = asyncio.run(
        scenario()
    )
    assert agent == {
        "binding_id": agent["binding_id"],
        "role": "agent",
        "psk": token_sha256,
    }
    assert client["binding_id"] == client_id and client["role"] == "client"
    assert len(client["psk"]) == 64
    assert mismatch == {"code": "role_mismatch", "params": {"role": "client"}}
    assert unknown == {"code": "binding_unknown", "params": {}}
    assert old["code"] == "protocol_too_old"


def test_the_ticket_question_spends_the_ticket_and_records_the_key(
    config, recorded, tmp_path
):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        ticket, _ = runtime.enrollments.make(kind="agent", name="box")
        fake, channel, task = await started(tmp_path, runtime)
        try:
            answer = await fake.ask(
                "ticket",
                ticket=ticket,
                role="agent",
                protocol=4,
                public_key=AGENT_KEY,
                machine_id="m-9",
                name="box",
                software="neutrino_agent/0.6.0",
                platform={"os": "linux", "family": "debian", "arch": "amd64"},
                address="192.168.100.7",
                listener="main",
            )
            spent = await fake.ask(
                "ticket",
                ticket=ticket,
                role="agent",
                protocol=4,
                public_key=AGENT_KEY,
                machine_id="m-9",
                name="box",
                software="neutrino_agent/0.6.0",
                platform={},
                address="a",
                listener="main",
            )
        finally:
            await stopped(fake, channel, task)
        device = DeviceRegistry().get(answer["binding_id"])
        return answer, spent, device

    answer, spent, device = asyncio.run(scenario())
    assert set(answer) == {"binding_id", "token"}
    assert device.client.public_key == AGENT_KEY
    assert (
        device.client.token_sha256
        == hashlib.sha256(answer["token"].encode()).hexdigest()
    )
    assert device.machine_id == "m-9"
    assert spent == {"code": "ticket_spent", "params": {}}


def test_a_hello_on_an_opened_session_is_welcomed_and_puts_the_device_online(
    config, recorded, tmp_path
):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            welcome = await admitted_agent(fake, device_id)
            is_online = runtime.agent_sessions.is_online(device_id)
            await fake.frame(
                "s1", {"type": "report", "state_hash": "", "modules": {}, "machine": {}}
            )
            state = await fake.next_frame()
            await fake.event("session_end", session="s1", reason="")
            await asyncio.sleep(0.1)
            is_online_after = runtime.agent_sessions.is_online(device_id)
        finally:
            await stopped(fake, channel, task)
        return welcome, is_online, state, is_online_after, recorded

    welcome, is_online, state, is_online_after, seen = asyncio.run(scenario())
    assert welcome["session"] == "s1" and welcome["frame"]["type"] == "welcome"
    assert is_online is True
    assert state["frame"] == {"type": "state", **STATE}
    assert [device for device, _ in seen["hello"]] == [device_id_of(seen)]
    assert len(seen["reports"]) == 1
    assert is_online_after is False
    assert seen["offline"] == [device_id_of(seen)]


def device_id_of(seen) -> str:
    return seen["hello"][0][0]


def test_a_hello_naming_another_binding_closes_the_session(config, recorded, tmp_path):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await fake.event(
                "session_open",
                session="s1",
                binding_id=device_id,
                role="agent",
                address="a",
                listener="main",
            )
            await fake.frame(
                "s1",
                {
                    "type": "hello",
                    "protocol": 4,
                    "role": "agent",
                    "id": "other",
                    "name": "x",
                    "software": "neutrino_agent/0.6.0",
                },
            )
            command = await fake.next_command()
        finally:
            await stopped(fake, channel, task)
        return command, runtime.agent_sessions.is_online(device_id)

    command, is_online = asyncio.run(scenario())
    assert command["command"] == "session_close"
    assert command["session"] == "s1"
    assert command["code"] == "hello_invalid"
    assert is_online is False


def test_a_leave_drops_the_token_and_writes_left_as_the_last_frame(
    config, recorded, tmp_path
):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await fake.event(
                "session_open",
                session="s1",
                binding_id=device_id,
                role="agent",
                address="a",
                listener="main",
            )
            await fake.frame("s1", {"type": "leave"})
            left = await fake.next_frame()
        finally:
            await stopped(fake, channel, task)
        device = DeviceRegistry().get(device_id)
        return (
            left,
            device.client.token_sha256,
            device.client.public_key,
            runtime.forgotten,
        )

    left, token, key, forgotten = asyncio.run(scenario())
    assert left["frame"] == {"type": "left"} and left["is_last"] is True
    assert token is None and key is None
    assert forgotten == [("device", forgotten[0][1])]


def test_a_log_stream_an_agent_opens_is_attached_accepted_and_read(
    config, recorded, tmp_path
):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await admitted_agent(fake, device_id)
            end = await fake.announce_stream(
                7, "s1", {"kind": "log", "module": "gitea"}
            )
            accepted = await end.read()
            await end.send(3, b"installing\n")
            await end.close("", {"state": "installed"})
            await asyncio.sleep(0.2)
            streams = runtime.tasks.streams()
        finally:
            await stopped(fake, channel, task)
        return accepted, fake.attaches, streams

    accepted, attaches, streams = asyncio.run(scenario())
    assert accepted == (2, b"")
    assert attaches[0]["stream"] == 7
    assert len(streams) == 1 and streams[0].label.endswith("gitea")


def test_the_entry_and_token_questions_carry_the_judgments_answers(
    config, recorded, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        channel_entry,
        "connect_target",
        lambda runtime, client_id, open_body, **_: (
            "",
            {},
            ConnectTarget(
                "dev-1", "", 3000, kind="web", provider="dev-1", protocol="tcp"
            ),
        ),
    )

    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        client_id = bound_client(config)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await admitted_agent(fake, device_id, session="agent-s")
            # The agent's session id is what a target names; the stub's
            # device is this one.
            runtime.agent_sessions.get(device_id).key = "dev-1"
            runtime.agent_sessions._sessions["dev-1"] = (
                runtime.agent_sessions._sessions.pop(device_id)
            )
            await fake.event(
                "session_open",
                session="client-s",
                binding_id=client_id,
                role="client",
                address="a",
                listener="main",
            )
            await fake.frame(
                "client-s",
                {
                    "type": "hello",
                    "protocol": 4,
                    "role": "client",
                    "id": client_id,
                    "name": "laptop",
                    "software": "neutrino_client/0.6.0",
                },
            )
            await fake.next_frame()
            entry = await fake.ask(
                "entry",
                session="client-s",
                binding_id=client_id,
                open={"kind": "connect", "id": "gitea_dev-1_web"},
            )
            unknown_kind = await fake.ask(
                "entry",
                session="client-s",
                binding_id=client_id,
                open={"kind": "package"},
            )
            token = await fake.ask(
                "token",
                session="client-s",
                binding_id=client_id,
                frame={"request": "r1", "is_panel": True},
            )
            material = await fake.ask(
                "token",
                session="client-s",
                binding_id=client_id,
                frame={"request": "r2", "id": "rdp_1"},
            )
            refused = await fake.ask(
                "token",
                session="client-s",
                binding_id=client_id,
                frame={"request": "r3", "id": "nothing"},
            )
        finally:
            await stopped(fake, channel, task)
        return entry, unknown_kind, token, material, refused

    entry, unknown_kind, token, material, refused = asyncio.run(scenario())
    assert entry == {
        "kind": "web",
        "device_id": "dev-1",
        "target": {
            "session": "agent-s",
            "open": {"kind": "connect", "port": 3000, "protocol": "tcp"},
        },
    }
    assert unknown_kind == {"code": "kind_unknown", "params": {"kind": "package"}}
    assert token == {"params": {"token": "t"}}
    assert material == {"params": {"password": "p"}}
    assert refused == {"code": "service_unknown", "params": {"service_id": "nothing"}}


def test_a_clients_persist_is_relayed_and_the_agents_reply_answered_back(
    config, recorded, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        channel_shell, "judge_terminal", lambda client_id, device_id: ("", {})
    )
    monkeypatch.setattr(
        channel_shell, "is_session_refused", lambda *args, **kwargs: False
    )

    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        client_id = bound_client(config)
        monkeypatch.setattr(
            channel_shell, "device_of_session", lambda sessions, session_id: device_id
        )

        async def no_sharing(*args, **kwargs):
            return None

        monkeypatch.setattr(channel_shell, "record_sharing", no_sharing)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await admitted_agent(fake, device_id, session="agent-s")
            await fake.event(
                "session_open",
                session="client-s",
                binding_id=client_id,
                role="client",
                address="a",
                listener="main",
            )
            await fake.frame(
                "client-s",
                {
                    "type": "hello",
                    "protocol": 4,
                    "role": "client",
                    "id": client_id,
                    "name": "laptop",
                    "software": "neutrino_client/0.6.0",
                },
            )
            await fake.next_frame()
            await fake.frame(
                "client-s",
                {
                    "type": "persist",
                    "request": "p1",
                    "session_id": "sh-1",
                    "is_shared": True,
                },
            )
            relayed = await fake.next_frame()
            await fake.frame(
                "agent-s",
                {
                    "type": "reply",
                    "request": relayed["frame"]["request"],
                    "code": "",
                    "params": {},
                },
            )
            answered = await fake.next_frame()
        finally:
            await stopped(fake, channel, task)
        return relayed, answered

    relayed, answered = asyncio.run(scenario())
    assert relayed["session"] == "agent-s"
    assert relayed["frame"]["type"] == "persist"
    assert (
        relayed["frame"]["session_id"] == "sh-1"
        and relayed["frame"]["is_shared"] is True
    )
    assert answered == {
        "frame": {"type": "reply", "request": "p1", "code": "", "params": {}},
        "session": "client-s",
    }


def test_a_dropped_control_connection_ends_every_session_and_is_dialled_again(
    config, recorded, tmp_path
):
    async def scenario():
        runtime = FakeRuntime(tmp_path)
        device_id = bound_device(config)
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await admitted_agent(fake, device_id)
            await fake.drop_control()
            await asyncio.sleep(0.2)
            offline = not runtime.agent_sessions.is_online(device_id)
            await fake.wait_control()
            await admitted_agent(fake, device_id, session="s2")
            online_again = runtime.agent_sessions.is_online(device_id)
        finally:
            await stopped(fake, channel, task)
        return offline, online_again, fake.control_count

    assert asyncio.run(scenario()) == (True, True, 2)
