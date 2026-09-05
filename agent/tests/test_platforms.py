"""The platform contract: advertised capabilities, honest refusals.

A platform says what it has; invoking what it lacks answers
``unsupported_platform``, never a guess. Linux steps down with ``runuser``
and judges people by its own floor.
"""

import collections
import struct
import subprocess

import pytest

import neutrino_agent.platforms.linux as linux_module
from neutrino_agent.platforms.base import (
    AgentPlatform,
    PlatformUnsupportedError,
    ShareAttachError,
)
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_shell pw_dir")


def test_the_base_platform_advertises_nothing():
    assert AgentPlatform().capabilities == frozenset()


def test_each_platform_advertises_its_capability_set():
    assert LinuxPlatform().capabilities == frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "agent_service",
            "power",
            "metrics",
            "packages",
            "openssh",
            "shares",
        }
    )
    assert DarwinPlatform().capabilities == frozenset(
        {
            "accounts",
            "account_files",
            "run_as",
            "control_socket",
            "packages",
            "openssh",
        }
    )
    assert WindowsPlatform().capabilities == frozenset(
        {"account_files", "packages", "openssh"}
    )


def test_only_linux_advertises_shares_so_far():
    assert LinuxPlatform().has_capability("shares")
    for platform in (DarwinPlatform(), WindowsPlatform()):
        assert not platform.has_capability("shares")


def test_an_absent_capability_is_refused_not_guessed():
    with pytest.raises(PlatformUnsupportedError) as caught:
        WindowsPlatform().run_as_account("bob", ["id"])
    assert caught.value.code == "unsupported_platform"
    with pytest.raises(PlatformUnsupportedError):
        AgentPlatform().read_host_metrics()
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().power("reboot")
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().human_accounts()
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().is_share_attached(location="/mnt/share")


def test_base_file_operations_refuse_without_run_as():
    with pytest.raises(PlatformUnsupportedError):
        AgentPlatform().read_account_file(account="alice", relative="f")


class FakePeerConnection:
    def __init__(self, credential: bytes):
        self._credential = credential

    def getsockopt(self, level, option, length):
        return self._credential[:length]


def test_linux_reads_peer_identity_from_peercred(monkeypatch):
    entry = PwdEntry("alice", 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwuid", lambda uid: entry)
    connection = FakePeerConnection(struct.pack("3i", 42, 1000, 1000))

    identity = LinuxPlatform().read_peer_identity(connection)

    assert identity == {"account": "alice", "uid": 1000, "is_privileged": False}


def test_linux_peer_uid_zero_is_privileged():
    connection = FakePeerConnection(struct.pack("3i", 1, 0, 0))

    identity = LinuxPlatform().read_peer_identity(connection)

    assert identity == {"account": "root", "uid": 0, "is_privileged": True}


def test_linux_refuses_an_unresolvable_peer_uid(monkeypatch):
    def unknown(uid):
        raise KeyError(uid)

    monkeypatch.setattr(linux_module.pwd, "getpwuid", unknown)
    connection = FakePeerConnection(struct.pack("3i", 42, 4242, 4242))

    with pytest.raises(KeyError):
        LinuxPlatform().read_peer_identity(connection)


def test_windows_has_no_peer_identity_yet():
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().read_peer_identity(object())
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().control_socket_path()


def test_linux_human_accounts_apply_the_floor(monkeypatch, tmp_path):
    home = tmp_path / "alice"
    home.mkdir()
    entries = [
        PwdEntry("root", 0, "/bin/bash", "/root"),
        PwdEntry("daemon", 1, "/usr/sbin/nologin", "/usr/sbin"),
        PwdEntry("service", 999, "/bin/bash", str(home)),
        PwdEntry("alice", 1000, "/bin/bash", str(home)),
        PwdEntry("shell_less", 1001, "/usr/sbin/nologin", str(home)),
        PwdEntry("homeless", 1002, "/bin/bash", str(tmp_path / "missing")),
        PwdEntry("nobody", 65534, "/bin/sh", "/nonexistent"),
    ]
    monkeypatch.setattr(linux_module.pwd, "getpwall", lambda: entries)

    assert LinuxPlatform().human_accounts() == ["alice"]


def test_linux_steps_down_with_runuser(monkeypatch):
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 0)

    LinuxPlatform().run_as_account("alice", ["id"])

    assert recorded["command"] == ["runuser", "-u", "alice", "--", "id"]


def test_linux_runs_directly_without_root_or_account(monkeypatch):
    recorded = []

    def record(command, **kwargs):
        recorded.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 1000)
    LinuxPlatform().run_as_account("alice", ["id"])
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 0)
    LinuxPlatform().run_as_account("", ["id"])

    assert recorded == [["id"], ["id"]]


def test_account_file_ops_ignore_the_home_variable(monkeypatch, tmp_path):
    """The account database, not $HOME, names the home: a root agent's
    environment says /root, and writing there is the bug of record."""
    home = tmp_path / "alice"
    home.mkdir()
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    monkeypatch.setenv("HOME", str(wrong))
    entry = PwdEntry("alice", 1000, "/bin/bash", str(home))
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    platform = LinuxPlatform()

    platform.write_account_file(
        account="alice", relative=".claude/settings.json", text='{"model": "opus"}'
    )

    assert (home / ".claude/settings.json").read_text() == '{"model": "opus"}'
    assert not (wrong / ".claude").exists()
    assert (
        platform.read_account_file(account="alice", relative=".claude/settings.json")
        == '{"model": "opus"}'
    )


MountPwdEntry = collections.namedtuple(
    "MountPwdEntry", "pw_name pw_uid pw_gid pw_shell pw_dir"
)


def test_linux_attach_mounts_with_a_credentials_file_never_an_argument(
    monkeypatch, tmp_path
):
    entry = MountPwdEntry("alice", 1000, 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    monkeypatch.setattr(linux_module.shutil, "which", lambda name: "/sbin/mount.cifs")
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    credentials = tmp_path / "creds" / "r1.credentials"

    LinuxPlatform().attach_share(
        account="alice",
        share_url="//hub/media",
        username="media",
        password="s3cret",  # scan: allow
        location="/home/alice/nas/media",
        credentials_path=str(credentials),
    )

    assert recorded["command"] == [
        "mount",
        "-t",
        "cifs",
        "//hub/media",
        "/home/alice/nas/media",
        "-o",
        f"credentials={credentials},uid=1000,gid=1000",
    ]
    assert "s3cret" not in " ".join(recorded["command"])  # scan: allow
    assert credentials.read_text() == "username=media\npassword=s3cret\n"  # scan: allow
    assert oct(credentials.stat().st_mode & 0o777) == "0o600"


def test_linux_maps_ownership_only_under_the_asking_accounts_home(monkeypatch):
    entry = MountPwdEntry("alice", 1000, 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    platform = LinuxPlatform()

    inside = platform._mount_options(
        account="alice", location="/home/alice/nas", credentials_path="/c"
    )
    outside = platform._mount_options(
        account="alice", location="/srv/nas", credentials_path="/c"
    )

    assert inside == "credentials=/c,uid=1000,gid=1000"
    assert outside == "credentials=/c"


def test_linux_attach_refusals_are_typed(monkeypatch, tmp_path):
    monkeypatch.setattr(linux_module.shutil, "which", lambda name: None)
    with pytest.raises(ShareAttachError) as caught:
        LinuxPlatform().attach_share(
            account="alice",
            share_url="//hub/media",
            username="media",
            password="",
            location="/mnt",
            credentials_path=str(tmp_path / "gone.credentials"),
        )
    assert caught.value.code == "cifs_missing"

    monkeypatch.setattr(linux_module.shutil, "which", lambda name: "/sbin/mount.cifs")
    with pytest.raises(ShareAttachError) as caught:
        LinuxPlatform().attach_share(
            account="alice",
            share_url="//hub/media",
            username="media",
            password="",
            location="/mnt",
            credentials_path=str(tmp_path / "gone.credentials"),
        )
    assert caught.value.code == "credentials_missing"


def test_linux_reads_attachment_from_proc_mounts_with_escapes(monkeypatch, tmp_path):
    table = tmp_path / "mounts"
    table.write_text(
        "//hub/media /home/alice/my\\040nas cifs rw 0 0\n" "tmpfs /tmp tmpfs rw 0 0\n"
    )
    monkeypatch.setattr(linux_module, "PROC_MOUNTS_PATH", str(table))
    platform = LinuxPlatform()

    assert platform.is_share_attached(location="/home/alice/my nas")
    assert not platform.is_share_attached(location="/home/alice/other")


def test_linux_step_down_env_carries_the_target_identity(monkeypatch):
    """runuser passes the environment through, so the child's HOME, USER and
    LOGNAME must be set to the target account's own values."""
    entry = PwdEntry("alice", 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        recorded["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    monkeypatch.setattr(linux_module.os, "geteuid", lambda: 0)

    LinuxPlatform().run_as_account("alice", ["id"])

    assert recorded["command"][:4] == ["runuser", "-u", "alice", "--"]
    assert recorded["env"]["HOME"] == "/home/alice"
    assert recorded["env"]["USER"] == "alice"
    assert recorded["env"]["LOGNAME"] == "alice"
