"""The word a module's tab shows after a press, held against the standard.

What these pin: after **Install**, **Uninstall**, **Start** and **Stop** the
tab reads the press's own word until the machine reports another state, as
ui_behavior.md names it; a tab reading starting or stopping is in transit,
with its buttons off and its spinner on, as one reading queued is; and the
two new words say in both languages what ui_text.md writes.
"""

import json
import re
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
DESIGN_DIR = HUB_DIR.parent / "skills/core-code-author/design"
# Each press and the word its tab shows, as ui_behavior.md names them.
PRESS_WORDS = {
    "install": "installing",
    "uninstall": "uninstalling",
    "start": "starting",
    "stop": "stopping",
}
# The two words of Start and Stop, as ui_text.md writes them.
WORDS = {
    "en": {"state.starting": "starting", "state.stopping": "stopping"},
    "zh-CN": {"state.starting": "启动中", "state.stopping": "停止中"},
}


def page() -> str:
    path = FRONTEND_SRC_DIR / "components/machine_modules.tsx"
    return " ".join(path.read_text(encoding="utf-8").split())


def design(name: str) -> str:
    return " ".join((DESIGN_DIR / name).read_text(encoding="utf-8").split())


def panel_list(name: str) -> list:
    """One of the page's lists of state words."""
    body = page()
    start = body.index(f"const {name} = [")
    return re.findall(r'"(\w+)"', body[start : body.index("];", start)])


def pressed_states() -> dict:
    body = page()
    start = body.index("const PRESSED_STATES: Record<ModuleAction, string> = {")
    return dict(re.findall(r'(\w+): "(\w+)"', body[start : body.index("};", start)]))


def test_each_press_shows_its_own_word():
    assert pressed_states() == PRESS_WORDS


def test_ui_behavior_names_each_press_s_word():
    text = design("ui_behavior.md")

    assert (
        "The step reads the press's own word: `state.installing` after "
        "**Install**, `state.uninstalling` after **Uninstall**, `state.starting` "
        "after **Start** and `state.stopping` after **Stop**."
    ) in text


def test_a_tab_starting_or_stopping_is_in_transit():
    busy = panel_list("BUSY_STATES")

    assert {"queued", "starting", "stopping"} <= set(busy)
    assert "queued" not in pressed_states().values()


def test_each_pressed_word_has_its_key():
    body = page()
    start = body.index("const STATE_KEYS: Record<string, string> = {")
    table = dict(
        re.findall(r'(\w+): "(state\.\w+)"', body[start : body.index("};", start)])
    )

    for word in PRESS_WORDS.values():
        assert table[word] == f"state.{word}"


@pytest.mark.parametrize("language", list(WORDS))
def test_the_words_say_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    words = json.loads(path.read_text(encoding="utf-8"))
    text = design("ui_text.md")

    for key, word in WORDS[language].items():
        assert words[key] == word
    for key in WORDS["en"]:
        assert f"| `{key}`," in text
        assert f"| {WORDS['en'][key]} | {WORDS['zh-CN'][key]} |" in text
