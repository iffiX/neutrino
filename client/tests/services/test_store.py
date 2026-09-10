"""The person's preference store: atomic, 0600, and free of secrets.

What the store keeps is what somebody typed: the tool choices and the mount
records. Nothing about a service standing on is in it, and a file an older
build wrote reads without the keys it had.
"""

import json
import os

import pytest

from neutrino_client.services.store import ClientServiceStore

RECORD = {
    "entry_id": "share_media",
    "host": "hub",
    "share": "media",
    "username": "media",
    "path": "/home/alice/nas/media",
}


@pytest.fixture
def store(tmp_path):
    return ClientServiceStore(path=str(tmp_path / "state.json"))


def test_mount_records_round_trip(store):
    store.set_mount("r1", RECORD)

    assert store.mounts() == {"r1": RECORD}

    store.remove_mount("r1")
    assert store.mounts() == {}


def test_a_record_keeps_only_the_fields_the_store_holds(store, tmp_path):
    store.set_mount("r1", dict(RECORD, is_enabled=True, is_attached=True))

    assert store.mounts() == {"r1": RECORD}
    assert "is_enabled" not in (tmp_path / "state.json").read_text()


def test_a_file_an_older_build_wrote_is_read_without_its_keys(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "ai": {
                    "is_enabled": True,
                    "granted": {"base_url": "http://hub:8080", "model": "m1"},
                    "tool_configs": {"claude": {"default": "m1"}},
                },
                "mounts": {"r1": dict(RECORD, is_enabled=True)},
            }
        )
    )
    store = ClientServiceStore(path=str(path))

    assert store.ai_tool_configs() == {"claude": {"default": "m1"}}
    assert store.mounts() == {"r1": RECORD}

    store.set_ai_tool_configs({"claude": {"default": "m2"}})

    written = json.loads(path.read_text())
    assert written == {
        "ai": {"tool_configs": {"claude": {"default": "m2"}}},
        "mounts": {"r1": RECORD},
    }


def test_passwords_never_reach_the_file(store, tmp_path):
    store.set_mount("r1", dict(RECORD, password="s3cret"))  # scan: allow

    text = (tmp_path / "state.json").read_text()
    assert "s3cret" not in text  # scan: allow
    assert "password" not in text
    assert "password" not in store.mounts()["r1"]


def test_the_file_is_written_0600_and_atomically(store, tmp_path):
    store.set_mount("r1", RECORD)

    path = tmp_path / "state.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert not os.path.exists(str(path) + ".tmp")


def test_an_unreadable_file_reads_as_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    store = ClientServiceStore(path=str(path))

    assert store.ai_tool_configs() == {}
    assert store.mounts() == {}

    store.set_mount("r1", RECORD)
    assert store.mounts() == {"r1": RECORD}
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
    store.set_ai_tool_configs({"claude": {"default": "m1"}, "codex": {"model": "m2"}})
    store.set_mount(
        "r1", dict(RECORD, password="leak-pw", api_key="leak-key")  # scan: allow
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
