"""``nagent gui``: the handover, walked as the person invokes it.

The invoking process connects as whoever ran it, hands the connected
descriptor to a window process running as the desktop user, and prints
nothing for a person to copy. On Windows the invocation hosts the window
itself over per-request pipe connections. Refusals are the wording tables'
own lines: an agent that is not running, a platform without a socket, a
machine without its web view.
"""

import socket
import sys

import pytest

import neutrino_agent.cli.gui as gui_cli
from neutrino_agent.cli import wording
from neutrino_agent.constants import AGENT_CONTROL_PIPE_NAME
from neutrino_agent.control.server import ControlServer
from neutrino_agent.gui.channel import GuiFdChannel, GuiPipeChannel
from neutrino_agent.gui.shell import GuiShellUnavailableError
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from tests.conftest import ALICE, FakeControlAgent, FakeControlPlatform, discard


class FakeGuiPlatform(FakeControlPlatform):
    """The machine gui asks: one socket path, one os name."""

    def __init__(self, socket_path: str, os_name: str = "linux"):
        super().__init__()
        self._socket_path = socket_path
        self.os_name = os_name

    def control_socket_path(self) -> str:
        return self._socket_path


class FakeWindowProcess:
    """The spawned window process, remembered instead of run."""

    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.is_terminated = False

    def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.is_terminated = True


@pytest.fixture
def gui_stack(tmp_path, monkeypatch):
    """A live control server and the platform pointing gui at it."""
    platform = FakeGuiPlatform(str(tmp_path / "agent.sock"))
    server = ControlServer(
        agent=FakeControlAgent(),
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    server.start()
    assert server.socket_path
    monkeypatch.setattr(gui_cli, "detect_platform", lambda: platform)
    yield server, platform
    server.stop()


def test_a_platform_without_a_socket_is_refused(monkeypatch, capsys):
    class NoSocketPlatform(AgentPlatform):
        def control_socket_path(self):
            raise PlatformUnsupportedError("none")

    monkeypatch.setattr(gui_cli, "detect_platform", NoSocketPlatform)

    assert gui_cli.main() == 1
    assert wording.NO_CONTROL_SOCKET in capsys.readouterr().err


def test_a_stopped_agent_is_worded_not_guessed(tmp_path, monkeypatch, capsys):
    platform = FakeGuiPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(gui_cli, "detect_platform", lambda: platform)

    assert gui_cli.main() == 1
    assert gui_cli.GUI_NOT_RUNNING in capsys.readouterr().err


def test_the_invoker_connects_and_hands_the_descriptor_over(gui_stack, monkeypatch):
    _server, _platform = gui_stack
    spawned = []
    window = FakeWindowProcess(returncode=0)

    def fake_popen(command, *, pass_fds, **kwargs):
        spawned.append((list(command), tuple(pass_fds), kwargs))
        return window

    monkeypatch.setattr(gui_cli.subprocess, "Popen", fake_popen)

    assert gui_cli.main() == 0

    command, pass_fds, _kwargs = spawned[0]
    fd = int(command[-1])
    assert command[:5] == [
        sys.executable,
        "-m",
        "neutrino_agent.cli.entry",
        "gui",
        "--window-fd",
    ]
    assert pass_fds == (fd,)


def test_the_window_processes_exit_status_is_the_commands(gui_stack, monkeypatch):
    _server, _platform = gui_stack
    monkeypatch.setattr(
        gui_cli.subprocess,
        "Popen",
        lambda command, **kwargs: FakeWindowProcess(returncode=3),
    )

    assert gui_cli.main() == 3


def test_nothing_is_printed_for_a_person_to_copy(gui_stack, monkeypatch, capsys):
    _server, _platform = gui_stack
    monkeypatch.setattr(
        gui_cli.subprocess, "Popen", lambda command, **kwargs: FakeWindowProcess()
    )

    gui_cli.main()

    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == ""


def test_the_window_role_speaks_the_inherited_connection(gui_stack, monkeypatch):
    # The end of the handover: the window process rebuilds the channel from
    # the bare descriptor and the page answers in the opener's scope — the
    # peer the kernel read, never anything the page said.
    server, platform = gui_stack
    platform.peer = dict(ALICE)
    opened = []

    def fake_shell(*, os_name, title, html, bridge, icon_path):
        opened.append({"os_name": os_name, "title": title, "html": html})
        reply = bridge.handle(
            {
                "id": 1,
                "method": "POST",
                "path": "/api/services/ai",
                "body": {"targets": {"bob": True}, "account": "root"},
            }
        )
        opened[-1]["reply"] = reply

    monkeypatch.setattr(gui_cli, "open_shell_window", fake_shell)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(server.socket_path)

    assert gui_cli.main(window_fd=sock.detach()) == 0

    window = opened[0]
    assert window["os_name"] == "linux"
    assert window["title"] == "Neutrino agent"
    assert "const WORDS" in window["html"]
    assert window["reply"]["body"]["caller"]["account"] == "alice"


def test_a_missing_shell_prints_the_wording_that_names_the_package(
    gui_stack, monkeypatch, capsys
):
    server, _platform = gui_stack

    def refuse(**kwargs):
        raise GuiShellUnavailableError(
            "gui_webkitgtk_missing", {"packages": "gir1.2-webkit2-4.1"}
        )

    monkeypatch.setattr(gui_cli, "open_shell_window", refuse)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(server.socket_path)

    assert gui_cli.main(window_fd=sock.detach()) == 1

    err = capsys.readouterr().err
    assert "gir1.2-webkit2-4.1" in err
    assert err.strip() == wording.word_code(
        "gui_webkitgtk_missing", {"packages": "gir1.2-webkit2-4.1"}
    )


def test_windows_hosts_the_window_in_the_invocation(monkeypatch):
    # The one platform without the de-elevation handoff: the elevated
    # invocation hosts the window, and every request opens the pipe as the
    # invoker, whose identity the kernel reads each time.
    platform = FakeGuiPlatform(AGENT_CONTROL_PIPE_NAME, os_name="windows")
    monkeypatch.setattr(gui_cli, "detect_platform", lambda: platform)
    probes = []
    opened = []

    class FakePipeChannel:
        def __init__(self, *, pipe_name):
            self.pipe_name = pipe_name

        def request(self, *, method, path, body=None):
            probes.append((self.pipe_name, method, path))
            return 200, {"caller": {"account": "admin"}}

    def fake_shell(*, os_name, title, html, bridge, icon_path):
        opened.append(os_name)

    monkeypatch.setattr(gui_cli, "GuiPipeChannel", FakePipeChannel)
    monkeypatch.setattr(gui_cli, "open_shell_window", fake_shell)
    monkeypatch.setattr(
        gui_cli.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("windows spawns no window process"),
    )

    assert gui_cli.main() == 0

    assert probes == [(AGENT_CONTROL_PIPE_NAME, "GET", "/api/state")]
    assert opened == ["windows"]


def test_a_windows_agent_that_answers_nothing_is_worded(monkeypatch, capsys):
    platform = FakeGuiPlatform(AGENT_CONTROL_PIPE_NAME, os_name="windows")
    monkeypatch.setattr(gui_cli, "detect_platform", lambda: platform)

    class DeadPipeChannel:
        def __init__(self, *, pipe_name):
            pass

        def request(self, *, method, path, body=None):
            raise OSError("no pipe")

    monkeypatch.setattr(gui_cli, "GuiPipeChannel", DeadPipeChannel)

    assert gui_cli.main() == 1
    assert gui_cli.GUI_NOT_RUNNING in capsys.readouterr().err


def test_the_window_runs_as_the_invoker_without_sudo(monkeypatch):
    monkeypatch.setattr(gui_cli.os, "geteuid", lambda: 1000)
    monkeypatch.setenv("SUDO_USER", "")

    assert gui_cli.window_process_keywords() == {}


def test_under_sudo_the_window_steps_down_to_the_desktop_user(monkeypatch):
    import pwd

    entry = pwd.struct_passwd(
        ("alice", "x", 1000, 1000, "", "/home/alice", "/bin/bash")
    )
    monkeypatch.setattr(gui_cli.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: entry)
    monkeypatch.setattr(gui_cli.os, "getgrouplist", lambda name, gid: [1000, 27])
    monkeypatch.setattr(gui_cli.os.path, "isdir", lambda path: True)

    keywords = gui_cli.window_process_keywords()

    assert keywords["user"] == 1000
    assert keywords["group"] == 1000
    assert keywords["extra_groups"] == [1000, 27]
    assert keywords["env"]["HOME"] == "/home/alice"
    assert keywords["env"]["USER"] == "alice"
    assert keywords["env"]["XDG_RUNTIME_DIR"] == "/run/user/1000"


def test_a_missing_runtime_dir_is_dropped_not_pointed_at_roots(monkeypatch):
    import pwd

    entry = pwd.struct_passwd(
        ("alice", "x", 1000, 1000, "", "/home/alice", "/bin/bash")
    )
    monkeypatch.setattr(gui_cli.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/0")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: entry)
    monkeypatch.setattr(gui_cli.os, "getgrouplist", lambda name, gid: [1000])
    monkeypatch.setattr(gui_cli.os.path, "isdir", lambda path: False)

    keywords = gui_cli.window_process_keywords()

    assert "XDG_RUNTIME_DIR" not in keywords["env"]


def test_root_without_sudo_spawns_the_window_as_root(monkeypatch):
    monkeypatch.setattr(gui_cli.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", "root")

    assert gui_cli.window_process_keywords() == {}


def test_every_gui_shell_code_has_cli_words():
    from tests.control.test_page import GUI_ONLY_CODES

    for code in GUI_ONLY_CODES:
        worded = wording.word_code(code, {})

        assert worded not in ("", code), f"code {code} has no CLI wording"


def test_the_gui_channels_are_the_commands_own():
    # The POSIX handover rides the fd channel; Windows rides the pipe one.
    assert gui_cli.GuiFdChannel is GuiFdChannel
    assert gui_cli.GuiPipeChannel is GuiPipeChannel
