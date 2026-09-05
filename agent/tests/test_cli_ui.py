"""``nagent ui``: a token as whoever ran it, and the session that waits.

The command mints over the socket, opens the browser through the standard
library, prints the one line, and stays: Ctrl-C revokes the token at once,
a dead pulse ends the wait, and an agent serving no page refuses to mint.
"""

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.ui as ui
import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.control import client
from neutrino_agent.control.server import ControlServer
from tests.test_control_server import ALICE, FakeControlAgent, FakeControlPlatform


class FakeUiPlatform(FakeControlPlatform):
    def __init__(self, socket_path: str):
        super().__init__()
        self._socket_path = socket_path

    def control_socket_path(self) -> str:
        return self._socket_path


@pytest.fixture
def running_control(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(tmp_path / "agent.json"))
    platform = FakeUiPlatform(str(tmp_path / "agent.sock"))
    platform.peer = dict(ALICE)
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=platform.control_socket_path(),
        page_port=0,
    )
    server.start()
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)
    opened = []
    monkeypatch.setattr(ui.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ui.time, "sleep", lambda seconds: None)
    yield server, opened
    server.stop()


def test_ui_opens_the_browser_and_prints_the_one_line(
    running_control, monkeypatch, capsys
):
    server, opened = running_control
    monkeypatch.setattr(ui, "_wait", lambda socket_path, token: 0)

    assert ui.main() == 0

    assert len(opened) == 1
    url = opened[0]
    assert url.startswith(f"http://127.0.0.1:{server.page_port}/#")
    assert len(url.split("#", 1)[1]) > 20
    out = capsys.readouterr().out
    assert (
        f"Please open {url} if the browser does not show up. "
        "Close the window or press Ctrl-C to stop." in out
    )


def test_ui_exits_when_the_windows_pulse_stops(running_control, monkeypatch, capsys):
    server, _opened = running_control
    revoked = []

    def claim_revoke_then_wait(socket_path, token):
        # A page claims the token, then it dies out from under the wait —
        # the closed-window story, told through revocation for speed.
        server._tokens.identity_of(token)
        client.request(
            socket_path=socket_path,
            method="POST",
            path="/api/token/revoke",
            body={"token": token},
        )
        revoked.append(token)
        return _wait(socket_path, token)

    _wait = ui._wait
    monkeypatch.setattr(ui, "_wait", claim_revoke_then_wait)

    assert ui.main() == 0

    assert revoked
    assert ui.UI_REVOKED in capsys.readouterr().out


def test_an_unclaimed_token_keeps_the_session_waiting(running_control, monkeypatch):
    server, _opened = running_control
    polls = []

    def wait_a_while(socket_path, token):
        # Nobody has opened the page yet: the wait must not end by itself.
        for _ in range(3):
            status, reply = client.request(
                socket_path=socket_path,
                method="POST",
                path="/api/token/watch",
                body={"token": token},
            )
            polls.append(reply)
        raise KeyboardInterrupt

    monkeypatch.setattr(ui, "_wait", wait_a_while)

    assert ui.main() == 0

    assert all(reply["is_alive"] for reply in polls)
    assert all(not reply["is_claimed"] for reply in polls)


def test_ctrl_c_revokes_the_token_at_once(running_control, monkeypatch, capsys):
    server, opened = running_control

    def interrupted(socket_path, token):
        raise KeyboardInterrupt

    monkeypatch.setattr(ui, "_wait", interrupted)

    assert ui.main() == 0

    token = opened[0].split("#", 1)[1]
    _status, reply = client.request(
        socket_path=server.socket_path,
        method="POST",
        path="/api/token/watch",
        body={"token": token},
    )
    assert reply == {"is_claimed": False, "is_alive": False}


def test_ui_refuses_plainly_when_no_page_is_served(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(tmp_path / "agent.json"))
    platform = FakeUiPlatform(str(tmp_path / "agent.sock"))
    platform.peer = dict(ALICE)
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=lambda message: None,
        socket_path=platform.control_socket_path(),
        is_page_served=False,
    )
    server.start()
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)
    try:
        assert ui.main() == 1
        assert "not serving its page" in capsys.readouterr().err
    finally:
        server.stop()


def test_ui_says_plainly_when_nothing_answers(tmp_path, monkeypatch, capsys):
    platform = FakeUiPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)

    assert ui.main() == 1
    assert "not running" in capsys.readouterr().err


def test_ui_is_never_gated_on_root():
    assert "ui" not in entry.ROOT_COMMANDS
