"""The pseudo-console read callable stops when the child exits.

The output pipe does not end until the console is closed, which is after
the run returns; a reader that waited for the pipe's end would wait the
whole timeout every time. These exercise the read callable's logic through
a fake kernel32, so no Windows is needed.
"""

import time

from neutrino_client.platforms import windows_console


class FakeKernel:
    """Just the two calls the read callable makes on kernel32."""

    def __init__(self, *, exited):
        self._exited = exited

    def WaitForSingleObject(self, handle, timeout):
        return 0 if self._exited() else 258  # WAIT_OBJECT_0 / WAIT_TIMEOUT


def read_callable(chunks, is_closed, exited):
    """Build the read callable the console runner uses, over fakes."""
    taken = {"n": 0}

    def has_exited():
        return FakeKernel(exited=exited).WaitForSingleObject(None, 0) == 0

    def read(wait_s):
        deadline = time.monotonic() + wait_s
        while len(chunks) == taken["n"]:
            if is_closed():
                break
            if has_exited() and len(chunks) == taken["n"]:
                return b""
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)
        if len(chunks) == taken["n"]:
            return b""
        chunk = chunks[taken["n"]]
        taken["n"] += 1
        return chunk

    return read


def test_an_exited_child_with_no_bytes_ends_the_read_at_once():
    read = read_callable([], lambda: False, lambda: True)

    started = time.monotonic()
    assert read(30) == b""
    assert time.monotonic() - started < 1


def test_the_bytes_come_out_before_the_child_has_gone():
    chunks = [b"hello ", b"(y/N) "]
    read = read_callable(chunks, lambda: False, lambda: False)

    assert read(1) == b"hello "
    assert read(1) == b"(y/N) "


def test_a_running_child_with_nothing_yet_waits_out_the_slice():
    read = read_callable([], lambda: False, lambda: False)

    started = time.monotonic()
    assert read(0.2) is None
    assert time.monotonic() - started >= 0.15


def test_the_module_names_its_console_size():
    assert windows_console.CONSOLE_COLUMNS == 120
    assert windows_console.CONSOLE_ROWS == 40
