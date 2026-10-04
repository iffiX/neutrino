"""The setup step that makes the machine agree with the overlays it stores.

A box being set up can be carrying an engine from a life before this one, so
the step is run whatever the answer: a configuration enabling no overlay has
to stand the engines down as surely as one enabling NetBird has to start it.
"""

import pytest

from neutrino_hub.cli import setup


class FakeSwitcher:
    """Records what it was told to run instead of running it."""

    calls: list = []

    def start(self, network, *, report=None) -> list:
        FakeSwitcher.calls.append(("start", _enabled(network)))
        return []

    def stop(self, network, *, report=None) -> list:
        FakeSwitcher.calls.append(("stop", _enabled(network)))
        return []


def _enabled(network) -> list:
    return [overlay.provider for overlay in network.enabled_overlays]


class FakeReporter:
    def note(self, text: str) -> None:
        pass


@pytest.fixture
def box(monkeypatch):
    """A setup whose switcher only records."""
    FakeSwitcher.calls = []
    monkeypatch.setattr(setup, "OverlaySwitcher", FakeSwitcher)
    return FakeSwitcher


def store(monkeypatch, overlays) -> None:
    """Make the configuration carry these overlay entries."""
    monkeypatch.setattr(
        setup, "read_config", lambda name: {"mode": "router", "overlays": overlays}
    )


@pytest.mark.feature("netbird")
def test_the_stored_engines_are_started_and_the_others_stood_down(box, monkeypatch):
    store(monkeypatch, [{"provider": "netbird"}])

    note = setup._step_overlay(FakeReporter())

    assert box.calls == [("start", ["netbird"]), ("stop", ["netbird"])]
    assert note == "netbird"


def test_a_box_that_stores_no_overlay_stands_every_engine_down(box, monkeypatch):
    store(monkeypatch, [])

    note = setup._step_overlay(FakeReporter())

    assert box.calls == [("start", []), ("stop", [])]
    assert note == "no overlay"


def test_a_setup_the_overlay_refuses_is_one_the_box_survives():
    assert setup._step_overlay in setup.SETUP_STEPS_THE_BOX_SURVIVES
