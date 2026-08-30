"""The AI provider registry: storage, one-way keys, and validation."""

import pytest

import neutrino_hub.utils.json_file
from neutrino_hub.modules.credentials.registry import AiProviderRegistry


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


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
    assert stored[0].api_key == "sk-ant-x"


def test_blank_key_on_update_keeps_stored_one(config_dir):
    registry = AiProviderRegistry()
    record = registry.add(name="relay", kind="custom", base_url="", api_key="tok")
    registry.update(record.id, name="renamed", api_key="")
    reloaded = AiProviderRegistry().get(record.id)
    assert reloaded is not None
    assert reloaded.name == "renamed"
    assert reloaded.api_key == "tok"


def test_unknown_kind_is_refused(config_dir):
    registry = AiProviderRegistry()
    with pytest.raises(ValueError):
        registry.add(name="x", kind="acme", base_url="", api_key="k")


def test_delete_unknown_id_raises(config_dir):
    with pytest.raises(KeyError):
        AiProviderRegistry().delete("nope")


def test_missing_file_reads_empty(config_dir):
    assert AiProviderRegistry().list_records() == []
