"""What the Containers tab says of hub containers and owners, held against ui_text.md.

The tab words where each container comes from with one of three chips, and
the Hub containers block with its title, its hint and its empty line; the
codes Containers adds for hub containers and for container modules have a
sentence in both languages; and the old badges are gone, so nothing names
a person's container anything but manual.
"""

import json
from pathlib import Path

import pytest

from neutrino_hub.modules.devices.constants import (
    DEVICE_CONTAINER_SOURCE_DECLARED,
    DEVICE_CONTAINER_SOURCE_HUB,
    DEVICE_CONTAINER_SOURCE_MANUAL,
)

LOCALES_DIR = Path(__file__).resolve().parents[2] / "frontend/src/locales"
PANELS_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/components/containers_panels.tsx"
)
WORDS = {
    "en": {
        "ui.containers.hub_title": "Hub containers",
        "ui.containers.hub_hint": "The hub's modules run these. Change them in their module's tab.",
        "ui.containers.hub_empty": "No module runs a container on this machine.",
        "ui.containers.source_hub": "hub",
        "ui.containers.source_declared": "declared",
        "ui.containers.source_manual": "manual",
    },
    "zh-CN": {
        "ui.containers.hub_title": "中枢的容器",
        "ui.containers.hub_hint": "这些由中枢的模块运行，要改就到对应模块的标签页里改。",
        "ui.containers.hub_empty": "这台机器上还没有模块运行容器。",
        "ui.containers.source_hub": "中枢",
        "ui.containers.source_declared": "声明",
        "ui.containers.source_manual": "手动",
    },
}
CODES = ("container_name_reserved", "module_in_use", "container_hub_owned")


def catalog(language: str, name: str) -> dict:
    return json.loads((LOCALES_DIR / language / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_tab_says_what_ui_text_writes(language):
    worded = catalog(language, "modules.json")

    for key, sentence in WORDS[language].items():
        assert worded[key] == sentence


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_every_code_of_hub_containers_has_a_sentence(language):
    worded = catalog(language, "codes.json")

    for code in CODES:
        assert worded[f"code.{code}"]
    assert "{modules}" in worded["code.module_in_use"]
    assert "{name}" in worded["code.container_hub_owned"]


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_old_badges_are_gone(language):
    worded = catalog(language, "modules.json")

    assert "state.ad_hoc" not in worded
    assert "state.declared" not in worded


def test_each_owner_the_hub_reports_has_its_chip():
    panels = PANELS_PATH.read_text(encoding="utf-8")

    for source in (
        DEVICE_CONTAINER_SOURCE_HUB,
        DEVICE_CONTAINER_SOURCE_DECLARED,
        DEVICE_CONTAINER_SOURCE_MANUAL,
    ):
        assert f'"ui.containers.source_{source}"' in panels
