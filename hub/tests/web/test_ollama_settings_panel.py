"""The Ollama tab's Settings: the context length field, held against ui_text.md and the hub's bounds.

What these pin: the label and the refusal say what ui_text.md writes in both
languages, the refusal filling ``{min}`` and ``{max}``; the field is a number
field bounded by the hub's least and most length; its text becomes the
request's ``context_length`` only while it is a whole number within them,
and otherwise the field shows the refusal under it and the apply bar is
disabled; the form starts from the view's stored length.
"""

import json
import re
from pathlib import Path

import pytest

from neutrino_hub.modules.devices.constants import (
    DEVICE_OLLAMA_CONTEXT_LENGTH_MAX,
    DEVICE_OLLAMA_CONTEXT_LENGTH_MIN,
)

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
SETTINGS_PATH = FRONTEND_SRC_DIR / "components/ollama_settings.tsx"
WORDS = {
    "en": {
        "modules.json": {"ui.ollama.context_length": "Context length (tokens)"},
        "codes.json": {
            "code.ollama_context_length_invalid": (
                "The context length must be between {min} and {max} tokens."
            )
        },
    },
    "zh-CN": {
        "modules.json": {"ui.ollama.context_length": "上下文长度（token）"},
        "codes.json": {
            "code.ollama_context_length_invalid": (
                "非法上下文长度：要在 {min} 到 {max} 个 token 之间。"
            )
        },
    },
}


def settings_source() -> str:
    return " ".join(SETTINGS_PATH.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_field_says_what_ui_text_writes(language):
    for name, words in WORDS[language].items():
        worded = json.loads((LOCALES_DIR / language / name).read_text("utf-8"))
        for key, sentence in words.items():
            assert worded[key] == sentence


def test_the_field_is_bounded_by_the_hub_s_least_and_most_length():
    source = settings_source()
    assert f"const CONTEXT_LENGTH_MIN = {DEVICE_OLLAMA_CONTEXT_LENGTH_MIN};" in source
    assert f"const CONTEXT_LENGTH_MAX = {DEVICE_OLLAMA_CONTEXT_LENGTH_MAX};" in source
    field = source[source.index('t("ui.ollama.context_length")') :]
    field = field[: field.index("</label>")]
    assert 'type="number"' in field
    assert "min={CONTEXT_LENGTH_MIN}" in field
    assert "max={CONTEXT_LENGTH_MAX}" in field
    assert "value={draft.context_length}" in field


def test_a_length_outside_the_bounds_shows_the_refusal_and_disables_the_bar():
    source = settings_source()
    parse = source[source.index("function contextLengthOf(") :]
    parse = parse[: parse.index("/** The GPUs as the settings store them")]
    assert re.search(r"/\^\\d\+\$/\.test\(text\.trim\(\)\)", parse)
    assert (
        "value >= CONTEXT_LENGTH_MIN && value <= CONTEXT_LENGTH_MAX ? value : null"
        in parse
    )
    assert (
        't("code.ollama_context_length_invalid", { min: CONTEXT_LENGTH_MIN, '
        "max: CONTEXT_LENGTH_MAX, })" in source
    )
    assert '<span className="field_error">{contextLengthError}</span>' in source
    assert "isApplyDisabled={isUnsupported || contextLengthError !== null}" in source
    assert "context_length: contextLength," in source


def test_the_form_starts_from_the_stored_length():
    source = settings_source()
    start = source[source.index("function draftOf(") :]
    assert "context_length: String(view.context_length)," in start
