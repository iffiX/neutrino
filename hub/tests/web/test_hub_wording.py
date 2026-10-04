"""How every word table names the hub, held against the fixed-name rule.

Each language has its own word for the hub: Chinese writes 中枢 and never
``hub``, English writes hub and never 中枢. No sentence in either says the
hub downloads, bundles or distributes software: what a module puts on a
machine is installed there by its owner. The tables are the panel's
catalogs, the desktop client's, which the Android app carries too, and the
Android app's own; a checkout without the clients checks the panel alone.
"""

import json
import re
from pathlib import Path

import pytest

REPOSITORY_DIR = Path(__file__).resolve().parents[3]
PANEL_LOCALES_DIR = REPOSITORY_DIR / "hub/frontend/src/locales"
CLIENT_LOCALES_DIR = REPOSITORY_DIR / "client/desktop/frontend/locales"
ANDROID_LOCALES_DIR = REPOSITORY_DIR / "client/android/app/src/main/assets/locales/app"

# What a sentence may carry that is not prose: placeholders, code spans,
# addresses and file paths.
NOT_PROSE = re.compile(
    r"\{\w+\}|`[^`]*`|https?://\S+|[A-Za-z0-9_.~-]*/[A-Za-z0-9_./~-]*"
)
# ``hub`` as a word, beside Chinese too; GitHub, nhub and neutrino_hub are not.
HUB_WORD = re.compile(r"(?<![A-Za-z0-9_-])hub(?![A-Za-z0-9_-])", re.IGNORECASE)
# The hub as the one that fetches, bundles or hands out software.
ENGLISH_DISTRIBUTES = re.compile(
    r"\bhub\b(\W+\w+){0,3}\W+(downloads|bundles|distributes|ships)\b"
    r"|\bhands? (it |them )?to (managed|a|every) machines?\b",
    re.IGNORECASE,
)
CHINESE_DISTRIBUTES = re.compile(r"代为下载|分发|中枢[^。；，]{0,6}(下载|自带)")


def flattened(value, prefix: str = "") -> dict:
    """A catalog's sentences under dotted keys, nested objects opened."""
    if not isinstance(value, dict):
        return {prefix: value}
    words = {}
    for key, inner in value.items():
        words.update(flattened(inner, f"{prefix}.{key}" if prefix else key))
    return words


def catalogs(language: str) -> list:
    """Every catalog in one language, as ``(name, {key: sentence})``.

    Args:
        language: ``en`` or ``zh-CN``.

    Returns:
        The panel's files, then the clients' where the checkout has them.
    """
    paths = sorted((PANEL_LOCALES_DIR / language).glob("*.json"))
    for directory in (CLIENT_LOCALES_DIR, ANDROID_LOCALES_DIR):
        path = directory / f"{language}.json"
        if path.is_file():
            paths.append(path)
    return [
        (
            str(path.relative_to(REPOSITORY_DIR)),
            flattened(json.loads(path.read_text(encoding="utf-8"))),
        )
        for path in paths
    ]


def offending(language: str, pattern: re.Pattern) -> list:
    """The sentences in one language whose prose matches a pattern."""
    found = []
    for name, words in catalogs(language):
        for key, sentence in words.items():
            if isinstance(sentence, str) and pattern.search(
                NOT_PROSE.sub(" ", sentence)
            ):
                found.append(f"{name}: {key}: {sentence}")
    return found


def test_chinese_never_calls_the_hub_hub():
    assert offending("zh-CN", HUB_WORD) == []


def test_english_never_writes_the_chinese_word():
    assert offending("en", re.compile("中枢")) == []


@pytest.mark.parametrize(
    "language, pattern",
    [("en", ENGLISH_DISTRIBUTES), ("zh-CN", CHINESE_DISTRIBUTES)],
)
def test_no_sentence_says_the_hub_hands_out_software(language, pattern):
    assert offending(language, pattern) == []


@pytest.mark.parametrize(
    "sentence, is_caught",
    [
        ("hub 没有响应。", True),
        ("Hub 名称", True),
        ("这台hub", True),
        ("从 GitHub 取回", False),
        ("运行 nhub apply", False),
        ("journalctl -u neutrino_hub_update", False),
        ("对端使用 {hub}", False),
        ("打开 https://hub.example/x", False),
    ],
)
def test_the_hub_rule_reads_names_and_code_as_not_prose(sentence, is_caught):
    assert bool(HUB_WORD.search(NOT_PROSE.sub(" ", sentence))) is is_caught


@pytest.mark.parametrize(
    "sentence, pattern, is_caught",
    [
        (
            "Open-source software this hub downloads and hands to managed machines.",
            ENGLISH_DISTRIBUTES,
            True,
        ),
        ("The hub no longer offers {network}", ENGLISH_DISTRIBUTES, False),
        ("中枢下载并分发给受管机器的开源软件。", CHINESE_DISTRIBUTES, True),
        ("中枢不再提供 {network}", CHINESE_DISTRIBUTES, False),
    ],
)
def test_the_distribution_rule_catches_what_it_means(sentence, pattern, is_caught):
    assert bool(pattern.search(NOT_PROSE.sub(" ", sentence))) is is_caught
