"""The person's service-choice store: atomic, 0600, and free of secrets."""

import json
import os

import pytest

from neutrino_client.services.store import ClientServiceStore


@pytest.fixture
def store(tmp_path):
    return ClientServiceStore(path=str(tmp_path / "state.json"))


def test_the_ai_choice_and_grant_round_trip(store):
    assert store.is_ai_enabled() is False
    assert store.ai_granted() == {}

    store.set_ai_enabled(True)
    store.set_ai_granted({"base_url": "http://hub:8080", "model": "m1"})

    assert store.is_ai_enabled() is True
    assert store.ai_granted() == {"base_url": "http://hub:8080", "model": "m1"}

    store.clear_ai_granted()
    assert store.ai_granted() == {}


def test_mount_records_round_trip(store):
    record = {
        "entry_id": "share_media",
        "host": "hub",
        "share": "media",
        "username": "media",
        "path": "/home/alice/nas/media",
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
            "entry_id": "o",
            "path": "/p",
            "is_enabled": True,
            "password": "s3cret",  # scan: allow
        },
    )

    text = (tmp_path / "state.json").read_text()
    assert "s3cret" not in text  # scan: allow
    assert "password" not in text
    assert "password" not in store.mounts()["r1"]


def test_the_file_is_written_0600_and_atomically(store, tmp_path):
    store.set_ai_enabled(True)

    path = tmp_path / "state.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert not os.path.exists(str(path) + ".tmp")


def test_an_unreadable_file_reads_as_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    store = ClientServiceStore(path=str(path))

    assert store.is_ai_enabled() is False
    assert store.mounts() == {}

    store.set_ai_enabled(True)
    assert store.is_ai_enabled() is True
    assert isinstance(json.loads(path.read_text()), dict)


def test_tool_configs_survive_the_round_trip(store):
    store.set_ai_tool_configs(
        {"claude": {"default": "m1"}, "codex": {"model_reasoning_effort": "low"}}
    )

    assert store.ai_tool_configs() == {
        "claude": {"default": "m1"},
        "codex": {"model_reasoning_effort": "low"},
    }


def test_no_write_path_serializes_a_secret(store, tmp_path):
    store.set_ai_enabled(True)
    store.set_ai_tool_configs({"claude": {"default": "m1"}, "codex": {"model": "m2"}})
    store.set_ai_granted(
        {
            "base_url": "http://hub:8080",
            "model": "m1",
            "api_key": "leak-key",  # scan: allow
        }
    )
    store.set_mount(
        "r1", {"path": "/p", "is_enabled": True, "password": "leak-pw"}  # scan: allow
    )

    raw = (tmp_path / "state.json").read_bytes()
    assert b"leak-key" not in raw and b"leak-pw" not in raw

    def keys_of(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys_of(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys_of(value)

    forbidden = {"password", "api_key", "key", "token"}
    assert forbidden.isdisjoint(set(keys_of(json.loads(raw.decode()))))
