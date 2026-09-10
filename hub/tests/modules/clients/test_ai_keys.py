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


def test_the_credential_names_the_hub_as_the_client_reaches_it(unlocked):
    registry = ClientRegistry()
    client_id = registry.create("alice")
    served = StubServedModels("claude-x")

    credential = client_credential(
        registry,
        registry.get(client_id),
        hub_host="192.168.100.1",
        served_models=served,
    )

    port = load_config().listen_port
    assert credential == {
        "base_url": f"http://192.168.100.1:{port}",
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
        client_credential(
            registry, registry.get(client_id), hub_host="h", served_models=served
        )
        is None
    )

    unlock_vault(monkeypatch, config_dir)
    registry.set_disabled(client_id, True)

    assert (
        client_credential(
            registry,
            ClientRegistry().get(client_id),
            hub_host="h",
            served_models=served,
        )
        is None
    )
    assert load_config().client_keys == []
    assert served.asked == []


def test_an_apply_that_refuses_does_not_undo_the_mint(unlocked, monkeypatch):
    def refuse(self):
        raise ValueError("no")

    monkeypatch.setattr(CliproxyApiConfigApplier, "apply", refuse)
    registry = ClientRegistry()
    client_id = registry.create("alice")

    assert ensure_client_key(registry, registry.get(client_id))
    assert len(load_config().client_keys) == 1
    assert ai_keys.load_config().client_keys[0].name == "client/alice"
