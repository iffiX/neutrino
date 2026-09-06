"""``nagent`` entry: the Windows console is switched to UTF-8.

The status output carries em-dashes and arrows; the Windows console default
mangles them, so the entry reconfigures the streams before anything prints.
Other platforms are left untouched.
"""

from neutrino_agent.cli import entry


class FakeStream:
    """A stream that only remembers how it was reconfigured."""

    def __init__(self):
        self.reconfigured = None

    def reconfigure(self, *, encoding, errors):
        self.reconfigured = (encoding, errors)


def test_the_windows_console_is_switched_to_utf8(monkeypatch):
    out, err = FakeStream(), FakeStream()
    monkeypatch.setattr(entry.os, "name", "nt")
    monkeypatch.setattr(entry.sys, "stdout", out)
    monkeypatch.setattr(entry.sys, "stderr", err)

    entry._use_utf8_console()

    assert out.reconfigured == ("utf-8", "replace")
    assert err.reconfigured == ("utf-8", "replace")


def test_other_platforms_leave_the_console_alone(monkeypatch):
    out = FakeStream()
    monkeypatch.setattr(entry.os, "name", "posix")
    monkeypatch.setattr(entry.sys, "stdout", out)

    entry._use_utf8_console()

    assert out.reconfigured is None


def test_a_stream_without_reconfigure_is_left_alone(monkeypatch):
    monkeypatch.setattr(entry.os, "name", "nt")
    monkeypatch.setattr(entry.sys, "stdout", object())
    monkeypatch.setattr(entry.sys, "stderr", object())

    entry._use_utf8_console()
