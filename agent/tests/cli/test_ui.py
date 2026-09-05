"""``nagent ui``: a token as whoever ran it, and the session that waits.

The command mints over the socket, opens the browser through the standard
library, prints the one line, and stays: an unclaimed token waits however
long the person takes, Ctrl-C revokes at once, a claimed pulse that stops is
a closed window, and an agent serving no page refuses to mint. Time moves
only where a test moves it: the token store's clock is injected and the
wait's sleep never reaches the real one.
"""

import http.client
import json
import socket

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.ui as ui
from neutrino_agent.constants import AGENT_CONTROL_TOKEN_IDLE_TTL_S
from neutrino_agent.control import client
from neutrino_agent.control.identity import ControlTokenStore
from neutrino_agent.control.server import ControlServer
from tests.conftest import ALICE, Clock, FakeControlAgent, FakeControlPlatform, discard


def over_page(server, token):
    """One page request carrying the token, the way the browser makes it.

    Args:
        server: The running control server.
        token: The token the page holds.

    Returns:
        The status code and the decoded reply.
    """
    connection = http.client.HTTPConnection("127.0.0.1", server.page_port, timeout=5)
    connection.request(
        "GET", "/api/state", headers={"Authorization": f"Bearer {token}"}
    )
    reply = connection.getresponse()
    status = reply.status
    payload = json.loads(reply.read().decode("utf-8"))
    connection.close()
    return status, payload


def token_of(opened) -> str:
    """The token in the URL the browser was handed."""
    return opened[0].split("#", 1)[1]


def build_control(socket_path: str, *, page_port=0, is_page_served=True, clock=None):
    """A started control server answering as ``alice``.

    Args:
        socket_path: The socket to serve on.
        page_port: The loopback port to ask for; 0 binds a free one.
        is_page_served: Serve the loopback page as well.
        clock: The token store's clock; None uses the real one.

    Returns:
        The started server and its platform.
    """
    platform = FakeUiPlatform(socket_path)
    platform.peer = dict(ALICE)
    tokens = ControlTokenStore(clock=clock) if clock is not None else None
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=discard,
        socket_path=socket_path,
        page_port=page_port,
        is_page_served=is_page_served,
        tokens=tokens,
    )
    server.start()
    return server, platform


def one_line_for(url: str) -> str:
    """The one line the command prints, exactly."""
    return (
        f"Please open {url} if the browser does not show up. "
        "Close the window or press Ctrl-C to stop.\n"
    )


def sleep_nothing(seconds) -> None:
    """The wait's sleep, never reaching the real clock."""


def open_no_browser(url) -> bool:
    """No browser to hand the URL to."""
    return False


def wait_no_longer(socket_path, token) -> int:
    """Skip the session, for the tests that only watch the minting."""
    return 0


def interrupt_the_wait(socket_path, token) -> int:
    """Ctrl-C, the moment the wait starts."""
    raise KeyboardInterrupt


class FakeUiPlatform(FakeControlPlatform):
    def __init__(self, socket_path: str):
        super().__init__()
        self._socket_path = socket_path

    def control_socket_path(self) -> str:
        return self._socket_path


@pytest.fixture(scope="module")
def control_stack(tmp_path_factory):
    """One agent for the whole module; every test mints its own token."""
    clock = Clock()
    socket_path = str(tmp_path_factory.mktemp("ui") / "agent.sock")
    server, platform = build_control(socket_path, clock=clock)
    assert server.socket_path and server.page_port
    yield server, platform, clock
    server.stop()


@pytest.fixture
def running_control(control_stack, monkeypatch):
    """The agent, its page, and a clock only the test moves."""
    server, platform, clock = control_stack
    platform.peer = dict(ALICE)
    opened = []

    def open_browser(url):
        opened.append(url)
        return True

    monkeypatch.setattr(ui, "detect_platform", lambda: platform)
    monkeypatch.setattr(ui.webbrowser, "open", open_browser)
    monkeypatch.setattr(ui.time, "sleep", sleep_nothing)
    return server, opened, clock


@pytest.fixture
def squatted_port():
    """A loopback port another local process already holds."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    yield holder.getsockname()[1]
    holder.close()


def test_ui_opens_the_browser_and_prints_the_one_line(
    running_control, monkeypatch, capsys
):
    server, opened, _clock = running_control
    monkeypatch.setattr(ui, "_wait", wait_no_longer)

    assert ui.main() == 0

    assert len(opened) == 1
    url = opened[0]
    assert url.startswith(f"http://127.0.0.1:{server.page_port}/#")
    assert len(token_of(opened)) > 20
    assert capsys.readouterr().out == one_line_for(url)


def test_the_line_is_printed_even_with_no_browser_to_open(
    running_control, monkeypatch, capsys
):
    _server, opened, _clock = running_control

    def find_no_browser(url):
        opened.append(url)
        return False

    monkeypatch.setattr(ui.webbrowser, "open", find_no_browser)
    monkeypatch.setattr(ui, "_wait", wait_no_longer)

    assert ui.main() == 0

    assert capsys.readouterr().out == one_line_for(opened[0])


def test_the_token_carries_the_scope_of_whoever_ran_it(running_control, monkeypatch):
    server, opened, _clock = running_control
    monkeypatch.setattr(ui, "_wait", wait_no_longer)

    assert ui.main() == 0

    status, state = over_page(server, token_of(opened))
    assert status == 200
    assert state["caller"] == {
        "account": "alice",
        "is_privileged": False,
        "home": "/home/alice",
    }
    assert state["accounts"] == ["alice"]


def test_an_unclaimed_token_waits_past_the_idle_ttl(
    running_control, monkeypatch, capsys
):
    _server, opened, clock = running_control
    polls = []

    def sleep_and_age(seconds):
        clock.now += seconds
        polls.append(clock.now)
        if len(polls) > 12:
            raise KeyboardInterrupt

    monkeypatch.setattr(ui.time, "sleep", sleep_and_age)

    assert ui.main() == 0

    assert len(polls) == 13
    assert clock.now > AGENT_CONTROL_TOKEN_IDLE_TTL_S
    out = capsys.readouterr().out
    assert out == one_line_for(opened[0])


def test_ctrl_c_revokes_the_token_and_the_page_is_locked_out(
    running_control, monkeypatch
):
    server, opened, _clock = running_control
    monkeypatch.setattr(ui, "_wait", interrupt_the_wait)

    assert ui.main() == 0

    status, payload = over_page(server, token_of(opened))
    assert status == 401
    assert payload == {"code": "control_token_invalid"}


def test_a_claimed_token_whose_pulse_stops_words_a_closed_window(
    running_control, monkeypatch, capsys
):
    server, _opened, clock = running_control
    real_wait = ui._wait

    def claim_the_page_then_wait(socket_path, token):
        assert over_page(server, token)[0] == 200
        clock.now += AGENT_CONTROL_TOKEN_IDLE_TTL_S + 1
        return real_wait(socket_path, token)

    monkeypatch.setattr(ui, "_wait", claim_the_page_then_wait)

    assert ui.main() == 0

    assert ui.UI_WINDOW_CLOSED in capsys.readouterr().out


def test_a_token_that_dies_unclaimed_words_the_agent_ending_it(
    running_control, monkeypatch, capsys
):
    _server, _opened, _clock = running_control
    real_wait = ui._wait

    def revoke_then_wait(socket_path, token):
        client.request(
            socket_path=socket_path,
            method="POST",
            path="/api/token/revoke",
            body={"token": token},
        )
        return real_wait(socket_path, token)

    monkeypatch.setattr(ui, "_wait", revoke_then_wait)

    assert ui.main() == 0

    out = capsys.readouterr().out
    assert ui.UI_REVOKED in out
    assert ui.UI_WINDOW_CLOSED not in out


def test_an_agent_that_stops_answering_ends_the_session(tmp_path, monkeypatch, capsys):
    server, platform = build_control(str(tmp_path / "agent.sock"))
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)
    monkeypatch.setattr(ui.webbrowser, "open", open_no_browser)
    monkeypatch.setattr(ui.time, "sleep", sleep_nothing)
    real_wait = ui._wait

    def stop_the_agent_then_wait(socket_path, token):
        server.stop()
        return real_wait(socket_path, token)

    monkeypatch.setattr(ui, "_wait", stop_the_agent_then_wait)
    try:
        assert ui.main() == 0

        assert ui.UI_AGENT_GONE in capsys.readouterr().out
    finally:
        server.stop()


def test_ui_refuses_plainly_when_no_page_is_served(tmp_path, monkeypatch, capsys):
    server, platform = build_control(str(tmp_path / "agent.sock"), is_page_served=False)
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)
    try:
        assert ui.main() == 1
        assert capsys.readouterr().err == ui.UI_NO_PAGE + "\n"
    finally:
        server.stop()


def test_a_squatted_loopback_port_mints_nothing(
    tmp_path, monkeypatch, capsys, squatted_port
):
    server, platform = build_control(
        str(tmp_path / "agent.sock"), page_port=squatted_port
    )
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)
    try:
        assert server.page_port == 0
        assert ui.main() == 1
        assert capsys.readouterr().err == ui.UI_NO_PAGE + "\n"
    finally:
        server.stop()


def test_ui_says_plainly_when_nothing_answers(tmp_path, monkeypatch, capsys):
    platform = FakeUiPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)

    assert ui.main() == 1

    assert capsys.readouterr().err == ui.UI_NOT_RUNNING + "\n"


def test_ui_is_never_gated_on_root():
    assert "ui" not in entry.ROOT_COMMANDS
