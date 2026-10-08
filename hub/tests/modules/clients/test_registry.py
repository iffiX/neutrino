"""The client records: created before they join, digest on disk, raw token once,
and the machine a row belongs to."""

import hashlib
import json

import pytest

from neutrino_hub.modules.clients.constants import CLIENT_PERMISSION_KINDS
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR
from neutrino_hub.utils.json_file import copy_example


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def stored(config_dir) -> dict:
    data = json.loads((config_dir / "clients" / "clients.json").read_text())
    return data["clients"]


def test_a_hub_set_up_from_the_examples_allows_every_kind_but_the_panel_and_exec(
    config_dir,
):
    copy_example(
        UTILS_EXAMPLES_DIR / "clients" / "clients.example.json",
        config_dir / "clients" / "clients.json",
    )

    registry = ClientRegistry()

    assert registry.default_permission() == [
        kind for kind in CLIENT_PERMISSION_KINDS if kind not in ("panel", "exec")
    ]
    assert registry.default_permission_devices() == {}


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
        "machine_id",
        "os_machine_id",
        "platform",
        "version",
        "is_disabled",
        "ai_key_id",
        "permission",
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


def test_a_row_is_found_by_the_machine_id_it_recorded(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.record_seen(
        client_id, hostname="laptop", platform={}, version="", machine_id="m-1"
    )

    assert stored(config_dir)[client_id]["machine_id"] == "m-1"
    found = ClientRegistry().find_by_machine_id("m-1")
    assert found is not None and found.id == client_id
    assert ClientRegistry().find_by_machine_id("m-2") is None


def test_an_empty_machine_id_matches_no_row(config_dir):
    registry = ClientRegistry()
    registry.create("alice")

    assert ClientRegistry().find_by_machine_id("") is None

    client_id = registry.create("bob")
    registry.record_seen(
        client_id, hostname="", platform={}, version="", machine_id="m-1"
    )
    registry.record_seen(client_id, hostname="", platform={}, version="", machine_id="")

    assert ClientRegistry().get(client_id).machine_id == "m-1"


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


def test_a_file_with_no_default_allows_every_kind_but_the_panel_and_exec(
    config_dir,
):
    registry = ClientRegistry()
    client_id = registry.create("alice")

    assert registry.default_permission() == [
        "web",
        "port",
        "ai",
        "file",
        "rdp",
        "overlay",
        "terminal",
    ]
    assert ClientRegistry().get(client_id).permission is None


def test_the_default_is_stored_beside_the_clients(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")

    registry.set_default_permission(["terminal", "web", "web"])
    registry.rename(client_id, "alice-laptop")

    data = json.loads((config_dir / "clients" / "clients.json").read_text())
    assert data["default_permission"] == {"kinds": ["web", "terminal"]}
    assert data["clients"][client_id]["name"] == "alice-laptop"
    assert ClientRegistry().default_permission() == ["web", "terminal"]
    with pytest.raises(ValueError):
        registry.set_default_permission(["telnet"])


def test_a_clients_own_set_is_written_and_cleared(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")

    registry.set_permission(client_id, ["overlay", "ai"])

    assert stored(config_dir)[client_id]["permission"] == {"kinds": ["ai", "overlay"]}
    assert ClientRegistry().get(client_id).permission == ["ai", "overlay"]

    registry.set_permission(client_id, None)

    assert stored(config_dir)[client_id]["permission"] is None
    assert ClientRegistry().get(client_id).permission is None
    with pytest.raises(KeyError):
        registry.set_permission("nobody", [])


def test_a_device_filter_is_stored_beside_the_kinds(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")

    registry.set_default_permission(["web", "rdp"], {"web": ["d1", "d1"], "rdp": []})
    registry.set_permission(client_id, ["terminal"], {"terminal": ["d2"]})

    data = json.loads((config_dir / "clients" / "clients.json").read_text())
    assert data["default_permission"] == {
        "kinds": ["web", "rdp"],
        "devices": {"web": ["d1"]},
    }
    assert data["clients"][client_id]["permission"] == {
        "kinds": ["terminal"],
        "devices": {"terminal": ["d2"]},
    }
    assert ClientRegistry().default_permission_devices() == {"web": ["d1"]}
    assert ClientRegistry().get(client_id).permission_devices == {"terminal": ["d2"]}
    with pytest.raises(ValueError):
        registry.set_permission(client_id, ["overlay"], {"overlay": ["d1"]})


def test_forgetting_a_device_takes_it_out_of_every_filter(config_dir):
    registry = ClientRegistry()
    alice = registry.create("alice")
    bob = registry.create("bob")
    registry.set_default_permission(
        ["web", "port"], {"web": ["d1", "d2"], "port": ["d1"]}
    )
    registry.set_permission(alice, ["terminal"], {"terminal": ["d1"]})
    registry.set_permission(bob, ["web"], {"web": ["d2"]})

    assert ClientRegistry().forget_device("d1") is True

    registry = ClientRegistry()
    assert registry.default_permission() == ["web"]
    assert registry.default_permission_devices() == {"web": ["d2"]}
    assert registry.get(alice).permission == []
    assert registry.get(alice).permission_devices == {}
    assert registry.get(bob).permission == ["web"]
    assert registry.get(bob).permission_devices == {"web": ["d2"]}
    assert ClientRegistry().forget_device("d1") is False


def test_a_list_with_other_devices_left_only_loses_the_id(config_dir):
    registry = ClientRegistry()
    alice = registry.create("alice")
    registry.set_default_permission(["web", "port"], {"web": ["d1", "d2"]})
    registry.set_permission(alice, ["web", "rdp"], {"web": ["d1", "d3"]})

    ClientRegistry().forget_device("d1")

    registry = ClientRegistry()
    assert registry.default_permission() == ["web", "port"]
    assert registry.default_permission_devices() == {"web": ["d2"]}
    assert registry.get(alice).permission == ["web", "rdp"]
    assert registry.get(alice).permission_devices == {"web": ["d3"]}


def test_a_list_the_device_emptied_turns_its_kind_off(config_dir):
    """An empty list allows every device, so the kind goes rather than the
    filter."""
    registry = ClientRegistry()
    alice = registry.create("alice")
    bob = registry.create("bob")
    registry.set_default_permission(["web", "terminal"], {"terminal": ["d1"]})
    registry.set_permission(alice, ["web", "rdp"], {"web": ["d1"], "rdp": ["d2"]})

    ClientRegistry().forget_device("d1")

    registry = ClientRegistry()
    assert registry.default_permission() == ["web"]
    assert registry.default_permission_devices() == {}
    assert registry.get(alice).permission == ["rdp"]
    assert registry.get(alice).permission_devices == {"rdp": ["d2"]}
    assert registry.get(bob).permission is None


def test_the_os_machine_id_is_kept_and_an_empty_one_keeps_it(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")

    registry.record_seen(
        client_id, hostname="", platform={}, version="", os_machine_id="m-1"
    )
    registry.record_seen(client_id, hostname="", platform={}, version="")

    assert ClientRegistry().get(client_id).os_machine_id == "m-1"
