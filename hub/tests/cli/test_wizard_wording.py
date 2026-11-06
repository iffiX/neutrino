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


FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"


def flat(name: str) -> str:
    """One frontend file with its whitespace folded to single spaces."""
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def test_the_welcome_title_is_the_product_s_word():
    page = flat("pages/setup_page.tsx")

    assert '<h1 className="setup_welcome_title">{t("ui.brand.hub")}</h1>' in page
    assert '"Neutrino Hub"' not in page


def test_the_review_names_the_mode_by_its_catalog_word():
    page = flat("pages/setup_page.tsx")

    assert (
        'name={t("ui.setup.review_shape")} value={t(`ui.setup.mode_${mode}`)}' in page
    )
    assert "mode.replace(" not in page


def test_a_step_s_row_is_its_name_and_its_dot():
    """The note is the terminal's English, kept there and in the setup log."""
    page = flat("pages/setup_page.tsx")
    style = flat("pages/setup_page.css")

    assert "step.note" not in page
    assert "setup_step_note" not in page + style


def test_the_review_s_names_take_their_own_width_on_a_phone():
    style = flat("pages/setup_page.css")
    narrow = style.split("@media (max-width: 479px) {", 1)[1].split("} }", 1)[0]

    assert (
        ".setup_review { grid-template-columns: max-content minmax(0, 1fr);" in narrow
    )
