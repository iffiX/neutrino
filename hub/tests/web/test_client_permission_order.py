"""The Clients page's permission drawers list the kinds in one fixed order.

The hub sends the kinds in :data:`CLIENT_PERMISSION_KINDS` order; the drawer
draws its switches in its own display order, the same for the default and
for one client. Pinned: that order, and that it names every kind the hub has.
"""

import re
from pathlib import Path

from neutrino_hub.modules.clients.constants import CLIENT_PERMISSION_KINDS

DRAWER_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/components/client_permission_drawer.tsx"
)


def display_order() -> list[str]:
    """The drawer's display order, read from its source."""
    source = DRAWER_PATH.read_text(encoding="utf-8")
    body = re.search(r"const KIND_DISPLAY_ORDER = \[(.*?)\];", source, re.S)
    assert body is not None, f"KIND_DISPLAY_ORDER is not in {DRAWER_PATH.name}"
    return re.findall(r'"(\w+)"', body.group(1))


def test_the_drawer_lists_the_overlay_first_and_the_desktops_last():
    assert display_order() == [
        "overlay",
        "web",
        "port",
        "ai",
        "file",
        "terminal",
        "rdp",
    ]


def test_the_display_order_names_every_kind_the_hub_has():
    assert sorted(display_order()) == sorted(CLIENT_PERMISSION_KINDS)


def test_every_switch_is_drawn_in_the_display_order():
    source = DRAWER_PATH.read_text(encoding="utf-8")

    assert "{displayed(kinds).map((kind) =>" in source
