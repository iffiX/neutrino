"""The command line's words, in both languages, held to the client's codes.

Every code the client emits, every code the page's catalog words, every
state token and every mount state has words in English and in Chinese on
this surface; the language is the store's, else the machine's own. The one
hub a command acts on is named by its name, its id, its binding or its
number in ``hub list``; a name that matches nothing prints the names there
are. A password is asked without echo at a terminal and read from a pipe
otherwise, never from the command line.
"""

import json

import pytest

from neutrino_client.cli import wording
from neutrino_client.constants import CLIENT_LANGUAGES
from tests.control.test_page import (
    ATTACH_RENDERED_STATES,
    DETAIL_FALLBACK_CODES,
    MOUNT_BUSY_STATES,
    catalog_keys,
    emitted_codes,
)

# The codes 0.6.0 adds that reach the command line (ui_text.md).
NEW_CODES = (
    "client_not_running",
    "control_unavailable",
    "terminal_account_missing",
    "account_not_enabled",
    "key_missing",
    "hub_untrusted",
    "hub_key_missing",
    "port_taken",
    "permission_denied",
    "agent_offline",
)


@pytest.fixture(params=CLIENT_LANGUAGES)
def language(request):
    wording.fix_language(request.param)
    yield request.param
    wording.fix_language("")


def test_both_languages_word_the_same_codes():
    tables = wording.CLIENT_CODE_WORDS

    assert set(tables) == set(CLIENT_LANGUAGES)
    assert set(tables["en"]) == set(tables["zh-CN"])


def test_both_languages_carry_the_same_lines_and_states():
    for tables in (
        wording.CLIENT_LINES,
        wording.CLIENT_STATE_WORDS,
        wording.CLIENT_MOUNT_STATE_WORDS,
    ):
        assert set(tables["en"]) == set(tables["zh-CN"])


def test_every_code_the_catalogs_word_has_words_in_each_language(language):
    for code in catalog_keys("code."):
        assert wording.CLIENT_CODE_WORDS[language].get(code), code


def test_every_emitted_code_has_words_in_each_language(language):
    for code in emitted_codes() - DETAIL_FALLBACK_CODES:
        assert wording.CLIENT_CODE_WORDS[language].get(code), code


def test_the_new_codes_of_0_6_have_words_in_each_language(language):
    for code in NEW_CODES:
        assert wording.CLIENT_CODE_WORDS[language].get(code), code


def test_the_three_refusals_say_what_the_standard_says():
    assert (
        wording.word_code("permission_denied", {"kind": "ssh"})
        == "the hub gives this client no ssh permission"
    )
    assert wording.word_code("agent_offline", {"device": "lab-gpu"}) == (
        "lab-gpu is offline"
    )
    assert wording.word_code("client_not_running") == (
        "The client is not running; start it with nclient gui."
    )


def test_the_chinese_refusals_are_the_help_pages_own(chinese):
    assert wording.word_code("permission_denied", {"kind": "ssh"}) == (
        "中枢没有给这个客户端 ssh 权限"
    )
    assert wording.word_code("agent_offline", {"device": "lab-gpu"}) == "lab-gpu 不在线"
    assert wording.word_code("client_not_running") == "客户端没有运行，先 nclient gui。"


def test_the_detail_codes_are_the_pages_own():
    assert set(wording.CLIENT_DETAIL_CODES) == set(DETAIL_FALLBACK_CODES)
    for code in wording.CLIENT_DETAIL_CODES:
        assert wording.word_code(code, {"detail": "its own words"}) == "its own words"


def test_every_state_the_catalogs_word_has_words(language):
    for state in catalog_keys("state."):
        assert state in wording.CLIENT_STATE_WORDS[language], state


def test_every_mount_record_state_has_words(language):
    for state in set(MOUNT_BUSY_STATES) | ATTACH_RENDERED_STATES:
        assert wording.word_mount_state(state), state


def test_a_code_outside_the_table_prints_as_itself():
    assert wording.word_code("some_future_code", {}) == "some_future_code"


def test_a_state_outside_the_table_reads_as_unknown():
    assert wording.word_state("x") == wording.CLIENT_STATE_WORDS["en"]["unknown"]


def test_an_unreachable_hub_prints_its_own_detail():
    assert wording.word_code("hub_unreachable", {"detail": "no route"}) == "no route"
    assert wording.word_code("hub_unreachable", {}) == "the hub cannot be reached"


def test_the_language_is_the_stores_else_the_machines(tmp_path, monkeypatch):
    class Platform:
        def config_dir(self):
            return str(tmp_path)

        def system_language(self):
            return "zh-CN"

    monkeypatch.setattr(wording, "detect_platform", Platform)
    assert wording.language() == "zh-CN"

    (tmp_path / "state.json").write_text(json.dumps({"language": "en"}))
    assert wording.language() == "en"


def test_a_language_the_client_does_not_offer_reads_as_english(monkeypatch, tmp_path):
    class Platform:
        def config_dir(self):
            return str(tmp_path)

        def system_language(self):
            return "fr"

    monkeypatch.setattr(wording, "detect_platform", Platform)
    assert wording.language() == "en"


def test_the_windows_console_takes_plain_dots(monkeypatch):
    monkeypatch.setattr(wording, "CLIENT_IS_WINDOWS_CONSOLE", True)
    assert wording.console_text("Connected · LAN… ") == "Connected - LAN... "


# --- the one hub a command acts on ---

HOME = {"hub_id": "h1", "hub_name": "home", "binding_id": "c1"}
OFFICE = {"hub_id": "h2", "hub_name": "", "gateway_url": "tcp://office.lan:8443"}


def test_one_hub_joined_is_the_one_a_command_acts_on():
    assert wording.choose_hub([HOME], "") == HOME


def test_several_hubs_and_no_name_are_refused_with_their_names(capsys):
    assert wording.choose_hub([HOME, OFFICE], "") is None

    names = "home, tcp://office.lan:8443"
    assert wording.word_code("ambiguous_hub", {"hubs": names}) in (
        capsys.readouterr().err
    )


def test_a_hub_is_named_by_name_id_binding_or_number(capsys):
    for needle in ("home", "h1", "c1", "1"):
        assert wording.choose_hub([HOME, OFFICE], needle) == HOME
    assert wording.choose_hub([HOME, OFFICE], "2") == OFFICE
    assert capsys.readouterr().err == ""


def test_a_name_nobody_joined_prints_the_hubs_there_are(capsys):
    assert wording.choose_hub([HOME, OFFICE], "nowhere") is None

    err = capsys.readouterr().err
    assert "nowhere" in err and "home" in err


def test_no_hub_joined_is_said_plainly(capsys):
    assert wording.choose_hub([], "home") is None

    assert wording.line("not_joined") in capsys.readouterr().err


def test_nothing_answering_is_client_not_running(monkeypatch, capsys, tmp_path):
    class Away:
        def control_socket_path(self):
            return str(tmp_path / "nothing.sock")

        def config_dir(self):
            return str(tmp_path)

        def system_language(self):
            return "en"

    monkeypatch.setattr(wording, "detect_platform", Away)

    assert wording.read_state() is None
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")


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

    assert wording.ask_secret("Password: ") == "hunter2"


def test_a_terminal_is_asked_without_echo(monkeypatch):
    prompts = []
    monkeypatch.setattr(wording.sys, "stdin", _Terminal())
    monkeypatch.setattr(
        wording.getpass, "getpass", lambda prompt: prompts.append(prompt) or "typed"
    )

    assert wording.ask_secret("Password: ") == "typed"
    assert prompts == ["Password: "]


def test_a_question_with_no_terminal_says_how_to_go_ahead(monkeypatch, capsys):
    monkeypatch.setattr(wording.sys, "stdin", _Piped("y\n"))

    assert wording.is_confirmed("leave? [y/N] ") is False
    assert "--yes" in capsys.readouterr().err


# --- who holds the machine ---


def test_the_hold_is_asked_of_the_easytier_daemon(monkeypatch):
    from tests.conftest import REAL_ASK_HOLD

    asked = []

    class Platform:
        def easytier_daemon_address(self):
            return "/run/neutrino/client/easytier.sock"

    def ask(address, request, *, timeout_s):
        asked.append((address, request, timeout_s))
        return {"code": "client_held", "params": {"account": "lab"}}

    monkeypatch.setattr(wording, "ask_hold", REAL_ASK_HOLD)
    monkeypatch.setattr(wording, "detect_platform", Platform)
    monkeypatch.setattr(wording, "ask_easytier_daemon", ask)

    assert wording.hold_machine() == "lab"
    assert asked == [("/run/neutrino/client/easytier.sock", {"verb": "hold"}, 2)]


def test_no_daemon_holds_nothing_and_names_nobody(monkeypatch):
    from tests.conftest import REAL_ASK_HOLD

    class Platform:
        def easytier_daemon_address(self):
            return "/nowhere/easytier.sock"

    def ask(address, request, *, timeout_s):
        raise FileNotFoundError(address)

    monkeypatch.setattr(wording, "ask_hold", REAL_ASK_HOLD)
    monkeypatch.setattr(wording, "detect_platform", Platform)
    monkeypatch.setattr(wording, "ask_easytier_daemon", ask)

    assert wording.hold_machine() == ""
    assert wording.other_holder() == ""


def test_the_holder_is_another_only_when_the_daemon_says_so(monkeypatch):
    monkeypatch.setattr(
        wording, "ask_hold", lambda verb: {"holder": "lab", "is_holder": True}
    )
    assert wording.other_holder() == ""

    monkeypatch.setattr(
        wording, "ask_hold", lambda verb: {"holder": "lab", "is_holder": False}
    )
    assert wording.other_holder() == "lab"
