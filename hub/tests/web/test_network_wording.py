"""What the Network page is sent about a mode, held against what it can word.

The mode panel is handed keys and nothing else: what a mode is called and the
line under it are the panel's own sentences. A key the catalog has no sentence
for reaches the card as the key, so every mode the API offers is named here.
"""

import json
from pathlib import Path

import pytest

from neutrino_hub.modules.router.constants import ROUTER_MODES_KEYS
from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE

CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/locales"
    / WEB_DEFAULT_LANGUAGE
    / "network.json"
)


def catalog() -> dict:
    """The network page's English sentences."""
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode", ROUTER_MODES_KEYS)
def test_every_mode_is_named_and_summarized(mode):
    worded = catalog()
    assert f"ui.network.mode_{mode}" in worded
    assert f"ui.network.mode_summary_{mode}" in worded
