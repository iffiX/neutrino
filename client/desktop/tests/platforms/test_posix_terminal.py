"""This process's terminal in raw mode on Linux and macOS.

Driven on a real pseudo-terminal pair: entering clears canonical input and
echo, leaving puts the saved mode back, and a non-terminal is refused.
"""

import os
import pty
import signal
import termios

import pytest

from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.posix_terminal import PosixRawTerminal


@pytest.fixture
def pair():
    main, side = pty.openpty()
    yield main, side
    os.close(main)
    os.close(side)


def test_raw_mode_is_set_inside_and_put_back_after(pair):
    _main, side = pair
    before = termios.tcgetattr(side)

    with PosixRawTerminal(stdin_fd=side, stdout_fd=side):
        inside = termios.tcgetattr(side)
        assert not inside[3] & termios.ICANON
        assert not inside[3] & termios.ECHO

    assert termios.tcgetattr(side) == before


def test_bytes_go_both_ways(pair):
    main, side = pair

    with PosixRawTerminal(stdin_fd=side, stdout_fd=side) as term:
        os.write(main, b"\x03")
        assert term.read() == b"\x03"
        term.write(b"out")
        assert os.read(main, 16) == b"out"


def test_a_resize_reaches_the_callback_and_the_handler_is_put_back(pair):
    _main, side = pair
    seen = []
    before = signal.getsignal(signal.SIGWINCH)

    with PosixRawTerminal(stdin_fd=side, stdout_fd=side) as term:
        term.on_resize(lambda cols, rows: seen.append((cols, rows)))
        os.kill(os.getpid(), signal.SIGWINCH)

    assert len(seen) == 1
    assert signal.getsignal(signal.SIGWINCH) == before


def test_a_file_that_is_no_terminal_is_refused(tmp_path):
    with open(tmp_path / "f", "w+") as stream:
        with pytest.raises(PlatformUnsupportedError):
            with PosixRawTerminal(stdin_fd=stream.fileno(), stdout_fd=stream.fileno()):
                pass
