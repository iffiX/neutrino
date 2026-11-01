"""The hint of a module's panels until its next Start, held against ui_text.md.

What these pin: ``ui.modules.stopped_hint`` says in both languages what
ui_text.md writes; the account layer's apply bar shows it in place of the
module's own hint while the module's want is not ``running``, an ``installed``
row never started among them, and its apply then waits for the want it has;
Terminal's and the SSH server's tabs, which the agent's package carries, never
show it; the folder shares and Containers' Run settings show it the same way.
Configure on any module opens its panel after the first import and posts no
Start, and Ayakaleaf's bar waits for ``running`` only under ``running``.
"""

import json
import re
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
COMPONENTS_DIR = FRONTEND_SRC_DIR / "components"
WORDS = {
    "en": "The module is stopped; these settings take effect at the next Start.",
    "zh-CN": "模块已停止，这些设置在下次启动时生效。",
}


def source(name: str) -> str:
    return (COMPONENTS_DIR / name).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("language", list(WORDS))
def test_the_stopped_hint_says_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    assert words["ui.modules.stopped_hint"] == WORDS[language]
    assert "ui.containers.run_stopped_hint" not in words


def test_the_account_layer_s_apply_bar_shows_it_and_waits_for_the_want_it_has():
    panel = flat(source("instances_panel.tsx"))

    assert (
        'hint={ isWaitingForStart ? t("ui.modules.stopped_hint") '
        ": t(descriptor.applyHint) }" in panel
    )
    assert (
        "useSettledApply( reportOf(saved), isWaitingForStart ? want : WANT_RUNNING, )"
        in panel
    )


def test_a_carried_module_never_shows_it_and_the_folder_shares_do():
    page = flat(source("machine_modules.tsx"))
    shares = flat(source("folder_shares_panel.tsx"))

    assert (
        "isWaitingForStart={!target.isCarried && target.want !== WANT_RUNNING}" in page
    )
    assert "isWaitingForStart={target.want !== WANT_RUNNING}" in page
    assert "isCarried: isCarriedRow," in page
    assert re.search(
        r'\{isWaitingForStart && \( <p className="field_hint">'
        r'\{t\("ui\.modules\.stopped_hint"\)\}</p> \)\}',
        shares,
    )


def test_the_run_settings_show_it_on_any_want_but_running():
    settings = flat(source("containers_run_settings.tsx"))

    assert 'want !== WANT_RUNNING ? t("ui.modules.stopped_hint")' in settings


def test_configure_on_any_module_opens_its_panel_and_posts_no_start():
    page = source("machine_modules.tsx")
    configure = page[page.index("const configure = async") :]
    configure = configure[: configure.index("\n  };\n")]

    assert configure.index("/import`") < configure.rindex("setConfigured(")
    assert "/agent/module/start" not in configure
    assert "notePress" not in configure
    assert '"configure"' not in flat(page).split("const PRESSED_STATES")[1][:200]


def test_a_new_ayakaleaf_model_waits_for_running_only_under_running():
    panel = flat(source("ayakaleaf_panels.tsx"))

    assert "const isRestarted = want === WANT_RUNNING;" in panel
    assert (
        "if (isRestarted) { setWait({ at: Date.now(), hasLeftRunning: false }); }"
        in panel
    )
    assert (
        'warning={isRestarted ? t("ui.ayakaleaf.apply_warning") : undefined}' in panel
    )


@pytest.mark.parametrize(
    "language, word",
    [("en", "running, no accounts"), ("zh-CN", "运行中，没有账户")],
)
def test_a_running_module_with_no_account_says_so_in_words(language, word):
    path = FRONTEND_SRC_DIR / "locales" / language / "common.json"
    words = json.loads(path.read_text(encoding="utf-8"))
    page = flat(source("machine_modules.tsx"))

    assert words["state.running_no_accounts"] == word
    assert (
        'if (row.state === "running" && row.is_without_accounts) { '
        'return t("state.running_no_accounts"); }'
    ) in page
