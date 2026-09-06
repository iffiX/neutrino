"""The macOS platform, driven entirely with fakes.

No Mac runs these: every command is recorded instead of run, and what is
pinned is the shape of what would run — dscl judging who is a person, the
xucred peer credential, mount_smbfs fed through a transient nsmb.conf and
never an argv password, Remote Login read both ways, launchd service
control, the pkg kind, and metrics parsed defensively. The mechanisms are
verified interactively on one real Mac.
"""

import collections
import struct
import subprocess

import pytest

import neutrino_agent.platforms.darwin as darwin_module
from neutrino_agent.modules import installers
from neutrino_agent.platforms.base import PlatformUnsupportedError, ShareAttachError
from neutrino_agent.platforms.darwin import DarwinPlatform

PwdEntry = collections.namedtuple("PwdEntry", "pw_name pw_uid pw_gid pw_dir")

USER_LISTING = """root                    0
_spotlight              89
under_the_floor         500
mia                     501
hidden_admin            502
zed                     503
_smbuser                510
"""


def ok(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def refusal(stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 1, stdout="", stderr=stderr)


class FakeMac:
    """Answers the commands the platform runs, recording each one."""

    def __init__(
        self,
        *,
        listing: str = USER_LISTING,
        hidden: tuple = (),
        homes: "dict | None" = None,
        answers: "dict | None" = None,
    ):
        self.listing = listing
        self.hidden = set(hidden)
        self.homes = homes or {}
        # Joined command prefix to its scripted answer, for the rest.
        self.answers = answers or {}
        self.commands: list = []

    def __call__(self, command, **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(list(command))
        if command[:2] == ["dscl", "."]:
            return self._dscl(command[2:])
        for prefix, answer in self.answers.items():
            if " ".join(command).startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return ok("")

    def _dscl(self, arguments) -> subprocess.CompletedProcess:
        if arguments[0] == "-list":
            return ok(self.listing)
        account = arguments[1].rsplit("/", 1)[1]
        if arguments[2] == "IsHidden":
            if account in self.hidden:
                return ok("IsHidden: 1\n")
            return refusal("No such key: IsHidden")
        if arguments[2] == "NFSHomeDirectory":
            home = self.homes.get(account)
            if home is None:
                return refusal("no such record")
            return ok(f"NFSHomeDirectory: {home}\n")
        return refusal("unknown query")


@pytest.fixture()
def mac(monkeypatch):
    fake = FakeMac()
    monkeypatch.setattr(darwin_module.subprocess, "run", fake)
    return fake


# --- who is a person, by the directory service's own judgment ---


def test_darwin_accounts_apply_the_floor_the_prefix_and_is_hidden(mac):
    assert darwin_module.DARWIN_HUMAN_UID_FLOOR == 501
    mac.hidden = {"hidden_admin"}

    # root and the system's own accounts are under the floor, an
    # underscore-prefixed account above it is still a service, and a hidden
    # account is the directory service saying it is not a person.
    assert DarwinPlatform().human_accounts() == ["mia", "zed"]


def test_darwin_accounts_are_empty_when_dscl_cannot_answer(monkeypatch):
    def broken(command, **kwargs):
        raise OSError("no directory service")

    monkeypatch.setattr(darwin_module.subprocess, "run", broken)

    assert DarwinPlatform().human_accounts() == []


def test_darwin_account_home_is_the_directory_services_answer(mac):
    mac.homes = {"mia": "/Users/mia"}

    assert DarwinPlatform().account_home("mia") == "/Users/mia"
    with pytest.raises(KeyError):
        DarwinPlatform().account_home("nobody")


# --- the peer credential, parsed off the socket ---


class PeerSocket:
    def __init__(self, data: bytes):
        self._data = data

    def getsockopt(self, level, option, size):
        assert (level, option) == (
            darwin_module.DARWIN_SOL_LOCAL,
            darwin_module.DARWIN_LOCAL_PEERCRED,
        )
        return self._data[:size]


def xucred(version: int, uid: int) -> bytes:
    packed = struct.pack(darwin_module.DARWIN_XUCRED_FORMAT, version, uid)
    return packed + b"\x00" * (darwin_module.DARWIN_XUCRED_SIZE - len(packed))


def test_darwin_peer_identity_reads_the_xucred(monkeypatch):
    monkeypatch.setattr(
        darwin_module.pwd,
        "getpwuid",
        lambda uid: PwdEntry("mia", uid, 20, "/Users/mia"),
    )

    identity = DarwinPlatform().read_peer_identity(PeerSocket(xucred(0, 501)))

    assert identity == {"account": "mia", "uid": 501, "is_privileged": False}


def test_darwin_peer_uid_zero_is_privileged():
    identity = DarwinPlatform().read_peer_identity(PeerSocket(xucred(0, 0)))

    assert identity == {"account": "root", "uid": 0, "is_privileged": True}


def test_darwin_peer_refusals_are_typed_not_guessed():
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().read_peer_identity(PeerSocket(xucred(7, 501)))
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().read_peer_identity(PeerSocket(b"\x00\x01"))


# --- acting for an account ---


def test_darwin_steps_down_with_su_never_sudo(monkeypatch):
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(darwin_module.subprocess, "run", record)
    monkeypatch.setattr(darwin_module.os, "geteuid", lambda: 0)

    DarwinPlatform().run_as_account("alice", ["id", "-u"], stdin="typed")

    assert recorded["command"] == ["su", "-", "alice", "-c", "id -u"]
    assert "sudo" not in recorded["command"]
    assert recorded["kwargs"]["input"] == "typed"

    monkeypatch.setattr(darwin_module.os, "geteuid", lambda: 501)
    DarwinPlatform().run_as_account("alice", ["id", "-u"])

    assert recorded["command"] == ["id", "-u"]


# --- attaching a share: mount_smbfs, the password never on argv ---


@pytest.fixture()
def smb(monkeypatch, tmp_path, mac):
    """A mount-ready fake Mac whose nsmb.conf lives under tmp_path."""
    monkeypatch.setattr(
        darwin_module, "DARWIN_NSMB_CONF_PATH", str(tmp_path / "nsmb.conf")
    )
    seen = {}

    def mount_answer():
        seen["nsmb"] = (tmp_path / "nsmb.conf").read_text(encoding="utf-8")
        return ok("")

    mac.answers["mount_smbfs"] = None  # replaced per test below
    mac.mount_answer = mount_answer
    mac.seen = seen

    def dispatch(command, **kwargs):
        mac.commands.append(list(command))
        if command[:2] == ["dscl", "."]:
            return mac._dscl(command[2:])
        if command[0] == "mount_smbfs":
            answer = mac.answers.get("mount_smbfs")
            if answer is None:
                return mac.mount_answer()
            return answer
        if command[0] in ("umount", "mount"):
            return mac.answers.get(command[0], ok(""))
        return ok("")

    monkeypatch.setattr(darwin_module.subprocess, "run", dispatch)
    return mac


def test_darwin_attach_feeds_the_password_through_nsmb_conf(smb, tmp_path, monkeypatch):
    def no_account(name):
        raise KeyError(name)

    monkeypatch.setattr(darwin_module.pwd, "getpwnam", no_account)
    credentials = tmp_path / "r1.credentials"
    location = str(tmp_path / "mnt")

    DarwinPlatform().attach_share(
        account="mia",
        share_url="//hub/media",
        username="media",
        password="s3cret",  # scan: allow
        location=location,
        credentials_path=str(credentials),
    )

    mount = [command for command in smb.commands if command[0] == "mount_smbfs"][0]
    assert mount == ["mount_smbfs", "-N", "//media@hub/media", location]
    assert "s3cret" not in " ".join(mount)
    # The password rode the transient section, uppercased the way
    # nsmb.conf(5) writes its examples…
    assert "[HUB:MEDIA:MEDIA]" in smb.seen["nsmb"]
    assert "password=s3cret" in smb.seen["nsmb"]
    # …and the file is gone again once the mount has run.
    assert not (tmp_path / "nsmb.conf").exists()
    stored = credentials.read_text(encoding="utf-8")
    assert stored == "username=media\npassword=s3cret\n"
    assert (credentials.stat().st_mode & 0o777) == 0o600


def test_darwin_attach_maps_ownership_only_under_the_askers_home(
    smb, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        darwin_module.pwd,
        "getpwnam",
        lambda name: PwdEntry("mia", 501, 20, "/Users/mia"),
    )
    smb.homes = {"mia": "/Users/mia"}
    credentials = tmp_path / "r1.credentials"

    DarwinPlatform().attach_share(
        account="mia",
        share_url="//hub/media",
        username="media",
        password="pw",  # scan: allow
        location="/Users/mia/nas/media",
        credentials_path=str(credentials),
    )
    inside = [command for command in smb.commands if command[0] == "mount_smbfs"][0]
    assert inside[1:6] == ["-N", "-u", "501", "-g", "20"]

    DarwinPlatform().attach_share(
        account="mia",
        share_url="//hub/media",
        username="media",
        password="pw",  # scan: allow
        location="/Volumes/media",
        credentials_path=str(credentials),
    )
    outside = [command for command in smb.commands if command[0] == "mount_smbfs"][1]
    assert "-u" not in outside and "-g" not in outside


def test_darwin_attach_without_the_credentials_file_is_typed(smb, tmp_path):
    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            account="mia",
            share_url="//hub/media",
            username="media",
            password="",
            location=str(tmp_path / "mnt"),
            credentials_path=str(tmp_path / "gone.credentials"),
        )

    assert caught.value.code == "credentials_missing"


def test_darwin_a_refused_mount_restores_nsmb_conf_exactly(smb, tmp_path, monkeypatch):
    def no_account(name):
        raise KeyError(name)

    monkeypatch.setattr(darwin_module.pwd, "getpwnam", no_account)
    (tmp_path / "nsmb.conf").write_text("[default]\nsigning_required=yes\n")
    smb.answers["mount_smbfs"] = refusal("mount_smbfs: server rejected the connection")
    credentials = tmp_path / "r1.credentials"

    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().attach_share(
            account="mia",
            share_url="//hub/media",
            username="media",
            password="pw",  # scan: allow
            location=str(tmp_path / "mnt"),
            credentials_path=str(credentials),
        )

    assert caught.value.code == "mount_failed"
    assert "rejected" in caught.value.detail
    assert (tmp_path / "nsmb.conf").read_text() == "[default]\nsigning_required=yes\n"


def test_darwin_detach_unmounts_and_types_a_refusal(smb):
    DarwinPlatform().detach_share(location="/Users/mia/nas/media")
    assert ["umount", "/Users/mia/nas/media"] in smb.commands

    smb.answers["umount"] = refusal("umount: /Users/mia/nas/media: busy")
    with pytest.raises(ShareAttachError) as caught:
        DarwinPlatform().detach_share(location="/Users/mia/nas/media")
    assert caught.value.code == "unmount_failed"
    assert "busy" in caught.value.detail


def test_darwin_attachment_is_read_from_the_mount_table(smb):
    smb.answers["mount"] = ok(
        "/dev/disk3s1 on / (apfs, local, journaled)\n"
        "//media@hub/media on /Users/mia/nas/media "
        "(smbfs, nodev, nosuid, mounted by mia)\n"
    )

    platform = DarwinPlatform()
    assert platform.is_share_attached(location="/Users/mia/nas/media") is True
    assert platform.is_share_attached(location="/Users/mia/nas") is False


# --- Remote Login is the SSH server, read both ways ---


@pytest.mark.parametrize(
    "stdout, is_serving",
    [("Remote Login: On\n", True), ("Remote Login: Off\n", False)],
)
def test_darwin_remote_login_state_is_systemsetups_answer(
    monkeypatch, stdout, is_serving
):
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return ok(stdout)

    monkeypatch.setattr(darwin_module.subprocess, "run", record)

    assert DarwinPlatform().read_openssh_status({}) is is_serving
    assert commands == [["systemsetup", "-getremotelogin"]]


def test_darwin_remote_login_reads_off_when_systemsetup_cannot_run(monkeypatch):
    def broken(command, **kwargs):
        raise OSError("no systemsetup")

    monkeypatch.setattr(darwin_module.subprocess, "run", broken)

    assert DarwinPlatform().read_openssh_status({}) is False


# --- the pkg kind, and the packages this platform receives ---


def test_darwin_a_pkg_is_installed_with_the_platforms_own_installer(monkeypatch):
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return ""

    monkeypatch.setattr(installers, "run_checked", record)

    DarwinPlatform().install_package("/tmp/agent.pkg", package_kind="pkg", entry={})

    assert commands == [["installer", "-pkg", "/tmp/agent.pkg", "-target", "/"]]


# --- the agent's own LaunchDaemon, and power ---


def test_darwin_service_state_is_launchds_own_word(monkeypatch):
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return ok("system/com.neutrino.agent = {\n\tstate = running\n}\n")

    monkeypatch.setattr(darwin_module.subprocess, "run", record)

    assert DarwinPlatform().read_agent_service_state() == "running"
    assert commands == [["launchctl", "print", "system/com.neutrino.agent"]]


def test_darwin_an_unloaded_service_reads_unknown(monkeypatch):
    monkeypatch.setattr(
        darwin_module.subprocess,
        "run",
        lambda command, **kwargs: refusal("Could not find service"),
    )

    assert DarwinPlatform().read_agent_service_state() == "unknown"


def test_darwin_service_start_bootstraps_then_kickstarts(monkeypatch):
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return ok("")

    monkeypatch.setattr(darwin_module.subprocess, "run", record)

    DarwinPlatform().start_agent_service()

    assert commands == [
        [
            "launchctl",
            "bootstrap",
            "system",
            "/Library/LaunchDaemons/com.neutrino.agent.plist",
        ],
        ["launchctl", "kickstart", "system/com.neutrino.agent"],
    ]


def test_darwin_power_actions_ride_shutdown(monkeypatch):
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="going down\n", stderr="")

    monkeypatch.setattr(darwin_module.subprocess, "run", record)

    code, output = DarwinPlatform().power("reboot")
    assert (code, output) == (0, "going down\n")
    DarwinPlatform().power("poweroff")

    assert commands == [["shutdown", "-r", "now"], ["shutdown", "-h", "now"]]


# --- metrics: sysctl, vm_stat and top, parsed defensively ---

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                              100000.
Pages active:                            200000.
Pages inactive:                          150000.
Pages speculative:                        50000.
Pages wired down:                         80000.
Pages occupied by compressor:             20000.
"""

TOP = """Processes: 400 total, 2 running
Load Avg: 1.50, 1.20, 1.00
CPU usage: 10.0% user, 15.0% sys, 75.0% idle
"""


def test_darwin_metrics_are_read_from_sysctl_vm_stat_and_top(monkeypatch):
    import time as time_module

    boot = int(time_module.time()) - 3600

    def dispatch(command, **kwargs):
        joined = " ".join(command)
        if joined == "sysctl -n kern.boottime":
            return ok(f"{{ sec = {boot}, usec = 0 }} Sat Sep  6 00:00:00 2026\n")
        if joined == "sysctl -n hw.memsize":
            # 1000000 pages of 16384 bytes.
            return ok(str(1000000 * 16384) + "\n")
        if command[0] == "vm_stat":
            return ok(VM_STAT)
        if command[0] == "top":
            return ok(TOP)
        raise AssertionError(f"unexpected command {command}")

    monkeypatch.setattr(darwin_module.subprocess, "run", dispatch)

    metrics = DarwinPlatform().read_host_metrics()

    assert 3595 <= metrics.uptime_s <= 3605
    # active + wired + compressor = 300000 of 1000000 pages.
    assert round(metrics.memory_percent, 1) == 30.0
    assert round(metrics.cpu_percent, 1) == 25.0
    assert 0.0 <= metrics.disk_percent <= 100.0
    assert len(metrics.load_average) == 3


def test_darwin_metrics_survive_a_machine_that_answers_garbage(monkeypatch):
    def garbage(command, **kwargs):
        raise OSError("nothing runs")

    monkeypatch.setattr(darwin_module.subprocess, "run", garbage)

    metrics = DarwinPlatform().read_host_metrics()

    assert metrics.uptime_s == 0
    assert metrics.memory_percent == 0.0
    assert metrics.cpu_percent == 0.0
    assert metrics.to_dict()


# --- what macOS honestly cannot do ---


def test_darwin_system_packages_are_refused_typed():
    with pytest.raises(PlatformUnsupportedError) as caught:
        DarwinPlatform().install_system_packages(["cifs-utils"])
    assert caught.value.code == "unsupported_platform"
    with pytest.raises(PlatformUnsupportedError):
        DarwinPlatform().remove_system_packages(["cifs-utils"])
