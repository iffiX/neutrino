"""What every command test shares: the first run's lock, token and mark kept
under the test's own directory."""

import io
import sys

import pytest

from neutrino_hub.cli import setup
from neutrino_hub.platforms.base import HubPlatform
from neutrino_hub.web import setup_app


@pytest.fixture(autouse=True)
def setup_files(monkeypatch, tmp_path):
    """The setup lock, the setup token and the local agent mark, in ``tmp_path``.

    Returns:
        The directory they are in.
    """
    directory = tmp_path / "setup_files"
    monkeypatch.setattr(
        setup,
        "SETUP_LOCK",
        setup_app.SetupLock(path=directory / "setup.lock", platform=HubPlatform()),
    )
    monkeypatch.setattr(setup_app, "WEB_SETUP_TOKEN_PATH", directory / "setup_token")
    monkeypatch.setattr(
        setup, "WEB_SETUP_LOCAL_AGENT_PATH", directory / "setup_local_agent"
    )
    monkeypatch.setattr(
        setup, "WEB_RESTORE_LOCAL_AGENT_PATH", directory / "restore_local_agent"
    )
    return directory


class TerminalStdin(io.StringIO):
    """A stdin that is a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def terminal(monkeypatch):
    """A terminal on stdin, for a command that asks before it acts."""
    monkeypatch.setattr(sys, "stdin", TerminalStdin())
