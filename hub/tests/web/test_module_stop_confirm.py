"""The question before Stop on the File share, held against ui_text.md.

What these pin: the two words in both languages, the same as ui_text.md writes;
the tab's Stop goes through one ask, which acts at once on every module but the
File share; the File share's dialog names the module and the machine, with
**Stop** on its button and the usual **Cancel**, and it posts Stop's route only
from its button.
"""

import json
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"
WORDS = {
    "en": {
        "ui.samba.stop_title": "Stop {module} on {device}",
        "ui.samba.stop_body": "The machine's SMB server stops, with every share on it.",
        "ui.modules.stop": "Stop",
    },
    "zh-CN": {
        "ui.samba.stop_title": "停止 {device} 上的 {module}",
        "ui.samba.stop_body": "这台机器的 SMB 服务会停止，上面所有共享都会停。",
        "ui.modules.stop": "停止",
    },
}


def page() -> str:
    path = FRONTEND_SRC_DIR / "components/machine_modules.tsx"
    return " ".join(path.read_text(encoding="utf-8").split())


def ask_stop() -> str:
    body = page()
    start = body.index("const askStop = () => {")
    return body[start : body.index("const askUninstall = () => {")]


@pytest.mark.parametrize("language", list(WORDS))
def test_the_words_say_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    for key, word in WORDS[language].items():
        assert words[key] == word


def test_ui_text_writes_both_languages_in_one_row():
    text = UI_TEXT.read_text(encoding="utf-8")

    for key in ("ui.samba.stop_title", "ui.samba.stop_body"):
        assert f"| `{key}` | {WORDS['en'][key]} | {WORDS['zh-CN'][key]} |" in text, key


def test_the_tab_s_stop_goes_through_the_ask():
    assert (
        '<ActionButton action="stop" isEnabled={ canAct && '
        '(activeRow.state === "running" ||'
    ) in page()
    assert 'isBusy={busyAction === "stop"} onClick={askStop} />' in page()
    assert 'onClick={() => void act("stop")}' not in page()


def test_only_the_file_share_asks():
    assert 'const FILE_SHARE_MODULE = "samba";' in page()
    assert (
        'if (activeRow.name !== FILE_SHARE_MODULE) { void act("stop"); return; }'
    ) in ask_stop()


def test_the_dialog_names_what_stops_and_says_what_its_button_does():
    ask = ask_stop()

    assert (
        'title: t("ui.samba.stop_title", { '
        "module: moduleTitle(activeRow.name, activeRow.title), "
        "device: deviceName, }),"
    ) in ask
    assert 'body: t("ui.samba.stop_body"),' in ask
    assert 'confirmLabel: t("ui.modules.stop"),' in ask
    assert 'onConfirm: () => void act("stop"),' in ask
    assert "cancelLabel" not in ask
    assert "isDanger" not in ask
