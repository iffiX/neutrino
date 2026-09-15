"""Every route follows the path rules of protocol.md.

A path is grouped as the sidebar is, under ``/api/hub`` or ``/api/agent``
(``/api/channel`` on the agent port, ``/ws/hub`` and ``/ws/agent`` for the
sockets); every segment is a singular ``under_score`` noun; an identifier is
in the query or the body, never in the path; a read is a GET ending in a
noun and a write a POST ending in one verb from the closed table.
"""

import re

import pytest
from starlette.routing import Route, WebSocketRoute

import neutrino_hub.web.app as app_module
from neutrino_hub.web.constants import (
    WEB_PATH_PREFIX_AGENT,
    WEB_PATH_PREFIX_CHANNEL,
    WEB_PATH_PREFIX_HUB,
    WEB_PATH_PREFIX_WS_AGENT,
    WEB_PATH_PREFIX_WS_HUB,
    WEB_PATH_VERBS,
)
from neutrino_hub.web.setup_app import WebSetupSession, create_setup_app

PREFIXES = (
    WEB_PATH_PREFIX_HUB,
    WEB_PATH_PREFIX_AGENT,
    WEB_PATH_PREFIX_CHANNEL,
    WEB_PATH_PREFIX_WS_HUB,
    WEB_PATH_PREFIX_WS_AGENT,
)
SEGMENT_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
# Singular nouns that end in an ``s``; every other ``s`` ending is a plural.
SINGULAR_S_NOUNS = frozenset({"status", "access", "address", "process", "dns", "zfs"})
# Reads whose last segment is a word of the verb table used as a noun, each
# a row of protocol.md chapter 6.
NOUN_READS = frozenset(
    {
        "/api/hub/credential/login",
        "/api/hub/device/online",
        "/api/hub/service/share",
        "/api/hub/network/interface/wifi/scan",
        "/api/agent/file/download",
        "/api/agent/file/directory/download",
    }
)
# What FastAPI and the single-page app serve beside the API.
FRAME_PATHS = frozenset(
    {"/openapi.json", "/docs", "/redoc", "/api/{path:path}", "/{path:path}"}
)


class StubLinkSampler:
    def start(self) -> None:
        return None


class StubUsageCollector:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self) -> None:
        return None


class StubRuntime:
    """Only what assembling the applications reaches for."""

    def __init__(self):
        self.served_models = None
        self.link_sampler = StubLinkSampler()

    def publish_ai_usage(self) -> None:
        return None


@pytest.fixture
def factories(monkeypatch):
    monkeypatch.setattr(app_module, "PanelRuntime", StubRuntime)
    monkeypatch.setattr(app_module, "PanelUsageCollector", StubUsageCollector)
    monkeypatch.setattr(app_module, "_shared_runtime", None)
    monkeypatch.setattr(app_module, "_usage_collector", None)
    return app_module


def routes_of(app) -> list:
    """Every ``(method, path)`` an application serves, sockets as ``WS``."""
    return _routes_under(app.routes, "")


def _routes_under(routes, prefix: str) -> list:
    # FastAPI mounts an included router as one entry holding the router and
    # its prefix, so the walk descends into it.
    found = []
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            child_prefix = prefix + route.include_context.prefix
            found.extend(_routes_under(included.routes, child_prefix))
        elif isinstance(route, WebSocketRoute):
            found.append(("WS", prefix + route.path))
        elif isinstance(route, Route):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, prefix + route.path))
    return found


def violations_of(method: str, path: str) -> list:
    """Every rule one route breaks, worded for the failure message."""
    if path in FRAME_PATHS:
        return []
    found = []
    if not path.startswith(PREFIXES):
        found.append("prefix")
    if "{" in path:
        found.append("identifier in the path")
    segments = path.split("/")[2:]
    for segment in segments:
        if not SEGMENT_PATTERN.match(segment):
            found.append(f"segment {segment!r} is not an under_score token")
        elif segment.endswith("s") and segment not in SINGULAR_S_NOUNS:
            found.append(f"segment {segment!r} is a plural")
    last = segments[-1] if segments else ""
    if method == "POST":
        if last not in WEB_PATH_VERBS:
            found.append(f"write ends in {last!r}, not a verb of the table")
    elif method in ("GET", "WS"):
        if last in WEB_PATH_VERBS and path not in NOUN_READS:
            found.append(f"read ends in the verb {last!r}")
    else:
        found.append(f"method {method}")
    return found


def assert_every_route_follows_the_rules(app) -> None:
    routes = routes_of(app)
    assert routes
    broken = {
        f"{method} {path}": violations_of(method, path)
        for method, path in routes
        if violations_of(method, path)
    }
    assert broken == {}


def test_every_panel_route_follows_the_rules(factories):
    assert_every_route_follows_the_rules(factories.create_app())


def test_every_agent_port_route_follows_the_rules(factories):
    assert_every_route_follows_the_rules(factories.create_agent_app())


def test_every_setup_route_follows_the_rules():
    assert_every_route_follows_the_rules(create_setup_app(WebSetupSession(context={})))


def test_the_panel_serves_no_route_at_the_top_level(factories):
    """Nothing is mounted beside the two groups: a route that fits no page
    is a route whose page has not been decided."""
    paths = {path for _, path in routes_of(factories.create_app())}

    assert not any(
        path.startswith("/api/") and not path.startswith(PREFIXES)
        for path in paths - FRAME_PATHS
    )
