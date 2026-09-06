"""The CLI's word tables, held to the page's own code list.

The page and the terminal each word the agent's typed codes in their own
register; what they share is the list of codes, never the strings. Every
code, state, cause and operation word the page's table carries must have a
wording on the terminal surface too, so the two cannot drift apart by one
forgotten entry.
"""

from neutrino_agent.cli import status as status_cli
from neutrino_agent.cli import wording
from tests.control.test_page import (
    ATTACH_RENDERED_STATES,
    DETAIL_FALLBACK_CODES,
    MOUNT_BUSY_STATES,
    words_block,
)


def test_every_code_the_page_words_has_cli_words():
    for code in words_block("codes"):
        worded = wording.word_code(code, {})

        assert worded not in ("", code), f"code {code} has no CLI wording"


def test_the_detail_codes_are_the_pages_own():
    assert set(wording.CLI_DETAIL_CODES) == set(DETAIL_FALLBACK_CODES)

    for code in wording.CLI_DETAIL_CODES:
        assert wording.word_code(code, {"detail": "its own words"}) == "its own words"


def test_every_state_the_page_words_has_cli_words():
    for state in words_block("states"):
        assert state in wording.CLI_STATE_WORDS, f"state {state} has no CLI wording"


def test_every_operation_state_the_page_words_has_cli_words():
    for state in words_block("operation"):
        assert (
            state in wording.CLI_OPERATION_WORDS
        ), f"operation state {state} has no CLI wording"


def test_every_mount_record_state_has_cli_words():
    for state in set(MOUNT_BUSY_STATES) | ATTACH_RENDERED_STATES:
        assert (
            state in wording.CLI_MOUNT_STATE_WORDS
        ), f"mount state {state} has no CLI wording"


def test_every_error_the_page_words_is_worded_by_status():
    for code in words_block("errors"):
        worded = status_cli.word_error({"code": code, "params": {}})

        assert worded not in ("", code), f"error {code} has no CLI wording"


def test_every_unbind_cause_the_page_words_is_worded_by_status():
    for cause in words_block("causes"):
        assert (
            cause in status_cli.UNBIND_CAUSE_WORDS
        ), f"cause {cause} has no CLI wording"


def test_a_code_outside_the_table_prints_as_itself():
    assert wording.word_code("some_future_code", {}) == "some_future_code"


def test_a_state_outside_the_table_reads_as_unknown():
    assert wording.word_state("some_future_state") == wording.CLI_STATE_WORDS["unknown"]
