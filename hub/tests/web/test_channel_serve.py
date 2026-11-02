"""A client's ``join``: the link's waiting row binds and keeps the permission
it waited with, and a machine that has a row lands back on it with the link's
name and permission while the waiting row goes. A package stream: how it ends
when the file or the agent goes. A client's report that lands after its
session ended: nothing raised and nothing else hidden."""

import asyncio
from types import SimpleNamespace

import pytest

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.clients.permissions import ClientPermission
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.channel.sessions import ChannelSession
from neutrino_hub.web import channel_serve
from neutrino_hub.web.channel_serve import join_client, serve_package_stream
from neutrino_hub.web.models import ChannelJoin

PUBLIC_KEY = "ab" * 32


class Events:
    def publish(self, event_type, key="", data=None):
        pass


class Runtime:
    def __init__(self):
        self.events = Events()
        self.forgotten: list = []

    def forget_client(self, client_id):
        self.forgotten.append(client_id)


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def joined(runtime, waiting_id, machine_id):
    request = ChannelJoin(
        ticket="t", role="client", machine_id=machine_id, name="laptop"
    )
    ticket = {"client_id": waiting_id, "name": "guest"}
    return join_client(runtime, request, ticket, public_key=PUBLIC_KEY)


def test_a_join_binds_the_waiting_row_with_the_permission_it_waited_with(config):
    waiting_id = ClientRegistry().create(
        "guest",
        permission=ClientPermission(entries={"ayakaleaf_d1": True}),
        link_expires_at=9e12,
    )

    client_id, token = joined(Runtime(), waiting_id, "m1")

    client = ClientRegistry().get(client_id)
    assert client_id == waiting_id and token
    assert not client.is_waiting
    assert client.permission == []
    assert client.permission_entries == {"ayakaleaf_d1": True}


def test_a_machine_with_a_row_lands_on_it_with_the_links_name_and_permission(
    config,
):
    registry = ClientRegistry()
    old_id = registry.create("old laptop")
    registry.record_seen(
        old_id, hostname="laptop", platform={}, version="0.6.0", machine_id="m1"
    )
    registry.set_permission(old_id, ["web", "panel"])
    waiting_id = registry.create(
        "guest",
        permission=ClientPermission(kinds=frozenset({"file"})),
        link_expires_at=9e12,
    )
    runtime = Runtime()

    client_id, _ = joined(runtime, waiting_id, "m1")

    client = ClientRegistry().get(client_id)
    assert client_id == old_id
    assert ClientRegistry().get(waiting_id) is None
    assert runtime.forgotten == [waiting_id]
    assert client.name == "guest"
    assert client.permission == ["file"]


class PackageStream:
    def __init__(self, *, is_offline=False):
        self.args = {"artifact": "agent", "digest": ""}
        self.is_offline = is_offline
        self.closed: list = []
        self.params: list = []

    async def send_bytes(self, data):
        if self.is_offline:
            raise AgentOfflineError("d1")

    async def close(self, code, params):
        if self.is_offline:
            raise AgentOfflineError("d1")
        self.closed.append(code)
        self.params.append(params)


def served_package(monkeypatch, stream, path):
    monkeypatch.setattr(
        "neutrino_hub.web.channel_serve._package_file",
        lambda *args: (path, "title", "name"),
    )
    runtime = SimpleNamespace(device_platform={"d1": {"os": "linux"}})
    session = SimpleNamespace(key="d1", name="machine")
    asyncio.run(serve_package_stream(runtime, session, stream))
    return stream.closed


def test_a_package_stream_says_nothing_to_an_agent_gone_mid_send(tmp_path, monkeypatch):
    package = tmp_path / "package"
    package.write_bytes(b"bytes")

    assert served_package(monkeypatch, PackageStream(is_offline=True), package) == []


def test_a_package_stream_names_a_file_it_cannot_read(tmp_path, monkeypatch):
    closed = served_package(monkeypatch, PackageStream(), tmp_path / "gone")

    assert closed == ["module_artifact_missing"]


def package_stream_failing(monkeypatch, stream, error):
    def failed(*args):
        raise error

    monkeypatch.setattr("neutrino_hub.web.channel_serve._package_file", failed)
    runtime = SimpleNamespace(device_platform={"d1": {"os": "linux"}})
    session = SimpleNamespace(key="d1", name="machine")
    asyncio.run(serve_package_stream(runtime, session, stream))


def test_a_failure_with_no_code_of_its_own_closes_the_package_stream(monkeypatch):
    """The agent waits on the stream until it closes, so a failure nothing
    names must not leave it open."""
    stream = PackageStream()

    package_stream_failing(monkeypatch, stream, ValueError("no sha256 digest"))

    assert stream.closed == ["module_cache_unwritable"]
    assert stream.params == [{"detail": "no sha256 digest"}]


def test_a_failure_with_the_agent_gone_closes_nothing(monkeypatch):
    stream = PackageStream(is_offline=True)

    package_stream_failing(monkeypatch, stream, RuntimeError("failed"))

    assert stream.closed == []


class RefusingChannel:
    """A local channel that takes the command ending a session."""

    def __init__(self):
        self.commands: list = []

    async def send_command(self, command, **fields):
        self.commands.append(command)
        return {}


def refused_session(client_id) -> ChannelSession:
    """A client's session the hub refused, whose transport has not ended it yet."""

    async def refuse():
        session = ChannelSession(
            key=client_id,
            role="client",
            session_id="s1",
            channel=RefusingChannel(),
            loop=asyncio.get_running_loop(),
        )
        await session.refuse("client_disabled", {})
        return session

    return asyncio.run(refuse())


def test_a_client_s_report_after_its_session_ended_raises_nothing(config, monkeypatch):
    """A report on its way at a Disable: the hub's log holds no traceback."""
    client_id = ClientRegistry().create("laptop", link_expires_at=9e12)
    client = ClientRegistry().get(client_id)
    session = refused_session(client_id)
    monkeypatch.setattr(
        channel_serve.channel_state,
        "client_state",
        lambda runtime, client_id: {"hash": "new"},
    )

    asyncio.run(channel_serve._ClientFrames(Runtime(), session, client).take_report({}))

    assert session.is_closed
    assert session.offered_hash is None


def test_a_client_s_report_keeps_a_failure_that_is_not_its_session_s_end(
    config, monkeypatch
):
    """A compose that fails is the hub's fault, whichever error it names."""
    client_id = ClientRegistry().create("laptop", link_expires_at=9e12)
    client = ClientRegistry().get(client_id)
    session = refused_session(client_id)

    def failed_compose(runtime, client_id):
        raise AgentOfflineError("another-machine")

    monkeypatch.setattr(channel_serve.channel_state, "client_state", failed_compose)

    with pytest.raises(AgentOfflineError):
        asyncio.run(
            channel_serve._ClientFrames(Runtime(), session, client).take_report({})
        )
