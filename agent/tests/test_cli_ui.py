"""``nagent ui``: a token as whoever ran it, and the URL that carries it.

Any account may run it; when no agent answers on the socket it says so
plainly instead of printing a dead URL.
"""

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.ui as ui
import neutrino_agent.enrollment as enrollment
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
        is_page_served=False,
    )
    server.start()
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)
    monkeypatch.setattr(ui.shutil, "which", lambda name: None)
    yield server
    server.stop()


def test_ui_prints_the_tokened_url(running_control, capsys):
    assert ui.main() == 0

    output = capsys.readouterr().out.strip()
    assert output.startswith("http://127.0.0.1:8765/#")
    assert len(output.split("#", 1)[1]) > 20


def test_ui_says_plainly_when_nothing_answers(tmp_path, monkeypatch, capsys):
    platform = FakeUiPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(ui, "detect_platform", lambda: platform)

    assert ui.main() == 1
    assert "not running" in capsys.readouterr().err


def test_ui_is_never_gated_on_root():
    assert "ui" not in entry.ROOT_COMMANDS
