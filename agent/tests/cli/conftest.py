"""What every command test shares: a terminal on stdin when one is asked for."""

import io
import sys

import pytest


class TerminalStdin(io.StringIO):
    """A stdin that is a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def terminal(monkeypatch):
    """A terminal on stdin, for a command that asks before it acts."""
    monkeypatch.setattr(sys, "stdin", TerminalStdin())
