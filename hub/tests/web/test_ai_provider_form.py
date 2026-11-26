"""The AI page's provider form, held against ui_behavior.md and ui_text.md.

What these pin: **Vendor** is the form's first field, with **Custom** after
the presets; **Plan and region** shows for a vendor of more than one
endpoint; **Kind** shows for **Custom** alone; the pickers follow the base
URL, compared without a trailing slash and with the host in any case; a pick
fills the kind ``custom``, the base URL and the model names, and the name
while it is empty or still the shown vendor's; every vendor and endpoint of
ai.md's preset table has its words; and the words say what ui_text.md writes
in both languages.
"""

import json
import re
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
SECTION_PATH = FRONTEND_SRC_DIR / "components/ai_providers_section.tsx"
DESIGN_DIR = HUB_DIR.parent / "skills/core-code-author/design"
UI_TEXT = DESIGN_DIR / "ui_text.md"
AI_MD = DESIGN_DIR / "hub_components/ai.md"
FORM_KEY_PATTERN = re.compile(
    r"^ui\.ai\.(field_vendor|vendor_|field_endpoint|endpoint_)"
)


def flat(text: str) -> str:
    return " ".join(text.split())


def form_source() -> str:
    source = SECTION_PATH.read_text(encoding="utf-8")
    start = source.index("function ProviderForm(")
    return flat(source[start : source.index("interface ProviderRowProps", start)])


def ui_text_words() -> dict:
    """The form's words as ui_text.md writes them, by language and key."""
    words = {"en": {}, "zh-CN": {}}
    for line in UI_TEXT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        keys = re.findall(r"`([a-z_.]+)`", cells[0])
        if not keys or not all(FORM_KEY_PATTERN.match(key) for key in keys):
            continue
        english = cells[1].split(", ") if len(keys) > 1 else [cells[1]]
        chinese = cells[2].split("、") if len(keys) > 1 else [cells[2]]
        for key, en, zh in zip(keys, english, chinese):
            words["en"][key] = en
            words["zh-CN"][key] = zh
    return words


def preset_ids() -> tuple:
    """The vendor ids and the endpoint ids of ai.md's preset table."""
    text = AI_MD.read_text(encoding="utf-8")
    table = text[text.index("## Vendor presets") : text.index('"Prices from" is')]
    vendors, endpoints = set(), set()
    for line in table.splitlines():
        if not line.startswith("| ") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        vendor = re.search(r"`([a-z]+)`", cells[0])
        endpoint = re.fullmatch(r"`([a-z_]+)`", cells[1])
        if vendor is not None:
            vendors.add(vendor.group(1))
        if endpoint is not None:
            endpoints.add(endpoint.group(1))
    return vendors, endpoints


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_words_say_what_ui_text_writes(language):
    catalog = json.loads((LOCALES_DIR / language / "modules.json").read_text("utf-8"))
    words = ui_text_words()[language]

    assert len(words) == 19
    for key, sentence in words.items():
        assert catalog[key] == sentence


def test_every_vendor_and_endpoint_of_the_preset_table_has_its_words():
    vendors, endpoints = preset_ids()
    words = ui_text_words()["en"]

    assert len(vendors) == 10
    assert {f"ui.ai.vendor_{vendor}" for vendor in vendors} | {
        "ui.ai.vendor_custom"
    } == {key for key in words if key.startswith("ui.ai.vendor_")}
    assert {f"ui.ai.endpoint_{endpoint}" for endpoint in endpoints} == {
        key for key in words if key.startswith("ui.ai.endpoint_")
    }


def test_vendor_is_the_first_field_and_custom_comes_after_the_presets():
    source = form_source()
    fields = [
        source.index('label={t("ui.ai.field_vendor")}'),
        source.index('label={t("ui.ai.field_endpoint")}'),
        source.index('t("ui.ai.field_name")'),
        source.index('label={t("ui.ai.field_kind")}'),
        source.index('t("ui.ai.field_base_url")'),
        source.index('t("ui.ai.field_models")'),
        source.index('label={t("ui.ai.field_token")}'),
    ]

    assert fields == sorted(fields)
    assert (
        "...vendors.map((vendor) => ({ id: vendor.id, name: vendorName(vendor.id), })), "
        '{ id: VENDOR_CUSTOM, name: t("ui.ai.vendor_custom") },'
    ) in source


def test_plan_and_region_shows_for_a_vendor_of_several_endpoints():
    assert (
        "{match !== null && match.vendor.endpoints.length > 1 && ( <Picker"
        in form_source()
    )


def test_kind_shows_for_custom_alone():
    source = form_source()

    assert "const isCustom = match === null;" in source
    assert "{isCustom && ( <Picker options={PROVIDER_KINDS.map(" in source


def test_the_pickers_follow_the_base_url():
    source = form_source()
    whole = flat(SECTION_PATH.read_text(encoding="utf-8"))

    assert "const match = matchEndpoint(vendors, baseUrl);" in source
    assert "value={match === null ? VENDOR_CUSTOM : match.vendor.id}" in source
    assert "value={match.endpoint.id}" in source
    assert 'const path = parsed.pathname.replace(/\\/+$/, "");' in whole
    assert "return `${parsed.protocol}//${parsed.host}${path}${parsed.search}`;" in (
        whole
    )
    assert "if (normalizedUrl(endpoint.base_url) === wanted) {" in whole


def test_a_pick_fills_the_kind_the_base_url_the_models_and_the_name():
    source = form_source()

    assert (
        'setKind("custom"); setBaseUrl(endpoint.base_url); '
        'setModelsText(endpoint.models.join("\\n"));'
    ) in source
    assert "if (name.trim().length === 0 || name === shownName) {" in source


def test_a_new_form_starts_on_custom_with_the_kind_anthropic():
    source = form_source()

    assert 'useState(initial?.base_url ?? "")' in source
    assert 'initial?.kind ?? "anthropic",' in source
