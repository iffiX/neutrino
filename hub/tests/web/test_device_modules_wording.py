"""The drawer's module rows word the tiers, and dead wording is gone.

The rows ship their words in ``device_modules.tsx``; what is pinned here is
the user tier's surface contract — the exact sentence an absent user-tier
row shows, and that such a row offers no install or uninstall button — plus
that the wording for codes nothing emits any more has been removed.
"""

from pathlib import Path

DEVICE_MODULES_PATH = (
    Path(__file__).resolve().parents[2] / "frontend/src/components/device_modules.tsx"
)

USER_TIER_SENTENCE = "Install it on the machine yourself; the hub only manages it"


def page_source() -> str:
    return DEVICE_MODULES_PATH.read_text(encoding="utf-8")


def test_an_absent_user_tier_row_words_the_tier_exactly():
    source = page_source()
    assert f'userTier: "{USER_TIER_SENTENCE}"' in source
    assert 'deviceModule.state === "absent"' in source
    assert "parts.push(WORDING.userTier);" in source


def test_a_user_tier_row_offers_no_install_or_uninstall_button():
    source = page_source()
    assert 'const USER_INSTALLER = "user";' in source
    assert "deviceModule.installer !== USER_INSTALLER && (" in source


def test_the_dead_impersonation_wording_is_gone():
    assert "module_fetch_unavailable" not in page_source()
