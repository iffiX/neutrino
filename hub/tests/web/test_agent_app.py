"""The panel and the agent channel are two applications on one runtime.

The agent port serves ``/api/channel`` and nothing else: the panel app must
not answer the channel on plain HTTP, and the agent app must answer nothing
but the channel. One runtime behind both is what lets a ticket generated
on the panel be spent on the agent port.
"""

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


class StubUsageCollector:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self) -> None:
        return None


class StubRuntime:
    """Only what assembling the two applications reaches for."""

    def __init__(self):
        self.served_models = None
        self.link_sampler = StubLinkSampler()
        self.exit_controller = StubExitController()

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


CHANNEL_ROUTES = {
    ("POST", "/api/channel/join"),
    ("POST", "/api/channel/leave"),
    ("WS", "/api/channel/socket"),
}


def test_the_agent_app_serves_the_three_channel_routes_and_nothing_else(factories):
    app = factories.create_agent_app()

    assert route_set(app) == CHANNEL_ROUTES
    assert api_paths(app) == {"/api/channel/join", "/api/channel/leave"}


def test_the_panel_app_serves_no_channel_route(factories):
    app = factories.create_app()
    paths = api_paths(app)

    assert paths
    assert not any(path.startswith("/api/channel") for path in paths)
    assert not route_set(app) & CHANNEL_ROUTES
    assert "/api/hub/client" in paths


def test_a_body_that_does_not_validate_is_refused_in_the_one_shape(factories):
    """FastAPI's own answer is a 422 carrying a list; a client written from
    protocol.md reads every refusal as ``{code, params}`` under a status of
    the 400 class, and this is where that promise is kept."""
    from fastapi.testclient import TestClient

    app = factories.create_agent_app()
    with TestClient(app) as client:
        answer = client.post("/api/channel/join", json={"ticket": 7})

    assert answer.status_code == 400
    detail = answer.json()["detail"]
    assert detail["code"] == "body_invalid"
    assert detail["params"]["fields"] == "ticket, role"


def test_both_apps_share_one_runtime(factories):
    panel = factories.create_app()
    agent = factories.create_agent_app()

    assert panel.state.runtime is agent.state.runtime


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
