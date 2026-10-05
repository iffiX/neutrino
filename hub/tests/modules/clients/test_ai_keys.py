"""One gateway key per client: minted on demand, revoked, minted again."""

import pytest

from neutrino_hub.modules.clients import ai_keys
from neutrino_hub.modules.clients.ai_keys import (
    client_credential,
    ensure_client_key,
    revoke_client_key,
)
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier, load_config
from tests.conftest import unlock_vault


class StubServedModels:
    def __init__(self, model: str = "gpt-x"):
        self.model = model
        self.asked: list = []

    def first_model(self, *, port, client_key):
        self.asked.append((port, client_key))
        return self.model


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    return tmp_path


@pytest.fixture
def unlocked(config_dir, monkeypatch):
    unlock_vault(monkeypatch, config_dir)
    return config_dir


def test_the_first_ask_mints_a_labelled_key_and_the_next_returns_it(unlocked):
    registry = ClientRegistry()
    client_id = registry.create("alice")

    material = ensure_client_key(registry, registry.get(client_id))

    assert material
    keys = load_config().client_keys
    assert [key.name for key in keys] == ["client/alice"]
    assert ClientRegistry().get(client_id).ai_key_id == keys[0].id
    assert keys[0].open_key() == material
    assert ensure_client_key(ClientRegistry(), ClientRegistry().get(client_id)) == (
        material
    )
    assert len(load_config().client_keys) == 1


def test_a_locked_vault_mints_nothing(config_dir):
    registry = ClientRegistry()
    client_id = registry.create("alice")

    assert ensure_client_key(registry, registry.get(client_id)) is None
    assert ClientRegistry().get(client_id).ai_key_id is None
    assert load_config().client_keys == []


def test_revoke_removes_the_key_and_a_second_ensure_mints_a_new_one(unlocked):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    first = ensure_client_key(registry, registry.get(client_id))

    revoke_client_key(registry, ClientRegistry().get(client_id))

    assert load_config().client_keys == []
    assert ClientRegistry().get(client_id).ai_key_id is None
    revoke_client_key(registry, ClientRegistry().get(client_id))

    second = ensure_client_key(registry, ClientRegistry().get(client_id))
    assert second and second != first


def test_a_key_removed_behind_the_record_is_minted_again(unlocked):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    ensure_client_key(registry, registry.get(client_id))
    config = load_config()
    config.client_keys = []
    cliproxyapi_ops.save_config(config)

    material = ensure_client_key(registry, ClientRegistry().get(client_id))

    assert material
    assert ClientRegistry().get(client_id).ai_key_id == load_config().client_keys[0].id


def test_the_credential_is_the_clients_key_and_the_first_model(unlocked):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    served = StubServedModels("claude-x")

    credential = client_credential(
        registry,
        registry.get(client_id),
        served_models=served,
    )

    port = load_config().listen_port
    assert credential == {
        "api_key": load_config().client_keys[0].open_key(),
        "model": "claude-x",
    }
    assert served.asked == [(port, credential["api_key"])]


def test_a_disabled_client_and_a_locked_vault_have_no_credential(
    config_dir, monkeypatch
):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    served = StubServedModels()
    assert (
        client_credential(registry, registry.get(client_id), served_models=served)
        is None
    )

    unlock_vault(monkeypatch, config_dir)
    registry.set_disabled(client_id, True)

    assert (
        client_credential(
            registry,
            ClientRegistry().get(client_id),
            served_models=served,
        )
        is None
    )
    assert load_config().client_keys == []
    assert served.asked == []


def test_an_apply_that_refuses_does_not_undo_the_mint(unlocked, monkeypatch):
    def refuse(self, **kwargs):
        raise ValueError("no")

    monkeypatch.setattr(CliproxyApiConfigApplier, "apply_keys", refuse)
    registry = ClientRegistry()
    client_id = registry.create("alice")

    assert ensure_client_key(registry, registry.get(client_id))
    assert len(load_config().client_keys) == 1
    assert ai_keys.load_config().client_keys[0].name == "client/alice"


def test_a_new_key_is_handed_to_the_gateway_as_one_to_await_and_a_revoke_is_not(
    unlocked, monkeypatch
):
    handed: list = []
    monkeypatch.setattr(
        CliproxyApiConfigApplier,
        "apply_keys",
        lambda self, *, new_key=None: handed.append(new_key) or "reloaded",
    )
    registry = ClientRegistry()
    client_id = registry.create("alice")

    material = ensure_client_key(registry, registry.get(client_id))
    ensure_client_key(registry, ClientRegistry().get(client_id))
    revoke_client_key(registry, ClientRegistry().get(client_id))

    assert handed == [material, None]


# --- a managed device's key ---


def test_a_devices_key_is_minted_once_under_its_id_and_revoked(unlocked):
    material = ai_keys.ensure_device_key("dev-1", "box")

    held = load_config().device_keys["dev-1"]
    assert held.name == "device/box"
    assert held.open_key() == material
    assert ai_keys.ensure_device_key("dev-1", "box") == material
    assert len(load_config().device_keys) == 1
    assert load_config().client_keys == []

    ai_keys.revoke_device_key("dev-1")
    ai_keys.revoke_device_key("dev-1")

    assert load_config().device_keys == {}


def test_a_locked_vault_mints_no_device_key(config_dir):
    assert ai_keys.ensure_device_key("dev-1", "box") is None
    assert load_config().device_keys == {}


def test_a_devices_gateway_is_the_hubs_address_and_its_own_key(unlocked):
    assert ai_keys.device_gateway("dev-1", "10.0.0.1") == {
        "gateway_url": "",
        "gateway_key": "",
    }
    material = ai_keys.ensure_device_key("dev-1", "box")

    assert ai_keys.device_gateway("dev-1", "10.0.0.1") == {
        "gateway_url": "http://10.0.0.1:8317",
        "gateway_key": material,
    }
    assert ai_keys.device_gateway("dev-1", "")["gateway_url"] == ""


def test_a_key_no_setting_holds_on_is_revoked_and_the_others_kept(
    unlocked, monkeypatch
):
    applied: list = []
    monkeypatch.setattr(ai_keys, "_apply", lambda **kwargs: applied.append(kwargs))
    kept = ai_keys.ensure_device_key("dev-on", "on")
    ai_keys.ensure_device_key("dev-cloudcli", "old")
    applied.clear()

    dropped = ai_keys.settle_device_keys(["dev-on"])
    again = ai_keys.settle_device_keys(["dev-on"])

    assert dropped == ["dev-cloudcli"]
    assert again == []
    assert applied == [{}]
    assert ai_keys.ensure_device_key("dev-on", "on") == kept


def test_the_served_models_are_probed_with_the_hubs_own_key(unlocked, monkeypatch):
    from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
    from neutrino_hub.modules.cliproxyapi.ops import load_config, save_config

    class Served:
        def __init__(self):
            self.asked: list = []

        def served(self, *, port, client_key):
            self.asked.append((port, client_key))
            return True, ["m1", "m2"]

    served = Served()
    assert ai_keys.gateway_models(served) == []
    config = load_config()
    config.hub_key = CliproxyApiClientKey.generated("hub")
    save_config(config)

    assert ai_keys.gateway_models(served) == ["m1", "m2"]
    assert served.asked == [(config.listen_port, config.hub_key.open_key())]
