"""The overlay helper: the root half of joining an EasyTier network.

Every refusal has its own exit status and happens before anything is
written; the file lands 0600 with the secret read from the caller's own
0600 file; the daemon is restarted after a join, restarted after a leave
that leaves a network, and stopped after the last.
"""

import collections
import os

import pytest

import neutrino_client.cli.overlay_helper as helper
from tests.conftest import completed

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_gid pw_dir")
SECRET = "s3cret"  # scan: allow
PEER = "tcp://203.0.113.7:11010"


class CommandRecorder:
    def __init__(self, returncode=0):
        self.commands = []
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        return completed(command, returncode=self.returncode, stderr="refused")


@pytest.fixture
def caller(tmp_path, monkeypatch):
    home = tmp_path / "home" / "alice"
    home.mkdir(parents=True)
    entry = PwdEntry("alice", os.getuid(), os.getgid(), str(home))

    class FakePwd:
        @staticmethod
        def getpwuid(uid):
            if uid != os.getuid():
                raise KeyError(uid)
            return entry

    monkeypatch.setattr(helper, "pwd", FakePwd)
    return entry


@pytest.fixture
def secret_file(caller):
    path = os.path.join(caller.pw_dir, "home.secret")
    with open(path, "w") as stream:
        stream.write(SECRET + "\n")
    os.chmod(path, 0o600)
    return path


def up(tmp_path, secret_path, recorder, **overrides):
    arguments = {
        "--network": "home",
        "--secret-file": secret_path,
        "--peer": PEER,
        "--hostname": "box",
    }
    arguments.update(overrides)
    argv = ["easytier", "up"]
    for flag, value in arguments.items():
        argv += [flag, value]
    return helper.run(
        argv,
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
        config_dir=str(tmp_path / "etc"),
    )


def test_up_writes_the_file_0600_and_restarts_the_daemon(tmp_path, secret_file):
    recorder = CommandRecorder()

    status = up(tmp_path, secret_file, recorder)

    written = tmp_path / "etc" / "home.toml"
    assert status == helper.EXIT_OK
    assert written.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "etc").stat().st_mode & 0o777 == 0o700
    assert f'network_secret = "{SECRET}"' in written.read_text()
    assert recorder.commands == [
        ["systemctl", "restart", "neutrino_client_easytier.service"]
    ]


def test_down_restarts_while_another_network_is_left(tmp_path, secret_file):
    recorder = CommandRecorder()
    up(tmp_path, secret_file, recorder)
    up(tmp_path, secret_file, recorder, **{"--network": "office"})

    status = helper.run(
        ["easytier", "down", "--network", "home"],
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
        config_dir=str(tmp_path / "etc"),
    )

    assert status == helper.EXIT_OK
    assert helper.network_files(str(tmp_path / "etc")) == ["office.toml"]
    assert recorder.commands[-1][1] == "restart"


def test_the_last_down_stops_the_daemon(tmp_path, secret_file):
    recorder = CommandRecorder()
    up(tmp_path, secret_file, recorder)

    helper.run(
        ["easytier", "down", "--network", "home"],
        {"PKEXEC_UID": str(os.getuid())},
        run_command=recorder,
        config_dir=str(tmp_path / "etc"),
    )

    assert recorder.commands[-1] == [
        "systemctl",
        "stop",
        "neutrino_client_easytier.service",
    ]
    assert helper.network_files(str(tmp_path / "etc")) == []


@pytest.mark.parametrize(
    "overrides, status",
    [
        ({"--network": "../passwd"}, helper.EXIT_NETWORK_INVALID),
        ({"--peer": "file:///etc/shadow"}, helper.EXIT_PEER_INVALID),
        ({"--hostname": "a b"}, helper.EXIT_USAGE),
        ({"--secret-file": "/etc/shadow"}, helper.EXIT_SECRET_MISSING),
        ({"--secret-file": "relative"}, helper.EXIT_SECRET_MISSING),
    ],
)
def test_every_refusal_writes_nothing(tmp_path, secret_file, overrides, status):
    recorder = CommandRecorder()

    assert up(tmp_path, secret_file, recorder, **overrides) == status
    assert not (tmp_path / "etc").exists()
    assert recorder.commands == []


def test_a_secret_file_others_may_read_is_refused(tmp_path, secret_file):
    os.chmod(secret_file, 0o644)

    assert up(tmp_path, secret_file, CommandRecorder()) == helper.EXIT_SECRET_MISSING


def test_an_unknown_caller_is_refused(tmp_path, secret_file):
    status = helper.run(
        ["easytier", "down", "--network", "home"],
        {},
        run_command=CommandRecorder(),
        config_dir=str(tmp_path / "etc"),
    )

    assert status == helper.EXIT_CALLER_UNKNOWN


@pytest.mark.parametrize(
    "argv",
    [[], ["netbird", "up"], ["easytier", "sideways", "--network", "x"]],
)
def test_usage_is_refused(tmp_path, argv, caller):
    status = helper.run(
        argv,
        {"PKEXEC_UID": str(os.getuid())},
        run_command=CommandRecorder(),
        config_dir=str(tmp_path / "etc"),
    )

    assert status == helper.EXIT_USAGE


def test_a_failed_restart_is_its_own_status(tmp_path, secret_file):
    assert up(tmp_path, secret_file, CommandRecorder(returncode=1)) == (
        helper.EXIT_RESTART_FAILED
    )


def test_the_exit_table_names_every_refusal():
    from neutrino_client.constants import CLIENT_OVERLAY_HELPER_EXIT_CODES

    assert CLIENT_OVERLAY_HELPER_EXIT_CODES == {
        helper.EXIT_CALLER_UNKNOWN: "overlay_not_authorized",
        helper.EXIT_NETWORK_INVALID: "overlay_network_invalid",
        helper.EXIT_PEER_INVALID: "overlay_peer_invalid",
        helper.EXIT_SECRET_MISSING: "overlay_secret_missing",
        helper.EXIT_RESTART_FAILED: "overlay_restart_failed",
    }
