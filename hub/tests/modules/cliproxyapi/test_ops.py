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

    stored_config = ops.load_config()
    material = stored_config.client_keys[0].open_key()
    assert _rendered(box)["api-keys"] == [material, stored_config.hub_key.open_key()]
    stored = (box / "cliproxyapi" / "cliproxyapi.json").read_text(encoding="utf-8")
    assert material not in stored


def test_the_first_apply_mints_the_hubs_own_key_and_later_ones_keep_it(box):
    """The gateway's key list is never empty once applied: with no key at
    all the gateway asks nobody for one, and the hub has nothing to probe
    with."""
    assert ops.load_config().hub_key is None

    CliproxyApiConfigApplier().apply()
    minted = ops.load_config().hub_key
    CliproxyApiConfigApplier().apply()

    assert minted is not None
    assert minted.name == "hub"
    assert ops.load_config().hub_key.id == minted.id
    assert _rendered(box)["api-keys"] == [minted.open_key()]
    stored = (box / "cliproxyapi" / "cliproxyapi.json").read_text(encoding="utf-8")
    assert minted.open_key() not in stored


def test_the_probe_key_is_the_hubs_own_before_any_clients(box):
    config = ops.load_config()
    assert config.probe_key() is None

    config.client_keys.append(CliproxyApiClientKey.generated("laptop"))
    assert config.probe_key() == config.client_keys[0].open_key()

    CliproxyApiConfigApplier().apply()
    applied = ops.load_config()
    assert applied.probe_key() == applied.hub_key.open_key()


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


def test_the_served_models_are_listed_by_name(monkeypatch):
    """The gateway lists them in the order its providers registered; a
    person picking one in the client reads them by name."""

    class _Answer:
        is_success = True
        status_code = 200

        def json(self):
            return {
                "data": [
                    {"id": "gpt-5"},
                    {"id": "claude-opus-5"},
                    {"id": ""},
                    {"id": "gemini-3-pro"},
                ]
            }

    monkeypatch.setattr(ops.httpx, "get", lambda *args, **kwargs: _Answer())

    is_answered, _, served = ops.CliproxyApiConfigApplier().probe(
        port=8317, client_key="k"
    )

    assert is_answered
    assert served == ["claude-opus-5", "gemini-3-pro", "gpt-5"]


def test_a_probe_that_finds_nothing_to_serve_answers_a_code(monkeypatch):
    class _Answer:
        is_success = False
        status_code = 503

    monkeypatch.setattr(ops.httpx, "get", lambda *args, **kwargs: _Answer())
    applier = ops.CliproxyApiConfigApplier()

    assert applier.probe(port=8317, client_key=None) == (
        False,
        {"code": "gateway_no_probe_key", "params": {}},
        [],
    )
    assert applier.probe(port=8317, client_key="k") == (
        False,
        {"code": "gateway_probe_status", "params": {"status": 503}},
        [],
    )
    _Answer.is_success = True
    _Answer.json = lambda self: {"data": []}
    assert applier.probe(port=8317, client_key="k") == (
        True,
        {"code": "gateway_no_models", "params": {}},
        [],
    )


def test_elsewhere_an_apply_restarts_the_child(
    elsewhere, installed_box, fake_controller
):
    assert CliproxyApiConfigApplier().apply().endswith("restarted")
    assert fake_controller.verbs() == [("restart", "cliproxyapi")]


# --- a change of keys is reloaded in place ---


class Gateway:
    """The running gateway as the probe sees it: each answer from a script."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked: list = []

    def probe(self, *, port, client_key):
        self.asked.append((port, client_key))
        status = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if status is None:
            return False, {"code": "gateway_unreachable", "params": {}}, []
        if status == 200:
            return True, None, ["m"]
        return False, {"code": "gateway_probe_status", "params": {"status": status}}, []

    def install(self, monkeypatch) -> "Gateway":
        """Answer every applier's probe from this script."""
        monkeypatch.setattr(
            CliproxyApiConfigApplier,
            "probe",
            lambda applier, **kwargs: self.probe(**kwargs),
        )
        return self


@pytest.fixture()
def served_box(installed_box, monkeypatch):
    """An installed box that has applied once, with every restart recorded and
    no real waiting."""
    restarts: list = []
    monkeypatch.setattr(ops, "run", lambda command, **kwargs: restarts.append(command))
    monkeypatch.setattr(ops.time, "sleep", lambda seconds: None)
    CliproxyApiConfigApplier().apply()
    restarts.clear()
    return installed_box, restarts


def _add_client_key(name: str) -> str:
    config = ops.load_config()
    key = CliproxyApiClientKey.generated(name)
    config.client_keys.append(key)
    ops.save_config(config)
    return key.open_key()


def test_a_new_key_is_written_in_place_and_awaited_with_no_restart(
    served_box, monkeypatch
):
    box, restarts = served_box
    served = box / "generated" / CLIPROXYAPI_GENERATED_NAME
    inode = served.stat().st_ino
    gateway = Gateway([401, 401, 200])
    gateway.install(monkeypatch)
    material = _add_client_key("client/alice")

    assert CliproxyApiConfigApplier().apply_keys(new_key=material) == "reloaded"

    assert served.stat().st_ino == inode
    assert served.stat().st_mode & 0o777 == 0o600
    assert material in _rendered(box)["api-keys"]
    assert [key for _, key in gateway.asked] == [material] * 3
    assert restarts == []
    assert not CliproxyApiConfigApplier().is_serving_stale


def test_a_render_equal_to_the_served_one_writes_nothing_and_restarts_nothing(
    served_box, monkeypatch
):
    box, restarts = served_box
    served = box / "generated" / CLIPROXYAPI_GENERATED_NAME
    before = served.stat().st_mtime_ns
    gateway = Gateway([200])
    gateway.install(monkeypatch)

    assert CliproxyApiConfigApplier().apply_keys(new_key="k") == "unchanged"

    assert served.stat().st_mtime_ns == before
    assert gateway.asked == []
    assert restarts == []


def test_a_removed_key_is_reloaded_without_a_wait(served_box, monkeypatch):
    box, restarts = served_box
    _add_client_key("client/bob")
    CliproxyApiConfigApplier().apply_keys(new_key=None)
    config = ops.load_config()
    config.client_keys = []
    ops.save_config(config)
    gateway = Gateway([200])
    gateway.install(monkeypatch)

    assert CliproxyApiConfigApplier().apply_keys() == "reloaded"

    assert gateway.asked == []
    assert restarts == []


def test_a_gateway_that_never_takes_the_key_is_restarted_and_awaited(
    served_box, monkeypatch
):
    _box, restarts = served_box
    monkeypatch.setattr(ops, "CLIPROXYAPI_RELOAD_WAIT_S", 0)
    gateway = Gateway([401, None, None, 200])
    gateway.install(monkeypatch)
    material = _add_client_key("client/carol")

    assert CliproxyApiConfigApplier().apply_keys(new_key=material) == "restarted"

    assert restarts == [["systemctl", "restart", "neutrino_hub_cliproxyapi.service"]]
    assert len(gateway.asked) == 4


def test_a_restart_that_never_listens_still_answers_after_its_bound(
    served_box, monkeypatch
):
    _box, restarts = served_box
    monkeypatch.setattr(ops, "CLIPROXYAPI_RELOAD_WAIT_S", 0)
    monkeypatch.setattr(ops, "CLIPROXYAPI_RESTART_WAIT_S", 0)
    Gateway([None]).install(monkeypatch)
    material = _add_client_key("client/dan")

    assert CliproxyApiConfigApplier().apply_keys(new_key=material) == "restarted"
    assert len(restarts) == 1


def test_elsewhere_a_gateway_that_never_takes_the_key_restarts_the_child(
    elsewhere, fake_controller, served_box, monkeypatch
):
    monkeypatch.setattr(ops, "CLIPROXYAPI_RELOAD_WAIT_S", 0)
    Gateway([401, 200]).install(monkeypatch)
    material = _add_client_key("client/erin")
    fake_controller.calls.clear()

    assert CliproxyApiConfigApplier().apply_keys(new_key=material) == "restarted"
    assert fake_controller.verbs() == [("restart", "cliproxyapi")]


def test_elsewhere_a_new_key_is_reloaded_with_no_restart(
    elsewhere, fake_controller, served_box, monkeypatch
):
    Gateway([200]).install(monkeypatch)
    before = list(fake_controller.verbs())
    material = _add_client_key("client/fay")

    assert CliproxyApiConfigApplier().apply_keys(new_key=material) == "reloaded"
    assert fake_controller.verbs() == before


def test_a_box_that_never_applied_is_applied_whole(installed_box, monkeypatch):
    restarts: list = []
    monkeypatch.setattr(ops, "run", lambda command, **kwargs: restarts.append(command))

    assert CliproxyApiConfigApplier().apply_keys(new_key="k").endswith("restarted")
    assert restarts == [["systemctl", "restart", "neutrino_hub_cliproxyapi.service"]]
