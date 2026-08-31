"""Getting the browser wizard a port, and never being stuck without one.

The wizard is an offer, not a requirement: whatever goes wrong reaching for
it, the terminal's own screens still ask the same questions. A first run that
cannot be answered at all is the one failure this must not produce.
"""

import socket

from neutrino_hub.cli import setup as setup_cli
from neutrino_hub.web.setup_app import WebSetupSession


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

    monkeypatch.setattr(setup_cli, "WebSetupServer", _refuse)

    assert setup_cli._browser_server(WebSetupSession(context={})) is None


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port
