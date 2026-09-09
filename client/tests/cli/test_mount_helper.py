"""The root mount helper: every refusal, and what reaches mount.

The caller is whoever ``PKEXEC_UID`` names and nothing on argv can change
that: the location must be the caller's own empty directory under their
home, the credentials file their own 0600 file under it, and the mount
options carry their uid and gid. An unmount touches only a CIFS mount under
their home.
"""

import collections
import os

import pytest

import neutrino_client.cli.mount_helper as helper
from neutrino_client.constants import CLIENT_MOUNT_HELPER_EXIT_CODES
from tests.conftest import completed

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_gid pw_dir")


class CommandRecorder:
    def __init__(self, results=None):
        self.commands = []
        self.results = list(results or [])

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        if self.results:
            return self.results.pop(0)
        return completed(command)


@pytest.fixture
def caller(tmp_path, monkeypatch):
    """This test process, as the account polkit names."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    entry = PwdEntry("alice", os.getuid(), os.getgid(), str(home))
    monkeypatch.setattr(helper.pwd, "getpwuid", lambda uid: entry)
    return entry


@pytest.fixture
def ready(caller, tmp_path):
    """An empty mount point and a 0600 credentials file, both the caller's."""
    location = tmp_path / "home" / "nas"
    location.mkdir()
    credentials = tmp_path / "home" / ".config" / "r1.credentials"
    credentials.parent.mkdir(parents=True)
    credentials.write_text("username=u\npassword=p\n")
    credentials.chmod(0o600)
    return str(location), str(credentials)


def mount_argv(location, credentials, share="//hub/media"):
    return [
        "mount",
        "--share",
        share,
        "--location",
        location,
        "--credentials",
        credentials,
    ]


def test_the_exit_codes_are_the_constants_table():
    assert CLIENT_MOUNT_HELPER_EXIT_CODES == {
        helper.EXIT_CALLER_UNKNOWN: "mount_not_authorized",
        helper.EXIT_MOUNTPOINT_INVALID: "mountpoint_invalid",
        helper.EXIT_MOUNTPOINT_NOT_EMPTY: "mountpoint_not_empty",
        helper.EXIT_CREDENTIALS_MISSING: "credentials_missing",
        helper.EXIT_MOUNT_FAILED: "mount_failed",
        helper.EXIT_UNMOUNT_FAILED: "unmount_failed",
    }


def test_a_good_mount_carries_the_callers_uid_and_gid(caller, ready):
    location, credentials = ready
    recorder = CommandRecorder()

    status = helper.run(
        mount_argv(location, credentials),
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert status == 0
    assert recorder.commands == [
        [
            "mount",
            "-t",
            "cifs",
            "//hub/media",
            os.path.realpath(location),
            "-o",
            f"credentials={os.path.realpath(credentials)},"
            f"uid={os.getuid()},gid={os.getgid()}",
        ]
    ]


def test_without_pkexec_uid_nothing_runs(caller, ready):
    location, credentials = ready
    recorder = CommandRecorder()

    for environ in ({}, {"PKEXEC_UID": "nope"}):
        status = helper.run(
            mount_argv(location, credentials), environ, run_command=recorder
        )
        assert status == helper.EXIT_CALLER_UNKNOWN
    assert recorder.commands == []


def test_a_uid_that_names_no_account_is_refused(ready, monkeypatch):
    location, credentials = ready

    def unknown(uid):
        raise KeyError(uid)

    monkeypatch.setattr(helper.pwd, "getpwuid", unknown)

    assert (
        helper.run(mount_argv(location, credentials), {"PKEXEC_UID": "5"})
        == helper.EXIT_CALLER_UNKNOWN
    )


def test_argv_cannot_choose_another_uid(caller, ready):
    location, credentials = ready
    recorder = CommandRecorder()

    helper.run(
        mount_argv(location, credentials) + ["--uid", "0"],
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert recorder.commands == []


@pytest.mark.parametrize(
    "location",
    ["relative/nas", "/etc", "/nonexistent/place"],
)
def test_a_location_outside_the_home_or_missing_is_invalid(caller, ready, location):
    _location, credentials = ready
    recorder = CommandRecorder()

    status = helper.run(
        mount_argv(location, credentials),
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert status == helper.EXIT_MOUNTPOINT_INVALID
    assert recorder.commands == []


def test_a_symlink_out_of_the_home_is_invalid(caller, ready, tmp_path):
    _location, credentials = ready
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "home" / "link"
    link.symlink_to(outside)

    status = helper.run(
        mount_argv(str(link), credentials), {"PKEXEC_UID": str(os.getuid())}
    )

    assert status == helper.EXIT_MOUNTPOINT_INVALID


def test_a_full_location_is_not_empty(caller, ready):
    location, credentials = ready
    with open(os.path.join(location, "kept"), "w") as stream:
        stream.write("x")
    recorder = CommandRecorder()

    status = helper.run(
        mount_argv(location, credentials),
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert status == helper.EXIT_MOUNTPOINT_NOT_EMPTY
    assert recorder.commands == []


def test_a_location_the_caller_does_not_own_is_invalid(ready, tmp_path, monkeypatch):
    location, credentials = ready
    entry = PwdEntry("alice", os.getuid() + 1, os.getgid(), str(tmp_path / "home"))
    monkeypatch.setattr(helper.pwd, "getpwuid", lambda uid: entry)

    status = helper.run(
        mount_argv(location, credentials), {"PKEXEC_UID": str(os.getuid() + 1)}
    )

    assert status == helper.EXIT_MOUNTPOINT_INVALID


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o700])
def test_a_credentials_file_that_is_not_0600_is_missing(caller, ready, mode):
    location, credentials = ready
    os.chmod(credentials, mode)
    recorder = CommandRecorder()

    status = helper.run(
        mount_argv(location, credentials),
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert status == helper.EXIT_CREDENTIALS_MISSING
    assert recorder.commands == []


def test_a_credentials_file_outside_the_home_is_missing(caller, ready, tmp_path):
    location, _credentials = ready
    outside = tmp_path / "outside.credentials"
    outside.write_text("")
    outside.chmod(0o600)

    status = helper.run(
        mount_argv(location, str(outside)), {"PKEXEC_UID": str(os.getuid())}
    )

    assert status == helper.EXIT_CREDENTIALS_MISSING


def test_a_gone_credentials_file_is_missing(caller, ready, tmp_path):
    location, _credentials = ready

    status = helper.run(
        mount_argv(location, str(tmp_path / "home" / "gone")),
        {"PKEXEC_UID": str(os.getuid())},
    )

    assert status == helper.EXIT_CREDENTIALS_MISSING


def test_a_share_that_is_not_a_unc_path_is_usage(caller, ready):
    location, credentials = ready

    status = helper.run(
        mount_argv(location, credentials, share="hub/media"),
        {"PKEXEC_UID": str(os.getuid())},
    )

    assert status == helper.EXIT_USAGE


def test_a_refusing_mount_is_mount_failed(caller, ready, capsys):
    location, credentials = ready
    recorder = CommandRecorder([completed(returncode=32, stderr="mount error(13)")])

    status = helper.run(
        mount_argv(location, credentials),
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert status == helper.EXIT_MOUNT_FAILED
    assert "mount error(13)" in capsys.readouterr().err


def test_unmount_touches_only_a_cifs_mount_under_the_home(
    caller, ready, tmp_path, monkeypatch
):
    location, _credentials = ready
    real = os.path.realpath(location)
    table = tmp_path / "mounts"
    table.write_text(f"//hub/media {real} cifs rw 0 0\n")
    monkeypatch.setattr(helper, "PROC_MOUNTS_PATH", str(table))
    recorder = CommandRecorder()

    status = helper.run(
        ["unmount", "--location", location],
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert status == 0
    assert recorder.commands == [["umount", real]]


def test_unmount_of_a_non_cifs_or_foreign_path_is_refused(
    caller, ready, tmp_path, monkeypatch
):
    location, _credentials = ready
    real = os.path.realpath(location)
    table = tmp_path / "mounts"
    table.write_text(f"tmpfs {real} tmpfs rw 0 0\n" "//hub/x /srv/x cifs rw 0 0\n")
    monkeypatch.setattr(helper, "PROC_MOUNTS_PATH", str(table))
    recorder = CommandRecorder()

    for path in (location, "/srv/x", "relative"):
        status = helper.run(
            ["unmount", "--location", path],
            {"PKEXEC_UID": str(os.getuid())},
            run_command=recorder,
        )
        assert status == helper.EXIT_MOUNTPOINT_INVALID
    assert recorder.commands == []


def test_a_refusing_umount_is_unmount_failed(caller, ready, tmp_path, monkeypatch):
    location, _credentials = ready
    real = os.path.realpath(location)
    table = tmp_path / "mounts"
    table.write_text(f"//hub/media {real} cifs rw 0 0\n")
    monkeypatch.setattr(helper, "PROC_MOUNTS_PATH", str(table))
    recorder = CommandRecorder([completed(returncode=32, stderr="target is busy")])

    status = helper.run(
        ["unmount", "--location", location],
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
    )

    assert status == helper.EXIT_UNMOUNT_FAILED


def test_bad_usage_is_its_own_status(caller):
    assert helper.run([], {"PKEXEC_UID": str(os.getuid())}) == helper.EXIT_USAGE
    assert helper.run(["mount"], {"PKEXEC_UID": str(os.getuid())}) == helper.EXIT_USAGE
