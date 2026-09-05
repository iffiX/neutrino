"""The Linux platform: peercred identity, the account floor, ``runuser``.

Linux steps down with ``runuser`` and judges people by its own floor; homes
come from the account database, never ``$HOME``; a share is a root CIFS
mount fed by a credentials file, never an argument.
"""

import collections
import struct
import subprocess

import pytest

import neutrino_agent.platforms.linux as linux_module
from neutrino_agent.constants import AGENT_SERVICE_NAME
from neutrino_agent.platforms.base import ShareAttachError
from neutrino_agent.platforms.linux import LinuxPlatform

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_shell pw_dir")


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


def test_linux_the_account_floor_is_the_platform_classes_own_number(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    assert linux_module.LINUX_HUMAN_UID_FLOOR == 1000
    entries = [
        PwdEntry("under_the_floor", 999, "/bin/bash", str(home)),
        PwdEntry("at_the_floor", 1000, "/bin/bash", str(home)),
    ]
    monkeypatch.setattr(linux_module.pwd, "getpwall", lambda: entries)

    assert LinuxPlatform().human_accounts() == ["at_the_floor"]


def test_linux_account_home_reads_the_account_database_not_the_environment(monkeypatch):
    monkeypatch.setenv("HOME", "/home/lying")
    entry = PwdEntry("alice", 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)

    assert LinuxPlatform().account_home("alice") == "/home/alice"

    def unknown(name):
        raise KeyError(name)

    monkeypatch.setattr(linux_module.pwd, "getpwnam", unknown)
    with pytest.raises(KeyError):
        LinuxPlatform().account_home("ghost")


def test_linux_ownership_mapping_follows_the_database_home_not_the_environment(
    monkeypatch,
):
    """$HOME says /home/alice, the account database says /srv/alice: the
    database decides which location is the account's own."""
    monkeypatch.setenv("HOME", "/home/alice")
    entry = MountPwdEntry("alice", 1000, 1000, "/bin/bash", "/srv/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    platform = LinuxPlatform()

    assert (
        platform._mount_options(
            account="alice", location="/srv/alice/nas", credentials_path="/c"
        )
        == "credentials=/c,uid=1000,gid=1000"
    )
    assert (
        platform._mount_options(
            account="alice", location="/home/alice/nas", credentials_path="/c"
        )
        == "credentials=/c"
    )
    assert (
        platform._mount_options(
            account="", location="/srv/alice/nas", credentials_path="/c"
        )
        == "credentials=/c"
    )


def test_linux_mount_tooling_is_the_cifs_helper_installed_by_the_package_manager(
    monkeypatch,
):
    present = {"mount.cifs": None, "apt-get": "/usr/bin/apt-get", "dnf": "/usr/bin/dnf"}
    monkeypatch.setattr(linux_module.shutil, "which", present.get)
    calls = []

    def record(command, **kwargs):
        calls.append((list(command), kwargs.get("timeout_s")))
        return ""

    monkeypatch.setattr(linux_module.installers, "run_checked", record)
    platform = LinuxPlatform()

    assert not platform.has_mount_tooling()
    platform.install_mount_tooling()
    present["apt-get"] = None
    platform.install_mount_tooling()
    present["dnf"] = None
    platform.install_mount_tooling()
    present["mount.cifs"] = "/sbin/mount.cifs"

    assert platform.has_mount_tooling()
    assert calls == [
        (
            ["apt-get", "install", "-y", "cifs-utils"],
            linux_module.installers.INSTALL_TIMEOUT_S,
        ),
        (
            ["dnf", "install", "-y", "cifs-utils"],
            linux_module.installers.INSTALL_TIMEOUT_S,
        ),
        (
            ["yum", "install", "-y", "cifs-utils"],
            linux_module.installers.INSTALL_TIMEOUT_S,
        ),
    ]


def test_linux_mount_and_unmount_failures_carry_the_tools_own_words(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(linux_module.shutil, "which", lambda name: "/sbin/mount.cifs")
    entry = MountPwdEntry("alice", 1000, 1000, "/bin/bash", "/home/alice")
    monkeypatch.setattr(linux_module.pwd, "getpwnam", lambda name: entry)
    recorded = {}
    result = {"returncode": 32, "stderr": "mount error(13): Permission denied"}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        return subprocess.CompletedProcess(
            command, result["returncode"], stdout="", stderr=result["stderr"]
        )

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    credentials = tmp_path / "r1.credentials"
    platform = LinuxPlatform()

    with pytest.raises(ShareAttachError) as caught:
        platform.attach_share(
            account="alice",
            share_url="//hub/media",
            username="media",
            password="s3cret",  # scan: allow
            location="/home/alice/nas/media",
            credentials_path=str(credentials),
        )
    assert caught.value.code == "mount_failed"
    assert caught.value.detail == "mount error(13): Permission denied"

    result["stderr"] = "umount: /home/alice/nas/media: target is busy."
    with pytest.raises(ShareAttachError) as caught:
        platform.detach_share(location="/home/alice/nas/media")
    assert recorded["command"] == ["umount", "/home/alice/nas/media"]
    assert caught.value.code == "unmount_failed"
    assert caught.value.detail == "umount: /home/alice/nas/media: target is busy."

    result["returncode"] = 0
    platform.detach_share(location="/home/alice/nas/media")
    assert recorded["command"] == ["umount", "/home/alice/nas/media"]


def test_linux_openssh_installs_the_server_then_switches_its_unit(monkeypatch):
    """The server is a package recommendation, so a machine that skipped it
    gets it installed before the unit is asked to start."""
    present = {"apt-get": "/usr/bin/apt-get"}
    monkeypatch.setattr(linux_module.shutil, "which", present.get)
    real_exists = linux_module.os.path.exists
    monkeypatch.setattr(
        linux_module.os.path,
        "exists",
        lambda path: False if path == "/usr/sbin/sshd" else real_exists(path),
    )
    commands = []
    monkeypatch.setattr(
        linux_module.installers,
        "run_checked",
        lambda command, **kwargs: commands.append(list(command)) or "",
    )
    platform = LinuxPlatform()

    platform.enable_openssh({"service": "sshd"})
    present["sshd"] = "/usr/sbin/sshd"
    platform.enable_openssh({})
    platform.disable_openssh({})

    assert commands == [
        ["apt-get", "install", "-y", "openssh-server"],
        ["systemctl", "enable", "--now", "sshd"],
        ["systemctl", "enable", "--now", "ssh"],
        ["systemctl", "disable", "--now", "ssh"],
    ]


def test_linux_service_state_and_power_go_through_systemd(monkeypatch):
    commands = []
    result = {"returncode": 0, "stdout": "active\n"}

    def record(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(
            command, result["returncode"], stdout=result["stdout"], stderr=""
        )

    monkeypatch.setattr(linux_module.subprocess, "run", record)
    platform = LinuxPlatform()

    assert platform.read_agent_service_state() == "running"
    assert commands[-1] == ["systemctl", "is-active", AGENT_SERVICE_NAME]
    result["stdout"] = "failed\n"
    assert platform.read_agent_service_state() == "failed"
    assert platform.read_openssh_status({"service": "ssh"}) is False
    assert commands[-1] == ["systemctl", "is-active", "ssh"]

    result["stdout"] = "reboot scheduled"
    assert platform.power("reboot") == (0, "reboot scheduled")
    assert commands[-1] == ["systemctl", "reboot"]
    platform.power("poweroff")
    assert commands[-1] == ["systemctl", "poweroff"]
    platform.start_agent_service()
    assert commands[-1] == ["systemctl", "enable", "--now", AGENT_SERVICE_NAME]

    def refuse(command, **kwargs):
        raise OSError("no systemctl")

    monkeypatch.setattr(linux_module.subprocess, "run", refuse)
    assert platform.read_agent_service_state() == "unknown"
    assert platform.read_openssh_status({}) is False
