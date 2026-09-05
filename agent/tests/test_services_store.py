"""The machine's service-choice store: atomic, 0600, and free of secrets."""

import json
import os

import pytest

from neutrino_agent.services.store import MachineServiceStore


@pytest.fixture
def store(tmp_path):
    return MachineServiceStore(path=str(tmp_path / "services.json"))


def test_ai_targets_and_granted_round_trip(store):
    assert store.ai_targets() == {}

    store.set_ai_target("alice", is_activated=True)
    store.set_ai_target("bob", is_activated=False)
    store.set_ai_granted("alice", {"base_url": "http://hub:8080", "model": "m1"})

    assert store.ai_targets() == {"alice": True, "bob": False}
    assert store.ai_granted() == {
        "alice": {"base_url": "http://hub:8080", "model": "m1"}
    }

    store.clear_ai_granted("alice")
    assert store.ai_granted() == {}


def test_mount_records_round_trip(store):
    record = {
        "offer_id": "hub_share_media",
        "host": "hub",
        "share": "media",
        "username": "media",
        "path": "/home/alice/nas/media",
        "account": "alice",
        "is_enabled": True,
    }
    store.set_mount("r1", record)

    assert store.mounts() == {"r1": record}

    store.remove_mount("r1")
    assert store.mounts() == {}


def test_passwords_never_reach_the_file(store, tmp_path):
    store.set_mount(
        "r1",
        {
            "offer_id": "o",
            "path": "/p",
            "account": "alice",
            "is_enabled": True,
            "password": "s3cret",  # scan: allow
        },
    )

    text = (tmp_path / "services.json").read_text()
    assert "s3cret" not in text  # scan: allow
    assert "password" not in text
    assert "password" not in store.mounts()["r1"]


def test_the_file_is_written_0600_and_atomically(store, tmp_path):
    store.set_ai_target("alice", is_activated=True)

    path = tmp_path / "services.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert not os.path.exists(str(path) + ".tmp")


def test_an_unreadable_file_reads_as_empty(tmp_path):
    path = tmp_path / "services.json"
    path.write_text("not json")
    store = MachineServiceStore(path=str(path))

    assert store.ai_targets() == {}
    assert store.mounts() == {}

    store.set_ai_target("alice", is_activated=True)
    assert store.ai_targets() == {"alice": True}
    assert isinstance(json.loads(path.read_text()), dict)


def test_tool_configs_survive_the_round_trip(tmp_path):
    store = MachineServiceStore(path=str(tmp_path / "services.json"))

    store.set_ai_tool_configs(
        {"claude": {"default": "m1"}, "codex": {"model_reasoning_effort": "low"}}
    )

    assert store.ai_tool_configs() == {
        "claude": {"default": "m1"},
        "codex": {"model_reasoning_effort": "low"},
    }


def test_the_connect_account_is_remembered(tmp_path):
    store = MachineServiceStore(path=str(tmp_path / "services.json"))
