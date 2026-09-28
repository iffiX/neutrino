"""What a client is allowed, by kind and by device: the default permission,
or one of its own."""

import pytest

from neutrino_hub.modules.clients.permissions import (
    entry_device_id,
    is_device_permitted,
    permission_devices,
    permission_kinds,
    permitted_devices,
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


def test_a_device_filter_drops_empty_lists_and_repeats_and_refuses_the_overlay():
    assert permission_devices(
        {"terminal": ["d2", "d1", "d2"], "web": [], "rdp": ["d1"]}
    ) == {"rdp": ["d1"], "terminal": ["d2", "d1"]}
    assert permission_devices(None) == {}
    with pytest.raises(ValueError):
        permission_devices({"overlay": ["d1"]})


def test_a_kind_with_no_list_allows_every_device():
    devices = {"web": ["d1"]}

    assert is_device_permitted(devices, "web", "d1")
    assert not is_device_permitted(devices, "web", "d2")
    assert not is_device_permitted(devices, "web", "")
    assert is_device_permitted(devices, "port", "d2")
    assert is_device_permitted(devices, "port", "")


def test_a_client_is_held_to_the_defaults_filter_until_it_has_its_own(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_default_permission(["web"], {"web": ["d1"]})

    assert permitted_devices(registry, registry.get(client_id)) == {"web": ["d1"]}

    registry.set_permission(client_id, ["web"])
    registry = ClientRegistry()

    assert permitted_devices(registry, registry.get(client_id)) == {}


@pytest.mark.parametrize(
    "entry, provider",
    [
        ({"device_id": "d1", "source": "module"}, "d1"),
        ({"source": "module", "payload": {}}, "hub"),
        (
            {"source": "declared", "payload": {"url": "http://192.168.100.20:8080/"}},
            "d2",
        ),
        ({"source": "declared", "payload": {"host": "192.168.100.20"}}, "d2"),
        ({"source": "declared", "payload": {"host": "192.168.100.99"}}, ""),
    ],
)
def test_an_entry_is_provided_by_its_host_its_address_or_the_hub(entry, provider):
    assert (
        entry_device_id(
            entry,
            hub_device_id="hub",
            device_ids_by_address={"192.168.100.20": "d2"},
        )
        == provider
    )
