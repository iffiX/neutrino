"""The declared-service store: what it keeps, and what it refuses.

The file is the only record of what somebody declared, so every kind must
round-trip through it unchanged — and a record that would not validate must
never reach it, because the panel renders whatever is there.
"""

import json

import pytest

import neutrino_hub.utils.json_file
from neutrino_hub.modules.services.config import (
    DeclaredServiceError,
    DeclaredServiceRegistry,
    DeclaredShare,
)
from neutrino_hub.modules.services.constants import SERVICES_DECLARED_PATH


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def _stored(config_dir) -> dict:
    text = (config_dir / SERVICES_DECLARED_PATH).read_text(encoding="utf-8")
    return json.loads(text)


def test_a_missing_file_reads_as_no_services(config_dir):
    assert DeclaredServiceRegistry().list_records() == []


def test_samba_round_trips_with_its_shares_and_default_port(config_dir):
    record = DeclaredServiceRegistry().add(
        name="nas",
        kind="samba",
        host="192.168.100.7",
        shares=[
            DeclaredShare(name="media"),
            DeclaredShare(name="backup", login_id="a" * 32),
        ],
    )
    assert record.port == 445

    stored = DeclaredServiceRegistry().get(record.id)
    assert stored is not None
    assert stored.kind == "samba"
    assert [share.name for share in stored.shares] == ["media", "backup"]
    assert stored.shares[0].login_id is None
    assert stored.shares[1].login_id == "a" * 32


def test_http_round_trips_with_scheme_and_path(config_dir):
    record = DeclaredServiceRegistry().add(
        name="wiki", kind="http", host="wiki.lan", port=8080, scheme="https", path="/w"
    )
    stored = DeclaredServiceRegistry().get(record.id)
    assert stored is not None
    assert (stored.scheme, stored.path, stored.port) == ("https", "/w", 8080)


def test_http_defaults_to_plain_scheme_and_the_root_path(config_dir):
    record = DeclaredServiceRegistry().add(
        name="wiki", kind="http", host="wiki.lan", port=8080
    )
    assert (record.scheme, record.path) == ("http", "/")


@pytest.mark.parametrize("kind", ["docker_engine", "generic_tcp"])
def test_the_plain_tcp_kinds_round_trip(config_dir, kind):
    record = DeclaredServiceRegistry().add(
        name="engine", kind=kind, host="10.0.0.5", port=2375
    )
    stored = DeclaredServiceRegistry().get(record.id)
    assert stored is not None
    assert (stored.kind, stored.host, stored.port) == (kind, "10.0.0.5", 2375)


def test_the_stored_entry_carries_only_the_fields_its_kind_has(config_dir):
    registry = DeclaredServiceRegistry()
    registry.add(name="engine", kind="docker_engine", host="10.0.0.5", port=2375)
    registry.add(name="wiki", kind="http", host="wiki.lan", port=80)

    entries = {entry["kind"]: entry for entry in _stored(config_dir)["services"]}
    assert "shares" not in entries["docker_engine"]
    assert "scheme" not in entries["docker_engine"]
    assert "shares" not in entries["http"]
    assert entries["http"]["scheme"] == "http"


def test_every_id_is_a_fresh_uuid_hex(config_dir):
    registry = DeclaredServiceRegistry()
    first = registry.add(name="a", kind="generic_tcp", host="h", port=1)
    second = registry.add(name="b", kind="generic_tcp", host="h", port=2)
    assert first.id != second.id
    assert len(first.id) == 32 and all(c in "0123456789abcdef" for c in first.id)


def test_replace_keeps_the_id_and_the_declaration_time(config_dir):
    registry = DeclaredServiceRegistry()
    record = registry.add(name="engine", kind="docker_engine", host="old", port=2375)

    replaced = DeclaredServiceRegistry().replace(
        record.id, name="engine", kind="docker_engine", host="new", port=2376
    )

    assert replaced.id == record.id
    assert replaced.created_at == record.created_at
    stored = DeclaredServiceRegistry().get(record.id)
    assert stored is not None and (stored.host, stored.port) == ("new", 2376)


def test_delete_removes_the_record(config_dir):
    registry = DeclaredServiceRegistry()
    record = registry.add(name="a", kind="generic_tcp", host="h", port=1)
    registry.delete(record.id)
    assert DeclaredServiceRegistry().list_records() == []


@pytest.mark.parametrize("action", ["replace", "delete"])
def test_an_unknown_id_raises_key_error(config_dir, action):
    registry = DeclaredServiceRegistry()
    with pytest.raises(KeyError):
        if action == "delete":
            registry.delete("missing")
        else:
            registry.replace("missing", name="a", kind="generic_tcp", host="h", port=1)


@pytest.mark.parametrize(
    "fields, refused",
    [
        ({"kind": "ai_endpoint"}, "kind"),
        ({"name": "  "}, "name"),
        ({"host": ""}, "host"),
        ({"port": None}, "port"),
        ({"port": 0}, "port"),
        ({"port": 65536}, "port"),
    ],
)
def test_a_bad_field_is_refused_by_name(config_dir, fields, refused):
    record = {"name": "a", "kind": "generic_tcp", "host": "h", "port": 1, **fields}
    with pytest.raises(DeclaredServiceError) as caught:
        DeclaredServiceRegistry().add(**record)
    assert caught.value.code == "declared_service_invalid"
    assert caught.value.params == {"field": refused}


def test_a_bad_scheme_and_a_relative_path_are_refused(config_dir):
    registry = DeclaredServiceRegistry()
    with pytest.raises(DeclaredServiceError) as caught:
        registry.add(name="w", kind="http", host="h", port=80, scheme="gopher")
    assert caught.value.params == {"field": "scheme"}
    with pytest.raises(DeclaredServiceError) as caught:
        registry.add(name="w", kind="http", host="h", port=80, path="w")
    assert caught.value.params == {"field": "path"}


def test_a_blank_or_duplicate_share_name_is_refused(config_dir):
    registry = DeclaredServiceRegistry()
    with pytest.raises(DeclaredServiceError) as caught:
        registry.add(
            name="nas", kind="samba", host="h", shares=[DeclaredShare(name=" ")]
        )
    assert caught.value.params == {"field": "shares"}
    with pytest.raises(DeclaredServiceError) as caught:
        registry.add(
            name="nas",
            kind="samba",
            host="h",
            shares=[DeclaredShare(name="media"), DeclaredShare(name="media")],
        )
    assert caught.value.params == {"field": "shares"}


def test_a_refused_record_writes_nothing(config_dir):
    with pytest.raises(DeclaredServiceError):
        DeclaredServiceRegistry().add(name="a", kind="nope", host="h", port=1)
    assert not (config_dir / SERVICES_DECLARED_PATH).exists()
