"""``nclient quit``: the ask that stops the running client.

The resident does the stopping itself; this command only carries the ask
over the control socket and words what came back. Nothing running is an
honest line, not a failure of this machine.
"""

import pytest

from neutrino_client.cli import quit as quit_cli
from neutrino_client.cli import wording
from neutrino_client.control import routes
from neutrino_client.control.server import ControlServer
from neutrino_client.exceptions import ControlSocketUnavailableError
from tests.conftest import FakeClientPlatform, FakeSession, discard


@pytest.fixture
def platform(monkeypatch):
    platform = FakeClientPlatform()
    monkeypatch.setattr(quit_cli, "detect_platform", lambda: platform)
    return platform


@pytest.fixture
def resident(platform, monkeypatch):
    """A live resident on this person's socket, its process end recorded."""
    monkeypatch.setattr(routes, "QUIT_ANSWER_GRACE_S", 0)
    monkeypatch.setattr(routes, "end_process", lambda: None)
    session = FakeSession()
    server = ControlServer(
        session=session,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    yield session
    server.stop()


def test_the_running_client_is_asked_to_quit(resident, capsys):
    assert quit_cli.main() == 0

    assert resident.is_shut_down.wait(timeout=5)
    assert capsys.readouterr().out.strip() == wording.QUIT_ASKED


def test_nothing_running_is_said_plainly(platform, capsys):
    assert quit_cli.main() == 1

    assert capsys.readouterr().err.strip() == wording.NOT_RUNNING


def test_a_refusal_is_worded_from_its_code(resident, platform, capsys):
    platform.peer = {"account": "bob", "uid": 1001, "is_same_user": False}

    assert quit_cli.main() == 1

    assert wording.word_code("control_peer_refused") in capsys.readouterr().err
    assert resident.shutdowns == 0


def test_a_platform_without_a_socket_is_refused(monkeypatch, capsys):
    class NoSocketPlatform(FakeClientPlatform):
        def control_socket_path(self):
            raise ControlSocketUnavailableError("none")

    monkeypatch.setattr(quit_cli, "detect_platform", NoSocketPlatform)

    assert quit_cli.main() == 1
    assert wording.word_code("control_socket_unavailable") in capsys.readouterr().err
