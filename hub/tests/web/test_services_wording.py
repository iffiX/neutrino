"""The Services page words every code the services API can send.

The API sends ``{code, params}`` and never a sentence, so a code the page has
no word for is a row that says nothing about why it is unhealthy, or a row
that says nothing about where it came from. Asserting the tables both ways
means a new code fails this suite until it is worded, and a word left behind
by a retired code fails it too.
"""

import re
from pathlib import Path

import pytest

from neutrino_hub.modules.services.constants import (
    SERVICES_DESCRIPTION_CODES,
    SERVICES_PROBE_DETAIL_CODES,
)

SERVICES_PAGE_PATH = (
    Path(__file__).resolve().parents[2] / "frontend/src/pages/services_page.tsx"
)

WORDING_TABLE = "DECLARED_DETAIL_KEYS"
DESCRIPTION_TABLE = "DESCRIPTION_KEYS"


def worded_codes(table: str) -> set[str]:
    """The keys of one wording table in the page.

    Args:
        table: The table's constant name.

    Returns:
        Every code it words.
    """
    source = SERVICES_PAGE_PATH.read_text(encoding="utf-8")
    body = re.search(rf"const {table}[^{{]*{{(.*?)^}};", source, re.S | re.M)
    assert body is not None, f"{table} is not in {SERVICES_PAGE_PATH.name}"
    return set(re.findall(r"^  (\w+):", body.group(1), re.M))


@pytest.fixture(scope="module")
def detail_words() -> set[str]:
    return worded_codes(WORDING_TABLE)


@pytest.fixture(scope="module")
def description_words() -> set[str]:
    return worded_codes(DESCRIPTION_TABLE)


@pytest.mark.parametrize("code", SERVICES_PROBE_DETAIL_CODES)
def test_every_probe_detail_code_is_worded(code, detail_words):
    assert code in detail_words


def test_no_word_is_left_for_a_code_that_no_longer_exists(detail_words):
    assert detail_words <= set(SERVICES_PROBE_DETAIL_CODES)


@pytest.mark.parametrize("code", SERVICES_DESCRIPTION_CODES)
def test_every_provenance_code_is_worded(code, description_words):
    assert code in description_words


def test_no_provenance_word_is_left_for_a_code_that_no_longer_exists(
    description_words,
):
    assert description_words <= set(SERVICES_DESCRIPTION_CODES)
