"""The applier: resolving every sealed key, provider and client, before it renders."""

import pytest
import yaml

import neutrino_hub.utils.json_file
from neutrino_hub.modules.cliproxyapi import ops
from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_GENERATED_NAME
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.credentials.vault import SecretVault
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


@pytest.fixture()
def installed_box(box, monkeypatch):
    """The same box with the gateway declared installed and systemctl stubbed.

    Staleness only means anything where there is a gateway to be behind, and a
    real ``systemctl restart`` would bounce the one this test runs on.
    """
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: True)
    )
    monkeypatch.setattr(ops, "run", lambda *args, **kwargs: None)
    return box


def _rendered(box) -> dict:
    path = box / "generated" / CLIPROXYAPI_GENERATED_NAME
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_sealed_key_reaches_the_rendered_file(box):
    token_id = (
        SecretVault()
        .add(kind="token", name="relay key", secret={"value": "sealed-key"})
        .id
    )
    AiProviderRegistry().add(
        name="relay",
        kind="custom",
        base_url="https://relay.example/v1",
        secret_id=token_id,
    )
    message = CliproxyApiConfigApplier().apply()
    assert message == "rendered; the service is not installed yet"
    entries = _rendered(box)["openai-compatibility"][0]["api-key-entries"]
    assert entries == [{"api-key": "sealed-key"}]


def test_the_client_key_is_unsealed_into_the_rendered_file(box):
    config = ops.load_config()
    config.client_keys.append(CliproxyApiClientKey.generated("laptop"))
    ops.save_config(config)

    CliproxyApiConfigApplier().apply()

    material = ops.load_config().client_keys[0].open_key()
    assert _rendered(box)["api-keys"] == [material]
    stored = (box / "cliproxyapi" / "cliproxyapi.json").read_text(encoding="utf-8")
    assert material not in stored


def test_a_provider_with_no_sealed_key_renders_nothing(box):
    AiProviderRegistry().add(
        name="relay", kind="custom", base_url="https://relay.example/v1"
    )
    CliproxyApiConfigApplier().apply()
    assert "openai-compatibility" not in _rendered(box)


def test_the_management_key_is_generated_on_first_apply(box):
    CliproxyApiConfigApplier().apply()
    sealed = box / "cliproxyapi" / "management_key.sealed"
    working = box / "state" / "cliproxyapi" / "management.key"
    assert sealed.is_file()
    key = working.read_text(encoding="utf-8").strip()
    assert len(key) == 64
    document = _rendered(box)
    assert document["usage-statistics-enabled"] is True
    assert document["remote-management"]["secret-key"] == key
    assert document["remote-management"]["allow-remote"] is False
    # A second apply reuses the sealed key rather than rotating it.
    CliproxyApiConfigApplier().apply()
    assert working.read_text(encoding="utf-8").strip() == key


def test_a_dry_run_render_generates_no_key(box):
    rendered = CliproxyApiConfigApplier().render_with_stored_key()
    document = yaml.safe_load(rendered)
    assert "remote-management" not in document
    assert not (box / "cliproxyapi" / "management_key.sealed").exists()
    assert not (box / "state" / "cliproxyapi" / "management.key").exists()


def test_a_box_that_has_never_applied_is_stale(installed_box):
    assert CliproxyApiConfigApplier().is_serving_stale is True


def test_an_apply_leaves_nothing_stale(installed_box):
    applier = CliproxyApiConfigApplier()
    applier.apply()
    fingerprint = installed_box / "state" / "cliproxyapi" / "served_fingerprint.txt"
    assert len(fingerprint.read_text(encoding="utf-8").strip()) == 64
    assert applier.is_serving_stale is False


def test_a_change_after_an_apply_is_stale(installed_box):
    CliproxyApiConfigApplier().apply()
    config = ops.load_config()
    config.listen_port += 1
    ops.save_config(config)
    assert CliproxyApiConfigApplier().is_serving_stale is True


def test_a_provider_added_after_an_apply_is_stale(installed_box):
    CliproxyApiConfigApplier().apply()
    token_id = (
        SecretVault().add(kind="token", name="relay key", secret={"value": "k"}).id
    )
    AiProviderRegistry().add(
        name="relay",
        kind="custom",
        base_url="https://relay.example/v1",
        secret_id=token_id,
    )
    assert CliproxyApiConfigApplier().is_serving_stale is True


def test_the_gateways_own_rewrite_of_the_file_leaves_nothing_stale(installed_box):
    """The fingerprint is of what the applier wrote, not of what is there now.

    The gateway replaces the management key in its copy with a bcrypt hash on
    first read, which is not a change the panel should ask anybody to apply.
    """
    applier = CliproxyApiConfigApplier()
    applier.apply()
    path = installed_box / "generated" / CLIPROXYAPI_GENERATED_NAME
    path.write_text(
        path.read_text(encoding="utf-8").replace("secret-key:", "secret-key: $2a$"),
        encoding="utf-8",
    )
    assert applier.is_serving_stale is False


def test_a_box_without_the_gateway_is_never_stale(box):
    assert CliproxyApiConfigApplier().is_serving_stale is False
