"""The catalog reader every Python surface of the client words itself from.

The catalogs themselves are held complete by ``tests/control/test_page.py``;
what is checked here is the reading: which directory wins, the fallback
chain, the ``{name}`` holes, and the locale mapping the first start takes.
"""

import json

import pytest

from neutrino_client import words
from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_LANGUAGES,
    CLIENT_TRAY_OPEN_LABEL_KEY,
)


def test_a_checkout_reads_the_frontend_catalogs():
    assert words.locales_dir() == words.LOCALES_SOURCE_DIR
    assert set(words.catalogs()) == set(CLIENT_LANGUAGES)


def test_a_built_package_reads_the_catalogs_beside_the_page(tmp_path, monkeypatch):
    built = tmp_path / "locales"
    built.mkdir()
    (built / "en.json").write_text(json.dumps({"ui.tray.open": "Open"}))
    monkeypatch.setattr(words, "LOCALES_DATA_DIR", built)

    assert words.locales_dir() == built
    assert words.word("en", CLIENT_TRAY_OPEN_LABEL_KEY) == "Open"


def test_a_machine_with_no_catalog_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(words, "LOCALES_DATA_DIR", tmp_path / "none")
    monkeypatch.setattr(words, "LOCALES_SOURCE_DIR", tmp_path / "neither")

    with pytest.raises(FileNotFoundError):
        words.locales_dir()


def test_each_language_says_the_tray_in_its_own_words():
    english = words.word("en", CLIENT_TRAY_OPEN_LABEL_KEY)
    chinese = words.word("zh-CN", CLIENT_TRAY_OPEN_LABEL_KEY)

    assert english == "Open"
    assert chinese != english


def test_a_language_the_client_does_not_offer_reads_as_english():
    assert words.words("de") == words.words(CLIENT_DEFAULT_LANGUAGE)
    assert words.word("de", CLIENT_TRAY_OPEN_LABEL_KEY) == "Open"


def test_a_key_no_catalog_carries_reads_as_itself():
    assert words.word("en", "ui.nothing_like_this") == "ui.nothing_like_this"


def test_a_wording_fills_its_holes_and_leaves_a_missing_one_empty():
    filled = words.word("en", "code.bundle_missing", {"binary": "rustdesk"})

    assert "rustdesk" in filled
    assert "{binary}" not in words.word("en", "code.bundle_missing")


def test_a_chinese_locale_tag_maps_to_the_one_chinese_the_client_offers():
    for tag in ("zh", "zh_CN.UTF-8", "zh-TW", "ZH_cn"):
        assert words.language_for_tag(tag) == "zh-CN"


def test_every_other_locale_tag_maps_to_english():
    for tag in ("", "C", "en_GB.UTF-8", "de_DE", "ja_JP"):
        assert words.language_for_tag(tag) == CLIENT_DEFAULT_LANGUAGE
