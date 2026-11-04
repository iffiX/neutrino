"""The machine page's module order and each tab's two chips, held against the standard.

What these pin: ``GET /api/agent/module`` sends the rows in the description
table's order, the one ui_behavior.md names, and the page keeps it; the page
reads the source chip from the row's ``source`` and the kind chip from its
``kind``, the words the hub sends, each word its own key and a word outside
the table no chip; so every shipped module on Linux, Windows and macOS shows
the chips ui_behavior.md gives it, Codex and Claude Code reading Program and
Upstream whatever the machine reports of their copy; the two chips
sit between the title and the state; and the words say in both languages what
ui_text.md writes.
"""

import json
import re
from pathlib import Path

import pytest

from neutrino_hub.modules.devices.module_table import DEVICE_MODULE_ROWS
from neutrino_hub.web.routers.agent import module as device_modules
from tests.web.module_api_box import DEVICE, module_box

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
DESIGN_DIR = HUB_DIR.parent / "skills/core-code-author/design"
DEBIAN = {"os": "linux", "family": "debian", "arch": "amd64"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
MACOS = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.1"}
ORDER = [
    "terminal",
    "ssh_server",
    "remote_desktop",
    "samba",
    "gitea",
    "vscode",
    "code_server",
    "cloudcli",
    "codeg",
    "claude_code",
    "codex",
    "siyuan",
    "podman",
    "hermes_webui",
    "ayakaleaf",
]
# The command line programs, whose kind chip reads Program.
PROGRAMS = ("claude_code", "codex")
WORDS = {
    "en": {
        "ui.modules.source_agent": "Built-in",
        "ui.modules.source_system": "System",
        "ui.modules.source_upstream": "Upstream",
        "ui.modules.source_container": "Container",
        "ui.modules.kind_service": "Service",
        "ui.modules.kind_program": "Program",
    },
    "zh-CN": {
        "ui.modules.source_agent": "自带",
        "ui.modules.source_system": "系统",
        "ui.modules.source_upstream": "外部源",
        "ui.modules.source_container": "容器",
        "ui.modules.kind_service": "服务",
        "ui.modules.kind_program": "普通程序",
    },
}
SOURCE_WORDS = ("agent", "system", "upstream", "container")
KIND_WORDS = ("service", "program")
# Each module's source chip on Linux, Windows and macOS before the machine
# reports it; None where the system has no entry for it.
SOURCES = {
    "terminal": ("source_agent",) * 3,
    "ssh_server": ("source_agent",) * 3,
    "remote_desktop": ("source_agent",) * 3,
    "samba": ("source_system",) * 3,
    "gitea": ("source_upstream",) * 3,
    "vscode": ("source_upstream",) * 3,
    "code_server": ("source_upstream", None, "source_upstream"),
    "cloudcli": ("source_upstream",) * 3,
    "codeg": ("source_upstream",) * 3,
    "claude_code": ("source_upstream",) * 3,
    "codex": ("source_upstream",) * 3,
    "siyuan": ("source_upstream",) * 3,
    "podman": ("source_system", "source_upstream", "source_upstream"),
    "hermes_webui": ("source_container",) * 3,
    "ayakaleaf": ("source_container",) * 3,
}


def page() -> str:
    path = FRONTEND_SRC_DIR / "components/machine_modules.tsx"
    return " ".join(path.read_text(encoding="utf-8").split())


def design(name: str) -> str:
    return " ".join((DESIGN_DIR / name).read_text(encoding="utf-8").split())


def panel_table(name: str, prefix: str) -> dict:
    """One of the panel's tables of a row's word to its chip key."""
    body = page()
    start = body.index(f"const {name}: Record<string, string> = {{")
    table = body[start : body.index("};", start)]
    return dict(re.findall(rf'(\w+): "ui\.modules\.({prefix}_\w+)"', table))


def chips_of(client) -> dict:
    """Each row's two chip keys as the page reads them, by module name."""
    sources = panel_table("SOURCE_KEYS", "source")
    kinds = panel_table("KIND_KEYS", "kind")
    rows = client.get("/api/agent/module", params={"device_id": DEVICE}).json()
    return {
        row["name"]: (sources.get(row["source"]), kinds.get(row["kind"]))
        for row in rows["modules"]
    }


@pytest.fixture
def api(monkeypatch, tmp_path):
    client, runtime = module_box(monkeypatch, tmp_path, device_modules.router)
    runtime.device_platform[DEVICE] = DEBIAN
    return client, runtime


def test_the_list_sends_the_rows_in_the_description_table_s_order(api):
    client, _ = api
    rows = client.get("/api/agent/module", params={"device_id": DEVICE}).json()

    assert [row["name"] for row in rows["modules"]] == ORDER
    assert [row.name for row in DEVICE_MODULE_ROWS] == ORDER


def test_the_page_keeps_the_hub_s_order():
    body = page()
    start = body.index("function shownModules(")
    shown = body[start : body.index("/** ", start)]

    assert ".sort(" not in shown
    assert "TAB_ORDER" not in body


def test_ui_behavior_names_the_table_s_order():
    text = design("ui_behavior.md")
    start = text.index("The rows of the module list, each a tab, come in one order")
    listed = text[text.index("runs first: ", start) + len("runs first: ") :]
    titles = listed[: listed.index(". ")].split(", ")
    en = json.loads(
        (FRONTEND_SRC_DIR / "locales/en/modules.json").read_text(encoding="utf-8")
    )

    assert [title.removeprefix("the ") for title in titles] == [
        en[f"ui.module_title.{name}"] for name in ORDER
    ]


@pytest.mark.parametrize("index,platform", list(enumerate((DEBIAN, WINDOWS, MACOS))))
def test_each_module_shows_the_chips_of_the_hub_s_words(api, index, platform):
    client, runtime = api
    runtime.device_platform[DEVICE] = platform

    assert chips_of(client) == {
        name: (
            chips[index],
            "kind_program" if name in PROGRAMS else "kind_service",
        )
        for name, chips in SOURCES.items()
    }


@pytest.mark.parametrize("module", PROGRAMS)
@pytest.mark.parametrize("has_module_copy", [True, False])
def test_a_program_reads_upstream_whatever_its_copy(api, module, has_module_copy):
    client, runtime = api
    runtime.device_modules[DEVICE] = {
        module: {
            "state": "running",
            "details": {"has_module_copy": has_module_copy, "accounts": []},
        }
    }

    assert chips_of(client)[module] == ("source_upstream", "kind_program")


def test_every_source_word_has_a_chip():
    assert panel_table("SOURCE_KEYS", "source") == {
        word: f"source_{word}" for word in SOURCE_WORDS
    }


def test_every_kind_word_has_a_chip():
    assert panel_table("KIND_KEYS", "kind") == {
        word: f"kind_{word}" for word in KIND_WORDS
    }


def test_the_chips_read_the_row_s_source_and_kind():
    body = page()
    chips = body[body.index("function ModuleChips(") :]
    chips = chips[: chips.index("/** ")]

    assert "row.method" not in chips
    assert "const sourceKey = SOURCE_KEYS[row.source];" in chips
    assert "const kindKey = KIND_KEYS[row.kind];" in chips
    assert (
        '{sourceKey !== undefined && <span className="badge">{t(sourceKey)}</span>}'
    ) in chips
    assert (
        '{kindKey !== undefined && <span className="badge">{t(kindKey)}</span>}'
    ) in chips


def test_the_chips_sit_between_the_title_and_the_state():
    body = page()
    head = body[body.index('<div className="modules_detail_head">') :]
    head = head[: head.index("</div>")]

    assert head.index("<h3>") < head.index("<ModuleChips row={activeRow} />")
    assert head.index("<ModuleChips row={activeRow} />") < head.index("<StatusDot")


@pytest.mark.parametrize("language", list(WORDS))
def test_the_words_say_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    for key, word in WORDS[language].items():
        assert words[key] == word


@pytest.mark.parametrize("chip,names", [("source", SOURCE_WORDS), ("kind", KIND_WORDS)])
def test_ui_text_writes_both_languages_of_each_chip(chip, names):
    text = design("ui_text.md")
    en, zh = WORDS["en"], WORDS["zh-CN"]
    keys = [f"ui.modules.{chip}_{name}" for name in names]

    assert (
        "| "
        + ", ".join(f"`{key}`" for key in keys)
        + f", the {chip} chip of a module's tab | "
        + ", ".join(en[key] for key in keys)
        + " | "
        + "、".join(zh[key] for key in keys)
        + " |"
    ) in text
    for key in keys:
        assert f"| {chip} | {en[key]} | {zh[key]} |" in text
