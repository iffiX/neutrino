"""Waiting for a browser, and the two ways of not waiting any longer.

The screen has to end in exactly one of three ways: the browser answered, the
Continue prompt was answered, or there is no keyboard at all — and the last
one is the one that spins if it is treated as the second.
"""

import io

from neutrino_hub.cli import wizard

URLS = ["http://192.168.8.1:8080"]


def test_it_returns_as_soon_as_the_browser_answers(monkeypatch):
    monkeypatch.setattr(wizard, "_is_terminal_wanted", lambda: False)
    answers = iter([False, False, True])

    assert wizard.offer_browser(urls=URLS, token="t0ken", arrived=lambda: next(answers))


def test_answering_the_prompt_asks_here_instead(monkeypatch):
    monkeypatch.setattr(wizard, "_is_terminal_wanted", lambda: True)

    assert not wizard.offer_browser(urls=URLS, token="t0ken", arrived=lambda: False)


def test_a_closed_input_keeps_waiting_rather_than_spinning(monkeypatch):
    """Nothing is at the keyboard, so there is nobody to press Enter — and
    watching a stream that is at end of file only burns a core."""
    reads = []

    def _at_end_of_file():
        reads.append(1)
        return None

    monkeypatch.setattr(wizard, "_is_terminal_wanted", _at_end_of_file)
    answers = iter([False, False, False, True])

    assert wizard.offer_browser(urls=URLS, token="t0ken", arrived=lambda: next(answers))
    assert len(reads) == 1


def test_end_of_input_is_told_apart_from_a_line(monkeypatch):
    monkeypatch.setattr(wizard.sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(
        wizard.select, "select", lambda *_: ([wizard.sys.stdin], [], [])
    )

    assert wizard._is_terminal_wanted() is None

    monkeypatch.setattr(wizard.sys, "stdin", io.StringIO("\n"))
    assert wizard._is_terminal_wanted() is True
