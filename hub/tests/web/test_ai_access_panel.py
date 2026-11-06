"""The Access panel of the AI page, held against ui_behavior.md and ui_text.md.

What these pin: the words of the default model's picker and of the panel's
apply bar say in both languages what ui_text.md writes; the picker lists the
served names by name, with a saved pick the gateway no longer serves as its
first row marked as such, and is disabled while the gateway serves none; the
picker shows the saved pick, or the first name served while none is saved;
the bar and the frame light only while the picked row differs from that row;
the bar has no hint, and its warning only while the view says an installed
Ayakaleaf follows the default model; the bar writes the pick alone with
``gateway/set``; and a key's generate and revoke write where they are pressed
and touch no draft.
"""

import json
from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
PANEL = "components/ai_access_panel.tsx"
WORDS = {
    "ui.ai.default_model": ("Default model", "默认模型"),
    "ui.ai.default_model_not_served": ("no longer served", "已不再提供"),
    "ui.ai.access_apply": ("Apply access settings", "应用接入配置"),
    "ui.ai.access_apply_warning": (
        "An Ayakaleaf on the gateway default restarts.",
        "用网关默认的 Ayakaleaf 会重启。",
    ),
}


def flat(name: str) -> str:
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def catalog(language: str) -> dict:
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_words_are_ui_text_s_in_both_languages():
    english = catalog("en")
    chinese = catalog("zh-CN")
    codes = {
        language: json.loads(
            (FRONTEND_SRC_DIR / "locales" / language / "codes.json").read_text(
                encoding="utf-8"
            )
        )
        for language in ("en", "zh-CN")
    }

    for key, (en, zh) in WORDS.items():
        assert english[key] == en
        assert chinese[key] == zh
    assert "ui.ai.access_apply_hint" not in english
    assert "ui.ai.access_apply_hint" not in chinese
    assert codes["en"]["code.model_not_served"] == "The gateway does not serve {model}."
    assert codes["zh-CN"]["code.model_not_served"] == "网关不提供 {model}。"


def test_the_picker_lists_the_served_names_and_a_saved_pick_no_longer_served_first():
    panel = flat(PANEL)

    assert (
        'const isSavedServed = defaultModel === "" || servedModels.includes(defaultModel);'
        in panel
    )
    assert (
        "...(isSavedServed ? [] : [ { id: defaultModel, name: defaultModel, "
        'detail: t("ui.ai.default_model_not_served"), }, ]), '
        "...servedModels.map((model) => ({ id: model, name: model })),"
    ) in panel
    assert 'label={t("ui.ai.default_model")}' in panel
    assert "isDisabled={servedModels.length === 0 || isModelBusy}" in panel


def test_the_bar_lights_only_while_the_picked_row_differs_from_the_saved_one():
    panel = flat(PANEL)

    assert 'const savedRow = defaultModel || (servedModels[0] ?? "");' in panel
    assert "const shownRow = pickedModel ?? savedRow;" in panel
    assert (
        "const isModelDirty = pickedModel !== null && pickedModel !== savedRow;"
        in panel
    )
    assert 'isModelDirty ? "settings_group--dirty" : ""' in panel
    assert "<ApplyBar isDirty={isModelDirty}" in panel
    assert 'label={t("ui.ai.access_apply")}' in panel
    bar = panel[panel.index("<ApplyBar ") :]
    bar = bar[: bar.index("/>")]
    assert "hint=" not in bar
    assert (
        'warning={ hasAyakaleafOnDefault ? t("ui.ai.access_apply_warning") : undefined }'
        in bar
    )


def test_the_bar_s_hint_may_be_left_out():
    bar = flat("components/apply_bar.tsx")

    assert "hint?: string;" in bar
    assert '{blockedHint ?? (isLit || isBusy ? hint : t("ui.apply_bar.clean"))}' in bar


def test_the_bar_writes_the_pick_alone_and_the_keys_touch_no_draft():
    panel = flat(PANEL)
    apply = panel[panel.index("const handleApplyModel = async") :]
    apply = apply[: apply.index("} finally {")]
    generate = panel[panel.index("const handleGenerate = async") :]
    generate = generate[: generate.index("const handleRevoke")]
    revoke = panel[panel.index("const handleRevoke = async") :]
    revoke = revoke[: revoke.index("const handleApplyModel")]

    assert (
        "apiPost<CliproxyApiStatusView>(GATEWAY_SET_PATH, { default_model: pickedModel, })"
        in apply
    )
    assert apply.index("onChanged(") < apply.index("setPickedModel(null);")
    assert "setPickedModel" not in generate and "setPickedModel" not in revoke
    assert 'const GATEWAY_SET_PATH = "/hub/ai/gateway/set";' in panel


def test_the_page_hands_the_panel_the_served_names_and_the_saved_pick():
    page = flat("pages/ai_page.tsx")

    assert "servedModels={servedModels}" in page
    assert 'defaultModel={view.default_model ?? ""}' in page
    assert "hasAyakaleafOnDefault={view.has_ayakaleaf_on_default ?? false}" in page
