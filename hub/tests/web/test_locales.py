"""The panel's catalogs, held against each other and against the sources.

A key the current language has no sentence for falls back to English, so a
missing translation is invisible in a review and obvious to whoever reads the
panel in Chinese. These assert the three things that cannot be seen by reading
one file: both languages carry the same keys in the same file, both fill the
same placeholders, and every key a source names is one English has.
"""

import json
import re
from pathlib import Path

import pytest

from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE, WEB_LANGUAGES

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"

# Anything that reads as a catalog key, wherever a source writes one: the call
# itself, and the tables of keys a page steps through.
KEY_PATTERN = re.compile(r'"((?:ui|state|code)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*)"')
PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")


def catalog(language: str, name: str) -> dict:
    """One catalog file's sentences.

    Args:
        language: The language directory.
        name: The file name.

    Returns:
        The parsed object.
    """
    return json.loads((LOCALES_DIR / language / name).read_text(encoding="utf-8"))


def catalog_names() -> list:
    """Every catalog file name English carries."""
    return sorted(
        path.name for path in (LOCALES_DIR / WEB_DEFAULT_LANGUAGE).glob("*.json")
    )


def english_keys() -> set:
    """Every key English words."""
    keys: set = set()
    for name in catalog_names():
        keys |= set(catalog(WEB_DEFAULT_LANGUAGE, name))
    return keys


def source_paths() -> list:
    """Every TypeScript source that could name a key."""
    return sorted(
        path
        for pattern in ("*.ts", "*.tsx")
        for path in FRONTEND_SRC_DIR.rglob(pattern)
    )


@pytest.mark.parametrize("language", list(WEB_LANGUAGES))
def test_every_language_carries_the_same_files(language):
    assert sorted(path.name for path in (LOCALES_DIR / language).glob("*.json")) == (
        catalog_names()
    )


@pytest.mark.parametrize("name", catalog_names())
@pytest.mark.parametrize("language", list(WEB_LANGUAGES))
def test_every_file_carries_the_same_keys(language, name):
    assert set(catalog(language, name)) == set(catalog(WEB_DEFAULT_LANGUAGE, name))


@pytest.mark.parametrize("name", catalog_names())
@pytest.mark.parametrize("language", list(WEB_LANGUAGES))
def test_every_sentence_fills_the_same_placeholders(language, name):
    """A translation that drops `{url}` is a sentence missing its address."""
    english = catalog(WEB_DEFAULT_LANGUAGE, name)
    for key, sentence in catalog(language, name).items():
        assert set(PLACEHOLDER_PATTERN.findall(sentence)) == set(
            PLACEHOLDER_PATTERN.findall(english[key])
        ), key


def test_every_key_a_source_names_is_one_english_words():
    worded = english_keys()
    for path in source_paths():
        for key in KEY_PATTERN.findall(path.read_text(encoding="utf-8")):
            assert key in worded, f"{key} in {path.name}"


def test_a_key_defined_in_two_files_carries_one_sentence():
    """The loader merges the files; a key worded twice must not differ."""
    for language in WEB_LANGUAGES:
        seen = {}
        for path in sorted((LOCALES_DIR / language).glob("*.json")):
            for key, value in json.loads(path.read_text(encoding="utf-8")).items():
                if key in seen and seen[key][1] != value:
                    raise AssertionError(
                        f"{language}: {key} is {seen[key][1]!r} in {seen[key][0]} "
                        f"and {value!r} in {path.name}"
                    )
                seen.setdefault(key, (path.name, value))
