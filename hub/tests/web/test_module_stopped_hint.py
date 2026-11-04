"""The hint of a module's panels until its next Start, held against ui_text.md.

What these pin: ``ui.modules.stopped_hint`` says in both languages what
ui_text.md writes; the account layer's apply bar shows it in place of the
module's own hint while the module's want is not ``running``, an ``installed``
row never started among them, and its apply then waits for the want it has;
Terminal's and the SSH server's tabs, which the agent's package carries, and
the command line programs' tabs, which have no Start, never show it, and a
program's apply waits for the want it has; the folder shares and Containers'
Run settings show it the same way.
Every apply bar the machine page reaches is listed here by its panel, and each
shows it in place of its own hint, Remote desktop's alone keeping its own. A
row with no want that reads ``running`` reaches its panels as wanted ``running``,
since its apply writes that want, and no other row does.
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
STOPPED_HINT = 't("ui.modules.stopped_hint")'
# The apply bars of the panels with a Start, by file, each bar by the hint it
# shows under ``running``.
PANEL_BARS = {
    "instances_panel.tsx": ["t(descriptor.applyHint)"],
    "gitea_panels.tsx": ['t("ui.gitea.access_apply_hint")'],
    "containers_run_settings.tsx": ['t("ui.containers.run_apply_hint")'],
    "containers_panels.tsx": [
        't("ui.containers.mirrors_apply_hint")',
        't("ui.containers.containers_apply_hint")',
    ],
    "ayakaleaf_panels.tsx": ['t("ui.ayakaleaf.model_hint")'],
}
# The apply bars of a module the agent carries, by file, each by its one hint.
CARRIED_BARS = {
    "remote_desktop_panels.tsx": ['t("ui.remote_desktop_module.apply_hint")'],
}


def source(name: str) -> str:
    return (COMPONENTS_DIR / name).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def apply_bar_hints(name: str) -> list:
    """The expression each apply bar of one component gives its ``hint``."""
    bars = flat(source(name)).split("<ApplyBar ")[1:]
    return [
        re.search(r"\bhint=\{\s*(.*?)\s*\} (?:warning|blockedHint)=", bar).group(1)
        for bar in bars
    ]


def components_with_a_bar_the_page_reaches() -> set:
    """The components the machine page imports, at any depth, with an apply bar."""
    found = set()
    seen = set()
    waiting = ["machine_modules.tsx"]
    while waiting:
        name = waiting.pop()
        if name in seen or not (COMPONENTS_DIR / name).exists():
            continue
        seen.add(name)
        text = source(name)
        if "<ApplyBar " in flat(text):
            found.add(name)
        waiting += [
            f"{imported}.tsx" for imported in re.findall(r'from "\./(\w+)"', text)
        ]
    return found


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
        "useSettledApply( reportOf(saved, descriptor), "
        "isWaitingForStart || descriptor.isProgram === true ? want : WANT_RUNNING, )"
        in panel
    )


def test_a_carried_module_or_a_program_never_shows_it_and_the_folder_shares_do():
    page = flat(source("machine_modules.tsx"))
    shares = flat(source("folder_shares_panel.tsx"))

    assert (
        "isWaitingForStart={ !target.isCarried && !target.isProgram && "
        "target.want !== WANT_RUNNING }" in page
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


def test_a_running_row_with_no_want_reaches_its_panels_as_wanted_running():
    page = flat(source("machine_modules.tsx"))

    assert (
        "function wantAtApply(row: DeviceModuleView): string { "
        'return row.want === "" && row.state === WANT_RUNNING '
        "? WANT_RUNNING : row.want; }"
    ) in page
    assert "want: wantAtApply(activeRow)," in page
    assert "want: activeRow.want," not in page


def test_every_apply_bar_the_machine_page_reaches_is_listed():
    assert components_with_a_bar_the_page_reaches() == set(PANEL_BARS) | set(
        CARRIED_BARS
    )


@pytest.mark.parametrize("name", list(PANEL_BARS))
def test_every_apply_bar_of_a_module_s_panel_shows_it(name):
    hints = apply_bar_hints(name)

    assert len(hints) == len(PANEL_BARS[name])
    for hint, own in zip(hints, PANEL_BARS[name]):
        assert STOPPED_HINT in hint and own in hint, hint


@pytest.mark.parametrize("name", list(CARRIED_BARS))
def test_a_carried_module_s_panel_keeps_its_own_hint(name):
    assert apply_bar_hints(name) == CARRIED_BARS[name]


def test_gitea_s_panel_is_told_its_want():
    page = flat(source("machine_modules.tsx"))
    gitea = page[page.index("<GiteaPanels ") :]

    assert (
        "isWaitingForStart={target.want !== WANT_RUNNING}" in gitea[: gitea.index("/>")]
    )


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
