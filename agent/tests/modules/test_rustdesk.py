"""The rustdesk module: what it writes, where, and what it never puts on argv.

Nothing here reaches a real RustDesk. What is pinned is the judgment around
it: that a configuration write lands at every path the running service and
the desktop session read, that it keeps what it did not come to change,
that direct mode names no rendezvous server, and that the password is on
one argument vector and in no file this module writes.
"""

import os

import pytest

from neutrino_agent.modules import rustdesk
from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules.rustdesk import (
    RUSTDESK_DIRECT_PORT,
    RUSTDESK_SHARE_OPTIONS,
    config_paths,
    render_config,
    write_config,
)

# --- the configuration, and where every copy of it goes ---


def test_direct_mode_names_no_rendezvous_or_relay_server():
    options = dict(RUSTDESK_SHARE_OPTIONS)

    # No hbbs, no hbbr: reachability is the LAN's or the overlay's job, and
    # an empty server is what stops RustDesk falling back to the public one.
    assert options["custom-rendezvous-server"] == ""
    assert options["relay-server"] == ""
    assert options["direct-server"] == "Y"
    assert options["direct-access-port"] == str(RUSTDESK_DIRECT_PORT)


def test_the_share_options_close_everything_this_hub_does_not_publish():
    options = dict(RUSTDESK_SHARE_OPTIONS)

    assert options["allow-auto-update"] == "N"
    assert options["verification-method"] == "use-permanent-password"
    assert options["approve-mode"] == "password"
    assert options["enable-file-transfer"] == "N"
    assert options["enable-tunnel"] == "N"
    assert options["enable-audio"] == "N"


def test_the_direct_port_is_the_one_a_bare_address_is_dialled_at():
    # RustDesk dials a bare address at its relay port plus one; naming any
    # other port here would need the peer spelled out at every client.
    assert RUSTDESK_DIRECT_PORT == 21118


def test_a_rendered_file_carries_every_option_under_one_table():
    rendered = render_config("", RUSTDESK_SHARE_OPTIONS)

    assert rendered.count("[options]") == 1
    for key, value in RUSTDESK_SHARE_OPTIONS:
        assert f"{key} = '{value}'" in rendered


def test_rendering_keeps_the_machines_own_state_above_the_options():
    existing = "rendezvous_server = 'x'\nnat_type = 1\n\n[options]\nkey = 'old'\n"

    rendered = render_config(existing, (("key", "new"),))

    assert "rendezvous_server = 'x'" in rendered
    assert "nat_type = 1" in rendered
    assert "key = 'new'" in rendered
    assert "key = 'old'" not in rendered


def test_rendering_keeps_an_option_it_was_not_asked_about():
    existing = "[options]\nkept-by-rustdesk = 'yes'\ndirect-server = 'N'\n"

    rendered = render_config(existing, (("direct-server", "Y"),))

    assert "kept-by-rustdesk = 'yes'" in rendered
    assert "direct-server = 'Y'" in rendered
    assert "direct-server = 'N'" not in rendered


def test_a_written_file_is_whole_and_readable_again(tmp_path):
    path = str(tmp_path / "config" / "RustDesk2.toml")

    write_config(path, RUSTDESK_SHARE_OPTIONS)
    write_config(path, RUSTDESK_SHARE_OPTIONS)

    text = open(path, encoding="utf-8").read()
    assert text.count("[options]") == 1
    assert text.count("direct-server = 'Y'") == 1
    # The temporary the write lands through is never left behind.
    assert not os.path.exists(f"{path}.tmp")


def test_a_write_says_whether_the_file_is_not_what_it_was(tmp_path):
    """A service already running reads its configuration once, so the caller
    has to know whether anything moved."""
    path = tmp_path / "RustDesk2.toml"

    assert write_config(str(path), RUSTDESK_SHARE_OPTIONS) is True
    assert write_config(str(path), RUSTDESK_SHARE_OPTIONS) is False


def test_a_file_that_cannot_be_written_is_a_typed_refusal(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")

    with pytest.raises(InstallError):
        write_config(str(blocker / "config" / "RustDesk2.toml"), (("a", "b"),))


def test_every_path_the_service_and_the_session_read():
    assert config_paths("/home/pat") == [
        "/root/.config/rustdesk/RustDesk2.toml",
        "/home/pat/.config/rustdesk/RustDesk2.toml",
    ]


def test_with_no_account_only_the_services_own_copy_is_written():
    assert config_paths("") == ["/root/.config/rustdesk/RustDesk2.toml"]


# --- the password: one argument vector, and no file of ours ---


def test_the_password_is_set_through_the_binarys_own_verb(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(rustdesk.subprocess, "run", _recording(calls, stdout="Done!"))

    rustdesk.set_password("hunter2")

    assert calls == [["/usr/bin/rustdesk", "--password", "hunter2"]]


def test_the_password_never_reaches_a_config_file(monkeypatch, tmp_path):
    # RustDesk stores it salted, so a file write could not set it anyway;
    # what matters is that nothing this module writes carries it.
    path = str(tmp_path / "RustDesk2.toml")

    write_config(path, RUSTDESK_SHARE_OPTIONS)

    assert "hunter2" not in open(path, encoding="utf-8").read()


def test_the_config_verb_is_never_used(monkeypatch):
    # --config takes a path RustDesk imports wholesale, which is the shape
    # CVE-2026-30791 is about; no argument vector here may reach for it.
    source = open(rustdesk.__file__, encoding="utf-8").read()

    assert '"--config"' not in source
    assert "'--config'" not in source


def test_a_refused_password_is_raised_rather_than_believed(monkeypatch):
    _fake_clock(monkeypatch)
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(
        rustdesk.subprocess,
        "run",
        _recording([], stdout="Installation and administrative privileges required!"),
    )

    with pytest.raises(InstallError) as refusal:
        rustdesk.set_password("hunter2")

    assert "administrative privileges" in str(refusal.value)


def test_a_socket_not_up_yet_is_waited_for_rather_than_reported(monkeypatch):
    """The service control returns as soon as the process is forked, and the
    socket the password travels over accepts a moment later; a share that
    reported that as a refusal would be reporting its own haste."""
    _fake_clock(monkeypatch)
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    calls = []
    answers = iter(
        ["Connection refused (os error 111)", "Connection refused (os error 111)"]
    )
    monkeypatch.setattr(
        rustdesk.subprocess,
        "run",
        _answering(calls, lambda: next(answers, "Done!")),
    )

    rustdesk.set_password("hunter2")

    assert calls == [["/usr/bin/rustdesk", "--password", "hunter2"]] * 3


def test_a_socket_that_never_comes_up_is_reported_after_the_wait(monkeypatch):
    clock = _fake_clock(monkeypatch)
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(
        rustdesk.subprocess,
        "run",
        _recording([], stdout="Connection refused (os error 111)"),
    )

    with pytest.raises(InstallError) as refusal:
        rustdesk.set_password("hunter2")

    assert "os error 111" in str(refusal.value)
    assert clock["now"] >= rustdesk.RUSTDESK_PASSWORD_READY_TIMEOUT_S


def test_a_binary_that_cannot_be_run_is_not_waited_on(monkeypatch):
    """No wait fixes a missing executable, and retrying one would only put
    the password on an argument vector again for nothing."""
    clock = _fake_clock(monkeypatch)
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")

    def refuse(*args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(rustdesk.subprocess, "run", refuse)

    with pytest.raises(InstallError):
        rustdesk.set_password("hunter2")

    assert clock["now"] == 0.0


def test_setting_a_password_without_rustdesk_is_refused(monkeypatch):
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "")

    with pytest.raises(InstallError):
        rustdesk.set_password("hunter2")


# --- reading the id ---


def test_the_id_is_read_with_the_binarys_own_verb(monkeypatch):
    calls = []
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(
        rustdesk.subprocess, "run", _recording(calls, stdout="123456789\n")
    )

    assert rustdesk.read_id() == "123456789"
    assert calls == [["/usr/bin/rustdesk", "--get-id"]]


@pytest.mark.parametrize(
    "printed, identifier",
    [
        # The two machines this has run on, verbatim: RustDesk issues eight
        # digits, and a pattern that waits for nine reads them as no id.
        ("10779585\n", "10779585"),
        ("15889145\r\n", "15889145"),
        ("123456789\n", "123456789"),
    ],
)
def test_the_ids_rustdesk_actually_issues_are_read(monkeypatch, printed, identifier):
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(rustdesk.subprocess, "run", _recording([], stdout=printed))

    assert rustdesk.read_id() == identifier


def test_a_longer_run_of_digits_is_not_taken_for_an_id(monkeypatch):
    """The bound keeps a banner's own numbers out: only what is short enough
    to be an id may be read as one."""
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(
        rustdesk.subprocess, "run", _recording([], stdout="1234567890123\n")
    )

    assert rustdesk.read_id() == ""


def test_an_unreadable_id_is_empty_rather_than_guessed(monkeypatch):
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(rustdesk.subprocess, "run", _recording([], stdout="no id here"))

    assert rustdesk.read_id() == ""


def test_no_rustdesk_reads_no_id(monkeypatch):
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "")

    assert rustdesk.read_id() == ""


class _RunRecorder:
    """A subprocess.run that records how each call was made, not only what."""

    def __init__(self, returncode=0):
        self.entries: list = []
        self.returncode = returncode

    def run(self, command, **kwargs):
        self.entries.append({"command": command, "kwargs": kwargs})
        return self


def _fake_clock(monkeypatch):
    """A clock that only moves when the module sleeps, so a wait is asserted
    on rather than served."""
    clock = {"now": 0.0}
    monkeypatch.setattr(rustdesk.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        rustdesk.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds)
    )
    return clock


def _answering(calls, next_stdout):
    """A subprocess.run that records its vector and answers a fresh line each
    time, for a service that is not up yet and then is."""

    class _Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def run(command, *args, **kwargs):
        calls.append(command)
        return _Result(next_stdout())

    return run


def _recording(calls, *, stdout="", returncode=0, is_shell=False):
    """A subprocess.run that records its argument vector and answers fixed."""

    class _Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def run(command, *args, **kwargs):
        calls.append(command if not is_shell else [command])
        return _Result()

    return run


# --- a session's config stays that person's own ---


def test_a_rewrite_keeps_the_owner_and_mode_the_file_had(monkeypatch, tmp_path):
    """RustDesk runs as the person at the screen and writes its Wayland
    screen-capture permission into this file. Left owned by root it cannot,
    and that permission dialog returns on every connection."""
    path = tmp_path / "RustDesk2.toml"
    path.write_text("[options]\nwayland-restore-token = 'tok'\n", encoding="utf-8")
    chowned, chmodded = [], []
    monkeypatch.setattr(rustdesk, "_owner_of", lambda target: (1000, 1000, 0o600))
    monkeypatch.setattr(
        rustdesk.os, "chown", lambda target, uid, gid: chowned.append((uid, gid))
    )
    monkeypatch.setattr(
        rustdesk.os, "chmod", lambda target, mode: chmodded.append(mode)
    )

    rustdesk.write_config(str(path), RUSTDESK_SHARE_OPTIONS)

    assert chowned == [(1000, 1000)]
    assert chmodded == [0o600]
    # And what RustDesk wrote there is still there.
    assert "tok" in path.read_text(encoding="utf-8")


def test_an_existing_config_answers_for_its_own_owner(tmp_path):
    path = tmp_path / "RustDesk2.toml"
    path.write_text("", encoding="utf-8")
    path.chmod(0o600)

    owner = rustdesk._owner_of(str(path))

    assert owner == (os.getuid(), os.getgid(), 0o600)


def test_a_fresh_config_takes_the_home_it_is_under(tmp_path):
    """Nothing exists to ask, so the directory answers: under a home that is
    the person whose permission RustDesk will want to store."""
    home = tmp_path / "pat"
    (home / ".config" / "rustdesk").mkdir(parents=True)

    owner = rustdesk._owner_of(str(home / ".config" / "rustdesk" / "RustDesk2.toml"))

    assert owner == (os.getuid(), os.getgid(), 0o644)


def test_a_config_under_nothing_but_root_is_left_to_root(monkeypatch, tmp_path):
    """Only a home says whose a file is; the service's own copy is root's."""
    monkeypatch.setattr(rustdesk.os, "name", "posix")

    class _Root:
        st_uid = 0
        st_gid = 0
        st_mode = 0o755

    # The file itself is absent; every directory above it is root's.
    monkeypatch.setattr(
        rustdesk,
        "_stat",
        lambda target: None if target.endswith(".toml") else _Root(),
    )

    assert rustdesk._owner_of("/root/.config/rustdesk/RustDesk2.toml") is None


def test_a_path_nothing_can_be_read_about_has_no_owner(monkeypatch):
    monkeypatch.setattr(rustdesk, "_stat", lambda target: None)

    assert rustdesk._owner_of("/root/.config/rustdesk/RustDesk2.toml") is None
