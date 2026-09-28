"""Which kinds a client is allowed: the default set, or a set of its own."""

import pytest

from neutrino_hub.modules.clients.permissions import (
    permission_kinds,
    permitted_entries,
    permitted_kinds,
)
from neutrino_hub.modules.clients.registry import ClientRegistry


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_a_client_follows_the_default_until_it_has_its_own(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_default_permission(["web", "file"])

    assert permitted_kinds(registry, registry.get(client_id)) == {"web", "file"}

    registry.set_permission(client_id, ["terminal"])
    registry = ClientRegistry()

    assert permitted_kinds(registry, registry.get(client_id)) == {"terminal"}


def test_an_empty_set_of_its_own_allows_nothing(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, [])
    registry = ClientRegistry()

    assert permitted_kinds(registry, registry.get(client_id)) == frozenset()


def test_filtering_keeps_the_allowed_entries_in_order():
    entries = [
        {"id": "a", "type": "web"},
        {"id": "b", "type": "ai"},
        {"id": "c", "type": "web"},
        {"id": "d", "type": "rdp"},
    ]

    kept = permitted_entries(entries, {"web", "rdp"})

    assert [entry["id"] for entry in kept] == ["a", "c", "d"]


def test_kinds_come_back_once_each_in_the_one_order():
    assert permission_kinds(["terminal", "web", "terminal"]) == ["web", "terminal"]
    with pytest.raises(ValueError):
        permission_kinds(["web", "ssh"])
