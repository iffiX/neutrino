"""The platform contract: honest refusals, the shared POSIX judgments.

A platform says what it has; invoking what it lacks answers a typed
refusal, never a guess. Every file operation is the standard library's own
in this process, with no step-down anywhere.
"""

import time
import inspect

import pytest

import neutrino_client.platforms.base as base_module
from neutrino_client.platforms.base import (
    ClientPlatform,
    ControlSocketUnavailableError,
    PlatformUnsupportedError,
)
from neutrino_client.platforms.linux import LinuxPlatform
from neutrino_client.platforms.windows import WindowsPlatform


def test_the_base_platform_refuses_what_it_does_not_have():
    platform = ClientPlatform()

    with pytest.raises(ControlSocketUnavailableError) as socket_refusal:
        platform.control_socket_path()
    assert socket_refusal.value.code == "control_socket_unavailable"
    assert isinstance(socket_refusal.value, PlatformUnsupportedError)
    for call in (
        lambda: platform.read_peer_identity(object()),
        lambda: platform.attach_share(
            share_url="//h/n", location="/p", credentials_path="/c"
        ),
        lambda: platform.detach_share(location="/p"),
        lambda: platform.is_share_attached(location="/p"),
    ):
        with pytest.raises(PlatformUnsupportedError) as caught:
            call()
        assert caught.value.code == "unsupported_platform"


def test_the_config_dir_is_redirected_by_the_suite_and_the_base_refuses_without():
    assert ClientPlatform().config_dir().endswith("config")


def test_the_posix_mount_location_judgment_wants_an_absolute_path():
    platform = ClientPlatform()

    assert platform.validate_mount_location(location="/mnt/media") is None
    for bad in ("", "nas/media", "Z:"):
        assert platform.validate_mount_location(location=bad) == {
            "code": "mountpoint_invalid",
            "params": {},
        }


def test_linux_shares_the_posix_mount_location_judgment():
    assert (
        LinuxPlatform.validate_mount_location is ClientPlatform.validate_mount_location
    )
    assert LinuxPlatform.prepare_mount_location is ClientPlatform.prepare_mount_location


def test_mount_locations_are_paths_except_windows_drive_letters():
    assert ClientPlatform.mount_location_shape == "path"
    assert LinuxPlatform.mount_location_shape == "path"
    assert WindowsPlatform.mount_location_shape == "drive_letter"


def test_the_posix_mount_preparation_wants_an_empty_directory(tmp_path):
    platform = ClientPlatform()
    full = tmp_path / "full"
    full.mkdir()
    (full / "kept").write_text("content")
    plain = tmp_path / "plain"
    plain.write_text("content")
    empty = tmp_path / "empty"
    empty.mkdir()
    fresh = tmp_path / "fresh"

    refusal = {"code": "mountpoint_not_empty", "params": {}}
    assert platform.prepare_mount_location(location=str(full)) == refusal
    assert platform.prepare_mount_location(location=str(plain)) == refusal
    assert platform.prepare_mount_location(location=str(empty)) is None
    assert platform.prepare_mount_location(location=str(fresh)) is None
    assert fresh.is_dir()


def test_directory_operations_are_plain_os_in_process(tmp_path):
    platform = ClientPlatform()
    root = tmp_path / "root"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "media").mkdir()
    (root / ".hidden").mkdir()
    (root / "file").write_text("")

    assert platform.list_directories(path=str(root)) == ["docs", "media"]
    platform.make_directory(path=str(root / "a" / "b"))
    assert (root / "a" / "b").is_dir()
    with pytest.raises(OSError):
        platform.list_directories(path=str(tmp_path / "missing"))


def test_share_credentials_are_written_0600_in_a_0700_directory(tmp_path):
    path = tmp_path / "creds" / "r1.credentials"

    ClientPlatform().write_share_credentials(
        credentials_path=str(path), username="media", password="s3cret"  # scan: allow
    )

    assert path.read_text() == "username=media\npassword=s3cret\n"  # scan: allow
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"


def test_the_browser_and_the_screen_are_the_platforms(monkeypatch):
    opened = []
    monkeypatch.setattr(base_module.webbrowser, "open", opened.append)
    spawned = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            spawned.append((list(argv), kwargs))

    monkeypatch.setattr(base_module.subprocess, "Popen", FakePopen)
    platform = ClientPlatform()

    platform.open_url("http://w/")
    platform.start_on_screen(["/r", "--connect", "h"])

    assert opened == ["http://w/"]
    assert spawned[0][0] == ["/r", "--connect", "h"]


def test_the_contract_carries_no_account_or_step_down():
    source = inspect.getsource(base_module)

    assert "run_as" not in source
    assert "human_accounts" not in source
    assert "is_privileged" not in source
    assert "runuser" not in source


from neutrino_client.platforms import base


class Terminal:
    """A scripted terminal: chunks to hand out, and what was typed in."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.typed = b""

    def read(self, wait_s):
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    def write(self, data):
        self.typed += data


def test_the_prompt_is_answered_once_even_when_it_arrives_in_pieces():
    terminal = Terminal([b"Delete provider 'x'? (y", b"/N) ", b"more (y/N)", b"done"])

    output = base.answer_on_prompt(
        terminal.read,
        terminal.write,
        prompt="(y/N)",
        answer="y\n",
        deadline=time.monotonic() + 5,
    )

    assert terminal.typed == b"y\n"
    assert output.endswith(b"done")


def test_no_prompt_means_nothing_typed():
    terminal = Terminal([b"already gone\n"])

    base.answer_on_prompt(
        terminal.read,
        terminal.write,
        prompt="(y/N)",
        answer="y\n",
        deadline=time.monotonic() + 5,
    )

    assert terminal.typed == b""


def test_a_silent_terminal_is_left_at_the_deadline():
    def never(wait_s):
        return None

    started = time.monotonic()
    output = base.answer_on_prompt(
        never, lambda data: None, prompt="?", answer="y", deadline=started + 0.2
    )

    assert output == b""
    assert time.monotonic() - started < 2


def test_the_contract_itself_has_no_terminal():
    with pytest.raises(base.PlatformUnsupportedError):
        base.ClientPlatform().run_answering(["x"], prompt="?", answer="y", timeout_s=1)


def test_a_prompt_drawn_with_colours_and_cursor_moves_is_still_found():
    drawn = (
        b"\x1b[?25l\x1b[38;5;10m?\x1b[39m delete 'x'? (y\x1b[0m/N) \x1b[58C\x1b[?25h"
    )
    terminal = Terminal([drawn])

    base.answer_on_prompt(
        terminal.read,
        terminal.write,
        prompt="(y/N)",
        answer="y",
        deadline=time.monotonic() + 5,
    )

    assert terminal.typed == b"y"
    assert base.plain_text(drawn) == b"? delete 'x'? (y/N) "


def test_a_title_sequence_without_its_bell_swallows_nothing_past_the_next_escape():
    drawn = b"\x1b]0;cc-switch\x1b[?25lAre you sure? (y/N) \x1b[?25h\x07"
    assert b"(y/N)" in base.plain_text(drawn)
