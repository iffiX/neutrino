"""The RustDesk card on the Remote desktop tab, held against ui_text.md.

What these pin: the card names who shares only while the report names an
account; with nobody at the screen the line is the viewer count alone.
"""

from pathlib import Path

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"


def flat(name: str) -> str:
    """One frontend file with its whitespace folded to single spaces."""
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def test_the_sharer_shows_only_while_the_report_names_one():
    card = flat("components/remote_desktop_panel.tsx")

    assert (
        '<span className="muted"> {rdp.account !== "" && ( '
        '<>{t("ui.remote_desktop.shared_by", { account: rdp.account })} </> )} '
        "{viewerWords(rdp.connected_count)} </span>"
    ) in card


def test_ui_text_writes_the_rule_beside_the_words():
    text = UI_TEXT.read_text(encoding="utf-8")

    assert (
        "| `ui.remote_desktop.shared_by`, the RustDesk card's line before the viewer "
        "count, shown only while the report names an account"
    ) in text
