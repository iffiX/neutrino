"""What a client is allowed, by kind, by device and by row: the default
permission, or one of its own."""

import pytest

from neutrino_hub.modules.clients.permissions import (
    ClientPermission,
    client_permission,
    entry_device_id,
    entry_row_id,
    is_device_permitted,
    is_permitted,
    is_row_of_device,
    permission_devices,
    permission_entries,
    permission_kinds,
    terminal_row_id,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.services.file_ids import (
    file_row_id,
    folder_share_entry_id,
    folder_share_id,
    home_share_entry_id,
)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_a_client_follows_the_default_until_it_has_its_own(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_default_permission(["web", "file"], entries={"gitea_d1": False})

    held = client_permission(registry, registry.get(client_id))
    assert held.kinds == {"web", "file"}
    assert held.entries == {"gitea_d1": False}

    registry.set_permission(client_id, ["terminal"], entries={"gitea_d1": True})
    registry = ClientRegistry()

    held = client_permission(registry, registry.get(client_id))
    assert held.kinds == {"terminal"}
    assert held.entries == {"gitea_d1": True}


def test_an_empty_set_of_its_own_allows_nothing(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, [])
    registry = ClientRegistry()

    assert client_permission(registry, registry.get(client_id)).kinds == frozenset()


def test_a_row_in_entries_wins_over_its_kind_both_ways():
    permission = ClientPermission(
        kinds=frozenset({"web"}),
        devices={"web": ["d1"]},
        entries={"vscode_d1_lab": False, "gitea_d2": True},
    )

    assert is_permitted(permission, "web", "d1", "hermes_webui_d1")
    assert not is_permitted(permission, "web", "d1", "vscode_d1_lab")
    assert is_permitted(permission, "web", "d2", "gitea_d2")
    assert is_permitted(permission, "port", "d2", "gitea_d2")
    assert not is_permitted(permission, "web", "d2", "cloudcli_d2_lab")
    assert not is_permitted(permission, "ai")


def test_a_kind_off_allows_only_the_rows_set_on():
    permission = ClientPermission(entries={"rdp_d1": True, "terminal_d2": True})

    assert is_permitted(permission, "rdp", "d1", "rdp_d1")
    assert not is_permitted(permission, "rdp", "d3", "rdp_d3")
    assert is_permitted(permission, "terminal", "d2", terminal_row_id("d2"))
    assert not is_permitted(permission, "overlay")
    assert not is_permitted(permission, "panel")


@pytest.mark.parametrize(
    "entry, row_id",
    [
        (
            {"id": "vscode_d1_lab_web", "type": "web", "app_id": "vscode_d1_lab"},
            "vscode_d1_lab",
        ),
        (
            {"id": "ssh_server_d1_lab", "type": "ssh", "app_id": "ssh_server_d1"},
            "ssh_server_d1",
        ),
        (
            {"id": "samba_d1_lab", "type": "file", "payload": {"account": ""}},
            "samba_d1_lab",
        ),
        (
            {
                "id": "samba_folder_d1_data_lab",
                "type": "file",
                "device_id": "d1",
                "payload": {"share": "data", "account": "lab"},
            },
            "samba_folder_d1_data",
        ),
        ({"id": "nas_files", "type": "file", "app_id": "nas", "payload": {}}, "nas"),
        ({"id": "rdp_d1", "type": "rdp"}, "rdp_d1"),
        ({"id": "ai", "type": "ai"}, ""),
    ],
)
def test_an_entry_is_judged_under_its_app_its_share_or_itself(entry, row_id):
    assert entry_row_id(entry) == row_id


def test_a_home_share_entry_is_its_own_row():
    assert file_row_id({"id": "samba_d1_lab", "payload": {}}) == "samba_d1_lab"


def share_entry(entry_id: str, share: str, account: str) -> dict:
    return {
        "id": entry_id,
        "type": "file",
        "app_id": "",
        "device_id": "d1",
        "payload": {"share": share, "account": account},
    }


def test_every_account_entry_of_a_folder_share_follows_the_share_row():
    permission = ClientPermission(
        kinds=frozenset({"file"}), entries={folder_share_id("d1", "lab"): False}
    )
    denied = [
        share_entry(folder_share_entry_id("d1", "lab", account), "lab", account)
        for account in ("ann", "bob")
    ]
    allowed = [
        share_entry(folder_share_entry_id("d1", "data", "ann"), "data", "ann"),
        share_entry(home_share_entry_id("d1", "ann"), "ann", ""),
    ]

    for entry in denied:
        assert not is_permitted(permission, "file", "d1", entry_row_id(entry))
    for entry in allowed:
        assert is_permitted(permission, "file", "d1", entry_row_id(entry))


def test_a_row_names_a_device_by_a_whole_part_of_its_id():
    assert is_row_of_device("vscode_d1_lab", "d1")
    assert is_row_of_device("rdp_d1", "d1")
    assert is_row_of_device("terminal_d1", "d1")
    assert not is_row_of_device("vscode_d10_lab", "d1")
    assert not is_row_of_device("nas", "")


def test_a_row_map_refuses_a_value_that_is_not_true_or_false():
    assert permission_entries({"a": True, "": False, "b": False}) == {
        "a": True,
        "b": False,
    }
    assert permission_entries(None) == {}
    with pytest.raises(ValueError):
        permission_entries({"a": 1})


def test_kinds_come_back_once_each_in_the_one_order():
    assert permission_kinds(["terminal", "web", "terminal"]) == ["web", "terminal"]
    with pytest.raises(ValueError):
        permission_kinds(["web", "exec"])


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

    held = client_permission(registry, registry.get(client_id))
    assert held.devices == {"web": ["d1"]}

    registry.set_permission(client_id, ["web"])
    registry = ClientRegistry()

    assert client_permission(registry, registry.get(client_id)).devices == {}


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
