"""The CLI's word tables, held to the page's own code list.

The page and the terminal each word the client's typed codes in their own
register; what they share is the list of codes, never the strings. Every
code, state and cause the catalogs carry must have a wording on the
terminal surface too, and every code the terminal words must be in the
catalogs, so the two surfaces agree on one code set.
"""

from neutrino_client.cli import wording
from tests.control.test_page import (
    ATTACH_RENDERED_STATES,
    DETAIL_FALLBACK_CODES,
    MOUNT_BUSY_STATES,
    catalog_keys,
    emitted_codes,
)


def test_every_code_the_catalogs_word_has_cli_words():
    for code in catalog_keys("code."):
        worded = wording.word_code(code, {})

        assert worded not in ("", code), f"code {code} has no CLI wording"


def test_every_code_the_cli_words_is_in_the_catalogs():
    missing = set(wording.CLIENT_CODE_WORDS) - catalog_keys("code.")

    assert missing == set(), f"codes the catalogs do not carry: {sorted(missing)}"


def test_every_emitted_code_has_cli_words():
    for code in emitted_codes() - DETAIL_FALLBACK_CODES:
        worded = wording.word_code(code, {})

        assert worded not in ("", code), f"code {code} has no CLI wording"


def test_the_detail_codes_are_the_pages_own():
    assert set(wording.CLIENT_DETAIL_CODES) == set(DETAIL_FALLBACK_CODES)

    for code in wording.CLIENT_DETAIL_CODES:
        assert wording.word_code(code, {"detail": "its own words"}) == "its own words"


def test_every_state_the_catalogs_word_has_cli_words():
    for state in catalog_keys("state."):
        assert state in wording.CLIENT_STATE_WORDS, f"state {state} has no CLI wording"


def test_every_mount_record_state_has_cli_words():
    for state in set(MOUNT_BUSY_STATES) | ATTACH_RENDERED_STATES:
        assert (
            state in wording.CLIENT_MOUNT_STATE_WORDS
        ), f"mount state {state} has no CLI wording"


def test_every_unbind_cause_the_catalogs_word_is_worded():
    for cause in catalog_keys("cause."):
        assert cause in wording.CLIENT_UNBIND_CAUSE_WORDS, f"cause {cause} has no words"
        worded = wording.word_code("self_unbound", {"cause": cause})
        assert wording.CLIENT_UNBIND_CAUSE_WORDS[cause] in worded


def test_the_new_codes_of_the_client_are_worded():
    for code in (
        "bundle_missing",
        "mount_not_authorized",
        "control_peer_refused",
        "resident_not_running",
        "link_not_for_client",
        "control_socket_unavailable",
    ):
        assert wording.word_code(code, {}) not in ("", code)


def test_a_code_outside_the_table_prints_as_itself():
    assert wording.word_code("some_future_code", {}) == "some_future_code"


def test_a_state_outside_the_table_reads_as_unknown():
    assert (
        wording.word_state("some_future_state") == wording.CLIENT_STATE_WORDS["unknown"]
    )


def test_an_unreachable_hub_prints_its_own_detail():
    assert wording.word_code("hub_unreachable", {"detail": "no route"}) == "no route"
    assert wording.word_code("hub_unreachable", {}) == "the hub cannot be reached"


# --- a password the person gives, never the command line ---


class _Piped:
    def __init__(self, text: str):
        self.text = text

    def isatty(self) -> bool:
        return False

    def readline(self) -> str:
        return self.text


class _Terminal:
    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        raise AssertionError("a terminal is asked without echo, never read")


def test_a_piped_secret_is_one_line_of_stdin(monkeypatch):
    monkeypatch.setattr(wording.sys, "stdin", _Piped("hunter2\r\n"))
    monkeypatch.setattr(wording.getpass, "getpass", lambda prompt: "never")

    assert wording.ask_secret("Share password: ") == "hunter2"


def test_a_terminal_is_asked_without_echo(monkeypatch):
    prompts = []
    monkeypatch.setattr(wording.sys, "stdin", _Terminal())
    monkeypatch.setattr(
        wording.getpass, "getpass", lambda prompt: prompts.append(prompt) or "typed"
    )

    assert wording.ask_secret("Share password: ") == "typed"
    assert prompts == ["Share password: "]
