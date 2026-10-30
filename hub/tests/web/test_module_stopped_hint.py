"""The hint a stopped module's account and folder share panels show, held against ui_text.md.

What these pin: ``ui.modules.stopped_hint`` says in both languages what
ui_text.md writes; the account layer's apply bar shows it in place of the
module's own hint while the module's want is ``stopped``, and its apply
then waits for ``stopped``; Terminal's and the SSH server's tabs, which the
agent's package carries, never show it; and the folder shares show it under
their hint while the file share is stopped. Configure on a stopped module
opens its panel after the first import and posts no Start.
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


def test_the_account_layer_s_apply_bar_shows_it_and_waits_for_stopped():
    panel = flat(source("instances_panel.tsx"))

    assert (
        'hint={ isStopped ? t("ui.modules.stopped_hint") : t(descriptor.applyHint) }'
        in panel
    )
    assert (
        "useSettledApply( reportOf(saved), isStopped ? WANT_STOPPED : WANT_RUNNING, )"
        in panel
    )
    assert 'const WANT_STOPPED = "stopped";' in panel


def test_a_carried_module_never_reads_stopped_and_the_folder_shares_do():
    page = flat(source("machine_modules.tsx"))
    shares = flat(source("folder_shares_panel.tsx"))

    assert "isStopped={!target.isCarried && target.want === WANT_STOPPED}" in page
    assert "isStopped={target.want === WANT_STOPPED}" in page
    assert "isCarried: isCarriedRow," in page
    assert re.search(
        r'\{isStopped && \( <p className="field_hint">'
        r'\{t\("ui\.modules\.stopped_hint"\)\}</p> \)\}',
        shares,
    )


def test_configure_on_a_stopped_module_posts_no_start():
    page = source("machine_modules.tsx")
    configure = page[page.index("const configure = async") :]
    configure = configure[: configure.index("\n  };\n")]

    imported = configure.index("/import`")
    guarded = configure.index("if (activeRow.want !== WANT_STOPPED) {")
    started = configure.index('"/agent/module/start"')
    opened = configure.index("setConfigured(", started)
    assert imported < guarded < started < opened
    assert configure.count('"/agent/module/start"') == 1
