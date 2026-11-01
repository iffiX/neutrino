"""Every word a phone app names in its source is in the words it ships."""

import json
import re
from pathlib import Path

import pytest

CLIENT_DIR = Path(__file__).resolve().parents[2]
SHARED_WORDS = CLIENT_DIR / "desktop" / "frontend" / "locales"
WORD_KEY = re.compile(r'"((?:ui|code)\.[a-z0-9_.]*[a-z0-9_])"')

PHONES = {
    "android": (
        CLIENT_DIR / "android" / "app" / "src" / "main" / "kotlin",
        "*.kt",
        CLIENT_DIR / "android" / "app" / "src" / "main" / "assets" / "locales" / "app",
    ),
    "ios": (
        CLIENT_DIR / "ios" / "Neutrino",
        "*.swift",
        CLIENT_DIR / "ios" / "app_locales",
    ),
}


def flattened(words: dict, prefix: str = "") -> set:
    """Every dotted key of a word file."""
    keys = set()
    for name, value in words.items():
        key = f"{prefix}.{name}" if prefix else name
        keys |= flattened(value, key) if isinstance(value, dict) else {key}
    return keys


def words_of(directory: Path, language: str) -> set:
    return flattened(json.loads((directory / f"{language}.json").read_text("utf-8")))


@pytest.mark.parametrize("language", ["en", "zh-CN"])
@pytest.mark.parametrize("phone", sorted(PHONES))
def test_a_phone_names_no_word_it_does_not_ship(phone, language):
    source, pattern, own_words = PHONES[phone]
    if not source.is_dir():
        pytest.skip(f"this tree has no {phone} app")
    shipped = words_of(SHARED_WORDS, language) | words_of(own_words, language)

    missing = {
        f"{path.name}: {key}"
        for path in source.rglob(pattern)
        for key in WORD_KEY.findall(path.read_text("utf-8"))
        if key not in shipped
    }

    assert not missing
