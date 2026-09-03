"""The applier: resolving each provider's sealed key before it renders."""

import pytest
import yaml

import neutrino_hub.utils.json_file
from neutrino_hub.modules.cliproxyapi import ops
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_GENERATED_NAME
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.ai.registry import AiProviderRegistry
from tests.conftest import unlock_vault


@pytest.fixture()
def box(tmp_path, monkeypatch):
    """A config root and a generated directory of their own, nothing installed.

    The binary is declared absent so the applier renders and stops: a test that
    reached ``systemctl restart`` would bounce the gateway it runs on.
    """
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    return tmp_path


def _rendered(box) -> dict:
    path = box / "generated" / CLIPROXYAPI_GENERATED_NAME
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_sealed_key_reaches_the_rendered_file(box):
    AiProviderRegistry().add(
        name="relay",
        kind="custom",
        base_url="https://relay.example/v1",
        api_key="sealed-key",
    )
    message = CliproxyApiConfigApplier().apply()
    assert message == "rendered; the service is not installed yet"
    entries = _rendered(box)["openai-compatibility"][0]["api-key-entries"]
    assert entries == [{"api-key": "sealed-key"}]


def test_a_provider_with_no_sealed_key_renders_nothing(box):
    AiProviderRegistry().add(
        name="relay", kind="custom", base_url="https://relay.example/v1", api_key=""
    )
    CliproxyApiConfigApplier().apply()
    assert "openai-compatibility" not in _rendered(box)
