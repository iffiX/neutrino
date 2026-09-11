"""``nclient gui``: the resident, walked as the person invokes it.

One process binds the socket, starts the session and the socket server, and
runs the window on the main thread; when the loop ends everything shuts
down. The tray's Quit reaches the session, and so does every signal that
means this process is ending. The window's own show is what a second
invocation's ask lands on. That second invocation finds the socket held,
asks the running one to show its window, and exits 0. Refusals are the
wording tables' own.
"""

import signal

import pytest

import neutrino_client.cli.gui as gui_cli
from neutrino_client.cli import wording
from neutrino_client.control import client
from neutrino_client.control.server import ControlServer
from neutrino_client.exceptions import (
    ControlSocketUnavailableError,
    GuiShellUnavailableError,
)
from tests.conftest import FakeClientPlatform, FakeSession, discard


class FakeSessionFactory:
    """Stands in for ``ClientSession``, remembering the one it made."""

    def __init__(self):
        self.made = []

    def __call__(self, *, platform, log=print):
        session = FakeSession(platform=platform)
        session.started = 0
        session.shutdowns = 0
        session.start = lambda: setattr(session, "started", session.started + 1)
        session.shutdown = lambda: setattr(session, "shutdowns", session.shutdowns + 1)
        self.made.append(session)
        return session


@pytest.fixture
def platform(monkeypatch):
    platform = FakeClientPlatform()
    monkeypatch.setattr(gui_cli, "detect_platform", lambda: platform)
    return platform


@pytest.fixture
def sessions(monkeypatch):
    factory = FakeSessionFactory()
    monkeypatch.setattr(gui_cli, "ClientSession", factory)
    return factory


def test_a_platform_without_a_socket_is_refused(monkeypatch, capsys):
    class NoSocketPlatform(FakeClientPlatform):
        def control_socket_path(self):
            raise ControlSocketUnavailableError("none")

    monkeypatch.setattr(gui_cli, "detect_platform", NoSocketPlatform)

    assert gui_cli.main() == 1
    assert wording.word_code("control_socket_unavailable") in capsys.readouterr().err


def test_the_resident_binds_starts_serves_and_shows_the_window(
    platform, sessions, monkeypatch
):
    opened = []

    def fake_shell(*, os_name, title, html, bridge, icon_path, **rest):
        status, _state = client.request(
            socket_path=platform.control_socket_path(), method="GET", path="/api/state"
        )
        reply = bridge.handle({"id": 1, "method": "GET", "path": "/api/state"})
        opened.append({"os_name": os_name, "title": title, "html": html})
        opened[-1]["socket"] = status
        opened[-1]["reply"] = reply

    monkeypatch.setattr(gui_cli, "open_shell_window", fake_shell)

    assert gui_cli.main() == 0

    (session,) = sessions.made
    window = opened[0]
    assert window["os_name"] == "linux"
    assert window["title"] == "Neutrino client"
    assert "const CATALOGS" in window["html"]
    assert '"ui.tray.open"' in window["html"]
    assert window["socket"] == 200
    assert window["reply"]["body"]["hostname"] == "box"
    assert session.started == 1
    assert session.shutdowns == 1


def test_quit_shuts_the_resident_down_before_the_loop_ends(
    platform, sessions, monkeypatch
):
    order = []

    def fake_shell(*, on_quit, on_show_ready, **rest):
        on_quit()
        order.append("quit")

    monkeypatch.setattr(gui_cli, "open_shell_window", fake_shell)

    assert gui_cli.main() == 0

    (session,) = sessions.made
    assert order == ["quit"]
    assert session.shutdowns >= 1


def test_the_window_registers_the_show_the_resident_hands_asks_to(
    platform, sessions, monkeypatch
):
    shown = []

    def show() -> None:
        shown.append(1)

    def fake_shell(*, on_show_ready, **rest):
        on_show_ready(show)

    monkeypatch.setattr(gui_cli, "open_shell_window", fake_shell)

    assert gui_cli.main() == 0

    (session,) = sessions.made
    session.on_show()
    assert shown == [1]


def test_hidden_reaches_the_shell(platform, sessions, monkeypatch):
    asked = []

    def fake_shell(*, is_hidden, **rest):
        asked.append(is_hidden)

    monkeypatch.setattr(gui_cli, "open_shell_window", fake_shell)

    assert gui_cli.main(is_hidden=True) == 0
    assert gui_cli.main() == 0

    assert asked == [True, False]


def test_a_second_invocation_posts_show_and_exits(platform, sessions, monkeypatch):
    running = FakeSession()
    server = ControlServer(
        session=running,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    monkeypatch.setattr(
        gui_cli, "open_shell_window", lambda **kwargs: pytest.fail("no window")
    )
    try:
        assert gui_cli.main() == 0
    finally:
        server.stop()

    assert running.shows == 1
    assert all(session.started == 0 for session in sessions.made)


def test_a_held_socket_that_answers_nobody_is_worded(
    platform, sessions, monkeypatch, capsys
):
    running = FakeSession()
    platform.peer = {"account": "bob", "uid": 1001, "is_same_user": False}
    server = ControlServer(
        session=running,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    try:
        assert gui_cli.main() == 1
    finally:
        server.stop()

    assert running.shows == 0
    assert wording.word_code("control_socket_unavailable") in capsys.readouterr().err


def test_a_missing_shell_prints_the_wording_that_names_the_package(
    platform, sessions, monkeypatch, capsys
):
    def refuse(**kwargs):
        raise GuiShellUnavailableError(
            "gui_webkitgtk_missing", {"packages": "gir1.2-webkit2-4.1"}
        )

    monkeypatch.setattr(gui_cli, "open_shell_window", refuse)

    assert gui_cli.main() == 1

    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err.strip().splitlines()[-1] == wording.word_code(
        "gui_webkitgtk_missing", {"packages": "gir1.2-webkit2-4.1"}
    )
    assert sessions.made[0].shutdowns == 1


def test_the_socket_is_released_when_the_window_closes(platform, sessions, monkeypatch):
    monkeypatch.setattr(gui_cli, "open_shell_window", lambda **kwargs: None)

    assert gui_cli.main() == 0

    with pytest.raises(OSError):
        client.request(
            socket_path=platform.control_socket_path(), method="GET", path="/api/state"
        )


def test_hidden_is_accepted_and_starts_the_resident(platform, sessions, monkeypatch):
    monkeypatch.setattr(gui_cli, "open_shell_window", lambda **kwargs: None)

    assert gui_cli.main(is_hidden=True) == 0
    assert sessions.made[0].started == 1


def test_nothing_is_printed_for_a_person_to_copy(
    platform, sessions, monkeypatch, capsys
):
    monkeypatch.setattr(gui_cli, "open_shell_window", lambda **kwargs: None)

    gui_cli.main()

    streams = capsys.readouterr()
    assert streams.out == ""
    # The resident's own log goes to stderr and names no link or token.
    assert "neutrino://" not in streams.err
    assert "token" not in streams.err


class FakeControlServer:
    """A control server that only remembers being stopped."""

    def __init__(self):
        self.stops = 0

    def stop(self) -> None:
        self.stops += 1


def test_a_signal_shuts_the_resident_down_and_ends_the_process(monkeypatch):
    """A terminal, an installer and a logout each send one of these."""
    installed = {}
    monkeypatch.setattr(
        gui_cli.signal,
        "signal",
        lambda number, handler: installed.setdefault(number, handler),
    )
    ended = []
    monkeypatch.setattr(gui_cli, "end_process", lambda: ended.append(1))
    session = FakeSession()
    server = FakeControlServer()

    gui_cli._install_quit_signals(session, server)
    installed[signal.SIGTERM](signal.SIGTERM, None)

    assert set(installed) >= {signal.SIGTERM, signal.SIGINT}
    assert session.shutdowns == 1
    assert server.stops == 1
    assert ended == [1]


def test_the_resident_installs_them_as_it_starts(platform, sessions, monkeypatch):
    installed = []
    monkeypatch.setattr(
        gui_cli.signal, "signal", lambda number, handler: installed.append(number)
    )
    monkeypatch.setattr(gui_cli, "open_shell_window", lambda **kwargs: None)

    assert gui_cli.main() == 0

    assert signal.SIGTERM in installed


def test_a_signal_a_thread_may_not_take_is_no_reason_to_refuse(monkeypatch):
    def refuse(number, handler):
        raise ValueError("signal only works in main thread")

    monkeypatch.setattr(gui_cli.signal, "signal", refuse)

    gui_cli._install_quit_signals(FakeSession(), FakeControlServer())


def test_the_windows_resident_ends_its_process_after_the_cleanup(monkeypatch):
    """.NET threads and the browser's helpers do not answer to this one."""
    monkeypatch.setattr(gui_cli.os, "name", "nt")
    ended = []
    monkeypatch.setattr(gui_cli.os, "_exit", lambda status: ended.append(status))

    gui_cli._end(3)

    assert ended == [3]


def test_elsewhere_the_resident_just_returns(monkeypatch):
    monkeypatch.setattr(gui_cli.os, "name", "posix")
    monkeypatch.setattr(
        gui_cli.os, "_exit", lambda status: pytest.fail("the process was killed")
    )

    assert gui_cli._end(0) == 0


def test_the_window_is_pushed_the_state_after_every_change(
    platform, sessions, monkeypatch
):
    pushed = []

    def fake_shell(*, on_push_ready, **rest):
        on_push_ready(pushed.append)

    monkeypatch.setattr(gui_cli, "open_shell_window", fake_shell)

    assert gui_cli.main() == 0

    (session,) = sessions.made
    (watcher,) = session.watchers
    watcher()
    assert pushed[0]["hostname"] == session.hostname()
    assert "services" in pushed[0]


def test_the_resident_writes_its_lines_to_a_file_and_turns_it(tmp_path):
    path = tmp_path / "logs" / "client.log"
    log = gui_cli.ResidentLog(path=str(path))

    log("starting")
    log("still here")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [line.split(" ", 1)[1] for line in lines] == ["starting", "still here"]

    path.write_text("x" * gui_cli.CLIENT_LOG_KEEP_BYTES, encoding="utf-8")
    log("after the turn")

    assert (tmp_path / "logs" / "client.log.1").stat().st_size == (
        gui_cli.CLIENT_LOG_KEEP_BYTES
    )
    assert path.read_text(encoding="utf-8").endswith("after the turn\n")


def test_the_log_lives_beside_the_state(platform, sessions, monkeypatch):
    seen = []
    monkeypatch.setattr(gui_cli, "open_shell_window", lambda **kwargs: None)
    monkeypatch.setattr(
        gui_cli, "ResidentLog", lambda *, path: seen.append(path) or print
    )

    assert gui_cli.main() == 0

    assert seen[0].endswith("client.log")
