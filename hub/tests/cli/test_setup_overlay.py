"""The setup step that makes the machine agree with the overlay it stores.

A box being set up can be carrying an engine from a life before this one, so
the step is run whatever the answer: a configuration naming no overlay has to
stand one down as surely as one naming NetBird has to start it.
"""

import pytest

from neutrino_hub.cli import setup


class FakeSwitcher:
    """Records what it was told to run instead of running it."""

    converged: list = []

    def converge(self, provider: str, *, report=None) -> str:
        FakeSwitcher.converged.append(provider)
        return "" if provider == "none" else "netbird 0.78.1"


class FakeReporter:
    def note(self, text: str) -> None:
        pass


@pytest.fixture
def box(monkeypatch):
    """A setup whose switcher only records."""
    FakeSwitcher.converged = []
    monkeypatch.setattr(setup, "OverlaySwitcher", FakeSwitcher)
    return FakeSwitcher


def store(monkeypatch, overlays) -> None:
    """Make the configuration carry these overlay entries."""
    monkeypatch.setattr(
        setup, "read_config", lambda name: {"mode": "router", "overlays": overlays}
    )


def test_the_stored_engine_is_the_one_started(box, monkeypatch):
    store(monkeypatch, [{"provider": "netbird"}])

    note = setup._step_overlay(FakeReporter())

    assert box.converged == ["netbird"]
    assert note == "netbird 0.78.1"


def test_a_box_that_stores_no_overlay_stands_every_engine_down(box, monkeypatch):
    store(monkeypatch, [])

    note = setup._step_overlay(FakeReporter())

    assert box.converged == ["none"]
    assert note == "no overlay"


def test_a_setup_the_overlay_refuses_is_one_the_box_survives():
    assert setup._step_overlay in setup.SETUP_STEPS_THE_BOX_SURVIVES
