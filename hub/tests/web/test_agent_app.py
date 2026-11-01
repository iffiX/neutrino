"""The panel application: its routes and what it starts and stops."""

import pytest

import neutrino_hub.web.app as app_module
from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.desired_state import (
    DesiredStateStore,
    account_layer_agent_config,
)
from neutrino_hub.modules.devices.folder_shares import with_folder_share
from neutrino_hub.modules.devices.module_import import import_module_config
from neutrino_hub.modules.devices.module_table import module_row
from neutrino_hub.modules.devices.registry import DeviceRegistry
from tests.conftest import unlock_vault
from tests.web.test_paths import routes_of


class StubLinkSampler:
    def start(self) -> None:
        return None


class StubExitController:
    """The exit rounds, which the application starts and nothing here runs."""

    def start(self) -> None:
        return None


class StubRelayMonitor:
    """The relay's monitor, which the application starts and nothing here runs."""

    def start(self) -> None:
        return None


class StubTrafficHistory:
    """The traffic history, recording its start and its stop."""

    def __init__(self):
        self.calls: list = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")


class StubUsageCollector:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self) -> None:
        return None


class StubRuntime:
    """Only what assembling the panel application reaches for."""

    def __init__(self):
        self.served_models = None
        self.link_sampler = StubLinkSampler()
        self.address_sampler = StubLinkSampler()
        self.release_sampler = StubLinkSampler()
        self.enrollment_sweeper = StubLinkSampler()
        self.web_share_sweeper = StubLinkSampler()
        self.traffic_history = StubTrafficHistory()
        self.proxy = StubExitController()
        self.relay_monitor = StubRelayMonitor()
        self.frp_monitors = {
            "sakurafrp": StubRelayMonitor(),
            "openfrp": StubRelayMonitor(),
        }

    def publish_ai_usage(self) -> None:
        return None


class StubGatewayApplier:
    """The gateway applier as the panel's start reaches for it."""

    is_installed = True
    applied = 0

    def apply(self) -> str:
        StubGatewayApplier.applied += 1
        return "applied"


class StubGatewayConfig:
    def __init__(self, hub_key):
        self.hub_key = hub_key


@pytest.fixture
def factories(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "PanelRuntime", StubRuntime)
    monkeypatch.setattr(app_module, "PanelUsageCollector", StubUsageCollector)
    monkeypatch.setattr(app_module, "_shared_runtime", None)
    monkeypatch.setattr(app_module, "_usage_collector", None)
    monkeypatch.setattr(app_module, "WEB_LEGACY_TLS_DIR", tmp_path / "agent_tls")
    monkeypatch.setattr(
        app_module, "WEB_LEGACY_TLS_SERVED_KEY_PATH", tmp_path / "agent_tls_key.pem"
    )
    # No gateway on the box the tests run on, whatever the box has.
    StubGatewayApplier.is_installed = False
    StubGatewayApplier.applied = 0
    monkeypatch.setattr(app_module, "CliproxyApiConfigApplier", StubGatewayApplier)
    return app_module


def api_paths(app) -> set:
    return {path for path in app.openapi()["paths"] if path.startswith("/api/")}


def route_set(app) -> set:
    """Every ``(method, path)`` under ``/api``, sockets as ``WS``."""
    return {
        (method, path)
        for method, path in routes_of(app)
        if path.startswith("/api/") and "{" not in path
    }


def test_the_panel_app_serves_no_channel_route(factories):
    app = factories.create_app()
    paths = api_paths(app)

    assert paths
    assert not any(path.startswith("/api/channel") for path in paths)
    assert not any(path.startswith("/api/channel") for _, path in route_set(app))
    assert "/api/hub/client" in paths


def test_the_panel_counts_the_traffic_history_and_writes_it_at_its_stop(factories):
    factories.create_app()
    factories.stop_samplers()

    assert factories.shared_runtime().traffic_history.calls == ["start", "stop"]


def test_a_stop_before_the_panel_started_builds_no_runtime(factories):
    factories.stop_samplers()

    assert factories._shared_runtime is None


@pytest.fixture
def gateway(factories):
    StubGatewayApplier.is_installed = True
    return factories


def test_the_panel_mints_the_hubs_gateway_key_at_start_when_the_box_has_none(
    gateway, monkeypatch
):
    monkeypatch.setattr(gateway, "load_config", lambda: StubGatewayConfig(None))

    gateway.create_app()

    assert StubGatewayApplier.applied == 1


def test_a_box_holding_the_hubs_key_applies_nothing_at_start(gateway, monkeypatch):
    monkeypatch.setattr(gateway, "load_config", lambda: StubGatewayConfig(object()))

    gateway.create_app()

    assert StubGatewayApplier.applied == 0


def test_a_box_without_the_gateway_applies_nothing_at_start(gateway, monkeypatch):
    StubGatewayApplier.is_installed = False
    monkeypatch.setattr(gateway, "load_config", lambda: StubGatewayConfig(None))

    gateway.create_app()

    assert StubGatewayApplier.applied == 0


def test_the_panel_deletes_the_tls_pair_of_0_5_at_start(
    factories, monkeypatch, tmp_path
):
    pair = tmp_path / "config" / "web" / "agent_tls"
    pair.mkdir(parents=True)
    (pair / "certificate.pem").write_text("cert")
    (pair / "key.sealed").write_text("{}")
    served = tmp_path / "state" / "agent_tls_key.pem"
    served.parent.mkdir()
    served.write_text("key")
    monkeypatch.setattr(factories, "WEB_LEGACY_TLS_DIR", pair)
    monkeypatch.setattr(factories, "WEB_LEGACY_TLS_SERVED_KEY_PATH", served)

    factories.create_app()

    assert not pair.exists()
    assert not served.exists()


@pytest.fixture
def config_box(factories, monkeypatch, tmp_path):
    """A ``config/`` of this test's own, with its vault unlocked."""
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", config
    )
    unlock_vault(monkeypatch, tmp_path)
    return factories


def enabled_with_folder_share(store: DesiredStateStore, device_id: str) -> dict:
    """The file share's file after an account is enabled and a folder share added."""
    DeviceAccountStore(store).add(device_id, DeviceAccount(account="lab"))
    store.set_enabled_accounts(device_id, "samba", ["lab"])
    store.write(
        device_id,
        "samba",
        with_folder_share(
            store.read(device_id, "samba"),
            {"name": "probe", "path": "/srv/probe", "accounts": ["lab"]},
        ),
    )
    return store.read(device_id, "samba")


def samba_section(store: DesiredStateStore, device_id: str) -> dict:
    """The file share's section as the agent is sent it."""
    return account_layer_agent_config(
        module_row("samba"),
        store.read(device_id, "samba"),
        DeviceAccountStore(store).accounts(device_id),
        {"os": "linux"},
        account_details={"lab": {"home": "/home/lab"}},
    )


@pytest.mark.parametrize(
    "adopted",
    [import_module_config("samba", {}), {"shares": [], "users": []}],
    ids=["this_build", "an_earlier_build"],
)
def test_a_restart_keeps_the_file_share_of_an_adopted_machine(config_box, adopted):
    device_id = DeviceRegistry().create("box").id
    store = DesiredStateStore()
    store.write(device_id, "samba", adopted)
    written = enabled_with_folder_share(store, device_id)

    config_box.create_app()
    config_box.create_app()

    assert store.read(device_id, "samba") == written
    section = samba_section(store, device_id)
    assert [share["name"] for share in section["shares"]] == ["lab", "probe"]
    assert section["users"] == ["neutrino-lab"]


def test_a_restart_moves_a_0_5_file_share_once_and_the_next_keeps_what_follows(
    config_box,
):
    device_id = DeviceRegistry().create("box").id
    store = DesiredStateStore()
    store.write(
        device_id,
        "samba",
        {
            "shares": [
                {
                    "name": "media",
                    "path": "/tank/media",
                    "comment": "",
                    "is_read_only": False,
                    "valid_users": ["ann"],
                }
            ],
            "users": ["ann"],
        },
    )

    config_box.create_app()

    assert store.read(device_id, "samba") == {"shares": []}

    written = enabled_with_folder_share(store, device_id)

    config_box.create_app()

    assert store.read(device_id, "samba") == written
    assert samba_section(store, device_id)["users"] == ["neutrino-lab"]
