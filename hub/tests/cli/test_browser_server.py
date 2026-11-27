"""Getting the browser wizard a port, and never being stuck without one.

The wizard is an offer, not a requirement: whatever goes wrong reaching for
it, the terminal's own screens still ask the same questions. A first run that
cannot be answered at all is the one failure this must not produce.
"""

import socket
from types import SimpleNamespace

import pytest

from neutrino_hub.cli import setup as setup_cli
from neutrino_hub.platforms.base import HubPlatform
from neutrino_hub.platforms.darwin import DarwinHubPlatform
from neutrino_hub.utils.loopback_listen import bind_ipv6_loopback, has_ipv6_loopback
from neutrino_hub.web import setup_app
from neutrino_hub.web.setup_app import WebSetupSession

needs_ipv6 = pytest.mark.skipif(
    not has_ipv6_loopback(), reason="the machine has no IPv6 loopback"
)


def _mac():
    return SimpleNamespace(has_panel_ipv6_loopback=True)


def test_the_wizard_opens_at_localhost_on_macos_and_at_127_0_0_1_elsewhere(
    monkeypatch,
):
    monkeypatch.setattr(setup_cli, "hub_platform", DarwinHubPlatform)
    mac = setup_cli._wizard_url(8080, "t0ken")
    monkeypatch.setattr(setup_cli, "hub_platform", HubPlatform)
    other = setup_cli._wizard_url(8080, "t0ken")

    assert mac == "http://localhost:8080/?token=t0ken"
    assert other == "http://127.0.0.1:8080/?token=t0ken"


@needs_ipv6
def test_on_macos_the_wizard_also_listens_on_the_ipv6_loopback(monkeypatch):
    free = _free_port()
    monkeypatch.setattr(setup_app, "hub_platform", _mac)
    monkeypatch.setattr(setup_cli, "_browser_port", lambda: free)
    monkeypatch.setattr(setup_cli, "SETUP_BROWSER_HOST", "127.0.0.1")
    session = WebSetupSession(context={})

    server = setup_cli._browser_server(session)

    try:
        assert server is not None
        assert server.port == free
        socket.create_connection(("::1", free), timeout=2).close()
        socket.create_connection(("127.0.0.1", free), timeout=2).close()
    finally:
        server.stop()


@needs_ipv6
def test_on_macos_a_held_ipv6_loopback_gets_the_wizard_another_port(monkeypatch):
    free = _free_port()
    held = bind_ipv6_loopback(free)
    held.listen(1)
    monkeypatch.setattr(setup_app, "hub_platform", _mac)
    monkeypatch.setattr(setup_cli, "_browser_port", lambda: free)
    monkeypatch.setattr(setup_cli, "SETUP_BROWSER_HOST", "127.0.0.1")
    session = WebSetupSession(context={})

    server = setup_cli._browser_server(session)

    try:
        assert server is not None
        assert server.port != free
    finally:
        if server is not None:
            server.stop()
        held.close()


def test_it_takes_the_panels_own_port_when_it_is_free(monkeypatch):
    """The port the firewall opens, and the one that stays in the address bar."""
    free = _free_port()
    monkeypatch.setattr(setup_cli, "_browser_port", lambda: free)
    session = WebSetupSession(context={})

    server = setup_cli._browser_server(session)

    try:
        assert server is not None
        assert server.port == free
    finally:
        server.stop()


def test_something_else_on_that_port_gets_it_another_one(monkeypatch):
    held = socket.socket()
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    taken = held.getsockname()[1]
    monkeypatch.setattr(setup_cli, "_browser_port", lambda: taken)
    monkeypatch.setattr(setup_cli, "SETUP_BROWSER_HOST", "127.0.0.1")
    session = WebSetupSession(context={})

    server = setup_cli._browser_server(session)

    try:
        assert server is not None
        assert server.port != taken
    finally:
        if server is not None:
            server.stop()
        held.close()


def test_a_server_that_cannot_be_built_at_all_leaves_the_terminal_asking(
    monkeypatch,
):
    """Whatever the reason, the answer is the same: ask here instead."""

    def _refuse(**_):
        raise OSError("no sockets today")

    monkeypatch.setattr(setup_cli, "_browser_port", lambda: 8080)
    monkeypatch.setattr(setup_cli, "WebSetupServer", _refuse)

    assert setup_cli._browser_server(WebSetupSession(context={})) is None


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port
