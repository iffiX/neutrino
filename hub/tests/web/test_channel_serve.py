"""A client's ``join``: the link's waiting row binds and keeps the permission
it waited with, and a machine that has a row lands back on it with the link's
name and permission while the waiting row goes."""

import pytest

from neutrino_hub.modules.clients.permissions import ClientPermission
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.channel_serve import join_client
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
