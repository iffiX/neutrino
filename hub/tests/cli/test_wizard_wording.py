"""What the browser wizard is sent, held against what it can word.

The setup page is handed identifiers — a mode key, a step id — and looks each
one up in its own catalog. An identifier the catalog has no sentence for
reaches the screen as the identifier, so every one the hub can send is named
here.
"""

import json
from pathlib import Path

import pytest

from neutrino_hub.cli.setup import (
    CORE_STEPS,
    SETUP_STEP_LOCAL_AGENT,
    SETUP_STEP_PANEL_PASSWORD,
    SETUP_STEP_WRITE_ANSWERS,
)
from neutrino_hub.modules.router.modes import ROUTER_MODES
from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE

CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/locales"
    / WEB_DEFAULT_LANGUAGE
    / "setup.json"
)

STEP_IDS = tuple(step_id for step_id, _, _ in CORE_STEPS) + (
    SETUP_STEP_WRITE_ANSWERS,
    SETUP_STEP_LOCAL_AGENT,
    SETUP_STEP_PANEL_PASSWORD,
)


def catalog() -> dict:
    """The setup page's English sentences."""
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode", [mode.key for mode in ROUTER_MODES])
def test_every_shape_is_named_and_summarized(mode):
    worded = catalog()
    assert f"ui.setup.mode_{mode}" in worded
    assert f"ui.setup.mode_summary_{mode}" in worded


@pytest.mark.parametrize("mode", [mode.key for mode in ROUTER_MODES if mode.caution])
def test_every_shape_that_costs_something_says_so(mode):
    assert f"ui.setup.mode_caution_{mode}" in catalog()


@pytest.mark.parametrize("step_id", STEP_IDS)
def test_every_step_is_worded(step_id):
    assert f"ui.setup.step_{step_id}" in catalog()
