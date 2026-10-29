"""The Agents page's badge, held against the count-of-one rule.

A count of one reads as a count with its noun in the singular, ``1 agent``.
"""

import json
from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
DEVICES_PAGE = FRONTEND_SRC_DIR / "pages/devices_page.tsx"


def catalog(language: str) -> dict:
    """The page's catalog in one language."""
    path = FRONTEND_SRC_DIR / "locales" / language / "devices.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_one_agent_reads_as_a_count_of_one():
    english = catalog("en")
    assert english["ui.devices.badge_one"] == "1 agent, {online} online"
    assert english["ui.devices.badge"] == "{total} agents, {online} online"
    assert catalog("zh-CN")["ui.devices.badge_one"] == "1 台被控端，{online} 台在线"
    source = DEVICES_PAGE.read_text(encoding="utf-8")
    assert 'count.total === 1\n    ? t("ui.devices.badge_one"' in source
