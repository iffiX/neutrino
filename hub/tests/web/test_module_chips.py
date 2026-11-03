"""The machine page's module order and each tab's two chips, held against the standard.

What these pin: ``GET /api/agent/module`` sends the rows in the description
table's order, the one ui_behavior.md names, and the page keeps it; each
install method reads as its source chip, so every shipped module on Linux,
Windows and macOS shows the chip ui_behavior.md gives it; every tab shows the
kind chip Service; the two chips sit between the title and the state; and the
words say in both languages what ui_text.md writes.
"""

import json
import re
from pathlib import Path

import pytest

from neutrino_hub.modules.devices.catalog import resolve_module
from neutrino_hub.modules.devices.manifests import load_module_manifests
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
    "siyuan",
    "podman",
    "hermes_webui",
    "ayakaleaf",
]
WORDS = {
    "en": {
        "ui.modules.source_agent": "Built-in",
        "ui.modules.source_system": "System",
        "ui.modules.source_upstream": "Upstream",
        "ui.modules.source_container": "Container",
        "ui.modules.kind_service": "Service",
    },
    "zh-CN": {
        "ui.modules.source_agent": "自带",
        "ui.modules.source_system": "系统",
        "ui.modules.source_upstream": "外部源",
        "ui.modules.source_container": "容器",
        "ui.modules.kind_service": "服务",
    },
}
# Each module's source chip on Linux, Windows and macOS; None where the
# system has no entry for it.
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


def panel_sources() -> dict:
    """The panel's table of install method to source chip key."""
    body = page()
    start = body.index("const SOURCE_KEYS: Record<string, string> = {")
    table = body[start : body.index("};", start)]
    return dict(re.findall(r'(\w+): "ui\.modules\.(source_\w+)"', table))


@pytest.fixture
def api(monkeypatch, tmp_path):
    client, runtime = module_box(monkeypatch, tmp_path, device_modules.router)
    runtime.device_platform[DEVICE] = DEBIAN
    return client


def test_the_list_sends_the_rows_in_the_description_table_s_order(api):
    rows = api.get("/api/agent/module", params={"device_id": DEVICE}).json()

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
def test_each_module_reads_its_source_chip_from_its_method(index, platform):
    sources = panel_sources()
    read = {}
    for name, manifest in load_module_manifests().items():
        method = resolve_module(manifest, platform)["method"]
        read[name] = sources.get(method) if method else None

    assert read == {name: chips[index] for name, chips in SOURCES.items()}


def test_every_method_has_a_source_chip():
    assert panel_sources() == {
        "agent": "source_agent",
        "builtin": "source_system",
        "system": "source_system",
        "hub": "source_upstream",
        "container": "source_container",
    }


def test_every_tab_reads_service():
    body = page()
    chips = body[body.index("function ModuleChips(") :]

    assert 'const KIND_SERVICE_KEY = "ui.modules.kind_service";' in body  # scan: allow
    assert '<span className="badge">{t(KIND_SERVICE_KEY)}</span>' in chips
    assert (
        '{sourceKey !== undefined && <span className="badge">{t(sourceKey)}</span>}'
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


def test_ui_text_writes_both_languages_of_each_chip():
    text = design("ui_text.md")
    en, zh = WORDS["en"], WORDS["zh-CN"]
    sources = [f"ui.modules.source_{name}" for name in ("agent", "system")]
    sources += [f"ui.modules.source_{name}" for name in ("upstream", "container")]

    assert (
        "| "
        + ", ".join(f"`{key}`" for key in sources)
        + ", the source chip of a module's tab | "
        + ", ".join(en[key] for key in sources)
        + " | "
        + "、".join(zh[key] for key in sources)
        + " |"
    ) in text
    assert (
        "| `ui.modules.kind_service`, the kind chip of a module's tab | Service | 服务 |"
    ) in text
    for chip, english, chinese in (
        ("source", "User-installed", "用户安装"),
        ("kind", "Program", "普通程序"),
    ):
        assert f"| {chip} | {english} | {chinese} |" in text
