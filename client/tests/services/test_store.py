"""The person's preference store: atomic, 0600, and free of secrets.

What the store keeps is what somebody typed, the language, the theme, the
tool choices and the mount records, and the one thing it makes itself: the
installation's id, generated on the first read and stable after. Nothing
about a service standing on is in it, a file an older build wrote reads
without the keys it had, and a mount record that names no hub is dropped
on request.
"""

import json
import os

import pytest

from neutrino_client.constants import CLIENT_DEFAULT_LANGUAGE, CLIENT_DEFAULT_THEME
from neutrino_client.services.store import ClientServiceStore

RECORD = {
    "hub_id": "h1",
    "entry_id": "share_media",
    "host": "hub",
    "share": "media",
    "username": "media",
    "path": "/home/alice/nas/media",
}


@pytest.fixture
def store(tmp_path):
    return ClientServiceStore(path=str(tmp_path / "state.json"))


def test_no_language_is_kept_until_one_is_set(store):
    assert store.language() == ""


def test_the_language_round_trips(store, tmp_path):
    store.set_language("zh-CN")

    assert store.language() == "zh-CN"
    assert json.loads((tmp_path / "state.json").read_text())["language"] == "zh-CN"


def test_a_language_the_client_does_not_offer_is_kept_as_the_default(store):
    store.set_language("de")

    assert store.language() == CLIENT_DEFAULT_LANGUAGE


def test_no_theme_is_kept_until_one_is_set(store):
    assert store.theme() == ""


def test_the_theme_round_trips(store, tmp_path):
    store.set_theme("light")

    assert store.theme() == "light"
    assert json.loads((tmp_path / "state.json").read_text())["theme"] == "light"


def test_a_theme_the_client_does_not_offer_is_kept_as_the_default(store):
    store.set_theme("sepia")

    assert store.theme() == CLIENT_DEFAULT_THEME


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
        "machine_id": "",
        "language": "",
        "theme": "",
        "ai": {"tool_configs": {"claude": {"default": "m2"}}},
        "mounts": {"r1": RECORD},
    }


def test_a_record_that_names_no_hub_is_read_and_dropped_on_request(store):
    hubless = {key: value for key, value in RECORD.items() if key != "hub_id"}
    store.set_mount("old", hubless)
    store.set_mount("r1", RECORD)

    assert store.mounts() == {"old": hubless, "r1": RECORD}
    assert store.drop_hubless_mounts() == ["old"]

    assert store.mounts() == {"r1": RECORD}
    assert store.drop_hubless_mounts() == []


def test_the_machine_id_is_made_once_and_kept(store, tmp_path):
    made = store.machine_id()

    assert len(made) == 32 and int(made, 16) >= 0
    assert store.machine_id() == made
    assert ClientServiceStore(path=str(tmp_path / "state.json")).machine_id() == made
    assert json.loads((tmp_path / "state.json").read_text())["machine_id"] == made


def test_two_installs_have_two_machine_ids(tmp_path):
    first = ClientServiceStore(path=str(tmp_path / "one.json")).machine_id()
    second = ClientServiceStore(path=str(tmp_path / "two.json")).machine_id()

    assert first != second


def test_a_machine_id_of_another_shape_is_replaced(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"machine_id": 42}))
    store = ClientServiceStore(path=str(path))

    made = store.machine_id()

    assert len(made) == 32
    assert json.loads(path.read_text())["machine_id"] == made


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
