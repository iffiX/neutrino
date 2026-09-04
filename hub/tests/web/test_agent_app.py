"""The panel and the agent channel are two applications on one runtime.

The agent routes left the panel with the move to pinned TLS: the panel app
must not answer them on plain HTTP, and the agent app must answer nothing
else. One runtime behind both is what lets a ticket generated on the panel be
spent on the agent port.
"""

from types import SimpleNamespace

import pytest

import neutrino_hub.web.app as app_module


@pytest.fixture
def factories(monkeypatch):
    monkeypatch.setattr(app_module, "PanelRuntime", SimpleNamespace)
    monkeypatch.setattr(app_module, "_shared_runtime", None)
    return app_module


def api_paths(app) -> set:
    return {path for path in app.openapi()["paths"] if path.startswith("/api/")}


def test_the_agent_app_serves_only_agent_routes(factories):
    paths = api_paths(factories.create_agent_app())

    assert paths
    assert all(path.startswith("/api/agent/") for path in paths)


def test_the_panel_app_serves_no_agent_routes(factories):
    paths = api_paths(factories.create_app())

    assert paths
    assert not any(path.startswith("/api/agent/") for path in paths)


def test_both_apps_share_one_runtime(factories):
    panel = factories.create_app()
    agent = factories.create_agent_app()

    assert panel.state.runtime is agent.state.runtime
