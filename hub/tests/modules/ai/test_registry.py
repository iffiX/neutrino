"""The AI provider registry: token references in, resolved keys out."""

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


def _token(value: str = "sk-ant-x") -> str:
    return SecretVault().add(kind="token", name="a key", secret={"value": value}).id


def test_add_and_list(config_dir):
    token_id = _token()
    record = AiProviderRegistry().add(
        name="Anthropic direct",
        kind="anthropic",
        base_url="",
        secret_id=token_id,
    )
    assert record.id
    stored = AiProviderRegistry().list_records()
    assert [r.name for r in stored] == ["Anthropic direct"]
    assert stored[0].secret_id == token_id
    assert AiProviderRegistry().open_api_key(stored[0]) == "sk-ant-x"


def test_only_the_reference_is_written_beside_the_provider(config_dir):
    token_id = _token("sk-plain")
    AiProviderRegistry().add(
        name="relay", kind="custom", base_url="", secret_id=token_id
    )
    text = _stored_text(config_dir)
    assert token_id in text
    assert "sk-plain" not in text


def test_add_without_a_reference_stores_none(config_dir):
    record = AiProviderRegistry().add(name="relay", kind="custom", base_url="")
    assert record.secret_id is None
    assert AiProviderRegistry().open_api_key(record) == ""


def test_an_untouched_update_keeps_the_reference(config_dir):
    token_id = _token()
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", secret_id=token_id)
    registry.update(record.id, name="renamed")
    reloaded = AiProviderRegistry().get(record.id)
    assert reloaded is not None
    assert reloaded.name == "renamed"
    assert reloaded.secret_id == token_id


def test_update_repoints_or_clears_the_reference(config_dir):
    first = _token("old")
    second = _token("new")
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", secret_id=first)

    registry.update(record.id, secret_id=second)
    reloaded = AiProviderRegistry().get(record.id)
    assert reloaded.secret_id == second
    assert AiProviderRegistry().open_api_key(reloaded) == "new"

    registry.update(record.id, secret_id=None)
    assert AiProviderRegistry().get(record.id).secret_id is None
    # The token itself is untouched: its lifecycle is the Credentials page's.
    assert SecretVault().get(second) is not None


def test_delete_leaves_the_token_in_the_vault(config_dir):
    token_id = _token()
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", secret_id=token_id)
    registry.delete(record.id)
    assert json.loads(_stored_text(config_dir))["providers"] == []
    assert SecretVault().get(token_id) is not None


def test_unknown_kind_is_refused(config_dir):
    with pytest.raises(ValueError):
        AiProviderRegistry().add(name="x", kind="acme", base_url="")


def test_delete_unknown_id_raises(config_dir):
    with pytest.raises(KeyError):
        AiProviderRegistry().delete("nope")


def test_missing_file_reads_empty(config_dir):
    assert AiProviderRegistry().list_records() == []


def test_a_dangling_secret_reference_reads_as_no_key(config_dir):
    token_id = _token("sk-x")
    registry = AiProviderRegistry()
    record = registry.add(name="p", kind="openai", base_url="", secret_id=token_id)
    SecretVault().delete(token_id)

    assert AiProviderRegistry().open_api_key(record) == ""
