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
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.rustdesk import (
    RUSTDESK_DIRECT_PORT,
    RUSTDESK_SHARE_OPTIONS,
    RustdeskModuleRunner,
    config_paths,
    render_config,
    write_config,
)
from neutrino_agent.platforms.base import AgentPlatform


class _Platform(AgentPlatform):
    """A platform that records what it was asked to install and remove."""

    def __init__(self):
        self.installed = []
        self.removed = []

    def install_package(self, path, *, package_kind, entry):
        self.installed.append((path, package_kind))

    def uninstall_package(self, command):
        self.removed.append(command)


def runner(platform=None):
    return RustdeskModuleRunner(
        platform=platform or _Platform(), log=lambda message: None
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


def test_a_file_that_cannot_be_written_is_a_typed_refusal(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")

    with pytest.raises(InstallError):
        write_config(str(blocker / "config" / "RustDesk2.toml"), (("a", "b"),))


@pytest.mark.parametrize(
    "os_name,is_darwin,expected",
    [
        (
            "posix",
            False,
            [
                "/root/.config/rustdesk/RustDesk2.toml",
                "/home/pat/.config/rustdesk/RustDesk2.toml",
            ],
        ),
        (
            "posix",
            True,
            [
                "/var/root/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml",
                "/home/pat/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml",
            ],
        ),
    ],
)
def test_every_path_the_service_and_the_session_read(
    monkeypatch, os_name, is_darwin, expected
):
    monkeypatch.setattr(rustdesk.os, "name", os_name)
    monkeypatch.setattr(rustdesk, "_is_darwin", lambda: is_darwin)

    assert config_paths("/home/pat") == expected


def test_windows_writes_the_service_profile_and_the_users_roaming(monkeypatch):
    monkeypatch.setattr(rustdesk.os, "name", "nt")
    monkeypatch.setattr(rustdesk.os.path, "join", lambda *parts: "\\".join(parts))

    paths = config_paths("C:\\Users\\pat")

    assert paths == [
        "C:\\Windows\\ServiceProfiles\\LocalService\\AppData\\Roaming\\RustDesk"
        "\\config\\RustDesk2.toml",
        "C:\\Users\\pat\\AppData\\Roaming\\RustDesk\\config\\RustDesk2.toml",
    ]


def test_with_no_account_only_the_services_own_copy_is_written(monkeypatch):
    monkeypatch.setattr(rustdesk.os, "name", "posix")
    monkeypatch.setattr(rustdesk, "_is_darwin", lambda: False)

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


# --- the runner's own contract ---


def test_verify_is_the_manifests_check_and_its_exit_status(monkeypatch):
    monkeypatch.setattr(
        rustdesk.subprocess, "run", _recording([], returncode=0, is_shell=True)
    )

    assert runner().verify({"verify": "which rustdesk"}) is True


def test_a_verify_that_exits_nonzero_reads_absent(monkeypatch):
    monkeypatch.setattr(
        rustdesk.subprocess, "run", _recording([], returncode=1, is_shell=True)
    )

    assert runner().verify({"verify": "which rustdesk"}) is False


def test_a_verify_that_cannot_run_reads_absent_rather_than_installed(monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("no shell")

    monkeypatch.setattr(rustdesk.subprocess, "run", explode)

    assert runner().verify({"verify": "which rustdesk"}) is False


def test_the_details_carry_the_id_for_every_surface(monkeypatch):
    monkeypatch.setattr(rustdesk, "read_id", lambda: "123456789")

    assert runner().details({}) == {"rustdesk_id": "123456789"}


def test_details_are_empty_when_no_id_can_be_read(monkeypatch):
    monkeypatch.setattr(rustdesk, "read_id", lambda: "")

    assert runner().details({}) == {}


def test_install_hands_the_package_to_the_platform(monkeypatch, tmp_path):
    platform = _Platform()
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "")
    monkeypatch.setattr(rustdesk, "write_config", lambda path, options: None)
    package = str(tmp_path / "rustdesk.deb")

    runner(platform).install({"entry": {"package_kind": "deb"}}, package)

    assert platform.installed == [(package, "deb")]


def test_install_points_the_service_at_the_lan_and_nothing_else(monkeypatch, tmp_path):
    """The moment the module lands, every machine is direct-only: no
    rendezvous, no relay, the port pinned — connect-only machines included,
    so nothing under a hub ever registers with public infrastructure. The
    port itself stays closed until a share opens it."""
    monkeypatch.setattr(rustdesk.os, "name", "posix")
    monkeypatch.setattr(rustdesk, "_is_darwin", lambda: False)
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "")
    written = {}
    monkeypatch.setattr(
        rustdesk,
        "write_config",
        lambda path, options: written.__setitem__(path, dict(options)),
    )

    runner().install({"entry": {"package_kind": "deb"}}, str(tmp_path / "rustdesk.deb"))

    options = written["/root/.config/rustdesk/RustDesk2.toml"]
    assert options["custom-rendezvous-server"] == ""
    assert options["relay-server"] == ""
    assert options["direct-access-port"] == "21118"
    assert "direct-server" not in options


def test_a_baseline_the_machine_cannot_take_does_not_fail_the_install(
    monkeypatch, tmp_path
):
    logged = []

    def refuse(path, options):
        raise InstallError("could not write " + path)

    monkeypatch.setattr(rustdesk.os, "name", "posix")
    monkeypatch.setattr(rustdesk, "_is_darwin", lambda: False)
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "")
    monkeypatch.setattr(rustdesk, "write_config", refuse)
    module = RustdeskModuleRunner(platform=_Platform(), log=logged.append)

    module.install({"entry": {"package_kind": "deb"}}, str(tmp_path / "r.deb"))

    assert len(logged) == 1 and "could not write" in logged[0]


def test_registering_the_service_hands_it_no_pipe(monkeypatch, tmp_path):
    """``--install-service`` leaves a service running behind it. A service
    that inherited a captured pipe holds it open, and the read outlives the
    timeout that was supposed to bound the call."""
    monkeypatch.setattr(rustdesk.os, "name", "nt")
    monkeypatch.setattr(
        rustdesk, "binary_path", lambda: "C:\\Program Files\\RustDesk\\RustDesk.exe"
    )
    calls = _RunRecorder()
    monkeypatch.setattr(rustdesk.subprocess, "run", calls.run)
    monkeypatch.setattr(rustdesk, "write_config", lambda path, options: None)

    runner().install({"entry": {"package_kind": "msi"}}, str(tmp_path / "rustdesk.msi"))

    assert calls.entries[0]["command"][-1] == "--install-service"
    assert calls.entries[0]["kwargs"]["stdout"] is rustdesk.subprocess.DEVNULL
    assert calls.entries[0]["kwargs"]["stderr"] is rustdesk.subprocess.DEVNULL
    assert "capture_output" not in calls.entries[0]["kwargs"]
    assert calls.entries[0]["kwargs"]["timeout"] == rustdesk.RUSTDESK_SERVICE_TIMEOUT_S


def test_a_registration_that_exits_nonzero_is_logged_and_not_raised(monkeypatch):
    logged = []
    monkeypatch.setattr(rustdesk.os, "name", "posix")
    monkeypatch.setattr(rustdesk, "_is_darwin", lambda: False)
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(rustdesk.subprocess, "run", _recording([], returncode=1))
    monkeypatch.setattr(rustdesk, "write_config", lambda path, options: None)
    module = RustdeskModuleRunner(platform=_Platform(), log=logged.append)

    module.install({"entry": {"package_kind": "deb"}}, "/tmp/rustdesk.deb")

    assert logged == ["rustdesk: systemctl exited 1"]


def test_uninstall_runs_the_manifests_own_command(monkeypatch):
    platform = _Platform()

    runner(platform).uninstall({"entry": {"uninstall": "apt-get purge -y rustdesk"}})

    assert platform.removed == ["apt-get purge -y rustdesk"]


def test_a_platform_naming_no_uninstall_is_left_alone():
    platform = _Platform()

    runner(platform).uninstall({"entry": {}})

    assert platform.removed == []


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


def test_windows_has_no_such_notion(monkeypatch):
    monkeypatch.setattr(rustdesk.os, "name", "nt")

    assert rustdesk._owner_of("C:\\x\\RustDesk2.toml") is None
