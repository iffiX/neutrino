"""The panel application: its routes and what it starts and stops."""

import pytest

import neutrino_hub.web.app as app_module
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
def factories(monkeypatch):
    monkeypatch.setattr(app_module, "PanelRuntime", StubRuntime)
    monkeypatch.setattr(app_module, "PanelUsageCollector", StubUsageCollector)
    monkeypatch.setattr(app_module, "_shared_runtime", None)
    monkeypatch.setattr(app_module, "_usage_collector", None)
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
