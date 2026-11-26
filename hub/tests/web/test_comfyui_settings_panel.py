"""The ComfyUI tab's Settings, held against ui_text.md, ui_behavior.md and the hub's choices.

What these pin: every word of the tab says what ui_text.md writes in both
languages; **Runs on** offers the view's builds in their order, each worded
by its build, and is not drawn on macOS; **Idle unload time** offers the
hub's five choices in their order; the models folder is the view's
``models_dir`` as text, which the form does not hold; the bar's warning
shows while the build differs and the module runs; a press posts ``set``
and then ``apply``; and the tab is drawn from ComfyUI's own panel.
"""

import json
from pathlib import Path

import pytest

from neutrino_hub.modules.devices.constants import (
    DEVICE_COMFYUI_IDLE_UNLOAD_CHOICES,
    DEVICE_COMFYUI_TORCH_BUILDS,
)

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
SETTINGS_PATH = FRONTEND_SRC_DIR / "components/comfyui_settings.tsx"
MODULES_PATH = FRONTEND_SRC_DIR / "components/machine_modules.tsx"
# ui_text.md, "The ComfyUI tab's words".
WORDS = {
    "en": {
        "ui.module_catalog.comfyui": (
            "Images and video from node workflows, on this machine."
        ),
        "ui.comfyui.settings_title": "Settings",
        "ui.comfyui.torch_build": "Runs on",
        "ui.comfyui.torch_build_nvidia": "NVIDIA GPU (CUDA)",
        "ui.comfyui.torch_build_amd": "AMD GPU (ROCm)",
        "ui.comfyui.torch_build_intel": "Intel Arc GPU (XPU)",
        "ui.comfyui.torch_build_cpu": "CPU",
        "ui.comfyui.idle_unload": "Idle unload time",
        "ui.comfyui.idle_unload_5m": "5 minutes",
        "ui.comfyui.idle_unload_30m": "30 minutes",
        "ui.comfyui.idle_unload_1h": "1 hour",
        "ui.comfyui.idle_unload_4h": "4 hours",
        "ui.comfyui.idle_unload_never": "Never",
        "ui.comfyui.models_dir": "Models folder",
        "ui.comfyui.settings_apply": "Apply settings",
        "ui.comfyui.settings_apply_hint": (
            "A new Runs on installs its PyTorch and restarts ComfyUI. The idle "
            "unload time takes effect at once."
        ),
        "ui.comfyui.torch_build_warning": (
            "ComfyUI stops while the new PyTorch downloads, several GB of it."
        ),
        "ui.modules.step.artifact.comfyui.python": "Install Python",
        "ui.modules.step.artifact.comfyui.uv": "Install uv",
        "ui.modules.step.artifact.comfyui.source": "Install ComfyUI",
        "ui.modules.step.artifact.comfyui.vc_runtime": (
            "Install the Visual C++ runtime"
        ),
        "ui.modules.step.artifact.comfyui.mcp": "Install comfy-mcp",
        "ui.modules.step.artifact.comfyui.venv": "Install ComfyUI's Python packages",
    },
    "zh-CN": {
        "ui.module_catalog.comfyui": "在这个系统上用节点工作流生成图片和视频。",
        "ui.comfyui.settings_title": "设置",
        "ui.comfyui.torch_build": "运行在",
        "ui.comfyui.torch_build_nvidia": "NVIDIA 显卡（CUDA）",
        "ui.comfyui.torch_build_amd": "AMD 显卡（ROCm）",
        "ui.comfyui.torch_build_intel": "Intel Arc 显卡（XPU）",
        "ui.comfyui.torch_build_cpu": "CPU",
        "ui.comfyui.idle_unload": "空闲多久后移出内存",
        "ui.comfyui.idle_unload_5m": "5 分钟",
        "ui.comfyui.idle_unload_30m": "30 分钟",
        "ui.comfyui.idle_unload_1h": "1 小时",
        "ui.comfyui.idle_unload_4h": "4 小时",
        "ui.comfyui.idle_unload_never": "从不",
        "ui.comfyui.models_dir": "模型文件夹",
        "ui.comfyui.settings_apply": "应用设置",
        "ui.comfyui.settings_apply_hint": (
            "换了“运行在”会安装对应的 PyTorch 并重启 ComfyUI。空闲时间立即生效。"
        ),
        "ui.comfyui.torch_build_warning": (
            "下载新的 PyTorch 期间 ComfyUI 会停止，要下载几 GB。"
        ),
        "ui.modules.step.artifact.comfyui.python": "安装 Python",
        "ui.modules.step.artifact.comfyui.uv": "安装 uv",
        "ui.modules.step.artifact.comfyui.source": "安装 ComfyUI",
        "ui.modules.step.artifact.comfyui.vc_runtime": "安装 Visual C++ 运行库",
        "ui.modules.step.artifact.comfyui.mcp": "安装 comfy-mcp",
        "ui.modules.step.artifact.comfyui.venv": "安装 ComfyUI 的 Python 软件包",
    },
}
SERVICE_LINES = {
    "en": "published by the ComfyUI module on {host}",
    "zh-CN": "由 {host} 上的 ComfyUI 模块发布",
}


def settings_source() -> str:
    return " ".join(SETTINGS_PATH.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_every_word_of_the_tab_says_what_ui_text_writes(language):
    worded = json.loads((LOCALES_DIR / language / "modules.json").read_text("utf-8"))
    devices = json.loads((LOCALES_DIR / language / "devices.json").read_text("utf-8"))

    for key, sentence in WORDS[language].items():
        assert worded[key] == sentence, key
    assert worded["ui.module_title.comfyui"] == "ComfyUI"
    assert devices["ui.services.description_comfyui_module"] == (
        SERVICE_LINES[language]
    )


def test_runs_on_offers_the_view_s_builds_each_worded_and_none_on_macos():
    source = settings_source()

    assert "saved.torch_builds.map((build) => ({ id: build," in source
    assert "name: t(`ui.comfyui.torch_build_${build}`)," in source
    assert (
        "const isBuildShown = platformOs !== DARWIN && saved.torch_builds.length > 0;"
        in source
    )
    assert 'const DARWIN = "darwin";' in source
    assert 'torch_build: isBuildShown ? draft.torch_build : "",' in source
    assert set(DEVICE_COMFYUI_TORCH_BUILDS) == {"nvidia", "amd", "intel", "cpu"}


def test_idle_unload_offers_the_hub_s_five_choices_in_their_order():
    source = settings_source()
    table = source[source.index("const IDLE_UNLOAD_CHOICES") :]
    table = table[table.index("= [") : table.index("];")]
    ids = [part.split('"')[1] for part in table.split("id: ")[1:]]

    assert tuple(ids) == DEVICE_COMFYUI_IDLE_UNLOAD_CHOICES
    assert 'key: "ui.comfyui.idle_unload_never"' in table


def test_the_models_folder_is_text_the_form_does_not_hold():
    source = settings_source()
    draft = source[source.index("function draftOf(") :]

    assert '{t("ui.comfyui.models_dir")}' in source
    assert "{saved.models_dir}</span>" in source
    assert "models_dir" not in draft
    assert "interface SettingsDraft { torch_build: string; idle_unload: string; }" in (
        source
    )


def test_the_warning_shows_while_the_build_differs_and_the_module_runs():
    source = settings_source()

    assert "const isBuildChanged = draft.torch_build !== saved.torch_build;" in source
    assert (
        "isDirty && isBuildChanged && saved.state === STATE_RUNNING "
        '? t("ui.comfyui.torch_build_warning") : undefined' in source
    )
    assert 'label={t("ui.comfyui.settings_apply")}' in source


def test_a_press_posts_set_then_apply():
    source = settings_source()

    set_at = source.index("apiPost<ComfyuiDeviceView>(`${basePath}/set`, request)")
    apply_at = source.index("apiPost<ApplyResult>(`${basePath}/apply`")
    assert set_at < apply_at
    assert "settle.begin();" in source


def test_the_tab_is_drawn_from_comfyui_s_own_panel():
    page = " ".join(MODULES_PATH.read_text(encoding="utf-8").split())

    assert "comfyui: (target) => ( <ComfyuiPanels" in page
