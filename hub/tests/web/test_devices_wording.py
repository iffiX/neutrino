"""The Agents page's badge, held against the count-of-one rule, the header
chip's count, and the install dialog's words for a key the hub cannot open.

A count of one reads as a count with its noun in the singular, ``1 agent``.
"""

import json
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
DEVICES_PAGE = FRONTEND_SRC_DIR / "pages/devices_page.tsx"
TOP_BAR = FRONTEND_SRC_DIR / "components/top_bar.tsx"


def catalog(language: str, name: str = "devices.json") -> dict:
    """One catalog file in one language, the page's own by default."""
    path = FRONTEND_SRC_DIR / "locales" / language / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_one_agent_reads_as_a_count_of_one():
    english = catalog("en")
    assert english["ui.devices.badge_one"] == "1 agent, {online} online"
    assert english["ui.devices.badge"] == "{total} agents, {online} online"
    assert catalog("zh-CN")["ui.devices.badge_one"] == "1 台被控端，{online} 台在线"
    source = DEVICES_PAGE.read_text(encoding="utf-8")
    assert 'count.total === 1\n    ? t("ui.devices.badge_one"' in source


def test_the_header_chip_counts_every_agent_as_the_badge_does():
    """The chip's ``{count} agents`` is the badge's ``{total} agents``. It read
    0 agents beside a badge of 2 agents, 0 online."""
    source = TOP_BAR.read_text(encoding="utf-8")
    assert 'useApiResource<DevicesResponse>("/hub/device"' in source
    assert "const agentCount = devices.data?.count.total ?? null;" in source
    assert "agent_device_count" not in source


@pytest.mark.parametrize(
    "language, word",
    [
        (
            "en",
            "This key is passphrase-protected and the hub cannot open it. "
            "Add it on the Credentials page with its passphrase.",
        ),
        ("zh-CN", "这个密钥有口令保护，中枢打不开它。请在凭据页带上口令添加这个密钥。"),
    ],
)
def test_a_stored_key_with_no_passphrase_names_the_credentials_page(language, word):
    """The install dialog asked for the passphrase and has no field for one."""
    assert catalog(language, "codes.json")["code.key_passphrase_not_stored"] == word
