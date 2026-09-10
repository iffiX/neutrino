"""The client records: created before they join, digest on disk, raw token once."""

import hashlib
import json

import pytest

from neutrino_hub.modules.clients.registry import ClientRegistry


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def stored(config_dir) -> dict:
    data = json.loads((config_dir / "clients" / "clients.json").read_text())
    return data["clients"]


def test_a_missing_file_is_an_empty_list(config_dir):
    assert ClientRegistry().all() == []
    assert ClientRegistry().get("nobody") is None


def test_create_makes_a_row_that_has_not_joined(config_dir):
    client_id = ClientRegistry().create("  alice-laptop ")

    client = ClientRegistry().get(client_id)
    assert client is not None
    assert client.name == "alice-laptop"
    assert not client.is_enrolled
    assert not client.is_disabled
    assert client.ai_key_id is None
    assert set(stored(config_dir)[client_id]) == {
        "name",
        "token_sha256",
        "hostname",
        "platform",
        "version",
        "is_disabled",
        "ai_key_id",
    }


def test_only_the_digest_reaches_the_file_and_the_raw_token_authenticates(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    token = registry.issue_token(client_id)

    entry = stored(config_dir)[client_id]
    assert entry["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in (config_dir / "clients" / "clients.json").read_text()
    found = ClientRegistry().find_by_token(token)
    assert found is not None and found.id == client_id
    assert ClientRegistry().find_by_token("not-the-token") is None
    assert ClientRegistry().find_by_token(entry["token_sha256"]) is None


def test_a_reissued_token_replaces_the_old_and_a_dropped_one_keeps_the_row(
    config_dir,
):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    old = registry.issue_token(client_id)
    new = registry.issue_token(client_id)
    assert ClientRegistry().find_by_token(old) is None
    assert ClientRegistry().find_by_token(new) is not None

    registry.drop_token(client_id)

    assert ClientRegistry().find_by_token(new) is None
    assert ClientRegistry().get(client_id).name == "alice"


def test_record_seen_writes_only_what_changed(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    platform = {"os": "linux", "arch": "amd64", "family": "debian"}
    registry.record_seen(
        client_id, hostname="laptop", platform=platform, version="0.2.0"
    )
    path = config_dir / "clients" / "clients.json"
    written_at = path.stat().st_mtime_ns

    registry.record_seen(client_id, hostname="laptop", platform=platform, version="")
    assert path.stat().st_mtime_ns == written_at

    client = ClientRegistry().get(client_id)
    assert (client.hostname, client.platform, client.version) == (
        "laptop",
        platform,
        "0.2.0",
    )
    registry.record_seen("nobody", hostname="x", platform={}, version="")


def test_the_switch_and_the_key_id_are_written_and_forget_removes_the_row(
    config_dir,
):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_disabled(client_id, True)
    registry.set_ai_key_id(client_id, "k1")

    client = ClientRegistry().get(client_id)
    assert client.is_disabled and client.ai_key_id == "k1"
    with pytest.raises(KeyError):
        registry.set_disabled("nobody", True)

    registry.forget(client_id)
    registry.forget("nobody")

    assert ClientRegistry().all() == []
