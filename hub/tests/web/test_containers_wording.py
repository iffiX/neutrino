"""What the Containers tab says of hub containers and owners, held against ui_text.md.

The tab words where each container comes from with one of three chips, and
the Hub containers block with its title, its hint and its empty line; the
Run settings' default line, the memory advice and the apply bar's hint
while the module is stopped say what ui_text.md writes, and the bar shows
that hint while the module's want is stopped; the codes Containers adds for hub containers and for container
modules have a sentence in both languages; the old badges are gone, so
nothing names a person's container anything but manual; and the
not-installed notice of Containers and Gitea shows for an absent module
alone.
"""

import json
import re
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
RUN_SETTINGS_PATH = PANELS_PATH.parent / "containers_run_settings.tsx"
WORDS = {
    "en": {
        "ui.containers.hub_title": "Hub containers",
        "ui.containers.hub_hint": "The hub's modules run these. Change them in their module's tab.",
        "ui.containers.hub_empty": "No module runs a container on this machine.",
        "ui.containers.source_hub": "hub",
        "ui.containers.source_declared": "declared",
        "ui.containers.source_manual": "manual",
        "ui.containers.run_default_hint": "0 uses the default: half the CPUs, half the memory up to 4 GiB, a 100 GiB disk.",
        "ui.containers.run_default_hint_windows": "A 0 for CPUs or memory uses the default: half the CPUs, half the memory up to 4 GiB.",
        "ui.containers.run_memory_need": "Set {need} GiB or more for the container modules installed here.",
        "ui.modules.memory_need": "The Podman machine has {memory} GiB of memory; set {need} GiB under Containers, Run settings.",
        "ui.modules.stopped_hint": "The module is stopped; these settings take effect at the next Start.",
    },
    "zh-CN": {
        "ui.containers.hub_title": "中枢的容器",
        "ui.containers.hub_hint": "这些由中枢的模块运行，要改就到对应模块的标签页里改。",
        "ui.containers.hub_empty": "这台机器上还没有模块运行容器。",
        "ui.containers.source_hub": "中枢",
        "ui.containers.source_declared": "声明",
        "ui.containers.source_manual": "手动",
        "ui.containers.run_default_hint": "填 0 用默认值：一半的 CPU、一半的内存（最多 4 GiB）、100 GiB 磁盘。",
        "ui.containers.run_default_hint_windows": "CPU 数或内存填 0 用默认值：一半的 CPU、一半的内存（最多 4 GiB）。",
        "ui.containers.run_memory_need": "为这里安装的容器模块，设为 {need} GiB 或更多。",
        "ui.modules.memory_need": "Podman 虚拟机现有 {memory} GiB 内存；请在“容器”的“运行设置”里设为 {need} GiB。",
        "ui.modules.stopped_hint": "模块已停止，这些设置在下次启动时生效。",
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


@pytest.mark.parametrize(
    ("panel", "key"),
    [
        ("containers_panels.tsx", "ui.containers.not_installed"),
        ("gitea_panels.tsx", "ui.gitea.not_installed"),
    ],
)
def test_the_not_installed_notice_shows_for_an_absent_module_alone(panel, key):
    source = (PANELS_PATH.parent / panel).read_text(encoding="utf-8")

    shown_when = re.search(
        r"\{([^{}]*) && \(\s*<div className=\"notice notice--warn\">"
        r"\s*<Icon name=\"alert\" size=\{15\} />"
        rf"\s*<div className=\"notice_body\">\{{t\(\"{re.escape(key)}\"\)\}}",
        source,
    )
    assert shown_when is not None
    assert shown_when.group(1) == "saved.state === ABSENT_STATE"
    assert 'const ABSENT_STATE = "absent";' in source


def test_the_run_settings_hint_names_the_next_start_while_the_module_is_stopped():
    source = RUN_SETTINGS_PATH.read_text(encoding="utf-8")
    bar = source[source.index("<ApplyBar") :]

    hint = re.search(r"\n\s*hint=\{([^{}]*)\}\n", bar)
    assert hint is not None
    assert " ".join(hint.group(1).split()) == (
        'want === WANT_STOPPED ? t("ui.modules.stopped_hint")'
        ' : t("ui.containers.run_apply_hint")'
    )
    assert 'const WANT_STOPPED = "stopped";' in source
