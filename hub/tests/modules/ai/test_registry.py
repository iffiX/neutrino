"""The AI provider registry: sealed keys, one-way reads, and validation."""

import json

import pytest

import neutrino_hub.utils.json_file
from neutrino_hub.modules.ai.constants import AI_PROVIDERS_PATH
from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.credentials.vault import SecretVault
from tests.conftest import unlock_vault


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


def _stored_text(config_dir) -> str:
    return (config_dir / AI_PROVIDERS_PATH).read_text(encoding="utf-8")


def test_add_and_list(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(
        name="Anthropic direct",
        kind="anthropic",
        base_url="",
        api_key="sk-ant-x",
    )
    assert record.id
    stored = AiProviderRegistry().list_records()
    assert [r.name for r in stored] == ["Anthropic direct"]
    assert AiProviderRegistry().open_api_key(stored[0]) == "sk-ant-x"


def test_the_key_is_never_written_beside_the_provider(config_dir):
    registry = AiProviderRegistry()
    registry.add(name="relay", kind="custom", base_url="", api_key="sk-plain")
    text = _stored_text(config_dir)
    assert "api_key" not in text
    assert "sk-plain" not in text


def test_add_seals_the_key_as_a_named_vault_object(config_dir):
    record = AiProviderRegistry().add(
        name="relay", kind="custom", base_url="", api_key="tok"
    )
    assert record.secret_id
    sealed = SecretVault().get(record.secret_id)
    assert sealed is not None
    assert sealed.kind == "token"
    assert sealed.name == "relay api key"


def test_add_without_a_key_references_nothing(config_dir):
    record = AiProviderRegistry().add(
        name="relay", kind="custom", base_url="", api_key=""
    )
    assert record.secret_id is None
    assert AiProviderRegistry().open_api_key(record) == ""
    assert SecretVault().list_records() == []


def test_blank_key_on_update_keeps_stored_one(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", api_key="tok")
    registry.update(record.id, name="renamed", api_key="")
    reloaded = AiProviderRegistry().get(record.id)
    assert reloaded is not None
    assert reloaded.name == "renamed"
    assert reloaded.secret_id == record.secret_id
    assert AiProviderRegistry().open_api_key(reloaded) == "tok"


def test_update_replaces_the_sealed_material_in_place(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", api_key="old")
    registry.update(record.id, api_key="new")
    reloaded = AiProviderRegistry().get(record.id)
    assert reloaded is not None
    assert reloaded.secret_id == record.secret_id
    assert AiProviderRegistry().open_api_key(reloaded) == "new"
    assert len(SecretVault().list_records()) == 1


def test_update_seals_a_key_for_a_provider_that_had_none(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", api_key="")
    registry.update(record.id, api_key="late")
    reloaded = AiProviderRegistry().get(record.id)
    assert reloaded is not None
    assert reloaded.secret_id
    assert AiProviderRegistry().open_api_key(reloaded) == "late"


def test_delete_takes_the_vault_object_with_it(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", api_key="tok")
    registry.delete(record.id)
    assert SecretVault().get(record.secret_id) is None
    assert json.loads(_stored_text(config_dir))["providers"] == []


def test_delete_survives_a_vault_object_already_gone(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", api_key="tok")
    SecretVault().delete(record.secret_id)
    registry.delete(record.id)
    assert AiProviderRegistry().list_records() == []


def test_unknown_kind_is_refused(config_dir):
    registry = AiProviderRegistry()
    with pytest.raises(ValueError):
        registry.add(name="x", kind="acme", base_url="", api_key="k")


def test_delete_unknown_id_raises(config_dir):
    with pytest.raises(KeyError):
        AiProviderRegistry().delete("nope")


def test_missing_file_reads_empty(config_dir):
    assert AiProviderRegistry().list_records() == []


def test_a_dangling_secret_reference_reads_as_no_key(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(name="p", kind="openai", base_url="", api_key="sk-x")
    SecretVault().delete(record.secret_id)

    assert AiProviderRegistry().open_api_key(record) == ""
