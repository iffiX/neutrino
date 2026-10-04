"""The last lines of a log file, read from its end.

What these pin: the lines come oldest first, capped, blank lines dropped; a
needle keeps only the lines that hold it and reads further back than a
plain tail; a file longer than the read starts at its first whole line; a
file another handle holds open for writing reads; a file that cannot be
read is an OSError. The mask hides a token in a URL's query and a token on
a line of its own, and leaves every other line as it was.
"""

import pytest

import neutrino_agent.modules.log_tail as log_tail_module
from neutrino_agent.modules.log_tail import file_tail, mask_secrets


def test_the_last_lines_come_oldest_first(tmp_path):
    log = tmp_path / "agent.log"
    log.write_text("one\n\ntwo\nthree\n", encoding="utf-8")

    assert file_tail(str(log), 2) == ["two", "three"]
    assert file_tail(str(log), 10) == ["one", "two", "three"]


def test_a_needle_keeps_only_the_lines_that_hold_it(tmp_path):
    log = tmp_path / "agent.log"
    log.write_text(
        "10:00 samba: created share media\n"
        "10:01 vscode: unchanged\n"
        "10:02 samba validate refused: share_path_relative\n",
        encoding="utf-8",
    )

    assert file_tail(str(log), 10, needle="samba") == [
        "10:00 samba: created share media",
        "10:02 samba validate refused: share_path_relative",
    ]


def test_a_long_file_is_read_from_its_end_at_a_whole_line(tmp_path, monkeypatch):
    monkeypatch.setattr(log_tail_module, "AGENT_MODULE_LOG_TAIL_BYTES", 12)
    log = tmp_path / "agent.log"
    log.write_text("first line\nsecond\nthird\n", encoding="utf-8")

    assert file_tail(str(log), 10) == ["third"]


def test_a_needle_reads_past_the_plain_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(log_tail_module, "AGENT_MODULE_LOG_TAIL_BYTES", 20)
    log = tmp_path / "agent.log"
    log.write_text(
        "10:00 samba: unchanged\n" + "10:01 report sent\n" * 20, encoding="utf-8"
    )

    assert file_tail(str(log), 10) == ["10:01 report sent"]
    assert file_tail(str(log), 10, needle="samba") == ["10:00 samba: unchanged"]


def test_a_file_held_open_for_writing_reads(tmp_path):
    path = tmp_path / "agent.log"
    with open(path, "a", encoding="utf-8") as writer:
        writer.write("10:00 samba: unchanged\n")
        writer.flush()

        assert file_tail(str(path), 10, needle="samba") == ["10:00 samba: unchanged"]


def test_a_missing_file_is_an_os_error(tmp_path):
    with pytest.raises(OSError):
        file_tail(str(tmp_path / "absent.log"), 10)


# --- the mask ---

TOKEN = "zZ2Z4CWHAnCH_qiBdPeGKRIh_NoaXewv"  # scan: allow


def test_a_token_in_a_url_is_masked():
    line = f"lab: Web UI available at http://0.0.0.0:8000?tkn={TOKEN}"

    assert mask_secrets(line) == "lab: Web UI available at http://0.0.0.0:8000?tkn=***"


def test_a_token_in_a_query_with_more_after_it_is_masked_alone():
    assert mask_secrets("open http://h:3001/?token=abc&x=1 now") == (
        "open http://h:3001/?token=***&x=1 now"
    )


def test_a_token_on_a_line_of_its_own_is_masked_after_its_prefix():
    text = f"lab: starting\nlab: {TOKEN}\n{TOKEN}\n"

    assert mask_secrets(text) == "lab: starting\nlab: ***\n***\n"


def test_a_line_that_is_more_than_one_word_is_left_as_it_was():
    lines = [
        "lab: [2026-10-04 07:46:42] info Downloading server "
        "07f806f999227108933c2e30515b24eecc1fda74",  # scan: allow
        "2026-10-04 15:18:45,296 vscode: registered the server of lab",
        "lab: * the Visual Studio Code Server License Terms",
        "lab: abcdefghijklmnopqrstuvwxyz",
    ]

    assert mask_secrets("\n".join(lines)) == "\n".join(lines)
