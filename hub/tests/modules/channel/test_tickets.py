"""The open enrolment tickets on disk.

A ticket is written when made, as its hash beside its kind, the row it binds
and its expiry, in a file of mode 0600; a new store over the same file reads
back every ticket still open; a spent or expired ticket leaves the file.
"""

import hashlib
import json
import stat
import time

import pytest

from neutrino_hub.modules.channel import tickets as tickets_module
from neutrino_hub.modules.channel.constants import ENROLLMENT_TTL_S
from neutrino_hub.modules.channel.tickets import ChannelTicketRegistry


@pytest.fixture
def path(tmp_path):
    return tmp_path / "state" / "enrollment_tickets.json"


def on_disk(path) -> list:
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_ticket_is_on_disk_as_its_hash_with_its_role_subject_and_expiry(path):
    registry = ChannelTicketRegistry(path=path)

    ticket, expires_at = registry.make(kind="client", name="alice", client_id="c-1")

    assert on_disk(path) == [
        {
            "token_sha256": hashlib.sha256(ticket.encode()).hexdigest(),
            "kind": "client",
            "name": "alice",
            "device_id": None,
            "client_id": "c-1",
            "expires_at": expires_at,
        }
    ]
    assert expires_at == pytest.approx(time.time() + ENROLLMENT_TTL_S, abs=5)


def test_the_file_holds_no_ticket_and_is_mode_0600(path):
    registry = ChannelTicketRegistry(path=path)

    device_ticket, _ = registry.make(kind="agent", device_id="d-1")
    client_ticket, _ = registry.make(kind="client", client_id="c-1")

    text = path.read_text(encoding="utf-8")
    assert device_ticket not in text and client_ticket not in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_ticket_survives_a_restart_and_is_spent_once(path):
    ticket, _ = ChannelTicketRegistry(path=path).make(kind="agent", name="box")

    restarted = ChannelTicketRegistry(path=path)

    assert restarted.get(ticket)["name"] == "box"
    assert restarted.spend(ticket)["name"] == "box"
    assert restarted.spend(ticket) is None
    assert on_disk(path) == []
    assert ChannelTicketRegistry(path=path).spend(ticket) is None


def test_an_expired_ticket_is_dropped_at_start_and_leaves_the_file(path, monkeypatch):
    ticket, expires_at = ChannelTicketRegistry(path=path).make(kind="agent")
    monkeypatch.setattr(tickets_module.time, "time", lambda: expires_at + 1)

    restarted = ChannelTicketRegistry(path=path)

    assert restarted.get(ticket) is None
    assert restarted.spend(ticket) is None
    assert on_disk(path) == []


def test_the_expiry_counts_across_a_restart(path, monkeypatch):
    now = time.time()
    monkeypatch.setattr(tickets_module.time, "time", lambda: now)
    ticket, _ = ChannelTicketRegistry(path=path).make(kind="client", client_id="c")
    monkeypatch.setattr(tickets_module.time, "time", lambda: now + ENROLLMENT_TTL_S - 1)

    assert ChannelTicketRegistry(path=path).get(ticket) is not None

    monkeypatch.setattr(tickets_module.time, "time", lambda: now + ENROLLMENT_TTL_S + 1)
    assert ChannelTicketRegistry(path=path).get(ticket) is None


def test_making_a_ticket_replaces_the_open_ticket_of_its_kind_only(path):
    registry = ChannelTicketRegistry(path=path)
    first, _ = registry.make(kind="agent")
    client, _ = registry.make(kind="client", client_id="c")

    second, _ = registry.make(kind="agent")

    assert registry.get(first) is None
    assert registry.get(second) is not None
    assert registry.get(client) is not None
    assert {entry["kind"] for entry in on_disk(path)} == {"agent", "client"}
    assert len(on_disk(path)) == 2


def test_an_expired_ticket_leaves_the_file_when_another_is_made(path):
    registry = ChannelTicketRegistry(path=path)
    registry.put("old", kind="client", expires_at=time.time() - 1)

    registry.make(kind="agent")

    assert [entry["kind"] for entry in on_disk(path)] == ["agent"]


def test_an_unreadable_file_opens_no_ticket(path):
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert ChannelTicketRegistry(path=path).entries() == []


def test_a_ticket_the_file_could_not_take_is_not_kept(path, monkeypatch):
    registry = ChannelTicketRegistry(path=path)
    kept, _ = registry.make(kind="agent")

    def refuse(*arguments, **keywords):
        raise OSError("read-only")

    monkeypatch.setattr(tickets_module, "write_generated", refuse)

    with pytest.raises(OSError):
        registry.make(kind="agent")
    assert registry.get(kept) is not None
    assert len(registry.entries()) == 1
