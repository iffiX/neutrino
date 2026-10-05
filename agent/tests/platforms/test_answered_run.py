"""A program on a terminal of its own, its one question answered.

What these pin: the answer is typed once the prompt shows, through any
colour or cursor sequence around it, and never before; a program that asks
nothing is read to its end; a real program on a real pseudo-terminal gets
the answer and its exit code comes back; one that cannot start is 127.
"""

import sys
import time

import pytest

from neutrino_agent.platforms.answered_run import (
    answer_on_prompt,
    plain_text,
    run_on_pty,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminals")


def scripted(chunks):
    """A read that hands out chunks, then the end."""
    queue = list(chunks)

    def read(wait_s):
        return queue.pop(0) if queue else b""

    return read


def test_the_answer_follows_the_prompt_through_terminal_sequences():
    written = []
    read = scripted([b"Delete it? \x1b[1m(y/", b"N)\x1b[0m ", b"Deleted\r\n"])

    output = answer_on_prompt(
        read,
        written.append,
        prompt="(y/N)",
        answer="y\n",
        deadline=time.monotonic() + 5,
    )

    assert written == [b"y\n"]
    assert plain_text(output) == b"Delete it? (y/N) Deleted\r\n"


def test_a_program_that_asks_nothing_is_read_to_its_end_unanswered():
    written = []

    output = answer_on_prompt(
        scripted([b"nothing to ask\n"]),
        written.append,
        prompt="(y/N)",
        answer="y\n",
        deadline=time.monotonic() + 5,
    )

    assert written == [] and output == b"nothing to ask\n"


def test_a_real_program_on_a_pty_gets_its_answer():
    program = (
        "import sys\n"
        "assert sys.stdin.isatty()\n"
        "answer = input('Delete it? (y/N) ')\n"
        "print('answered', answer)\n"
        "sys.exit(0 if answer == 'y' else 5)\n"
    )

    code, output = run_on_pty(
        [sys.executable, "-c", program], prompt="(y/N)", answer="y\n", timeout_s=20
    )

    assert code == 0
    assert "answered y" in output


def test_a_program_that_cannot_start_is_127():
    assert run_on_pty(
        ["/nonexistent/program"], prompt="(y/N)", answer="y\n", timeout_s=5
    ) == (127, "")
